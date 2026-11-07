"""Durable task/transaction state. Replacement is atomic; the lock spans each turn."""
import dataclasses
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
from runtime.timing import measure

_STATE_RECORDS = ()

def freeze(value):
    kind = type(value)
    if kind in (str, int, float, bool, type(None)):
        return value
    if kind is dict or kind is MappingProxyType:
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if kind is list or kind is tuple:
        return tuple(freeze(v) for v in value)
    if isinstance(value, _STATE_RECORDS):
        return MappingProxyType({f.name: freeze(getattr(value, f.name)) for f in dataclasses.fields(value)})
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    kind = type(value)
    if kind in (str, int, float, bool, type(None)):
        return value
    if kind is dict or kind is MappingProxyType:
        return {k: thaw(v) for k, v in value.items()}
    if kind is list or kind is tuple:
        return [thaw(v) for v in value]
    if dataclasses.is_dataclass(value):
        return {f.name: thaw(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def json_record(value):
    """Expose only record/container edges; the JSON C encoder traverses ordinary evidence scalars."""
    if dataclasses.is_dataclass(value):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')


@dataclass
class Intent:
    turn_id: int
    action: dict
    log_mark: int
    written_at: float
    before: dict = field(default_factory=dict)
    expects: dict = field(default_factory=dict)
    experience: dict = None  # write-ahead outcome: replay integration without recapturing
    provenance: dict = field(default_factory=dict)  # originating boundary/adapter/preparation; legacy missing = unknown
    journaled: bool = False  # canonical intent append completed; false is safe and repaired on recovery


@dataclass
class Interaction:
    transaction_id: str
    phase: str = 'approach'
    provisional: dict = field(default_factory=dict)
    actual_node: str = None
    crop: str = None
    evidence_ids: list = field(default_factory=list)
    completed_actions: list = field(default_factory=list)
    pending_intent: Intent = None


@dataclass
class Subgoal:
    goal: object
    params: dict = field(default_factory=dict)
    phase: str = 'observe'
    status: str = 'active'
    parent_interaction: Interaction = None
    evidence_refs: list = field(default_factory=list)
    result: dict = field(default_factory=dict)
    started_turn: int = None  # root-relative version boundary; older saved children have unknown attribution


def interaction(data):
    if not data:
        return None
    data = dict(data)
    if data.get('pending_intent'):
        data['pending_intent'] = Intent(**data['pending_intent'])
    return Interaction(**data)


@dataclass
class TaskState:
    task_id: str
    goal: str
    params: dict = field(default_factory=dict)
    revision: int = 0
    status: str = 'active'
    targets: list = field(default_factory=list)
    covered: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    active: Interaction = None
    last_experience: dict = None
    last_surprise: dict = None
    global_interrupt: object = None
    turn_seq: int = 0
    current_turn: dict = None
    pending_intent: Intent = None  # administrative input, independent of an object interaction
    stack: list[Subgoal] = field(default_factory=list)
    evidence_refs: list = field(default_factory=list)
    history_schema: int = 2

    def to_dict(self):
        return thaw(self)

    def snapshot(self, **overrides):
        """Complete immutable guard/policy view in one traversal, without an intermediate mutable copy."""
        return freeze({f.name: getattr(self, f.name) for f in dataclasses.fields(self)} | overrides)

    def finish_if_accounted(self):
        """Complete accounting, not successful work: blocked targets remain explicitly unresolved."""
        blocked = {row['node'] for row in self.unresolved
                   if isinstance(row, dict) and row.get('node') and row.get('reason')}
        if self.active is None and set(self.targets) <= set(self.covered) | blocked:
            self.status = 'complete'

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data.setdefault('history_schema', 1)  # pre-compact persisted tasks embedded complete outcome bodies
        if data.get('pending_intent'):
            data['pending_intent'] = Intent(**data['pending_intent'])
        data['active'] = interaction(data.get('active'))
        data['stack'] = [Subgoal(**dict(row, parent_interaction=interaction(row.get('parent_interaction'))))
                         for row in data.get('stack', [])]
        return cls(**data)


_STATE_RECORDS = (Intent, Interaction, Subgoal, TaskState)


class TaskStore:
    def __init__(self, path):
        self.path = os.path.abspath(path)

    @contextmanager
    def locked(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def create(self, task):
        with self.locked():
            if os.path.exists(self.path):
                raise FileExistsError(self.path)
            self.save(task)
        return task

    def load(self):
        with measure('task.load'), open(self.path) as f:
            return TaskState.from_dict(json.load(f))

    def compact(self):
        """Atomically migrate reconstructible inline history to journal references once."""
        from . import history
        with self.locked():
            task = self.load()
            changed = history.compact(task, os.path.join(os.path.dirname(self.path), 'log.jsonl'))
            if changed:
                self.save(task)
            return changed

    def save(self, task):
        """Caller holds locked() when reading/modifying a task. A crash leaves the old or new JSON."""
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.task-', suffix='.json', dir=directory)
        try:
            with os.fdopen(fd, 'w') as f:
                with measure('task.serialize'):
                    # One-shot encoding uses the JSON C encoder. Streaming dump emits a write for nearly
                    # every historical scalar and makes a large long-running task miss the RPC deadline.
                    f.write(json.dumps(task, default=json_record, sort_keys=True))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
