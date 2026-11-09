"""One durable model decision. Policy supplies recommendations; only decide can execute input."""
import os
import time
from dataclasses import dataclass, fields, replace

from . import experience as X, integrate as I
from .task_state import Intent, Subgoal, freeze, thaw
from runtime.timing import measure, scope as timing_scope


class StaleTurn(ValueError):
    pass


class DecisionRejected(ValueError):
    pass


def _saved_position(observation):
    """A coherent authoritative save reading, never a model assertion or a newer scene-log projection."""
    import math
    from .world import when
    proofs = observation.get('state_provenance') or {}
    proof = proofs.get('position') or {}
    position, scene = observation.get('position'), observation.get('save_scene')
    if (proof.get('source') != 'save' or not isinstance(proof.get('path'), str) or not proof['path'] or
            type(proof.get('save_count')) is not int or when(proof.get('game_time')) is None or
            proofs.get('save_scene') != proof or not isinstance(scene, str) or not scene or
            observation.get('scene') != scene or not isinstance(position, (list, tuple)) or len(position) != 2 or
            any(type(n) not in (int, float) or not math.isfinite(n) for n in position)):
        return None
    return {'position': list(position), 'scene': scene, 'provenance': proof}


def _source_intent(task, source, log_path):
    """Full original expectations are server-owned; old outcomes recover them only from their exact WAL intent."""
    expects = source.get('expects')
    original = source['experience']
    if expects is None:
        matches = []
        try:
            from .history import event_rows
            for row in event_rows(log_path):
                saved = row.get('intent') or {}
                if (row.get('type') == 'turn' and row.get('phase') == 'intent' and
                        row.get('task_id') == task.task_id and
                        saved.get('turn_id') == original['artifacts'].get('turn_id') and
                        saved.get('action') == source['action'] and saved.get('before') == source['before'] and
                        isinstance(saved.get('expects'), dict)):
                    matches.append(saved['expects'])
        except Exception:  # noqa: BLE001 - projections must never change the canonical commit result
            return None
        if not matches or any(row != matches[0] for row in matches):
            return None  # a partial Prediction cannot prove that region/node/mode/etc were never expected
        expects = matches[0]
    if not isinstance(expects, dict):
        return None
    return Intent(original['artifacts'].get('turn_id'), source['action'], original['artifacts'].get('log_mark'),
                  original['artifacts'].get('t'), source['before'], expects)


def _reconcile_observation(task, evidence, log_path):
    """Attach fresh read proof to a new immutable outcome; never reinterpret a refused input as performed."""
    from .world import when
    surprise = task.last_surprise
    if not surprise:
        return evidence
    source_id = surprise['experience_id']
    from .history import records
    refs = list(task.evidence_refs)
    for child in task.stack:
        refs.extend(child.evidence_refs)
    for child in task.params.get('_subgoal_results', ()):
        refs.extend(child.get('evidence_refs', ()))
    try:
        rows = records(log_path, refs)
    except ValueError as error:
        after = dict(evidence.state)
        after['observation_reconciliation'] = {
            'source_experience': source_id, 'result': 'history_incomplete', 'error': str(error),
            'before': None, 'after': None}
        return replace(evidence, state=X._t(tuple(after.items())))
    history_complete = True
    source = next((row for row in rows if row['experience']['id'] == source_id), None)
    if not source:
        return evidence
    original, before = source['experience'], source['before']
    original_intent = _source_intent(task, source, log_path)
    after = dict(evidence.state)
    known_screen = evidence.mode not in (None, 'unknown') and after.get('capture_validity') != 'black'
    proof = {'source_experience': source_id, 'result': 'need_vision', 'before': None, 'after': None}
    moved = None
    proposed = None
    if (original['verdict']['value'] == 'unsafe' and
            any(c.get('field') == 'guard' and c.get('got') == 'world input blocked by unknown'
                for c in original['verdict'].get('checks', ()))):
        # This source has no after-state precisely because the guard issued zero inputs. A fresh known
        # screen resolves that observation refusal; it grants no movement/domain credit.
        if known_screen:
            proposed = 'guard_refusal_observed'
            proof['input_issued'] = False
    elif (source['action'].get('kind') == 'waypoint' and original['verdict']['value'] != 'unsafe' and
          original['evidence'].get('moved') is None and original['prediction'].get('moved') is True):
        a, b = _saved_position(before), _saved_position(after)
        action_time = when(before.get('game_time'))
        if a and b:
            proof.update(before=a, after=b)
            ap, bp = a['provenance'], b['provenance']
            isolated = history_complete
            for row in rows:
                previous = row['experience']
                if previous['id'] == source_id or previous['verdict']['value'] == 'unsafe':
                    continue
                try:
                    _cancellable_outcome(row)  # proved administrative/read work cannot supply the movement
                    continue
                except DecisionRejected:
                    pass
                tid, source_turn = previous['artifacts'].get('turn_id'), original['artifacts'].get('turn_id')
                if type(tid) is int and type(source_turn) is int and tid >= source_turn:
                    continue
                stamp = dict(previous['evidence'].get('state', ())).get('game_time') or row['before'].get('game_time')
                if when(stamp) is None or when(stamp) >= when(ap['game_time']):
                    isolated = False  # stale baseline also spans another domain input: effect is ambiguous
            # Save count and game time must both advance, in the same save lineage, beyond the attempted
            # input's game clock. A newly discovered autosave from before that input proves no effect of it.
            newer = (isolated and
                     os.path.dirname(os.path.abspath(ap['path'])) == os.path.dirname(os.path.abspath(bp['path'])) and
                     bp['save_count'] > ap['save_count'] and when(bp['game_time']) > when(ap['game_time']) and
                     action_time is not None and when(bp['game_time']) >= action_time)
            if newer:
                moved = a['scene'] != b['scene'] or a['position'] != b['position']
                if moved and known_screen:
                    proposed = 'verified_movement'
    elif (original_intent and original['verdict']['value'] != 'unsafe' and known_screen and
          source['action'].get('kind') in ('press', 'close', 'key', 'space', 'select_card') and
          not source['action'].get('sale') and not source['action'].get('purchase') and
          original_intent.expects.get('mode') is not None and
          original_intent.expects['mode'] == evidence.mode and
          original_intent.expects['mode'] != (before.get('screen') or {}).get('kind') and
          original['evidence'].get('mode') in ('unknown', (before.get('screen') or {}).get('kind'))):
        proposed = 'verified_observation'  # all original checks/outcome rules below must still pass
    if proposed and original_intent:
        from . import primitives
        intent = original_intent
        if proposed == 'guard_refusal_observed':
            # No input happened: resolve the guard's observation, not an attempted move. All other original
            # expectations still use the normal verifier and outcome semantics; no domain success is credited.
            intent = replace(intent, action={'kind': 'read'},
                             expects={k: v for k, v in intent.expects.items() if k != 'moved'})
        actual = replace(evidence, moved=moved)
        # Re-use verification without re-capturing/reprojecting fresh positioned events through the old
        # before-scene. Their current read provenance is immutable and remains the identity authority.
        candidate = replace(X.Experience.from_dict(original), evidence=actual,
                            verdict=I._verdict(primitives.verification_checks(intent.expects, actual)))
        reason = outcome_surprise(task, intent, candidate)
        proof.update(expectations=original_intent.expects, checks=thaw(candidate.verdict.checks), surprise=reason)
        if candidate.verdict.value not in ('miss', 'unsafe') and reason is None:
            proof['result'] = proposed
    after['observation_reconciliation'] = proof
    return replace(evidence, moved=moved, state=X._t(tuple(after.items())))


