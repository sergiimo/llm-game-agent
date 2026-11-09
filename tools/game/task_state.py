"""Durable task/transaction state in the canonical SQLite runtime store."""
import dataclasses
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
from runtime.timing import measure
from runtime.db import Database

_STATE_RECORDS = ()


class StaleTask(RuntimeError):
    pass

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
    """One run's task state and write-ahead intents.

    The path-only constructor remains as an in-memory test/legacy-fixture adapter: it maps that identity to a
    SQLite database beside the requested path but never creates the JSON file.
    """
    _locks = {}
    _locks_guard = threading.Lock()

    def __init__(self, db, run_id=None):
        if isinstance(db, Database):
            if not run_id:
                raise ValueError('run_id is required with Database')
            self.db, self.run_id = db, run_id
            with self.db.connect() as connection:
                row = connection.execute('SELECT directory FROM runs WHERE id = ?', (run_id,)).fetchone()
            if not row:
                raise KeyError(f'unknown run: {run_id}')
            self.run_dir = row['directory']
            self.path = os.path.join(self.run_dir, '.task-state')  # identity only; never read or written
        else:
            self.path = os.path.abspath(os.fspath(db))
            self.run_dir = os.path.dirname(self.path)
            self.db = Database(os.path.join(self.run_dir, 'wf.sqlite3'))
            self.run_id = uuid.uuid5(uuid.NAMESPACE_URL, self.path).hex
            self._ensure_fixture_run()
        key = (self.db.path, self.run_id)
        with self._locks_guard:
            self._lock = self._locks.setdefault(key, threading.RLock())

    def _ensure_fixture_run(self):
        now = time.time()
        with self.db.transaction(immediate=True) as connection:
            if not connection.execute('SELECT 1 FROM runs WHERE id = ?', (self.run_id,)).fetchone():
                connection.execute(
                    'INSERT INTO runs(id, slug, directory, goal, status, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (self.run_id, os.path.basename(self.path), self.path + '.runtime', 'fixture', 'active', now))

    @contextmanager
    def locked(self):
        with self._lock:
            yield

    @staticmethod
    def _encode(task):
        # `_encode` runs while the caller may hold SQLite's write transaction. Persisting this nested diagnostic
        # through a second connection would wait for its own lock and turn observation into a five-second stall.
        with measure('task.serialize', _persist_db=False):
            return json.dumps(task, default=json_record, sort_keys=True, separators=(',', ':'))

    def exists(self):
        with self.db.connect() as connection:
            return connection.execute('SELECT 1 FROM task_state WHERE run_id = ?', (self.run_id,)).fetchone() is not None

    def _write_task(self, connection, task, create=False):
        payload = self._encode(task)
        row = connection.execute(
            'SELECT revision, payload_json FROM task_state WHERE run_id = ?', (self.run_id,)).fetchone()
        if row:
            current = json.loads(row['payload_json'])
            if current.get('task_id') != task.task_id:
                raise ValueError('task identity is immutable for a run')
            if create:
                raise FileExistsError(self.path)
            if task.revision < row['revision']:
                raise StaleTask(f'task revision {task.revision} is older than {row["revision"]}')
            connection.execute(
                'UPDATE task_state SET revision = ?, payload_json = ?, updated_at = ? WHERE run_id = ?',
                (task.revision, payload, time.time(), self.run_id))
        else:
            connection.execute(
                'INSERT INTO task_state(run_id, revision, payload_json, updated_at) VALUES (?, ?, ?, ?)',
                (self.run_id, task.revision, payload, time.time()))

    def create(self, task):
        with self.db.transaction(immediate=True) as connection:
            self._write_task(connection, task, create=True)
        return task

    def restart(self, task, hint=None):
        """Replace expired operational state; history survives only as one advisory run event."""
        now = time.time()
        with self.locked(), self.db.transaction(immediate=True) as connection:
            pending = connection.execute(
                "SELECT COUNT(*) AS n FROM intents WHERE run_id=? AND status!='settled'", (self.run_id,)
            ).fetchone()['n']
            if pending:
                raise StaleTask('task restart refuses an unresolved in-flight input; read once to reconcile it')
            row = connection.execute(
                'SELECT payload_json FROM task_state WHERE run_id=?', (self.run_id,)
            ).fetchone()
            old = json.loads(row['payload_json']) if row else {}
            max_turn = connection.execute(
                'SELECT max(turn_id) AS n FROM intents WHERE run_id=?', (self.run_id,)
            ).fetchone()['n']
            task.turn_seq = max(int(old.get('turn_seq') or 0), int(max_turn or 0))
            payload = self._encode(task)
            if row:
                connection.execute(
                    'UPDATE task_state SET revision=?, payload_json=?, updated_at=? WHERE run_id=?',
                    (task.revision, payload, now, self.run_id))
            else:
                connection.execute(
                    'INSERT INTO task_state(run_id,revision,payload_json,updated_at) VALUES (?,?,?,?)',
                    (self.run_id, task.revision, payload, now))
            connection.execute('UPDATE runs SET pinned_profile_id=NULL WHERE id=?', (self.run_id,))
            connection.execute(
                "UPDATE live_evals SET status='fail', ended_at=?, result_json=? "
                "WHERE run_id=? AND status='active'",
                (now, json.dumps({'reason': 'task_restarted'}), self.run_id))
            self._insert_event(connection, None, 'task_restart', {
                'old_task_id': old.get('task_id'), 'new_task_id': task.task_id,
                'hint': thaw(hint or {}), 'authoritative': False})
        return task

    def load(self):
        with measure('task.load'), self.db.connect() as connection:
            row = connection.execute('SELECT payload_json FROM task_state WHERE run_id = ?', (self.run_id,)).fetchone()
        if not row:
            raise FileNotFoundError(self.path)
        return TaskState.from_dict(json.loads(row['payload_json']))

    def compact(self):
        from . import history
        with self.locked():
            task = self.load()
            changed = history.compact(task, self)
            if changed:
                self.save(task)
            return changed

    def save(self, task):
        with self.db.transaction(immediate=True) as connection:
            self._write_task(connection, task)
        return task

    def compare_and_swap(self, expected_revision, task):
        if task.revision <= expected_revision:
            raise ValueError('new task revision must increase')
        payload = self._encode(task)
        with self.db.transaction(immediate=True) as connection:
            row = connection.execute('SELECT payload_json FROM task_state WHERE run_id = ?', (self.run_id,)).fetchone()
            if not row:
                raise FileNotFoundError(self.path)
            if json.loads(row['payload_json']).get('task_id') != task.task_id:
                raise ValueError('task identity is immutable for a run')
            cursor = connection.execute(
                'UPDATE task_state SET revision = ?, payload_json = ?, updated_at = ? '
                'WHERE run_id = ? AND revision = ?',
                (task.revision, payload, time.time(), self.run_id, expected_revision))
            if cursor.rowcount != 1:
                raise StaleTask(f'task revision {expected_revision} is stale')
        return task

    def _insert_event(self, connection, turn_id, phase, payload):
        encoded = json.dumps(payload, default=json_record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return connection.execute(
            'INSERT INTO run_events(run_id, turn_id, t, type, phase, payload_json) VALUES (?, ?, ?, ?, ?, ?)',
            (self.run_id, turn_id, time.time(), 'turn', phase, encoded)).lastrowid

    def append_event(self, task, turn_id, phase, **data):
        payload = {'task_id': task.task_id, **thaw(data)}
        with self.db.transaction(immediate=True) as connection:
            return self._insert_event(connection, turn_id, phase, payload)

    def begin_intent(self, task, intent):
        """Atomically persist task WAL, prepared intent, and its canonical run event before input."""
        canonical = thaw(intent)
        canonical['experience'] = None
        canonical['journaled'] = False
        now = time.time()
        with self.db.transaction(immediate=True) as connection:
            self._write_task(connection, task)
            encoded = json.dumps(canonical, sort_keys=True)
            row = connection.execute(
                'SELECT id, payload_json FROM intents WHERE run_id = ? AND turn_id = ?',
                (self.run_id, intent.turn_id)).fetchone()
            if row:
                # Recovery never rewrites the original prepared envelope. Legacy task payloads may have lost
                # provenance fields; the already-canonical intent row remains authoritative.
                return None
            connection.execute(
                'INSERT INTO intents(run_id, turn_id, observation_id, status, payload_json, created_at, updated_at) '
                "VALUES (?, ?, ?, 'prepared', ?, ?, ?)",
                (self.run_id, intent.turn_id,
                 intent.action.get('lineage_observation_id') or intent.before.get('observation_id'),
                 encoded, now, now))
            event_id = self._insert_event(connection, intent.turn_id, 'intent',
                                          {'task_id': task.task_id, 'intent': canonical})
        return event_id

    def record_capture(self, task, intent, experience):
        payload = thaw(intent)
        now = time.time()
        with self.db.transaction(immediate=True) as connection:
            self._write_task(connection, task)
            row = connection.execute(
                'SELECT status, payload_json FROM intents WHERE run_id = ? AND turn_id = ?',
                (self.run_id, intent.turn_id)).fetchone()
            if not row:
                raise StaleTask('intent is not capturable')
            if row['status'] in ('captured', 'settled'):
                saved = json.loads(row['payload_json'])
                if saved.get('experience') != payload.get('experience'):
                    raise ValueError('conflicting capture for turn')
                return None
            cursor = connection.execute(
                "UPDATE intents SET status = 'captured', payload_json = ?, updated_at = ? "
                "WHERE run_id = ? AND turn_id = ? AND status IN ('prepared','performed')",
                (json.dumps(payload, sort_keys=True), now, self.run_id, intent.turn_id))
            if cursor.rowcount != 1:
                raise StaleTask('intent is not capturable')
            event_id = self._insert_event(connection, intent.turn_id, 'outcome',
                                          {'task_id': task.task_id, 'experience': thaw(experience)})
        return event_id

    def settle(self, task, intent, result):
        now = time.time()
        with self.db.transaction(immediate=True) as connection:
            self._write_task(connection, task)
            row = connection.execute('SELECT status FROM intents WHERE run_id = ? AND turn_id = ?',
                                     (self.run_id, intent.turn_id)).fetchone()
            if row and row['status'] == 'settled':
                return None
            cursor = connection.execute(
                "UPDATE intents SET status = 'settled', updated_at = ? "
                "WHERE run_id = ? AND turn_id = ? AND status IN ('captured','performed','prepared')",
                (now, self.run_id, intent.turn_id))
            if cursor.rowcount != 1:
                raise StaleTask('intent is not settleable')
            return self._insert_event(connection, intent.turn_id, 'integration',
                                      {'task_id': task.task_id, 'experience': intent.experience.get('id'),
                                       'result': thaw(result)})
