"""One durable model decision. Policy supplies recommendations; only decide can execute input."""
import json
import os
import time
from dataclasses import dataclass, fields

from . import experience as X, integrate as I
from .task_state import Subgoal, freeze, thaw


class StaleTurn(ValueError):
    pass


class DecisionRejected(ValueError):
    pass


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
    rationale: str = 'model_choice'
    evidence_refs: tuple = ()


@dataclass(frozen=True)
class Surprise(Snapshot):
    experience_id: str
    before: object
    intended: object
    expected: object
    actual: object
    artifacts: object
    reason: str = 'mismatch'

    @classmethod
    def of(cls, e, reason='mismatch'):
        return cls(e.id, thaw(e.before), thaw(e.action), thaw(e.prediction), thaw(e.evidence), thaw(e.artifacts), reason)


@dataclass(frozen=True)
class TurnContext(Snapshot):
    turn_id: int
    task: object
    transaction: object
    screen: object
    frame_path: str
    visible_affordances: tuple
    graph_clues: tuple
    coverage: object
    last_outcome: object
    surprise: object
    interrupts: tuple
    recommendation: Recommendation
    allowed_decisions: tuple

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d['recommendation'] = Recommendation(**d['recommendation'])
        if d.get('surprise'):
            d['surprise'] = Surprise(**d['surprise'])
        return cls(**d)


def outcome_surprise(task, intent, e):
    """Compare one immutable outcome to the active goal, never equate camera movement with progress."""
    import math
    current = task.stack[-1] if task.stack else task
    params, goal = current.params, current.goal
    expected, before, after = intent.expects, intent.before, dict(e.evidence.state)
    for key in ('region', 'node'):
        want = expected.get(key)
        got = after.get(key) if key == 'region' else (I.event_node(e) or e.evidence.node)
        if want is not None and got != want:
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
    # A new card is a relevant observation of a model-selected interaction even before its object is bound.
    changed_card = (e.evidence.mode in ('card', 'picker') and bool(e.evidence.texts) and
                    tuple(e.evidence.texts) != tuple((before.get('screen') or {}).get('texts') or ()))
    garden_event = goal == 'garden' and bool(set(e.evidence.events) & {
        'inspect', 'unplant', 'unplant_impl', 'plant', 'plant_growing', 'water', 'hazel_waterplant',
        'harvest', 'grab_item', 'beehive_collect', 'beehive_progress'})
    purchase = intent.action.get('purchase')
    receipt = False
    if purchase:
        item = purchase['item']
        old_count, count = before.get('inventory', {}).get(item), after.get('inventory', {}).get(item)
        old_money, money = before.get('money'), after.get('money')
        receipt = (None not in (old_count, count, old_money, money) and
                   count - old_count == purchase['quantity'] and old_money - money == purchase['price'])
    closed = intent.action.get('kind') == 'close' and changed_mode and e.evidence.mode == 'gameplay'
    sleep_event = goal == 'sleep' and 'sleep_transition' in e.evidence.events
    relevant = (matched_event or matched_card or matched_mode or matched_log or changed_card or garden_event or
                receipt or closed or sleep_event)
    if expected.get('region') and after.get('region') == expected['region']:
        relevant = True
    walking = intent.action.get('kind') == 'waypoint'
    if e.evidence.moved is False and not relevant and intent.action.get('kind') != 'close':
        return 'no_progress'
    if walking or e.evidence.moved:
        destination = expected.get('destination_position', params.get('destination_position'))
        old_pos, new_pos = before.get('position'), after.get('position')
        reduction = (destination is not None and old_pos is not None and new_pos is not None and
                     math.dist(new_pos, destination) < math.dist(old_pos, destination) - .01)
        if not reduction and not relevant:
            return 'irrelevant_movement' if e.evidence.moved else 'missing_progress_evidence'
        relevant = relevant or reduction
    if not relevant:
        return 'unexpected_evidence' if e.evidence.events or changed_mode else 'missing_evidence'
    return None


