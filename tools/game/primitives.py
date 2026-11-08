"""Atomic I/O: persist one intent, issue at most one raw input, capture one experience.

No target selection, workflow, vision request, modal cleanup, or input retries live here. A refused guard performs zero
inputs. The caller owns integration/final state persistence via TurnLoop's write-ahead completion boundary.
"""
import os
import re
import time
import uuid
from dataclasses import replace

from . import experience as X
from .task_state import Intent, Interaction, freeze
from runtime.timing import measure


def _affordances(rows):
    """Use the experience boundary's established flat bubble schema in both observations and outcomes."""
    return tuple((a['kind'], int(a['point'][0]), int(a['point'][1]), bool(a.get('drop')), bool(a.get('ready')),
                  bool(a.get('highlighted'))) for a in rows)


def verification_checks(expects, evidence):
    """One expectation verifier for initial capture and later authoritative observation reconciliation."""
    from . import integrate
    from .params import expectations
    expects = expectations(expects)
    checks, _ = integrate.verify(expects, evidence.lines, evidence.events, ' / '.join(evidence.texts))
    if expects.get('moved') is not None:
        checks.append(X.Check('moved', expects['moved'], evidence.moved, evidence.moved == expects['moved']))
    if expects.get('mode') is not None:
        checks.append(X.Check('mode', expects['mode'], evidence.mode, evidence.mode == expects['mode']))
    if expects.get('events') and expects['events'] != '?':
        allowed = {ev for alt in expects['events'] for ev in alt.split('|')}
        allowed.update(expects.get('allowed_events') or ())
        unexpected = sorted(set(evidence.events) - allowed)
        if unexpected:
            checks.append(X.Check('unexpected_events', [], unexpected, False))
    return checks


def goal_expectations(goal, expects):
    """Add deterministic co-events that belong to a goal's declared completion event."""
    expects = dict(expects)
    events = expects.get('events')
    if goal == 'sleep' and events != '?' and 'sleep_transition' in (events or ()):
        allowed = set(expects.get('allowed_events') or ())
        allowed.update(('advance_day', 'complete', 'day_start_intro'))
        expects['allowed_events'] = sorted(allowed)
    return expects


def experience(intent, before, expects, evidence, frames=()):
    from . import integrate
    from . import learn, world
    after_state = dict(evidence.state)
    # Presence matters: an explicit unknown before-state cannot borrow the final scene from after the action.
    initial_scene = before['scene'] if 'scene' in before else before.get('region')
    initial_scope = before['region'] if 'region' in before else initial_scene
    sources = world.positioned_sources(evidence.lines, initial_scene, initial_scope)
    legacy = not any(key in before or key in after_state for key in ('scene', 'region'))
    if legacy and not any(row['scene'] for row in sources):
        sources = []  # only genuinely undeclared legacy context retains the compatibility lookup
    if sources:
        after_state['event_sources'] = sources
    proof = world.region_proof(learn.MEMORY.get('graph'), evidence.lines, after_state.get('region'), sources)
    if proof:
        after_state.update(regions=proof['regions'], region_provenance=proof)
    if sources or proof:
        evidence = replace(evidence, state=X._t(tuple(after_state.items())))
    checks = verification_checks(expects, evidence)
    screen = before.get('screen') or {}
    original = intent.action['kind']
    kind, what = {'bubble': ('click', 'bubble'), 'target': ('click', 'object'), 'cell': ('click', 'point'),
                  'waypoint': ('click', 'step'), 'select_card': ('pick', None)}.get(
                      original, (original, intent.action.get('what')))
    if kind == 'click' and what is None:
        what = 'point'
    state = {k: v for k, v in before.items() if k not in ('screen', 'visible_affordances', 'graph_clues')}
    state.update(screen)
    if before.get('game_time') is not None:
        state['game_time'] = before['game_time']
    return X.Experience.new(
        goal=X.GoalRef(row=intent.action.get('row'), step=intent.action.get('step')),
        before=X.Observation(screen.get('kind'), _affordances(before.get('visible_affordances') or ()),
                             X._t(tuple(sorted(state.items())))),
        prediction=X.Prediction(events=X._t(expects.get('events') or ()), card=expects.get('card'),
                                log=expects.get('log'), moved=expects.get('moved')),
        action=X.Action(kind, what, X._t(intent.action.get('point')),
                        intent.action.get('label') or intent.action.get('name'),
                        tuple(row for row in (
                            ('turn_id', intent.turn_id), ('primitive', original),
                            ('lineage_observation_id', intent.action.get('lineage_observation_id')))
                              if row[1] is not None)),
        evidence=evidence, verdict=integrate._verdict(checks),
        artifacts=X.Artifacts(tuple(frames), before.get('frame_path'), None, intent.log_mark, intent.written_at,
                              intent.turn_id))


