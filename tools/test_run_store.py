"""Tests for the canonical SQLite run lifecycle and event stream."""
import os
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime.db import Database
from runtime.run_store import RunStore
import wf


class RunStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(os.path.join(self.tmp.name, 'wf.sqlite3'))
        self.store = RunStore(self.db)

    def start(self, slug='test-run', goal='exercise the store'):
        directory = os.path.join(self.tmp.name, slug)
        os.makedirs(directory, exist_ok=True)
        return self.store.start(slug, goal, directory), directory

    def test_start_end_and_new_start_abandons_the_previous_run(self):
        first, first_dir = self.start('first', 'first goal')
        self.assertEqual(self.store.active()['id'], first)

        second, second_dir = self.start('second', 'second goal')

        self.assertNotEqual(first, second)
        self.assertEqual(self.store.active()['id'], second)
        rows = {row['id']: row for row in self.store.runs()}
        self.assertEqual(rows[first]['status'], 'abandoned')
        self.assertIsNotNone(rows[first]['ended_at'])
        self.assertEqual(rows[second]['status'], 'active')
        self.assertEqual(rows[first]['directory'], os.path.abspath(first_dir))
        self.assertEqual(rows[second]['directory'], os.path.abspath(second_dir))
        self.assertEqual(self.store.events(first)[-1]['result'], 'abandoned')

        self.store.end('done', 'finished')
        self.assertIsNone(self.store.active())
        self.assertEqual(self.store.events(second)[-1]['text'], 'finished')
        self.assertEqual(self.store.runs()[-1]['status'], 'done')

    def test_events_have_never_reused_ordered_ids_and_explicit_timestamps(self):
        run_id, _ = self.start()
        first = self.store.append_event('note', {'text': 'one'}, t=10.25)
        second = self.store.append_event('turn', {'answer': 'accept'}, turn_id=7, phase='decision', t=11.5)

        self.assertGreater(second, first)
        rows = self.store.events(run_id, after_id=first)
        self.assertEqual([row['id'] for row in rows], [second])
        self.assertEqual(rows[0], {
            'id': second, 'run_id': run_id, 't': 11.5, 'type': 'turn', 'turn_id': 7,
            'phase': 'decision', 'answer': 'accept',
        })

    def test_concurrent_appends_are_complete_unique_and_chronological(self):
        run_id, _ = self.start()
        barrier = threading.Barrier(5)
        errors = []

        def append(worker):
            try:
                barrier.wait()
                for index in range(20):
                    self.store.append_event('note', {'worker': worker, 'index': index})
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [threading.Thread(target=append, args=(worker,)) for worker in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        rows = [row for row in self.store.events(run_id) if row['type'] == 'note']
        ids = [row['id'] for row in rows]
        self.assertEqual(len(rows), 100)
        self.assertEqual(ids, sorted(set(ids)))

    def test_run_selection_accepts_id_and_directory(self):
        run_id, directory = self.start()
        expected = self.store.events(run_id)
        self.assertEqual(self.store.events(directory), expected)
        self.assertEqual(self.store.resolve(directory)['id'], run_id)

    def test_malformed_event_rolls_back_without_consuming_an_event_id(self):
        run_id, _ = self.start()
        before = self.store.events(run_id)
        with self.assertRaises(TypeError):
            self.store.append_event('note', {'not-json': object()})
        event_id = self.store.append_event('note', {'text': 'valid'})

        after = self.store.events(run_id)
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1]['id'], event_id)
        self.assertEqual(after[-1]['text'], 'valid')

    def test_append_without_an_active_run_is_a_noop(self):
        self.assertIsNone(self.store.append_event('note', {'text': 'ignored'}))

    def test_run_export_jsonl_is_explicit_and_diagnostic_only(self):
        run_id, _ = self.start()
        event_id = self.store.append_event('note', {'text': 'portable'})
        output = io.StringIO()
        with mock.patch.dict(os.environ, WF_DB=self.db.path), contextlib.redirect_stdout(output):
            wf.main(['run', 'export', '--jsonl', run_id])
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[-1]['id'], event_id)
        self.assertEqual(rows[-1]['text'], 'portable')


if __name__ == '__main__':
    unittest.main()
