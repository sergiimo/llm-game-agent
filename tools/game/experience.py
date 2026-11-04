"""EXPERIENCE: one immutable record per attempted action (spec docs/superpowers/specs/2026-11-04-unified-improvement-
loop-refactor.md): goal -> prediction -> action -> evidence -> verdict -> correction.

Structured data only (no formatted explanations); tuples, so records are hashable and compare by value. The id is a
content hash of the action and its evidence (log mark, lines, frames, capture time): stable for a recorded attempt,
different between attempts; every consumer records it so a replay never applies the same update twice."""
import dataclasses
import hashlib
import json
from dataclasses import dataclass, field


def _t(v):
    """Lists -> tuples (recursively): records stay immutable and hashable."""
    if isinstance(v, (list, tuple)):
        return tuple(_t(x) for x in v)
    return v


@dataclass(frozen=True)
class GoalRef:
    name: str = None
    params: tuple = ()          # ((key, value), ...)
    target: str = None          # the target node id
    row: str = None             # the transition row
    step: int = None            # the row's step index


@dataclass(frozen=True)
class Observation:
    screen: str = None          # screen mode before
    affordances: tuple = ()     # visible bubbles before (str)
    state: tuple = ()           # relevant world state ((key, value), ...)


@dataclass(frozen=True)
class Prediction:
    events: tuple = ()          # expected events (alternatives 'a|b')
    card: str = None            # expected card text
    log: str = None             # expected log regex
    moved: bool = None          # a walk: she moves
    arrive: str = None          # a walk toward a kind: its bubble/event shows
    delta: tuple = ()           # expected state change ((key, value), ...)


@dataclass(frozen=True)
class Action:
    kind: str                   # click | press | space | pick | close | cell | read
    what: str = None            # click: bubble | point | step | explore | soil | object; press: the label
    pt: tuple = None
    arg: str = None
    context: tuple = ()         # ((key, value), ...): det_box, det_kind, toward, target, here


@dataclass(frozen=True)
class Evidence:
    lines: tuple = ()
    events: tuple = ()
    at: tuple = None
    node: str = None
    mode: str = None
    texts: tuple = ()
    burst_texts: tuple = ()
    after: tuple = ()           # bubbles after (str)
    moved: bool = None


@dataclass(frozen=True)
class Check:
    field: str
    expected: object
    got: object
    ok: bool                    # None = a gap ('?': observe, never a failure)


@dataclass(frozen=True)
class Verdict:
    value: str = 'unknown'      # hit | miss | unknown | unsafe
    checks: tuple = ()          # (Check, ...)


@dataclass(frozen=True)
class Discrepancy:
    field: str
    expected: object
    got: object
    representable: bool = True  # the system can represent the correction now (else: a gap bundle)


@dataclass(frozen=True)
class Artifacts:
    frames: tuple = ()          # burst frame paths
    img0: str = None            # the frame before the click (bubble / answer / detection clicks)
    run_dir: str = None
    log_mark: int = None
    t: float = None             # capture time (s)


FIELDS = ('goal', 'before', 'prediction', 'action', 'evidence', 'verdict', 'discrepancy', 'artifacts')
_TYPES = {'goal': GoalRef, 'before': Observation, 'prediction': Prediction, 'action': Action, 'evidence': Evidence,
          'verdict': Verdict, 'discrepancy': Discrepancy, 'artifacts': Artifacts}


def _hash(d):
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Experience:
    id: str
    goal: GoalRef = field(default_factory=GoalRef)
    before: Observation = field(default_factory=Observation)
    prediction: Prediction = field(default_factory=Prediction)
    action: Action = None
    evidence: Evidence = field(default_factory=Evidence)
    verdict: Verdict = field(default_factory=Verdict)
    discrepancy: Discrepancy = None
    artifacts: Artifacts = field(default_factory=Artifacts)

    @staticmethod
    def new(**kw):
        """A record with its content id (the action + evidence + artifacts identify the attempt)."""
        parts = {k: (dataclasses.asdict(kw[k]) if kw.get(k) is not None else None)
                 for k in ('action', 'evidence', 'artifacts')}
        return Experience(id=_hash(parts), **{k: kw[k] for k in FIELDS if k in kw})

    def to_dict(self):
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d):
        kw = {}
        for k in FIELDS:
            v = d.get(k)
            if v is None:
                kw[k] = None if k == 'discrepancy' else _TYPES[k]()
                continue
            if k == 'verdict':
                kw[k] = Verdict(v.get('value', 'unknown'), tuple(Check(**c) for c in v.get('checks') or ()))
            else:
                kw[k] = _TYPES[k](**{f: _t(x) for f, x in v.items()})
        return Experience(id=d['id'], **kw)


# ---- corrections ----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Update:
    consumer: str               # world | evals | memory | transitions | gap
    op: str                     # e.g. card_state, bubble_label, answer_look, relabel, direction, observation, bundle
    args: dict = field(default_factory=dict, hash=False, compare=True)

    def key(self, exp_id):
        """The update's identity: applied once per experience (idempotent replay)."""
        return f'{exp_id}:{self.consumer}:{self.op}:' + json.dumps(self.args, sort_keys=True, default=str)


ORDER = ('world', 'evals', 'memory', 'transitions', 'gap')   # spec: facts, scores, memory, journal, escalation


@dataclass(frozen=True)
class Correction:
    experience: str
    world: tuple = ()
    evals: tuple = ()
    memory: tuple = ()
    transitions: tuple = ()
    gap: tuple = ()

    def updates(self):
        """Every update in the commit order."""
        return [u for c in ORDER for u in getattr(self, c)]