def execute(store, task, turn_id, action, expects, adapter, log, guard=None):
    """Leave a durable pending intent if input/capture crashes. Never retry an uncertain input."""
    from .params import expectations
    current_goal = task.stack[-1].goal if task.stack else task.goal
    expects = goal_expectations(current_goal, expectations(expects))
    # Validate before observation, ownership, WAL intent or physical input; goal profiles only add known co-events.
    action = dict(action)
    # The raw-click spelling has the same world-target semantics as target. Normalize before guards,
    # ownership bookkeeping, preparation, and intent persistence so no alias can evade the invariant.
    if action.get('kind') == 'click':
        action['kind'] = 'target'
    source_view = task.current_turn
    leased = hasattr(adapter, 'preflight')
    before = (adapter.observe() if action.get('kind') == 'read' or source_view is None or not leased
              else dict(source_view))
    if source_view is not None and leased and action.get('kind') != 'read':
        before.update(source_view.get('resources') or {})
    source_view = source_view or before
    refusal = None
    try:
        resolver = getattr(adapter, 'resolve_selection', None)
        if resolver:
            action = resolver(action, source_view)
        # The canonical observation has no input or resource metadata to authorize. Metadata-bearing
        # act/read aliases still take the complete ordinary guard path.
        if guard and not (action == {'kind': 'read'} and not expects):
            refusal = guard(task.snapshot(_observation=before), freeze(action))
            if refusal:
                raise ValueError(refusal)
        if action.get('kind') not in ('read', 'wait') and leased:
            adapter.preflight(action, source_view)
        prepared = adapter.prepare(dict(action), source_view)
    except ValueError as ex:
        prepared, refusal = dict(action), str(ex)
    administrative = (action.get('kind') == 'press' and str(action.get('label', '')).casefold() == 'resume game' or
                      (before.get('screen') or {}).get('kind') not in ('gameplay', 'card', 'picker') or
                      task.active is None and action.get('kind') in ('wait', 'read', 'close'))
    if not administrative and task.active is None:
        task.active = Interaction(f'{task.task_id}:{turn_id}', provisional={
            'frame': before.get('frame_path'), 'point': action.get('point'), 'cell': action.get('cell'),
            'projected_node': action.get('projected_node')}, crop=action.get('crop') if not refusal else None)
    if not administrative and not refusal and action.get('crop'):
        task.active.crop = action['crop']  # explicit model classification; never object identity
    if not administrative and not refusal and action.get('kind') in ('target', 'cell', 'bubble', 'space'):
        if not task.active.provisional.get('target_selected'):
            task.active.provisional.update(frame=before.get('frame_path'), point=prepared.get('point'),
                                           cell=prepared.get('cell'))
        task.active.provisional['target_selected'] = True
    owner = task if administrative else task.active
    if task.pending_intent is not None or task.active and task.active.pending_intent is not None:
        raise ValueError('pending intent must be reconciled before input')
    intent = Intent(turn_id, prepared, adapter.mark(), time.time(), before, expects, provenance={
        'boundary': 'primitives.execute/v1',
        'adapter': f'{type(adapter).__module__}.{type(adapter).__qualname__}',
        'preparation': 'refused' if refusal else 'prepared', 'refusal': refusal})
    owner.pending_intent = intent
    if not refusal:
        for key, ledger in (('purchase', '_purchase_intents'), ('sale', '_sale_intents')):
            if action.get(key):
                task.params.setdefault(ledger, []).append(dict(action[key], turn_id=turn_id))
    store.begin_intent(task, intent)
    log('intent', intent=intent, _canonical=False)
    # In-memory fast path for the normal same-process finish. A crash before this assignment leaves the
    # durable WAL unmarked, so recovery safely re-establishes the canonical intent before its outcome.
    intent.journaled = True
    if refusal:
        s = before.get('screen') or {}
        e = experience(intent, before, expects, X.Evidence(mode=s.get('kind'), texts=tuple(s.get('texts') or ())))
        e = replace(e, verdict=X.Verdict('unsafe', (X.Check('guard', 'safe input', refusal, False),)),
                    discrepancy=X.Discrepancy('guard', 'safe input', refusal))
        intent.experience = e.to_dict()
        store.record_capture(task, intent, e.to_dict())
        release = getattr(adapter, 'discard_preflight', None)
        if release:
            release()
        return
    if prepared['kind'] not in ('wait', 'read'):
        adapter.perform(prepared)
    # TurnLoop._finish captures and persists the result, including zero-input observations.