def _cancellable_outcome(row):
    """Only proved administrative/observational inputs are discardable; unknown domain effects fail closed."""
    import re
    from . import act
    action, exp = row.get('action', {}), row.get('experience', {})
    kind = action.get('kind')
    label = str(action.get('label', '')).strip().casefold()
    if action.get('purchase') or action.get('sale') or re.match(r'^(buy|purchase|sell)\b', label):
        raise DecisionRejected('cancellation refuses financial inputs or receipts')
    evidence = exp.get('evidence', {})
    before, after = row.get('before', {}), dict(evidence.get('state', ()))
    position_proof = (after.get('state_provenance') or {}).get('position') or {}
    position_only_waypoint = (kind == 'waypoint' and evidence.get('moved') is True and
                              after.get('position') is not None and after['position'] != before.get('position') and
                              position_proof.get('source') == 'save')
    if (evidence.get('at') is not None or evidence.get('node') is not None or
            after.get('at') is not None or after.get('node') is not None or after.get('region_provenance') or
            after.get('regions') or after.get('event_sources') or
            position_proof.get('source') in ('event', 'positioned_event') or
            after.get('position') is not None and (position_proof.get('source') != 'save' or
                                                  after['position'] != before.get('position')) and
            not position_only_waypoint or
            any(act.position_of(line) is not None for line in evidence.get('lines', ()))):
        raise DecisionRejected('cancellation refuses positioned domain evidence even without a named event')
    if evidence.get('events') or any(re.search(r'\[STATS\]|\[QUEST\]|\[REL\]|>\s*\w+', line)
                                     for line in evidence.get('lines', ())):
        raise DecisionRejected('cancellation refuses irreversible or uncertain domain effects')
    for key in ('money', 'inventory'):
        if key in before and key in after and before[key] != after[key]:
            raise DecisionRejected('cancellation refuses resource changes')
    no_effect_world_miss = (kind in ('target', 'waypoint', 'cell', 'bubble') and
                            exp.get('verdict', {}).get('value') in ('miss', 'unsafe') and
                            evidence.get('moved') is False and not evidence.get('texts') and
                            evidence.get('mode') == (before.get('screen') or {}).get('kind'))
    if no_effect_world_miss:
        return
    menu = kind == 'key' and label in ('j', 'm', 'i')
    resumed = (kind == 'press' and label == 'resume game' and
               before.get('screen', {}).get('kind') == 'pause' and evidence.get('mode') == 'gameplay')
    if kind not in ('read', 'wait', 'close') and not menu and not resumed and not position_only_waypoint:
        raise DecisionRejected('cancellation refuses unclassified domain input')


class Snapshot:
    def __post_init__(self):
        for f in fields(self):
            object.__setattr__(self, f.name, freeze(getattr(self, f.name)))

    def to_dict(self):
        return thaw(self)


@dataclass(frozen=True)
class Recommendation(Snapshot):
    action: object = None
    confidence: float = 0.
    reasons: tuple = ()
    expects: object = None


@dataclass(frozen=True)
class Decision(Snapshot):
    kind: str
    action: object = None
    correction: object = None
    belief_update: object = None
    rationale: str = 'model_choice'
    evidence_refs: tuple = ()


_BELIEF_ASSESSMENTS = frozenset({'initial', 'progress', 'no_progress', 'contradiction', 'arrived'})
_BELIEF_LISTS = ('confirmed', 'blocked', 'rejected', 'unknown')
_SEMANTIC_SURPRISES = frozenset({
    'wrong_direction', 'no_progress', 'irrelevant_movement', 'missing_progress_evidence', 'stale_route_clue'})


def _navigation_owner(task):
    current = task.stack[-1] if task.stack else task
    return current if current.goal == 'navigate' else None


def _frame_referenced(frame_path, refs):
    return isinstance(frame_path, str) and bool(frame_path) and any(
        ref == frame_path or (isinstance(ref, str) and os.path.basename(ref) == os.path.basename(frame_path))
        for ref in refs)


def _bounded_belief_list(update, name):
    value = update.get(name, ())
    if not isinstance(value, (list, tuple)) or len(value) > 6:
        raise DecisionRejected(f'belief {name} must be a list of at most 6 statements')
    out = []
    for statement in value:
        if not isinstance(statement, str) or not statement.strip() or len(statement.strip()) > 240:
            raise DecisionRejected(f'belief {name} statements must be nonempty and at most 240 characters')
        out.append(statement.strip())
    return out


