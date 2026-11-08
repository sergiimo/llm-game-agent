"""SQLite-backed live gameplay evaluation contracts."""
import json
import contextlib
import io
import os
import tempfile
import time
import unittest
from unittest import mock

import wf
from runtime.db import Database
from runtime.run_store import RunStore


class LiveEvalStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(os.path.join(self.tmp.name, 'wf.sqlite3'))
        self.runs = RunStore(self.db)
        self.run_id = self.runs.start('live-route', 'bed to well', os.path.join(self.tmp.name, 'run'))
        self.now = time.time()

    def clue(self, scene, kinds, created_at):
        with self.db.transaction(immediate=True) as connection:
            observation_id = connection.execute(
                "INSERT INTO observations(run_id,status,scene,payload_json,created_at) "
                "VALUES (?,'coherent',?,'{}',?)", (self.run_id, scene, created_at)).lastrowid
        return self.runs.append_event('turn', {
            'view': {'scene': scene, 'candidates': [
                {'id': f'candidate-{index}', 'kind': kind, 'point': [1000 + index, 600]}
                for index, kind in enumerate(kinds)]},
            'resources': {'region': scene}, 'observation_id': observation_id,
        }, phase='clues', t=created_at, run_id=self.run_id)

    def store(self):
        from runtime.live_eval import LiveEvalStore
        return LiveEvalStore(self.db)

    def test_start_requires_a_fresh_house_bed_checkpoint(self):
        self.clue('Farm', ['Bed'], self.now)
        with self.assertRaisesRegex(ValueError, 'House.*Bed'):
            self.store().start('bed-to-well', self.run_id, 'abc123')
        self.clue('House', ['Bed'], self.now + 1)
        row = self.store().start('bed-to-well', self.run_id, 'abc123')
        self.assertEqual(row['scenario'], 'bed-to-well')
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['start_scene'], 'House')

    def test_checkpoint_is_immutable_and_idempotent_for_one_clue_event(self):
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        first = self.store().checkpoint(evaluation['id'])
        second = self.store().checkpoint(evaluation['id'])
        self.assertEqual(first['id'], second['id'])
        with self.db.connect() as connection:
            count = connection.execute(
                'SELECT count(*) FROM live_eval_checkpoints WHERE eval_id=?',
                (evaluation['id'],)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_finish_passes_only_with_a_new_garden_well_proof(self):
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        failed = self.store().finish(evaluation['id'])
        self.assertEqual(failed['status'], 'fail')

        other_run = self.runs.start('live-route-2', 'bed to well', os.path.join(self.tmp.name, 'run-2'))
        self.run_id = other_run
        self.clue('House', ['Bed'], self.now + 2)
        evaluation = self.store().start('bed-to-well', self.run_id, 'def456')
        self.clue('Garden', ['Well'], self.now + 3)
        passed = self.store().finish(evaluation['id'], revision='def789')
        self.assertEqual(passed['status'], 'pass')
        self.assertEqual(passed['finished_revision'], 'def789')
        self.assertEqual(passed['result']['destination'], 'Well')
        self.assertEqual(passed['result']['scene'], 'Garden')
        report = self.store().report(evaluation['id'])
        self.assertEqual(report['revision'], 'def456')
        self.assertEqual(report['finished_revision'], 'def789')

    def test_report_is_idempotent_and_counts_persisted_inputs_and_no_moves(self):
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO intents(run_id,turn_id,status,payload_json,created_at,updated_at) "
                "VALUES (?,1,'performed','{}',?,?)", (self.run_id, self.now - 2, self.now - 2))
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO intents(run_id,turn_id,status,payload_json,created_at,updated_at) "
                "VALUES (?,2,'performed','{}',?,?)", (self.run_id, self.now + 1, self.now + 1))
            connection.execute(
                "INSERT INTO experiences(id,run_id,turn_id,payload_json,created_at) VALUES (?,?,?,?,?)",
                ('no-move', self.run_id, 2, json.dumps({'evidence': {'moved': False},
                                                       'verdict': {'value': 'miss'}}), self.now + 1))
        self.clue('Garden', ['Well'], self.now + 2)
        self.store().finish(evaluation['id'])
        first = self.store().report(evaluation['id'])
        second = self.store().report(evaluation['id'])
        self.assertEqual(first, second)
        self.assertEqual(first['inputs'], 1)
        self.assertEqual(first['no_moves'], 1)
        with self.db.connect() as connection:
            count = connection.execute('SELECT count(*) FROM live_evals').fetchone()[0]
        self.assertEqual(count, 1)


class LiveEvalCLITest(unittest.TestCase):
    setUp = LiveEvalStoreTest.setUp
    clue = LiveEvalStoreTest.clue

    def command(self, *args):
        output = io.StringIO()
        with mock.patch.dict(os.environ, WF_DB=self.db.path), contextlib.redirect_stdout(output):
            code = wf.live_eval_cmd(list(args))
        self.assertIsNone(code)
        return json.loads(output.getvalue())

    def test_cli_start_status_finish_report_and_compare(self):
        self.clue('House', ['Bed'], self.now)
        started = self.command('start', 'bed-to-well')
        self.assertEqual(started['status'], 'active')
        status = self.command('status', 'bed-to-well')
        self.assertEqual(status['id'], started['id'])
        self.clue('Garden', ['Well'], self.now + 1)
        finished = self.command('finish', started['id'])
        self.assertEqual(finished['status'], 'pass')
        report = self.command('report', started['id'])
        self.assertEqual(report['scenario'], 'bed-to-well')
        compared = self.command('compare', 'bed-to-well')
        self.assertEqual([row['id'] for row in compared], [started['id']])

    def test_cli_rejects_an_unknown_scenario_without_writing(self):
        self.clue('House', ['Bed'], self.now)
        with mock.patch.dict(os.environ, WF_DB=self.db.path):
            with self.assertRaisesRegex(ValueError, 'unknown live evaluation scenario'):
                wf.live_eval_cmd(['start', 'teleport'])
        with self.db.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM live_evals').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