def invalid_expectation_outcome(intent, adapter, error):
    """Recover an old malformed WAL intent without replay or pretending its unknown input status is safe."""
    origin = intent.provenance if isinstance(intent.provenance, dict) else {}
    not_issued = (origin.get('boundary') == 'primitives.execute/v1' and
                  isinstance(origin.get('adapter'), str) and bool(origin['adapter'].strip()) and
                  origin.get('preparation') == 'refused' and
                  isinstance(origin.get('refusal'), str) and bool(origin['refusal'].strip()))
    proof = {'original': intent.expects, 'error': str(error),
             'input_status': 'not_issued' if not_issued else 'unknown',
             'provenance': 'durable preparation refusal' if not_issued else 'originating preparation unproved',
             'intent_provenance': origin}
    if not_issued:
        # Only originating WAL proof establishes that execute skipped perform. The current adapter or
        # missing command says nothing about a different adapter that may already have executed the intent.
        screen = intent.before.get('screen') or {}
        e = experience(intent, intent.before, {}, X.Evidence(mode=screen.get('kind'),
            texts=tuple(screen.get('texts') or ())))
    else:
        e = adapter.capture(intent, intent.before, {})  # observation only; original expectations remain in proof
    state = dict(e.evidence.state, invalid_expectations=proof)
    return replace(e, evidence=replace(e.evidence, state=X._t(tuple(state.items()))),
                   verdict=X.Verdict('unsafe', (X.Check('expectations', 'valid schema', str(error), False),)),
                   discrepancy=X.Discrepancy('expectations', 'valid schema', str(error)))