def _apply_navigation_belief(task, context, decision, action):
    """Record an optional model-owned navigation belief without turning semantics into an input guard."""
    owner = _navigation_owner(task)
    if owner is None:
        if decision.belief_update is not None:
            raise DecisionRejected('belief_update is valid only for an active navigation task')
        return action, None
    action = dict(action)
    if action.get('kind') == 'click' and (context.get('screen') or {}).get('kind') != 'gameplay':
        point = action.get('point')
        if isinstance(point, (list, tuple)) and len(point) == 2:
            controls = [row for row in context.get('controls', ()) if row.get('point') and row.get('label')]
            nearest = min(controls, key=lambda row: sum((float(point[i]) - float(row['point'][i])) ** 2
                                                       for i in (0, 1)), default=None)
            if nearest and sum((float(point[i]) - float(nearest['point'][i])) ** 2 for i in (0, 1)) <= 80 ** 2:
                action = {'kind': 'press', 'label': nearest['label']}
    # Closing a modal, pressing Space, or any other non-world action does not need a route thesis. The adapter's
    # current-screen checks remain the mechanical safety boundary.
    if action.get('kind') not in ('waypoint', 'target', 'cell', 'bubble'):
        return action, None
    update = thaw(decision.belief_update or {})
    if not isinstance(update, dict):
        update = {}
    assessment = update.get('assessment', 'initial')
    if assessment not in _BELIEF_ASSESSMENTS:
        assessment = 'initial'
    observed_hour = update.get('observed_hour')
    if (observed_hour is not None and
            (type(observed_hour) not in (int, float) or not 0 <= observed_hour < 24)):
        observed_hour = None
    navigation = context.get('navigation') or {}
    destination = owner.params.get('destination') or owner.params.get('where') or owner.params.get('region')
    canonical_goal = ((navigation.get('goal') or {}).get('node') or navigation.get('resolved_as') or destination)
    frame_path = context.get('frame_path')
    previous = owner.params.get('_navigation_belief') or {}
    current = str(update.get('current') or 'unknown').strip()[:320]
    next_objective = str(update.get('next_objective') or action.get('objective') or
                         f'continue toward {canonical_goal or "destination"}').strip()[:320]
    action.setdefault('objective', next_objective)
    revision = int(previous.get('revision') or 0) + 1
    belief = {
        # Goal identity belongs to the versioned task. The model may phrase its intent naturally, but cannot
        # replace the canonical destination through a belief update.
        'goal': str(canonical_goal or destination or 'unknown'), 'assessment': assessment,
        'current': current,
        **{name: _bounded_belief_list(update, name) if name in update else [] for name in _BELIEF_LISTS},
        'next_objective': next_objective, 'revision': revision,
        'turn_id': context['turn_id'], 'frame_path': frame_path,
        'evidence_refs': list(decision.evidence_refs) or ([frame_path] if frame_path else []),
    }
    if observed_hour is not None:
        belief['observed_hour'] = float(observed_hour)
    owner.params['_navigation_belief'] = belief
    if context.get('surprise'):
        task.last_surprise = None
    action['belief_revision'] = revision
    action['belief_objective'] = belief['next_objective']
    context['belief'] = belief
    if context.get('navigation'):
        context['navigation'] = dict(context['navigation'], belief=belief)
    task.current_turn = context
    return action, belief


@dataclass(frozen=True)
class Surprise(Snapshot):
    experience_id: str
    before: object
    intended: object
    expected: object
    actual: object
    artifacts: object
    reason: str = 'mismatch'
    checks: object = ()

    @classmethod
    def of(cls, e, reason='mismatch'):
        return cls(e.id, thaw(e.before), thaw(e.action), thaw(e.prediction), thaw(e.evidence), thaw(e.artifacts),
                   reason, tuple(thaw(check) for check in e.verdict.checks))


@dataclass(frozen=True)
class TurnContext(Snapshot):
    turn_id: int
    task: object
    transaction: object
    screen: object
    frame_path: str
    observation_freshness: str
    visible_affordances: tuple
    graph_clues: tuple
    coverage: object
    last_outcome: object
    surprise: object
    interrupts: tuple
    recommendation: Recommendation
    allowed_decisions: tuple
    vector_detections: tuple = ()
    model_workflow: tuple = ()
    vector_status: object = None
    view_id: str = None
    candidates: tuple = ()
    controls: tuple = ()
    view: object = None
    result: object = None
    need: object = None
    memory: object = None
    resources: object = None
    navigation: object = None
    belief: object = None
    observation_id: int = None

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.setdefault('observation_freshness', 'fresh')
        d.setdefault('vector_detections', ())
        # Workflow prose was a repeated rendering of the state below.  Old
        # persisted turns are upgraded on read instead of leaking it forever.
        d['model_workflow'] = ()
        d.setdefault('vector_status', None)
        d.setdefault('view_id', None)
        d.setdefault('candidates', ())
        d.setdefault('controls', ())
        d.setdefault('view', None)
        d.setdefault('result', None)
        d.setdefault('need', None)
        d.setdefault('memory', None)
        d.setdefault('resources', None)
        d.setdefault('navigation', None)
        d.setdefault('belief', None)
        d.setdefault('observation_id', None)
        d['recommendation'] = Recommendation(**d['recommendation'])
        if d.get('surprise'):
            d['surprise'] = Surprise(**d['surprise'])
        return cls(**d)


def _compact_projection(task, observation, surprise):
    """One bounded model view; journals retain the verbose evidence and trace."""
    screen = observation.get('screen') or {}
    view = {
        'id': observation.get('view_id'),
        'path': observation.get('frame_path'),
        'mode': screen.get('kind'),
        'clock': observation.get('hour'),
        'scene': observation.get('region') or observation.get('scene'),
        'controls': observation.get('controls', ()),
        'bubbles': observation.get('visible_affordances', ()),
        'vectors': observation.get('vector_status'),
        'candidates': observation.get('candidates', ()),
    }
    latest = task.last_experience or {}
    evidence = latest.get('evidence') or {}
    verdict = latest.get('verdict') or {}
    result = {
        'experience': latest.get('id'),
        'status': verdict.get('value', 'pending'),
        'events': evidence.get('events', ()),
    }
    reconciliation = dict(evidence.get('state') or ()).get('observation_reconciliation')
    if isinstance(reconciliation, dict) and reconciliation.get('result') in (
            'guard_refusal_observed', 'verified_movement', 'verified_observation'):
        result.update(status=reconciliation['result'],
                      source_experience=reconciliation.get('source_experience'))
    missing = any(clue.get('appearance_needed') for clue in observation.get('graph_clues', ())
                  if isinstance(clue, dict))
    vector_error = (observation.get('vector_status') or {}).get('status') == 'error'
    need = None
    if surprise:
        need = {'kind': 'vision', 'reason': surprise.reason,
                'experience': surprise.experience_id, 'frame': view['path']}
    elif missing or vector_error:
        need = {'kind': 'vision', 'reason': 'missing_appearance' if missing else 'vector_error',
                'frame': view['path']}
    memory = {'revision': observation.get('memory_revision'),
              'clues': observation.get('graph_clues', ())}
    resource_keys = ('hour', 'hud_hour', 'light', 'rain', 'can', 'money', 'inventory', 'inventory_complete',
                     'position', 'region', 'scene', 'save_scene', 'game_time', 'log_time', 'save_time',
                     'state_provenance', 'lineage_status', 'lineage_mismatch')
    resources = {key: observation.get(key) for key in resource_keys if key in observation}
    if resources.get('region'):
        # The compact model receipt has one semantic location. A save may retain its outer scene while Tara is
        # visibly/logically inside a nested region (House); keep that raw value only as save_scene provenance.
        resources['scene'] = resources['region']
    provenance = observation.get('state_provenance') or {}
    resources['provenance'] = {key: provenance[key] for key in resources if key in provenance}
    return view, result, need, memory, resources


