"""One durable model decision. Policy supplies recommendations; only decide can execute input."""
import json
import os
import time
from dataclasses import dataclass, fields

from . import experience as X, integrate as I
from .task_state import freeze, thaw


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
        if task.status != 'active':
            allowed = ('look', 'stop')
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
        intent = task.active.pending_intent
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
        if e.evidence.at and e.evidence.events:
            actual = I.event_node(e) or result.get('event_state') or result.get('card_state') or e.evidence.node
            if actual:
                previous = task.active.actual_node
                if previous and previous != actual:
                    identity_conflict = {'previous': previous, 'observed': actual, 'experience': e.id}
                    task.active.provisional['identity_conflict'] = identity_conflict
                else:
                    task.active.actual_node = actual
        if e.id not in task.active.evidence_ids:
            task.active.evidence_ids.append(e.id)
        if e.verdict.value == 'hit' and e.id not in task.active.completed_actions:
            task.active.completed_actions.append(e.id)
        task.last_experience = e.to_dict()
        if self.reducer:
            self.reducer(task, e)
        if identity_conflict or recovered or e.verdict.value in ('miss', 'unsafe') or result.get('errors'):
            task.last_surprise = Surprise.of(e, 'conflicting_positioned_identity' if identity_conflict else
                                             'pending_intent_reconciled' if recovered else
                                             'integration_error' if result.get('errors') else 'mismatch').to_dict()
        if task.active:
            task.active.pending_intent = None
        task.current_turn = None
        task.revision += 1
        self.store.save(task)

    def context(self):
        with self.store.locked():
            task = self.store.load()
            if task.active and task.active.pending_intent:
                self._finish(task, recovered=True)
            return self._context(task)

    def decide(self, turn_id, decision):
        from . import primitives
        with self.store.locked():
            task = self.store.load()
            if task.active and task.active.pending_intent:
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
            elif decision.kind == 'correct':
                correction = thaw(decision.correction or {})
                kind, data = correction.get('kind'), correction.get('data', {})
                e = X.Experience.from_dict(task.last_experience)
                result = I.correct(e, kind, data)
                self._log(task, turn_id, 'correction', experience=e.id, kind=kind, data=data, result=result)
                if result.get('errors'):
                    raise DecisionRejected(f'correction failed: {result["errors"]}')
                if kind == 'unresolved':
                    task.unresolved.append({'experience': e.id, **data})
                    task.status = 'unresolved'
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
