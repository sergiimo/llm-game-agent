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


def freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if dataclasses.is_dataclass(value):
        return {f.name: thaw(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


@dataclass
class Intent:
    turn_id: int
    action: dict
    log_mark: int
    written_at: float
    before: dict = field(default_factory=dict)
    expects: dict = field(default_factory=dict)
    experience: dict = None  # write-ahead outcome: replay integration without recapturing


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

    def to_dict(self):
        return thaw(self)

    def finish_if_accounted(self):
        """Complete accounting, not successful work: blocked targets remain explicitly unresolved."""
        blocked = {row['node'] for row in self.unresolved
                   if isinstance(row, dict) and row.get('node') and row.get('reason')}
        if self.active is None and set(self.targets) <= set(self.covered) | blocked:
            self.status = 'complete'

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        if data.get('pending_intent'):
            data['pending_intent'] = Intent(**data['pending_intent'])
        data['active'] = interaction(data.get('active'))
        data['stack'] = [Subgoal(**dict(row, parent_interaction=interaction(row.get('parent_interaction'))))
                         for row in data.get('stack', [])]
        return cls(**data)


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
        with open(self.path) as f:
            return TaskState.from_dict(json.load(f))

    def save(self, task):
        """Caller holds locked() when reading/modifying a task. A crash leaves the old or new JSON."""
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.task-', suffix='.json', dir=directory)
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(task.to_dict(), f, sort_keys=True)
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