def outcome_surprise(task, intent, e):
    """Compare the immutable outcome to explicit expectations and goal-related proof; arrival is verified separately."""
    import math
    current = task.stack[-1] if task.stack else task
    params, goal = current.params, current.goal
    expected, before, after = intent.expects, intent.before, dict(e.evidence.state)
    from .play import region_matches
    for key in ('region', 'node'):
        want = expected.get(key)
        got = after.get(key) if key == 'region' else (I.event_node(e) or e.evidence.node)
        if want is not None and not (region_matches(after, want) if key == 'region' else got == want):
            return 'wrong_' + key
    for key in ('route_valid', 'vector_match'):
        if after.get(key) is False:
            return 'stale_route_clue' if key == 'route_valid' else 'stale_vector_clue'
    if intent.action.get('kind') in ('read', 'wait'):
        return None
    requested = expected.get('events') or ()
    matched_event = any(any(ev in e.evidence.events for ev in alt.split('|')) for alt in requested)
    expected_card = expected.get('card')
    matched_card = bool(expected_card and expected_card != '?' and
                        expected_card.casefold() in ' / '.join(e.evidence.texts).casefold())
    import re
    matched_log = bool(expected.get('log') and expected['log'] != '?' and
                       any(re.search(expected['log'], line) for line in e.evidence.lines))
    changed_mode = e.evidence.mode != (before.get('screen') or {}).get('kind')
    changed_text = tuple(e.evidence.texts) != tuple((before.get('screen') or {}).get('texts') or ())
    matched_mode = bool(expected.get('mode') and e.evidence.mode == expected['mode'] and
                        (changed_mode or changed_text))
    matched_movement = expected.get('moved') is True and e.evidence.moved is True
    # A new card is a relevant observation of a model-selected interaction even before its object is bound.
    changed_card = (e.evidence.mode in ('card', 'picker') and bool(e.evidence.texts) and
                    tuple(e.evidence.texts) != tuple((before.get('screen') or {}).get('texts') or ()))
    garden_event = goal == 'garden' and bool(set(e.evidence.events) & {
        'inspect', 'unplant', 'unplant_impl', 'plant', 'plant_growing', 'water', 'hazel_waterplant',
        'harvest', 'grab_item', 'beehive_collect', 'beehive_progress'})
    from .play import trade_receipt
    purchase, sale = intent.action.get('purchase'), intent.action.get('sale')
    receipt = False
    if e.verdict.value != 'unsafe' and (purchase or sale):
        receipt = trade_receipt(before, after, purchase or sale, 'buy' if purchase else 'sell')
        if not receipt:
            return 'unverified_trade'
    closed = intent.action.get('kind') == 'close' and changed_mode and e.evidence.mode == 'gameplay'
    sleep_event = goal == 'sleep' and 'sleep_transition' in e.evidence.events
    selected_nav_target = False
    if intent.action.get('kind') == 'target' and e.evidence.moved:
        nav_goal = ((before.get('navigation') or {}).get('goal') or {}).get('node')
        candidate_id = intent.action.get('candidate')
        selected = next((row for row in before.get('candidates', ()) if row.get('id') == candidate_id), None)
        selected_nav_target = bool(nav_goal and selected and selected.get('kind') == nav_goal)
    # A navigation primitive bound to the model's persisted belief is semantically owned by that belief, not by
    # the advisory graph compass.  Once the immutable outcome proves movement, the next model turn decides whether
    # that movement advanced or contradicted its objective.  The engine still reports no_progress when no movement
    # occurred and still enforces explicit region/node/event expectations above.
    belief = before.get('belief') or ((before.get('navigation') or {}).get('belief')) or {}
    model_owned_movement = bool(
        goal == 'navigate' and e.evidence.moved is True and
        intent.action.get('belief_revision') == belief.get('revision') and
        intent.action.get('belief_objective') == belief.get('next_objective') and
        intent.action.get('objective') == belief.get('next_objective'))
    relevant = (matched_event or matched_card or matched_mode or matched_movement or matched_log or changed_card or garden_event or
                receipt or closed or sleep_event or selected_nav_target or model_owned_movement)
    if (expected.get('region') and region_matches(after, expected['region']) and
            (not region_matches(before, expected['region']) or
             (after.get('region_provenance') or {}).get('source') == 'positioned_event')):
        relevant = True
    walking = intent.action.get('kind') == 'waypoint'
    if e.evidence.moved is False and not relevant and intent.action.get('kind') != 'close':
        return 'no_progress'
    if walking or e.evidence.moved:
        destination = expected.get('destination_position', params.get('destination_position'))
        old_pos, new_pos = before.get('position'), after.get('position')
        reduction = (destination is not None and old_pos is not None and new_pos is not None and
                     math.dist(new_pos, destination) < math.dist(old_pos, destination) - .01)
        aligned_waypoint = False
        if walking and e.evidence.moved and before.get('navigation'):
            from . import navigation
            try:
                assessment = navigation.assess(intent.action, before['navigation'])
                actual_alignment = navigation.movement_alignment(before, after, before['navigation'])
                aligned_waypoint = bool(assessment.get('allowed') and assessment.get('alignment') in
                                        ('aligned', 'aligned_approach', 'visible_detour', 'map_postcheck') and
                                        (actual_alignment is None or actual_alignment.get('allowed')))
            except (TypeError, ValueError):
                aligned_waypoint = False
        if not reduction and not aligned_waypoint and not relevant:
            return 'irrelevant_movement' if e.evidence.moved else 'missing_progress_evidence'
        relevant = relevant or reduction or aligned_waypoint
    if not relevant:
        return 'unexpected_evidence' if e.evidence.events or changed_mode else 'missing_evidence'
    return None


