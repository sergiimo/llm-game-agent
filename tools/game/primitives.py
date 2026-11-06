"""Atomic I/O: persist one intent, issue at most one raw input, capture one experience.

No target selection, workflow, vision request, modal cleanup, or retries live here. A refused guard performs zero
inputs. The caller owns integration/final state persistence via TurnLoop's write-ahead completion boundary.
"""
import os
import re
import time
import uuid
from dataclasses import replace

from . import experience as X
from .task_state import Intent, Interaction, freeze


def _affordances(rows):
    """Use the experience boundary's established flat bubble schema in both observations and outcomes."""
    return tuple((a['kind'], int(a['point'][0]), int(a['point'][1]), bool(a.get('drop')), bool(a.get('ready')),
                  bool(a.get('highlighted'))) for a in rows)


def experience(intent, before, expects, evidence, frames=()):
    from . import integrate
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
                        (('turn_id', intent.turn_id), ('primitive', original))),
        evidence=evidence, verdict=integrate._verdict(checks),
        artifacts=X.Artifacts(tuple(frames), before.get('frame_path'), None, intent.log_mark, intent.written_at,
                              intent.turn_id))


def execute(store, task, turn_id, action, expects, adapter, log, guard=None):
    """Leave a durable pending intent if input/capture crashes. Never retry an uncertain input."""
    action = dict(action)
    # The raw-click spelling has the same world-target semantics as target. Normalize before guards,
    # ownership bookkeeping, preparation, and intent persistence so no alias can evade the invariant.
    if action.get('kind') == 'click':
        action['kind'] = 'target'
    before = adapter.observe()
    refusal = None
    try:
        if guard:
            refusal = guard(freeze(dict(task.to_dict(), _observation=before)), freeze(action))
            if refusal:
                raise ValueError(refusal)
        prepared = adapter.prepare(dict(action), before)
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
    intent = Intent(turn_id, prepared, adapter.mark(), time.time(), before, expects)
    owner.pending_intent = intent
    if not refusal:
        for key, ledger in (('purchase', '_purchase_intents'), ('sale', '_sale_intents')):
            if action.get(key):
                task.params.setdefault(ledger, []).append(dict(action[key], turn_id=turn_id))
    store.save(task)
    log('intent', intent=intent)
    if refusal:
        s = before.get('screen') or {}
        e = experience(intent, before, expects, X.Evidence(mode=s.get('kind'), texts=tuple(s.get('texts') or ())))
        e = replace(e, verdict=X.Verdict('unsafe', (X.Check('guard', 'safe input', refusal, False),)),
                    discrepancy=X.Discrepancy('guard', 'safe input', refusal))
        intent.experience = e.to_dict()
        store.save(task)
        return
    if prepared['kind'] not in ('wait', 'read'):
        adapter.perform(prepared)
    # TurnLoop._finish captures and persists the result, including zero-input observations.


class GameAdapter:
    """Production I/O adapter. clue_provider may add domain graph clues and interrupts, never inputs."""
    def __init__(self, clue_provider=None):
        self.clue_provider = clue_provider

    def mark(self):
        from . import core
        return core.WF.log_mark()

    def observe(self):
        from . import act, core, observe, screen
        image = core.WF.grab()
        directory = act.frames_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f'turn-{uuid.uuid4().hex}.jpg')
        image.convert('RGB').save(path, quality=90)  # full virtual frame; never resize
        affordances = observe.scan()
        s = screen.read(world_visible=any(a.kind not in (None, 'unknown') for a in affordances))
        if s.kind == 'gameplay' and getattr(core.WF, 'map_pin', None) and core.WF.map_pin(image):
            from .screen import Screen
            s = Screen('map', [])
        clues = dict(self.clue_provider() if self.clue_provider else {})
        clues.update(screen={'kind': s.kind, 'texts': s.texts}, frame_path=path,
                     visible_affordances=[{'kind': a.kind, 'point': list(a.pt), 'drop': a.drop, 'ready': a.ready,
                                           'highlighted': a.highlighted} for a in affordances])
        clues.setdefault('graph_clues', [])
        clues.setdefault('interrupts', [])
        stamp = getattr(core.WF, 'game_stamp', None)
        if stamp is not None:
            clues['game_time'] = stamp()
        return clues

    def prepare(self, action, observation):
        """Resolve only the model-selected control. Guards may refuse, never close menus or choose another target."""
        from . import core, observe
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
            if screen not in ('gameplay', 'dialogue', 'popup', 'cutscene'):
                raise ValueError(f'Space blocked by {screen}; choose its named control')
            if screen == 'gameplay' and not any(a.get('highlighted') for a in observation.get('visible_affordances', ())):
                raise ValueError('Space requires a visible highlighted affordance')
            action['command'] = 'key:space'
        elif kind == 'key':
            label = str(action.get('label', '')).casefold()
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
            hits = core.WF.find_text(label, exact=True)
            if len(hits or ()) != 1:
                raise ValueError('named control missing or ambiguous')
            action['point'] = [round(hits[0]['cx']), round(hits[0]['cy'])]
            # The daemon deliberately rejects raw clicks while paused. Its named-control path issues one click
            # without invoking resume's retry/fallback loop.
            action['command'] = ('text:Resume Game' if screen == 'pause' else
                                 f'click:{action["point"][0]}:{action["point"][1]}')
        elif kind == 'select_card':
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

    def _release(self):
        from . import core
        if getattr(self, '_focused', False):
            release = getattr(core.WF, 'release_focus', None)
            if release:
                release()
            self._focused = False

    def perform(self, action):
        from . import core
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
            core.WF.wait_settle()
            if expects.get('events'):
                core.seen(act.EVENT.pattern, intent.log_mark, act.EVENT_WAIT)
            after = self.observe()
            lines = core.log_text(intent.log_mark).splitlines()
            at = next((p for p in map(act.position_of, lines) if p), None)
            # Canonical identity is assigned by integration's positioned-event consumer, not target=kind.
            moved = None
            if before.get('frame_path') and after.get('frame_path'):
                from PIL import Image
                with Image.open(before['frame_path']) as a, Image.open(after['frame_path']) as b:
                    moved = observe.view_changed(a, b)
            if moved and not at:
                from . import where
                where.walked()
            evidence = X.Evidence(tuple(lines), tuple(act.events_of(lines)), at, None,
                                  after['screen']['kind'], tuple(after['screen']['texts']), (),
                                  _affordances(after['visible_affordances']), moved,
                                  X._t(tuple((k, v) for k, v in after.items()
                                             if k not in ('screen', 'visible_affordances', 'graph_clues'))))
            return experience(intent, before, expects, evidence, (after['frame_path'],))
        finally:
            self._release()