class TurnLoop:
    """adapter: observe/mark/prepare/perform/capture; policy(task snapshot, clues) is input-free.

    Optional reducer(task, integrated_experience) only folds domain evidence into durable state. It must be
    idempotent, perform no input, and never choose a target or execute a follow-up action.

    The task file lives in the active run directory; its sibling log.jsonl is the turn timeline.
    A persisted context is returned unchanged until consumed, so accept always refers to exact saved data.
    """
    def __init__(self, store, adapter=None, policy=None, reducer=None, guard=None):
        from .primitives import GameAdapter
        self.store, self.adapter = store, adapter or GameAdapter()
        self.policy = policy or (lambda task, obs: Recommendation())
        self.reducer = reducer  # evidence-only domain state update; never input or target selection
        self.guard = guard  # optional pure transaction invariant, checked before any primitive input

    def _log(self, task, turn_id, phase, **data):
        path = os.path.join(os.path.dirname(self.store.path), 'log.jsonl')
        with open(path, 'a') as f:
            f.write(json.dumps({'t': time.time(), 'type': 'turn', 'task_id': task.task_id,
                                'turn_id': turn_id, 'phase': phase, **thaw(data)}) + '\n')
            f.flush()

    def _context(self, task):
        if task.current_turn is not None:
            return TurnContext.from_dict(task.current_turn)
        observation = self.adapter.observe()
        task.turn_seq += 1
        task.revision += 1
        rec = self.policy(freeze(task.to_dict()), freeze(observation))
        surprise = Surprise(**task.last_surprise) if task.last_surprise else None
        allowed = ('look', 'correct', 'stop') if surprise else ('accept', 'act', 'look', 'stop')
        if not surprise and task.last_experience:
            allowed += ('correct',)  # explicit model resolution also covers ambiguous, non-mismatching outcomes
        if not surprise:
            allowed += ('push', 'suspend', 'complete')
            if task.stack:
                if task.stack[-1].status == 'complete':
                    allowed = ('look', 'stop', 'resume')
                elif task.stack[-1].status == 'suspended':
                    allowed = ('look', 'stop', 'resume', 'push')
        if task.status != 'active' and not surprise:
            allowed = ('look', 'stop', 'push') if task.status == 'complete' and task.unresolved else ('look', 'stop')
        c = TurnContext(task.turn_seq, task.to_dict() | {'current_turn': None}, thaw(task.active),
                        observation.get('screen'), observation.get('frame_path'),
                        observation.get('visible_affordances', ()), observation.get('graph_clues', ()),
                        {'targets': task.targets, 'covered': task.covered, 'unresolved': task.unresolved},
                        task.last_experience, surprise, observation.get('interrupts', ()), rec, allowed)
        task.current_turn = c.to_dict()
        self.store.save(task)
        self._log(task, c.turn_id, 'clues', screen=c.screen, frame_path=c.frame_path,
                  visible_affordances=c.visible_affordances, graph_clues=c.graph_clues,
                  coverage=c.coverage, transaction=c.transaction, interrupts=c.interrupts,
                  region=task.params.get('region'), task_status=task.status, surprise=c.surprise)
        self._log(task, c.turn_id, 'recommendation', recommendation=rec)
        return c

    def _finish(self, task, recovered=False):
        """Complete or reconcile a write-ahead intent; never invoke perform here."""
        administrative = task.pending_intent is not None
        intent = task.pending_intent if administrative else task.active.pending_intent
        if intent.experience:
            e = X.Experience.from_dict(intent.experience)
        else:
            e = self.adapter.capture(intent, intent.before, intent.expects)
            intent.experience = e.to_dict()
            self.store.save(task)  # stable experience ID if integration or final save crashes
        self._log(task, intent.turn_id, 'outcome', experience=e.to_dict(), recovered=recovered)
        result = I.apply(e)
        self._log(task, intent.turn_id, 'integration', experience=e.id, result=result)
        # A projection/name alone cannot own an interaction. Only a positioned event can bind it.
        identity_conflict = None
        if not administrative and e.evidence.at and e.evidence.events:
            actual = I.event_node(e) or result.get('event_state') or result.get('card_state') or e.evidence.node
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
            rows = task.params.setdefault('_outcomes', [])
            if not any(row['experience']['id'] == e.id for row in rows):
                rows.append({'experience': e.to_dict(), 'before': intent.before, 'action': intent.action})
        if task.stack:
            top = task.stack[-1]
            if e.id not in top.evidence_refs:
                top.evidence_refs.append(e.id)
                top.result.setdefault('outcomes', []).append({'experience': e.to_dict(), 'before': intent.before,
                                                            'action': intent.action})
            top.phase = 'verify'
        if self.reducer and not administrative:
            self.reducer(task, e)
        mismatch = outcome_surprise(task, intent, e)
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
        self.store.save(task)

    def context(self):
        with self.store.locked():
            task = self.store.load()
            if task.pending_intent or task.active and task.active.pending_intent:
                self._finish(task, recovered=True)
            return self._context(task)

    def _subgoal(self, task, decision):
        """Explicit durable model operations; verification folds captured evidence and performs no input."""
        from .play import verify_completion
        if decision.kind == 'push':
            data = thaw(decision.action or {})
            if not data.get('goal') or not isinstance(data.get('params', {}), dict):
                raise DecisionRejected('push needs goal and params')
            if task.stack:
                task.stack[-1].status = 'suspended'
            task.stack.append(Subgoal(data['goal'], data.get('params', {}), parent_interaction=task.active))
            task.active = None
            task.status = 'active'
        elif decision.kind == 'suspend':
            if not task.stack:
                raise DecisionRejected('suspend needs an active subgoal; push preserves the root interaction')
            task.stack[-1].status = 'suspended'
        elif decision.kind == 'complete':
            current = task.stack[-1] if task.stack else task
            result = verify_completion(task, current)
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
                self._finish(task, recovered=True)
                self._context(task)
                raise StaleTurn('pending input reconciled; read the new context')
            if not task.current_turn or turn_id != task.current_turn['turn_id']:
                raise StaleTurn(f'turn {turn_id} is stale; request context')
            c = TurnContext.from_dict(task.current_turn)
            if decision.kind not in c.allowed_decisions:
                raise DecisionRejected(f'{decision.kind} unavailable: {c.allowed_decisions}')
            self._log(task, turn_id, 'decision', decision=decision)
            if decision.kind == 'look':
                self._log(task, turn_id, 'vision', frame_path=c.frame_path)
                return c
            if decision.kind == 'stop':
                task.status = 'stopped'
            elif decision.kind in ('push', 'suspend', 'complete', 'resume'):
                self._subgoal(task, decision)
            elif decision.kind == 'correct':
                correction = thaw(decision.correction or {})
                kind, data = correction.get('kind'), correction.get('data', {})
                e = X.Experience.from_dict(task.last_experience)
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
                            'experience': e.id, 'evidence_refs': list(decision.evidence_refs) or [e.id, c.frame_path]}
                if kind == 'blocked_target' and item:
                    data['item'] = item
                if kind in ('graph', 'appearance'):
                    data.setdefault('frame_path', e.artifacts.frames[-1] if e.artifacts.frames else e.artifacts.img0)
                    data.setdefault('rationale', decision.rationale)
                    data.setdefault('evidence_refs', list(decision.evidence_refs) or [e.id, c.frame_path])
                result = I.correct(e, kind, data)
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
                action = thaw(c.recommendation.action if decision.kind == 'accept' else decision.action)
                if not action:
                    raise DecisionRejected('no action recommended or supplied')
                expected = thaw(c.recommendation.expects or {}) if decision.kind == 'accept' else action.pop('expects', {})
                primitives.execute(self.store, task, turn_id, action, expected, self.adapter,
                                   lambda phase, **kw: self._log(task, turn_id, phase, **kw), guard=self.guard)
                self._finish(task)
                return self._context(task)
            task.current_turn = None
            task.revision += 1
            self.store.save(task)
            return self._context(task)
