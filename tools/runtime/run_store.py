"""Canonical run lifecycle and ordered event stream backed by SQLite."""
import contextlib
import json
import os
import time
import uuid

from .db import Database


_RESERVED = {'id', 'run_id', 't', 'type', 'turn_id', 'phase'}
_FINAL = {'done', 'partial', 'blocked', 'stopped', 'abandoned'}


class RunStore:
    def __init__(self, database=None):
        self.database = database or Database()

    @staticmethod
    def _row(row):
        return dict(row) if row is not None else None

    @staticmethod
    def _payload(payload):
        if not isinstance(payload, dict):
            raise TypeError('event payload must be a dict')
        overlap = _RESERVED.intersection(payload)
        if overlap:
            raise ValueError('event payload contains reserved keys: ' + ', '.join(sorted(overlap)))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    @staticmethod
    def _insert_event(connection, run_id, type_, payload_json, turn_id=None, phase=None, t=None):
        if not isinstance(type_, str) or not type_:
            raise ValueError('event type must be a non-empty string')
        timestamp = time.time() if t is None else float(t)
        cursor = connection.execute(
            'INSERT INTO run_events(run_id, turn_id, t, type, phase, payload_json) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (run_id, turn_id, timestamp, type_, phase, payload_json))
        return cursor.lastrowid

    def start(self, slug, goal, run_dir):
        """Start one run, atomically abandoning any previously active run."""
        if not isinstance(slug, str) or not slug:
            raise ValueError('run slug must be a non-empty string')
        now = time.time()
        run_id = uuid.uuid4().hex
        directory = os.path.abspath(os.fspath(run_dir))
        goal = str(goal or '')
        start_payload = self._payload({'quest': slug, 'goal': goal})
        abandoned_payload = self._payload({'result': 'abandoned', 'text': 'a new run started'})
        with self.database.transaction(immediate=True) as connection:
            active = connection.execute('SELECT run_id FROM active_run WHERE singleton = 1').fetchone()
            if active:
                previous = active['run_id']
                self._insert_event(connection, previous, 'end', abandoned_payload, t=now)
                connection.execute(
                    "UPDATE runs SET status = 'abandoned', ended_at = ? WHERE id = ?", (now, previous))
                connection.execute('DELETE FROM active_run WHERE singleton = 1')
            connection.execute(
                'INSERT INTO runs(id, slug, directory, goal, status, created_at) '
                "VALUES (?, ?, ?, ?, 'active', ?)",
                (run_id, slug, directory, goal, now))
            connection.execute('INSERT INTO active_run(singleton, run_id) VALUES (1, ?)', (run_id,))
            self._insert_event(connection, run_id, 'start', start_payload, t=now)
        return run_id

    def active(self):
        with contextlib.closing(self.database.connect()) as connection:
            row = connection.execute(
                'SELECT r.* FROM active_run a JOIN runs r ON r.id = a.run_id WHERE a.singleton = 1').fetchone()
        return self._row(row)

    def end(self, result='done', text=''):
        if result not in _FINAL:
            raise ValueError(f'invalid run result: {result}')
        payload_json = self._payload({'result': result, 'text': str(text or '')})
        now = time.time()
        with self.database.transaction(immediate=True) as connection:
            active = connection.execute('SELECT run_id FROM active_run WHERE singleton = 1').fetchone()
            if not active:
                return None
            run_id = active['run_id']
            event_id = self._insert_event(connection, run_id, 'end', payload_json, t=now)
            connection.execute('UPDATE runs SET status = ?, ended_at = ? WHERE id = ?', (result, now, run_id))
            connection.execute('DELETE FROM active_run WHERE singleton = 1')
        return event_id

    def append_event(self, type_, payload, turn_id=None, phase=None, t=None, run_id=None):
        """Append to the active run (or explicit run_id); return None if there is no active run."""
        payload_json = self._payload(payload)
        with self.database.transaction(immediate=True) as connection:
            selected = run_id
            if selected is None:
                active = connection.execute('SELECT run_id FROM active_run WHERE singleton = 1').fetchone()
                if not active:
                    return None
                selected = active['run_id']
            exists = connection.execute('SELECT 1 FROM runs WHERE id = ?', (selected,)).fetchone()
            if not exists:
                raise KeyError(f'unknown run: {selected}')
            return self._insert_event(connection, selected, type_, payload_json, turn_id, phase, t)

    def resolve(self, reference=None):
        if reference is None:
            return self.active()
        reference = os.fspath(reference)
        absolute = os.path.abspath(reference)
        with contextlib.closing(self.database.connect()) as connection:
            row = connection.execute('SELECT * FROM runs WHERE id = ?', (reference,)).fetchone()
            if row is None:
                row = connection.execute('SELECT * FROM runs WHERE directory = ?', (absolute,)).fetchone()
        return self._row(row)

    def events(self, run_id=None, after_id=0):
        run = self.resolve(run_id)
        if not run:
            return []
        with contextlib.closing(self.database.connect()) as connection:
            rows = connection.execute(
                'SELECT id, run_id, turn_id, t, type, phase, payload_json FROM run_events '
                'WHERE run_id = ? AND id > ? ORDER BY id', (run['id'], int(after_id))).fetchall()
        events = []
        for row in rows:
            event = json.loads(row['payload_json'])
            event.update(id=row['id'], run_id=row['run_id'], t=row['t'], type=row['type'])
            if row['turn_id'] is not None:
                event['turn_id'] = row['turn_id']
            if row['phase'] is not None:
                event['phase'] = row['phase']
            events.append(event)
        return events

    def runs(self):
        with contextlib.closing(self.database.connect()) as connection:
            rows = connection.execute('SELECT * FROM runs ORDER BY created_at, rowid').fetchall()
        return [dict(row) for row in rows]