class GameAdapter:
    """Production I/O adapter. clue_provider may add domain graph clues and interrupts, never inputs."""
    def __init__(self, clue_provider=None, observation_provider=None):
        self.clue_provider = clue_provider
        self.observation_provider = observation_provider
        self._latest_observation = None
        self._captured_outcome = None
        self._vector_store = None

    def mark(self):
        from . import core
        return core.WF.log_mark()

    def observe(self, image=None):
        from . import act, core, observe, screen
        if image is None:
            with measure('observe.grab'):
                image = core.WF.grab()
        directory = act.frames_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f'turn-{uuid.uuid4().hex}.jpg')
        image.convert('RGB').save(path, quality=90)  # full virtual frame; never resize
        from . import view
        view_id = view.new_id(path, image)
        # The saved frame, affordances and OCR must describe one capture. A second grab can see a fade/menu
        # while the artifact shows the world (live split-observation guard refusals). Never interpret black as
        # textless gameplay or count its difference from a rendered frame as movement.
        valid = image.convert('L').getextrema()[1] > 20
        hour = None
        with measure('observe.perception'):
            affordances = observe.scan(image) if valid else []
            try:
                hour = getattr(core.WF, 'game_hour', lambda frame: None)(image) if valid else None
                hud_clock = hour is not None
            except Exception:  # noqa: BLE001 (a missing/unreadable clock is simply not positive evidence)
                hud_clock = False
            s = (screen.read(image=image, world_visible=(hud_clock or
                             any(a.kind not in (None, 'unknown') for a in affordances)))
                 if valid else screen.Screen('unknown', []))
        map_pin = None
        pin_reader = getattr(core.WF, 'map_pin', None)
        map_open = False
        if s.kind in ('gameplay', 'unknown') and screen.map_panel(image):
            map_pin = pin_reader(image) if pin_reader else None
            if map_pin:
                map_open = True
            else:
                try:
                    map_open = screen.map_header_vector(image)
                except Exception:  # appearance inference failure keeps the modal unproved
                    map_open = False
        if map_open:
            from .screen import Screen
            s = Screen('map', [])
        frame_context = {'image': image, 'frame_path': path, 'view_id': view_id,
                         'hour': hour, 'screen': s.kind, 'map_pin': map_pin,
                         'light': getattr(core.WF, 'light_period', lambda value: None)(hour) if hour is not None else None}
        coherent = None
        if self.observation_provider:
            coherent = self.observation_provider(frame_context)
            frame_context['observation_snapshot'] = coherent
        with measure('observe.clues'):
            if coherent is not None and coherent.status == 'save_lineage_mismatch':
                clues = {'lineage_status': coherent.status, 'observation_id': coherent.observation_id,
                         'lineage_mismatch': coherent.mismatch, 'graph_clues': [],
                         'interrupts': ['SAVE_LINEAGE_MISMATCH: ' + str(coherent.mismatch)]}
            elif self.clue_provider:
                import inspect
                try:
                    inspect.signature(self.clue_provider).bind(frame_context)
                except (TypeError, ValueError):
                    provided = self.clue_provider()  # legacy/test providers with an explicit no-argument contract
                else:
                    provided = self.clue_provider(frame_context)
                clues = dict(provided)
            else:
                clues = {}
        if coherent is not None and coherent.status == 'coherent':
            clues.update(lineage_status=coherent.status, observation_id=coherent.observation_id,
                         profile_id=coherent.profile_id, slot_id=coherent.slot_id,
                         log_epoch_id=coherent.log_epoch_id)
        scope = clues.get('vector_scope')
        detections = []
        vector_status = {'status': 'not_requested'}
        if valid and s.kind in ('gameplay', 'unknown') and isinstance(scope, dict):
            effective = {'searched': [], 'disabled': [], 'untrained': list(scope.get('kinds') or ())}
            try:
                if self._vector_store is None:
                    from objects.store import Store
                    self._vector_store = Store()
                effective = observe.inspect_vector_scope(
                    self._vector_store, scope.get('kinds'), scope.get('region'))
                with measure('observe.vectors'):
                    detections = observe.detect_frame(
                        image, region=scope.get('region'), kinds=scope.get('kinds'), store=self._vector_store,
                        cache_key=(view_id, self._vector_store.revision()))
                vector_status = {'status': 'ok' if detections else 'no_match', 'region': scope.get('region'),
                                 **effective, 'hits': len(detections)}
            except Exception as error:  # the model must distinguish detector failure from a valid empty frame
                vector_status = {'status': 'error', 'region': scope.get('region'),
                                 **effective,
                                 'error': f'{type(error).__name__}: {error}'}
        # Semantic modal/card classifiers have already had priority above.  On an
        # otherwise unclassified frame, a Tara appearance hit is positive proof
        # that the rendered world is visible even when OCR finds no HUD controls.
        if s.kind == 'unknown' and any(d.kind == 'Tara' for d in detections):
            s = screen.Screen('gameplay', s.texts, s.controls)
            frame_context['screen'] = s.kind
        clues.update(screen={'kind': s.kind, 'texts': s.texts}, frame_path=path,
                     capture_validity='rendered' if valid else 'black',
                     visible_affordances=[{'kind': a.kind, 'point': list(a.pt), 'drop': a.drop, 'ready': a.ready,
                                           'highlighted': a.highlighted} for a in affordances],
                     vector_detections=[{'kind': d.kind, 'point': list(d.point), 'box': list(d.box),
                                         'score': d.dist, 'raw': d.raw} for d in detections],
                     vector_status=vector_status)
        if s.kind == 'map' and map_pin:
            clues['map_pin'] = list(map_pin)
        clues['view_id'] = view_id
        clues['candidates'] = view.candidates(clues)
        clues['controls'] = [dict(row, id=f'control-{i}', view_id=view_id)
                             for i, row in enumerate(s.controls)]
        clues.setdefault('graph_clues', [])
        clues.setdefault('interrupts', [])
        # These clocks describe different evidence sources.  The log stamp is the action timeline; a save stamp
        # belongs only to the save-derived snapshot/provenance and must never silently replace it.
        clues.setdefault('hud_hour', hour)
        stamp = getattr(core.WF, 'game_stamp', None)
        if stamp is not None:
            log_time = stamp()
            clues['log_time'] = log_time
            clues['game_time'] = log_time  # compatibility for experience/world consumers: always the action clock
        self._latest_observation = clues
        return clues

    def take_outcome_observation(self, experience_id):
        """Consume this action's in-process settled receipt; never reuse it across outcomes or restarts."""
        receipt, self._captured_outcome = self._captured_outcome, None
        return receipt[1] if receipt and receipt[0] == experience_id else None

    def resolve_selection(self, action, observation):
        """Bind current-view candidate/control identity before any semantic authorization guard."""
        action = dict(action)
        if action.get('view_id') and action['view_id'] != observation.get('view_id'):
            raise ValueError('stale view: decision does not match the observed frame')
        if action.get('candidate'):
            matches = [row for row in observation.get('candidates', ())
                       if row.get('id') == action['candidate'] and row.get('view_id') == observation.get('view_id')]
            if len(matches) != 1:
                raise ValueError('candidate missing or stale for this view')
            action['point'] = list(matches[0]['point'])
        if action.get('control'):
            matches = [row for row in observation.get('controls', ())
                       if row.get('id') == action['control'] and row.get('view_id') == observation.get('view_id')]
            if len(matches) != 1:
                raise ValueError('control missing or stale for this view')
            action['point'] = list(matches[0]['point'])
            action['label'] = matches[0].get('label')
        return action

    def prepare(self, action, observation):
        """Resolve only the model-selected control. Guards may refuse, never close menus or choose another target."""
        from . import core, observe
        action = self.resolve_selection(action, observation)
        kind = action.get('kind')
        screen = (observation.get('screen') or {}).get('kind', 'unknown')
        if kind in ('wait', 'read'):
            return action
        if kind in ('click', 'target', 'cell', 'bubble', 'waypoint'):
            if screen != 'gameplay':
                raise ValueError(f'world input blocked by {screen}')
            point = action.get('point')
            if point is None and action.get('cell'):
                m = re.fullmatch(r'([A-Xa-x])(1[0-6]|[1-9])', action['cell'])
                if not m:
                    raise ValueError('cell must be A1-X16')
                point = ((ord(m[1].upper()) - 65 + .5) * 80, (int(m[2]) - .5) * 67.5)
            if point is None or len(point) != 2 or not observe.on_frame(point):
                raise ValueError('click point is outside walkable frame or on HUD')
            if kind == 'waypoint' and not action.get('walkable'):
                raise ValueError('waypoint needs model-confirmed visible walkable ground')
            if kind != 'waypoint' and not action.get('visible_road'):
                raise ValueError('target and full visible walkable road must be confirmed')
            action['point'] = [round(p) for p in point]
            action['command'] = f'click:{action["point"][0]}:{action["point"][1]}'
        elif kind == 'space':
            if screen == 'card':
                if not action.get('control') or str(action.get('label', '')).strip().casefold() != 'yes':
                    raise ValueError('Space on a card requires the current affirmative control')
            elif screen not in ('gameplay', 'dialogue', 'popup', 'cutscene'):
                raise ValueError(f'Space blocked by {screen}; choose its named control')
            if screen == 'gameplay' and not any(a.get('highlighted') for a in observation.get('visible_affordances', ())):
                raise ValueError('Space requires a visible highlighted affordance')
            action['command'] = 'key:space'
        elif kind == 'key':
            if 'key' in action:
                raise ValueError('key action uses label, not key; choose one supported menu key')
            label = str(action.get('label', '')).casefold()
            if label == 'm' and observation.get('region') == 'House':
                raise ValueError('map unavailable indoors; exit the house and porch before opening it')
            if screen != 'gameplay' or label not in ('j', 'm', 'i'):
                raise ValueError('menu key requires gameplay and one of j/m/i; movement keys are forbidden')
            action['command'] = 'key:' + label
        elif kind == 'press':
            if screen not in ('card', 'picker', 'shop', 'journal', 'inventory', 'pause', 'dialogue', 'popup'):
                raise ValueError(f'named control blocked by {screen}')
            label = action.get('label')
            if not isinstance(label, str) or not label.strip():
                raise ValueError('press requires a label')
            if screen == 'pause' and label.lower() != 'resume game':
                raise ValueError('only Resume Game may be pressed on pause')
            hits = [{'cx': row['point'][0], 'cy': row['point'][1]} for row in observation.get('controls', ())
                    if str(row.get('label', '')).strip().casefold() == label.strip().casefold()]
            finder = getattr(core.WF, 'find_text', None)
            if not hits and finder:
                hits = finder(label, path=observation.get('frame_path'), exact=True)
            if len(hits or ()) != 1:
                raise ValueError('named control missing or ambiguous')
            action['point'] = [round(hits[0]['cx']), round(hits[0]['cy'])]
            # The daemon deliberately rejects raw clicks while paused. Its named-control path issues one click
            # without invoking resume's retry/fallback loop.
            action['command'] = ('text:Resume Game' if screen == 'pause' else
                                 f'click:{action["point"][0]}:{action["point"][1]}')
        elif kind == 'select_card':
            if action.get('label'):
                # A named item inspection must resolve that visible text; a supplied point cannot redirect it
                # onto Buy/Sell. Financial labels still require trade authority at the universal guard.
                hits = [{'cx': row['point'][0], 'cy': row['point'][1]} for row in observation.get('controls', ())
                        if str(row.get('label', '')).strip().casefold() == action['label'].strip().casefold()]
                finder = getattr(core.WF, 'find_text', None)
                if not hits and finder:
                    hits = finder(action['label'], path=observation.get('frame_path'), exact=True)
                if len(hits or ()) != 1:
                    raise ValueError('named card missing or ambiguous')
                action['point'] = [round(hits[0]['cx']), round(hits[0]['cy'])]
            if screen not in ('card', 'picker', 'shop', 'inventory') or not action.get('point'):
                raise ValueError('select_card needs one model-selected visible card point')
            x, y = action['point']
            if not (0 <= x < 1920 and 0 <= y < 1080):
                raise ValueError('card point outside frame')
            action['command'] = f'click:{round(x)}:{round(y)}'
        elif kind == 'close':
            if screen not in ('card', 'picker', 'map', 'journal', 'inventory', 'shop'):
                raise ValueError(f'close blocked by {screen}')
            action['command'] = 'key:escape'
        else:
            raise ValueError(f'unknown primitive {kind!r}')
        return action

    def preflight(self, action, observation, current=None):
        """Cheap pixel/scene lease check; it performs no OCR, DINO, graph refresh or input."""
        if self.observation_provider and observation.get('observation_id') is not None:
            fresh = self.observation_provider({
                'frame_path': observation.get('frame_path'), 'view_id': observation.get('view_id')},
                validate_only=True)
            if fresh.status != 'coherent':
                raise ValueError('save_lineage_mismatch: ' + str(fresh.mismatch))
            action['lineage_observation_id'] = fresh.observation_id
        if action.get('view_id') is not None and action.get('view_id') != observation.get('view_id'):
            raise ValueError('stale view: decision does not match its source')
        old_path = observation.get('frame_path')
        if not old_path:
            raise ValueError('stale view: source frame is unavailable')
        from PIL import Image
        from . import core, observe
        # A background window can retain its last gameplay pixels, then materialize Unity's Pause menu only after
        # focus returns. Acquire focus before the final lease image so that transition is refused before run_action
        # (live D5 market trip, outcome ad2dbba00c1b6a97).
        settled_frame = None
        focus = getattr(core.WF, 'ensure_front', None)
        if focus:
            changed_focus = bool(focus())
            self._focused = True
            if changed_focus:
                settle = getattr(core.WF, 'wait_settle', None)
                if settle:
                    settled = settle()
                    frame = getattr(settled, 'frame', None)
                    settled_frame = frame if isinstance(frame, Image.Image) else None
        try:
            with Image.open(old_path) as old:
                now = settled_frame if settled_frame is not None else current
                if isinstance(now, dict) and now.get('frame_path'):
                    with Image.open(now['frame_path']) as opened:
                        changed = observe.view_changed(old, opened)
                else:
                    now = core.WF.grab() if now is None else now
                    changed = observe.view_changed(old, now)
                # World scenes contain localized animation (NPCs, fire, clocks).  A single animated tile does not
                # invalidate a visible-road decision when the coarse camera view is unchanged.  UI actions remain
                # strict because even a small newly appeared control/modal can redirect them.
                world_input = action.get('kind') in ('click', 'target', 'cell', 'bubble', 'waypoint')
                if not changed and not world_input:
                    from PIL import ImageChops, ImageStat
                    diff = ImageChops.difference(old.convert('RGB'), now.convert('RGB'))
                    width, height = diff.size
                    tile = 96
                    changed = any(max(ImageStat.Stat(diff.crop((x, y, min(x + tile, width),
                                                                 min(y + tile, height)))).mean) > 12
                                  for y in range(0, height, tile) for x in range(0, width, tile))
        except OSError as error:
            raise ValueError(f'stale view: source frame unavailable: {error}') from None
        if changed:
            raise ValueError('stale view: camera or modal changed before input')
        return action

    def _release(self):
        from . import core
        if getattr(self, '_focused', False):
            release = getattr(core.WF, 'release_focus', None)
            if release:
                release()
            self._focused = False

    def perform(self, action):
        from . import core
        if not getattr(self, '_focused', False):
            focus = getattr(core.WF, 'ensure_front', None)
            if focus:
                focus()
                self._focused = True
        try:
            msg = core.WF.run_action(action['command'])  # exactly one actuator invocation, even if it fails
            if msg:
                raise RuntimeError(str(msg))
        except BaseException:
            self._release()
            raise

    def capture(self, intent, before, expects):
        try:
            from . import act, core, observe
            is_read = intent.action.get('kind') == 'read'
            self._captured_outcome = None
            same_read = is_read and self._latest_observation is before
            self._latest_observation = None  # a receipt is valid only inside this execute/capture pair
            if expects.get('events'):
                core.seen(act.EVENT.pattern, intent.log_mark, act.EVENT_WAIT)
            settled = None if same_read else core.WF.wait_settle()
            settle_frame = getattr(settled, 'frame', None)
            from PIL import Image
            settle_frame = settle_frame if isinstance(settle_frame, Image.Image) else None
            after = before if same_read else self.observe(image=settle_frame)
            samples = [after]
            if after['screen']['kind'] == 'unknown':
                # Pixel stability alone does not establish a readable modal (live Resume had scenery OCR
                # while the following coherent observation read gameplay). Take one bounded settling read,
                # preserve both sources, and let the ordinary verifier judge the final observation.
                settled = core.WF.wait_settle()
                settle_frame = getattr(settled, 'frame', None)
                after = self.observe(image=settle_frame if isinstance(settle_frame, Image.Image) else None)
                samples.append(after)
                after = dict(after, observation_samples=[{k: sample.get(k) for k in
                    ('frame_path', 'screen', 'capture_validity', 'game_time')} for sample in samples])
            lines = core.log_text(intent.log_mark).splitlines()
            at = next((p for p in map(act.position_of, lines) if p), None)
            # Canonical identity is assigned by integration's positioned-event consumer, not target=kind.
            moved = None
            if (not same_read and before.get('frame_path') and after.get('frame_path') and
                    (before.get('screen') or {}).get('kind') == 'gameplay' and
                    after['screen']['kind'] == 'gameplay' and
                    before.get('capture_validity') != 'black' and after.get('capture_validity') != 'black'):
                from PIL import Image
                with Image.open(before['frame_path']) as a, Image.open(after['frame_path']) as b:
                    if a.convert('L').getextrema()[1] > 20 and b.convert('L').getextrema()[1] > 20:
                        moved = observe.view_changed(a, b)
            if moved and not at:
                from . import where
                where.walked()
            evidence = X.Evidence(tuple(lines), tuple(act.events_of(lines)), at, None,
                                  after['screen']['kind'], tuple(after['screen']['texts']), (),
                                  _affordances(after['visible_affordances']), moved,
                                  X._t(tuple((k, v) for k, v in after.items()
                                             if k not in ('screen', 'visible_affordances', 'graph_clues'))))
            result = experience(intent, before, expects, evidence, tuple(sample['frame_path'] for sample in samples))
            self._captured_outcome = (result.id, after)
            return result
        finally:
            self._release()

    def discard_preflight(self):
        """Release focus acquired by a preflight that safely refused before physical input."""
        self._release()