class TurnLoop:
    """adapter: observe/mark/prepare/perform/capture; policy(task snapshot, clues) is input-free.

    Optional reducer(task, integrated_experience) only folds domain evidence into durable state. It must be
    idempotent, perform no input, and never choose a target or execute a follow-up action.

    Task state, intents, and the turn timeline live in the active run's SQLite rows.
    A persisted context is returned unchanged until consumed, so accept always refers to exact saved data.
    """
    def __init__(self, store, adapter=None, policy=None, reducer=None, guard=None, rebind=None):
        from .primitives import GameAdapter
        self.store, self.adapter = store, adapter or GameAdapter()
        self.policy = policy or (lambda task, obs: Recommendation())
        self.reducer = reducer  # evidence-only domain state update; never input or target selection
        self.guard = guard  # optional pure transaction invariant, checked before any primitive input
        self.rebind = rebind  # recompute task-derived clues after reducer mutations

    def _rebound(self, task, observation):
        return self.rebind(task, observation) if observation is not None and self.rebind else observation

    def _log(self, task, turn_id, phase, _canonical=True, **data):
        readable = thaw(data)
        if phase == 'decision' and task.current_turn:
            from . import navigation
            nav = thaw(task.current_turn.get('navigation'))
            if nav:
                readable['navigation'] = nav
                decision = readable.get('decision') or {}
                action = decision.get('action') or task.current_turn.get('recommendation', {}).get('action')
                if action and action.get('kind') == 'waypoint':
                    readable['waypoint'] = navigation.assess(action, nav)
        if _canonical:
            self.store.append_event(task, turn_id, phase, **readable)

    def _ensure_intent(self, task, intent, recovered=False):
        """Idempotently make the persisted WAL intent canonical before its outcome can be referenced."""
        if intent.journaled:
            return
        canonical = thaw(intent)
        canonical['experience'] = None  # the original pre-input intent shape, even after outcome capture
        canonical['journaled'] = False
        self.store.begin_intent(task, intent)
        intent.journaled = True

    def _records(self, evidence_refs):
        from .history import records
        return records(self.store, evidence_refs)

    def _context(self, task, observation=None):
        if task.current_turn is not None:
            return TurnContext.from_dict(task.current_turn)
        observation = self.adapter.observe() if observation is None else observation
        screen_hint = task.params.get('_screen_hint') or {}
        screen = observation.get('screen') or {}
        if (screen.get('kind') == 'unknown' and screen_hint.get('kind') == 'gameplay' and
                screen_hint.get('region') == (observation.get('region') or observation.get('scene')) and
                task.turn_seq + 1 <= int(screen_hint.get('expires_turn') or -1)):
            observation = dict(observation, screen=dict(screen, kind='gameplay'),
                               screen_provenance={'source': 'model_vision', **screen_hint})
        task.turn_seq += 1
        task.revision += 1
        lineage_mismatch = observation.get('lineage_status') == 'save_lineage_mismatch'
        rec = (Recommendation(None, 0., ('save_lineage_mismatch',), {}) if lineage_mismatch else
               self.policy(task.snapshot(), freeze(observation)))
        surprise = Surprise(**task.last_surprise) if task.last_surprise else None
        allowed = ('accept', 'act', 'look', 'read', 'stop')
        if task.last_experience:
            allowed += ('correct',)  # explicit model resolution also covers ambiguous, non-mismatching outcomes
            current = task.stack[-1] if task.stack else task
            if current.goal in ('navigate', 'enter', 'exit'):
                allowed += ('complete',)  # evidence-only verifier remains the completion authority
        if not surprise:
            allowed += ('push', 'suspend', 'complete', 'catalogue')
            if task.stack:
                allowed += ('cancel',)
                if task.stack[-1].status == 'complete':
                    allowed = ('look', 'stop', 'resume')
                elif task.stack[-1].status == 'suspended':
                    allowed = ('look', 'stop', 'resume', 'push', 'cancel')
        if task.status != 'active' and not surprise:
            allowed = ('look', 'stop', 'push') if task.status == 'complete' and task.unresolved else ('look', 'stop')
        from .history import public_task
        view, result, need, memory, resources = _compact_projection(task, observation, surprise)
        # Surprises and vector errors are evidence for the gameplay owner. They do not revoke its authority to
        # replan and act from the current frame; only hard lineage mismatch below remains a zero-input boundary.
        labels = [str(row.get('label', '')).strip().casefold() for row in observation.get('controls', ())]
        terminal_cleanup = screen.get('kind') == 'popup' and labels.count('zzzz') == 1
        if terminal_cleanup and 'act' not in allowed:
            # Involuntary pass-out supersedes the interrupted workflow. The exact singleton control is
            # independently revalidated by prepare/preflight and is already exempt from navigation beliefs.
            allowed += ('act',)
        sleep_required = any(str(reason).startswith('SLEEP_REQUIRED')
                             for reason in observation.get('interrupts', ()))
        if sleep_required and task.status == 'active' and 'push' not in allowed:
            allowed += ('push',)
        if lineage_mismatch:
            allowed = ('look', 'read', 'stop') + (('act',) if terminal_cleanup else ())
        c = TurnContext(task.turn_seq, public_task(task), thaw(task.active),
                        observation.get('screen'), observation.get('frame_path'), 'fresh',
                        observation.get('visible_affordances', ()), observation.get('graph_clues', ()),
                        {'targets': task.targets, 'covered': task.covered, 'unresolved': task.unresolved},
                        task.last_experience, surprise, observation.get('interrupts', ()), rec, allowed,
                        observation.get('vector_detections', ()), (), observation.get('vector_status'))
        c = replace(c, view_id=observation.get('view_id'), candidates=observation.get('candidates', ()),
                    controls=observation.get('controls', ()), view=view, result=result, need=need,
                    memory=memory, resources=resources, navigation=observation.get('navigation'),
                    belief=((observation.get('navigation') or {}).get('belief')),
                    observation_id=observation.get('observation_id'))
        task.current_turn = c.to_dict()
        self.store.save(task)
        self._log(task, c.turn_id, 'clues', screen=c.screen, frame_path=c.frame_path,
                  visible_affordances=c.visible_affordances, graph_clues=c.graph_clues,
                  coverage=c.coverage, transaction=c.transaction, interrupts=c.interrupts,
                  vector_detections=c.vector_detections, vector_status=c.vector_status,
                  view=c.view, result=c.result, need=c.need, memory=c.memory, resources=c.resources,
                  navigation=c.navigation, belief=c.belief, region=task.params.get('region'), task_status=task.status,
                  surprise=c.surprise, observation_id=c.observation_id)
        self._log(task, c.turn_id, 'recommendation', recommendation=rec)
        return c

    def _finish(self, task, recovered=False):
        """Complete or reconcile a write-ahead intent; never invoke perform here."""
        administrative = task.pending_intent is not None
        intent = task.pending_intent if administrative else task.active.pending_intent
        self._ensure_intent(task, intent, recovered=recovered)
        from .params import expectations
        from . import primitives
        invalid = None
        try:
            expected = expectations(intent.expects)
        except ValueError as error:
            invalid = error
        if intent.experience:
            e = X.Experience.from_dict(intent.experience)
        else:
            with timing_scope(turn_id=intent.turn_id, component='gameplay'), measure('turn.capture'):
                e = (primitives.invalid_expectation_outcome(intent, self.adapter, invalid) if invalid else
                     self.adapter.capture(intent, intent.before, expected))
            if intent.action.get('kind') == 'read':
                e = replace(e, evidence=_reconcile_observation(
                    task, e.evidence, self.store))
            intent.experience = e.to_dict()
        with measure('turn.persist_capture', turn_id=intent.turn_id, component='gameplay'):
            self.store.record_capture(task, intent, e.to_dict())
        with measure('turn.integrate', turn_id=intent.turn_id, component='gameplay'):
            result = I.apply(e, store=self.store)
        reconciliation = dict(e.evidence.state).get('observation_reconciliation')
        if reconciliation:
            self._log(task, intent.turn_id, 'observation_reconciliation', experience=e.id, **reconciliation)
            if reconciliation['result'] in ('guard_refusal_observed', 'verified_movement', 'verified_observation'):
                task.last_surprise = None
        # A projection/name alone cannot own an interaction. Only a positioned event can bind it.
        identity_conflict = None
        if not administrative and e.evidence.at and e.evidence.events:
            actual = e.evidence.node or I.event_node(e) or result.get('event_state') or result.get('card_state')
            if actual:
                previous = task.active.actual_node
                if previous and previous != actual:
                    identity_conflict = {'previous': previous, 'observed': actual, 'experience': e.id}
                    task.active.provisional['identity_conflict'] = identity_conflict
                else:
                    task.active.actual_node = actual
        if not administrative and e.id not in task.active.evidence_ids:
            task.active.evidence_ids.append(e.id)
        if not administrative and e.verdict.value == 'hit' and e.id not in task.active.completed_actions:
            task.active.completed_actions.append(e.id)
        task.last_experience = e.to_dict()
        if not task.stack:
            if e.id not in task.evidence_refs:
                task.evidence_refs.append(e.id)
        else:
            top = task.stack[-1]
            if e.id not in top.evidence_refs:
                top.evidence_refs.append(e.id)
            top.phase = 'verify'
        if self.reducer and not administrative:
            self.reducer(task, e)
        mismatch = 'invalid_expectations' if invalid else outcome_surprise(task, intent, e)
        if identity_conflict or recovered or mismatch or e.verdict.value in ('miss', 'unsafe') or result.get('errors'):
            task.last_surprise = Surprise.of(e, 'conflicting_positioned_identity' if identity_conflict else
                                             'pending_intent_reconciled' if recovered else
                                             'integration_error' if result.get('errors') else
                                             'mismatch' if e.verdict.value in ('miss', 'unsafe') else mismatch).to_dict()
        if administrative:
            task.pending_intent = None
        elif task.active:
            task.active.pending_intent = None
        task.current_turn = None
        task.revision += 1
        self.store.settle(task, intent, result)
        take_outcome = getattr(self.adapter, 'take_outcome_observation', None)
        return take_outcome(e.id) if take_outcome else None

    def context(self, observation=None):
        """Return the persisted turn, optionally consuming one already captured coherent observation."""
        with self.store.locked():
            task = self.store.load()
            cached = task.current_turn is not None
            if task.pending_intent or task.active and task.active.pending_intent:
                observation = self._rebound(task, self._finish(task, recovered=True))
                cached = False
            context = self._context(task, observation)
            if not cached:
                return context
            return replace(context, observation_freshness='cached')

    def _subgoal(self, task, decision):
        """Explicit durable model operations; verification folds captured evidence and performs no input."""
        from .play import bind_shop, register_catalogue, verify_completion
        from .params import validate
        if decision.kind == 'push':
            data = thaw(decision.action or {})
            if set(data) - {'goal', 'params'} or not data.get('goal') or not isinstance(data.get('params', {}), dict):
                raise DecisionRejected('push needs only goal and declared params')
            sleep_required = any(str(reason).startswith('SLEEP_REQUIRED')
                                 for reason in (task.current_turn or {}).get('interrupts', ()))
            if sleep_required and data['goal'] != 'sleep':
                raise DecisionRejected('late-clock surprise allows only the sleep subgoal')
            try:
                data['params'] = validate(data.get('params', {}), data['goal'], phase='subgoal')
            except ValueError as error:
                raise DecisionRejected(str(error)) from None
            if data['goal'] == 'shop':
                frames = {task.current_turn.get('frame_path')}
                if task.last_experience:
                    frames.update(task.last_experience['artifacts'].get('frames', ()))
                register_catalogue(task, data.get('params', {}), frames)
                bind_shop(task, data['params'])
            if task.stack:
                task.stack[-1].status = 'suspended'
            task.stack.append(Subgoal(data['goal'], data.get('params', {}), parent_interaction=task.active,
                                      started_turn=task.current_turn['turn_id']))
            task.active = None
            task.status = 'active'
        elif decision.kind == 'suspend':
            if not task.stack:
                raise DecisionRejected('suspend needs an active subgoal; push preserves the root interaction')
            task.stack[-1].status = 'suspended'
        elif decision.kind == 'cancel':
            if (not task.stack or task.stack[-1].status not in ('active', 'suspended') or decision.action is not None or
                    not isinstance(decision.rationale, str) or not decision.rationale.strip()):
                raise DecisionRejected('cancel needs an active/suspended child, a rationale and no action payload')
            top = task.stack[-1]
            if (task.pending_intent or task.active and task.active.pending_intent or
                    top.parent_interaction and top.parent_interaction.pending_intent):
                raise DecisionRejected('cancellation refuses pending/uncertain input')
            start = top.started_turn
            for key in ('_sale_intents', '_purchase_intents'):
                for reservation in task.params.get(key, ()):
                    tid = reservation.get('turn_id')
                    if start is None or type(tid) is not int or tid >= start:
                        raise DecisionRejected('cancellation refuses an attributable or unscoped financial reservation')
            try:
                rows = self._records(top.evidence_refs)
            except ValueError as error:
                raise DecisionRejected(f'cancellation cannot classify missing child evidence: {error}') from None
            if set(top.result) - {'outcomes'}:
                raise DecisionRejected('cancellation refuses completed domain proof')
            known = {row.get('experience', {}).get('id') for row in rows}
            if set(top.evidence_refs) - known:
                raise DecisionRejected('cancellation cannot classify missing child experience evidence')
            for row in rows:
                _cancellable_outcome(row)
            for completed in task.params.get('_subgoal_results', ()):
                try:
                    outcomes = self._records(completed.get('evidence_refs', ()))
                except ValueError as error:
                    raise DecisionRejected(f'cancellation cannot classify archived evidence: {error}') from None
                if not outcomes:
                    raise DecisionRejected('cancellation cannot attribute earlier domain results')
                for row in outcomes:
                    tid = row.get('experience', {}).get('artifacts', {}).get('turn_id')
                    if start is None or type(tid) is not int or tid >= start:
                        _cancellable_outcome(row)
            if task.active and (task.active.actual_node or task.active.provisional.get('facts') or
                                set(task.active.evidence_ids) - known or set(task.active.completed_actions) - known or
                                task.active.provisional.get('target_selected') and not rows):
                raise DecisionRejected('cancellation refuses an unclassified active domain interaction')
            task.params.setdefault('_cancelled_subgoals', []).append({
                'subgoal': thaw(top), 'status': 'cancelled', 'turn_id': task.current_turn['turn_id'],
                'rationale': decision.rationale.strip()})
            task.stack.pop()
            task.active = top.parent_interaction
            if task.stack:
                task.stack[-1].status = 'active'
            self._log(task, task.current_turn['turn_id'], 'cancellation', goal=top.goal, params=top.params,
                      started_turn=top.started_turn, remaining_subgoals=len(task.stack),
                      evidence_refs=top.evidence_refs, rationale=decision.rationale.strip())
        elif decision.kind == 'complete':
            current = task.stack[-1] if task.stack else task
            refs = current.evidence_refs if hasattr(current, 'evidence_refs') else task.evidence_refs
            try:
                outcomes = self._records(refs)
            except ValueError as error:
                raise DecisionRejected(f'completion cannot verify canonical evidence: {error}') from None
            navigation = (task.current_turn or {}).get('navigation') or {}
            graph = navigation.get('graph') or {}
            if (current.goal in ('navigate', 'enter', 'exit') and
                    navigation.get('status') == 'arrived' and
                    graph.get('current_source') == 'visible_affordance' and
                    not _frame_referenced((task.current_turn or {}).get('frame_path'), decision.evidence_refs)):
                raise DecisionRejected('visible-affordance completion needs the current full-scale frame evidence')
            result = verify_completion(task, current, outcomes, context=task.current_turn)
            if not task.stack:
                task.status = 'complete'
            else:
                current.result.update(result)
                current.status = 'complete'
                current.phase = 'verified'
                task.active = None
                if result.get('item') and result.get('acquired', 0) > 0:
                    item = result['item']
                    # Acquiring seeds removes only matching constraints, never garden action facts or coverage.
                    def matches(row):
                        return (row.get('reason') == 'seed_shortage' and row.get('item') == item)
                    task.unresolved = [row for row in task.unresolved if not matches(row)]
        elif decision.kind == 'resume':
            if not task.stack:
                raise DecisionRejected('resume needs a subgoal')
            top = task.stack[-1]
            if top.status == 'complete':
                task.stack.pop()
                task.active = top.parent_interaction
                task.params.setdefault('_subgoal_results', []).append(
                    {'goal': top.goal, 'params': top.params, 'evidence_refs': top.evidence_refs, 'result': top.result})
                if task.stack:
                    task.stack[-1].status = 'active'
            elif top.status == 'suspended':
                top.status = 'active'
            else:
                raise DecisionRejected('parent resumes only after verified subgoal completion')
        task.last_experience = None
        task.last_surprise = None

    def decide(self, turn_id, decision):
        from . import primitives
        with self.store.locked():
            task = self.store.load()
            if task.pending_intent or task.active and task.active.pending_intent:
                observation = self._rebound(task, self._finish(task, recovered=True))
                self._context(task, observation)
                raise StaleTurn('pending input reconciled; read the new context')
            if not task.current_turn or turn_id != task.current_turn['turn_id']:
                raise StaleTurn(f'turn {turn_id} is stale; request context')
            # Consume only the saved decision metadata. Public returns are still immutable TurnContexts,
            # but decoding the entire history again just to check a version/allowed kind is unnecessary.
            c = task.current_turn
            # Also accept this zero-input operation for a pre-upgrade persisted context (same task/turn).
            # No public action/correction/state payload can enter the authoritative reading.
            if decision.kind == 'read' and (decision.action is not None or decision.correction is not None):
                raise DecisionRejected('read accepts no action, correction or runtime state')
            if decision.kind not in ('accept', 'act') and decision.belief_update is not None:
                raise DecisionRejected('belief_update must be atomic with accept or act')
            if decision.kind not in c['allowed_decisions'] and not (decision.kind == 'read' and task.status == 'active'):
                raise DecisionRejected(f'{decision.kind} unavailable: {c["allowed_decisions"]}')
            self._log(task, turn_id, 'decision', decision=decision)
            if decision.kind == 'look':
                self._log(task, turn_id, 'vision', frame_path=c['frame_path'])
                return replace(TurnContext.from_dict(c), observation_freshness='cached')
            if decision.kind == 'stop':
                task.status = 'stopped'
            elif decision.kind == 'read':
                primitives.execute(self.store, task, turn_id, {'kind': 'read'}, {}, self.adapter,
                                   lambda phase, **kw: self._log(task, turn_id, phase, **kw), guard=self.guard)
                observation = self._rebound(task, self._finish(task))
                return self._context(task, observation)
            elif decision.kind == 'catalogue':
                from .params import catalogue_observation, fields, sequence, boolean
                from .play import register_catalogue
                try:
                    data = fields(thaw(decision.action), {'catalogue': sequence(catalogue_observation),
                                                        'catalogue_complete': boolean}, required=('catalogue',))
                except ValueError as error:
                    raise DecisionRejected(str(error)) from None
                frames = {c['frame_path']}
                if task.last_experience:
                    frames.update(task.last_experience['artifacts'].get('frames', ()))
                register_catalogue(task, data, frames)
                self._log(task, turn_id, 'catalogue', **data)
            elif decision.kind in ('push', 'suspend', 'complete', 'resume', 'cancel'):
                self._subgoal(task, decision)
            elif decision.kind == 'correct':
                correction = thaw(decision.correction or {})
                kind, data = correction.get('kind'), correction.get('data', {})
                e = X.Experience.from_dict(task.last_experience)
                if kind == 'route_transition':
                    before, after = dict(e.before.state), dict(e.evidence.state)
                    navigation = before.get('navigation') or {}
                    path = ((navigation.get('graph') or {}).get('path') or ())
                    region = after.get('region') or after.get('scene')
                    from .navigation import _load_graph
                    graph = _load_graph(after)
                    matched = next(((a, b) for a, b in zip(path, path[1:])
                                    for edge in graph.edges(a, 'nav')
                                    if edge.get('b') == b and edge.get('transition') == region), None)
                    if not matched or region == (before.get('region') or before.get('scene')):
                        raise DecisionRejected('route_transition needs a captured new region matching the resolved path')
                    current = task.stack[-1] if task.stack and task.stack[-1].goal == 'navigate' else task
                    current.params['_nav_current'] = matched[1]
                    current.params['_nav_current_proof'] = {
                        'source': 'transition', 'experience': e.id, 'region': region}
                    result = {'applied': 1, 'status': 'route_transition', 'node': matched[1], 'region': region}
                    self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                    task.last_surprise = None
                    task.current_turn = None
                    self.store.save(task)
                    return self._context(task)
                if kind == 'route_step':
                    before = dict(e.before.state)
                    navigation = before.get('navigation') or {}
                    edge = navigation.get('next_edge') or {}
                    node = data.get('node')
                    if (node != edge.get('to') or not edge.get('navigation_only') or e.evidence.moved is not True or
                            not e.action or e.action.kind != 'click' or e.action.what != 'step'):
                        raise DecisionRejected('route_step needs moved waypoint evidence for the current navigation-only node')
                    current = task.stack[-1] if task.stack and task.stack[-1].goal == 'navigate' else task
                    current.params['_nav_current'] = node
                    current.params['_nav_current_proof'] = {
                        'source': 'navigation_step', 'experience': e.id,
                        'region': dict(e.evidence.state).get('region')}
                    result = {'applied': 1, 'status': 'route_step', 'node': node}
                    self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                    task.last_surprise = None
                    task.current_turn = None
                    self.store.save(task)
                    return self._context(task)
                if kind == 'screen':
                    frame_path = data.get('frame_path')
                    region = data.get('region')
                    frame_referenced = any(
                        ref == frame_path or (isinstance(ref, str) and isinstance(frame_path, str) and
                                              os.path.basename(ref) == os.path.basename(frame_path))
                        for ref in decision.evidence_refs)
                    if ((c.get('screen') or {}).get('kind') != 'unknown' or data.get('kind') != 'gameplay' or
                            frame_path != c.get('frame_path') or not isinstance(region, str) or not region or
                            not frame_referenced):
                        raise DecisionRejected('screen correction needs current unknown frame, gameplay, region and evidence ref')
                    task.params['_screen_hint'] = {
                        'kind': 'gameplay', 'region': region, 'frame_path': frame_path,
                        'set_turn': turn_id, 'expires_turn': turn_id + 2}
                    result = {'applied': 1, 'status': 'screen', 'hint': dict(task.params['_screen_hint'])}
                    self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                    task.last_surprise = None
                    task.current_turn = None
                    self.store.save(task)
                    return self._context(task)
                if kind == 'route':
                    from .navigation import map_route, map_target
                    frame_path = data.get('frame_path')
                    region = data.get('region')
                    frames = {e.artifacts.img0, *e.artifacts.frames, c.get('frame_path')} - {None}
                    navigation = c.get('navigation') or {}
                    goal = (navigation.get('goal') or {}).get('node')
                    target = map_target(navigation)
                    if (data.get('target') != target or not isinstance(region, str) or not region or frame_path not in frames or
                            (c.get('screen') or {}).get('kind') != 'map'):
                        raise DecisionRejected('route correction needs current map frame, region and map-labeled target')
                    try:
                        derived = map_route(data.get('origin_point'), data.get('target_point'))
                    except ValueError as exc:
                        raise DecisionRejected(str(exc)) from exc
                    ttl = data.get('expires_after_turns', 6)
                    if type(ttl) is not int or not 1 <= ttl <= 12:
                        raise DecisionRejected('route correction expiry must be 1..12 turns')
                    owner = _navigation_owner(task)
                    if owner is None:
                        raise DecisionRejected('route correction needs an active navigation task')
                    owner.params['_route_hint'] = {
                        **derived, 'target': target, 'ultimate_goal': goal, 'region': region,
                        'frame_path': frame_path, 'set_turn': turn_id, 'expires_turn': turn_id + ttl,
                        'remaining_steps': ttl, 'source': 'model_map'}
                    if owner is not task:
                        task.params.pop('_route_hint', None)  # repair pre-fix corrections on the wrong stack frame
                    result = {'applied': 1, 'status': 'route', 'route': dict(owner.params['_route_hint'])}
                    self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                    task.last_surprise = None
                    task.current_turn = None
                    self.store.save(task)
                    return self._context(task)
                if kind == 'route_clear':
                    current = task.stack[-1] if task.stack and task.stack[-1].goal == 'navigate' else task
                    hint = current.params.get('_route_hint')
                    reason = data.get('reason')
                    frame_path = data.get('frame_path')
                    if (not hint or not isinstance(reason, str) or not reason.strip() or
                            frame_path != c.get('frame_path') or
                            not any(ref == frame_path or (isinstance(ref, str) and
                                    os.path.basename(ref) == os.path.basename(frame_path))
                                    for ref in decision.evidence_refs)):
                        raise DecisionRejected(
                            'route_clear needs active hint, reason, current frame and frame evidence')
                    removed = current.params.pop('_route_hint')
                    result = {'applied': 1, 'status': 'route_clear', 'removed': removed,
                              'reason': reason.strip()}
                    self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                    task.last_surprise = None
                    task.current_turn = None
                    self.store.save(task)
                    return self._context(task)
                if kind == 'blocked_target':
                    active = task.active
                    reason = data.get('reason')
                    if (not active or not active.actual_node or active.actual_node not in task.targets or
                            data.get('node') != active.actual_node or not isinstance(reason, str) or not reason.strip()):
                        raise DecisionRejected('blocked_target needs the active event-owned target and a nonempty reason')
                    item = data.get('item')
                    if reason.strip() == 'seed_shortage' and (not isinstance(item, str) or not item.strip()):
                        raise DecisionRejected('seed_shortage needs the exact inventory seed item')
                    data = {'node': active.actual_node, 'phase': active.phase, 'crop': active.crop,
                            'transaction_id': active.transaction_id, 'reason': reason.strip(),
                            'experience': e.id, 'evidence_refs': list(decision.evidence_refs) or [e.id, c['frame_path']]}
                if kind == 'blocked_target' and item:
                    data['item'] = item
                if kind in ('graph', 'appearance'):
                    data.setdefault('frame_path', e.artifacts.frames[-1] if e.artifacts.frames else e.artifacts.img0)
                    data.setdefault('rationale', decision.rationale)
                    data.setdefault('evidence_refs', list(decision.evidence_refs) or [e.id, c['frame_path']])
                result = I.correct(e, kind, data, store=self.store)
                self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                if result.get('errors'):
                    raise DecisionRejected(f'correction failed: {result["errors"]}')
                if kind in ('unresolved', 'human'):
                    task.unresolved.append({'experience': e.id, **data})
                    task.status = 'unresolved'
                if kind == 'blocked_target':
                    task.unresolved.append(data)
                    task.active = None
                    task.finish_if_accounted()
                if kind == 'stop':
                    task.status = 'stopped'
                task.last_surprise = None
            else:
                action = thaw(c['recommendation']['action'] if decision.kind == 'accept' else decision.action)
                if not action:
                    raise DecisionRejected('no action recommended or supplied')
                action, belief = _apply_navigation_belief(task, c, decision, action)
                expected = thaw(c['recommendation'].get('expects') or {}) if decision.kind == 'accept' else action.pop('expects', {})
                from .params import expectations
                try:
                    expected = expectations(expected)
                except ValueError as error:
                    raise DecisionRejected(str(error)) from None
                primitives.execute(self.store, task, turn_id, action, expected, self.adapter,
                                   lambda phase, **kw: self._log(task, turn_id, phase, **kw), guard=self.guard)
                if belief:
                    self._log(task, turn_id, 'belief', belief=belief,
                              action={'kind': action.get('kind'), 'objective': action.get('objective'),
                                      'belief_revision': action.get('belief_revision')})
                observation = self._rebound(task, self._finish(task))
                return self._context(task, observation)
            task.current_turn = None
            task.revision += 1
            self.store.save(task)
            return self._context(task)
