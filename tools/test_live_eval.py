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

    def clue(self, scene, kinds, created_at, *, status='coherent', graph_kinds=(), event_at=None,
             task_id=None, current_node=None, current_source=None, mode='gameplay'):
        with self.db.transaction(immediate=True) as connection:
            observation_id = connection.execute(
                "INSERT INTO observations(run_id,status,scene,payload_json,created_at) "
                "VALUES (?,?,?,?,?)", (self.run_id, status, scene, '{}', created_at)).lastrowid
        payload = {
            'view': {'scene': scene, 'candidates': [
                {'id': f'candidate-{index}', 'kind': kind, 'point': [1000 + index, 600]}
                for index, kind in enumerate(kinds)], 'mode': mode},
            'graph_clues': [{'id': kind, 'kind': kind, 'node': kind} for kind in graph_kinds],
            'resources': {'region': scene}, 'observation_id': observation_id,
        }
        if task_id is not None:
            payload['task_id'] = task_id
        if current_node is not None:
            payload['navigation'] = {'graph': {'current_node': current_node,
                                               'current_source': current_source}}
        return self.runs.append_event('turn', payload, phase='clues',
                                      t=created_at if event_at is None else event_at,
                                      run_id=self.run_id)

    def active_task(self, task_id):
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO task_state(run_id,revision,payload_json,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET revision=excluded.revision,"
                "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (self.run_id, 1, json.dumps({'task_id': task_id, 'status': 'active'}), self.now))

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

    def test_start_rejects_stale_or_incoherent_observation_and_static_bed_knowledge(self):
        stale = self.now - 24 * 3600
        self.clue('House', ['Bed'], stale)
        with self.assertRaisesRegex(ValueError, 'fresh.*House.*Bed'):
            self.store().start('bed-to-well', self.run_id, 'stale')
        self.clue('House', ['Bed'], stale, event_at=self.now)
        with self.assertRaisesRegex(ValueError, 'fresh.*House.*Bed'):
            self.store().start('bed-to-well', self.run_id, 'stale-observation')
        self.clue('House', ['Bed'], self.now, status='save_lineage_mismatch')
        with self.assertRaisesRegex(ValueError, 'fresh.*House.*Bed'):
            self.store().start('bed-to-well', self.run_id, 'mismatch')
        self.clue('House', [], self.now + 1, graph_kinds=['Bed'])
        with self.assertRaisesRegex(ValueError, 'fresh.*House.*Bed'):
            self.store().start('bed-to-well', self.run_id, 'static')

    def test_start_can_bind_to_same_active_tasks_immutable_sleep_spawn(self):
        task_id = 'same-restarted-task'
        self.active_task(task_id)
        start = self.clue('House', [], self.now - 600, task_id=task_id,
                          current_node='Bed', current_source='sleep_spawn')
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO intents(run_id,turn_id,status,payload_json,created_at,updated_at) "
                "VALUES (?,1,'settled',?,?,?)",
                (self.run_id, json.dumps({'action': {'kind': 'waypoint'},
                                          'provenance': {'preparation': 'prepared'}}),
                 self.now - 500, self.now - 500))
        self.clue('House', [], self.now, task_id=task_id,
                  current_node='House/BedroomPassage', current_source='navigation_step')

        evaluation = self.store().start('bed-to-well', self.run_id, 'retroactive')

        self.assertEqual(evaluation['start_event_id'], start)
        self.assertEqual(evaluation['created_at'], self.now - 600)
        self.assertEqual(self.store().report(evaluation['id'])['inputs'], 1)

    def test_persisted_sleep_spawn_after_movement_binds_the_original_bed_clue(self):
        task_id = 'stale-sleep-source'
        self.active_task(task_id)
        original = self.clue('House', [], self.now - 20, task_id=task_id,
                             current_node='Bed', current_source='sleep_spawn')
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO intents(run_id,turn_id,status,payload_json,created_at,updated_at) "
                "VALUES (?,1,'settled',?,?,?)",
                (self.run_id, json.dumps({'action': {'kind': 'waypoint'},
                                          'provenance': {'preparation': 'prepared'}}),
                 self.now - 10, self.now - 10))
        later = self.clue('House', [], self.now, task_id=task_id,
                          current_node='Bed', current_source='sleep_spawn')

        evaluation = self.store().start('bed-to-well', self.run_id, 'stale-source')

        self.assertNotEqual(later, original)
        self.assertEqual(evaluation['start_event_id'], original)
        self.assertEqual(evaluation['created_at'], self.now - 20)

    def test_start_does_not_reuse_sleep_spawn_from_an_old_task(self):
        self.active_task('new-task')
        self.clue('House', [], self.now - 10, task_id='old-task',
                  current_node='Bed', current_source='sleep_spawn')
        self.clue('House', [], self.now, task_id='new-task',
                  current_node='House/BedroomPassage', current_source='navigation_step')

        with self.assertRaisesRegex(ValueError, 'fresh.*House.*Bed'):
            self.store().start('bed-to-well', self.run_id, 'wrong-task')

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
        self.clue('Farm', ['Well'], self.now + 3)
        passed = self.store().finish(evaluation['id'], revision='def789')
        self.assertEqual(passed['status'], 'pass')
        self.assertEqual(passed['finished_revision'], 'def789')
        self.assertEqual(passed['result']['destination'], 'Well')
        self.assertEqual(passed['result']['scene'], 'Farm')
        report = self.store().report(evaluation['id'])
        self.assertEqual(report['revision'], 'def456')
        self.assertEqual(report['finished_revision'], 'def789')

    def test_static_graph_membership_cannot_prove_destination_visibility(self):
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        self.clue('Farm', [], self.now + 1, graph_kinds=['Well'])
        finished = self.store().finish(evaluation['id'])
        self.assertEqual(finished['status'], 'fail')

    def test_well_to_bed_requires_fresh_bed_endpoint_not_static_graph_knowledge(self):
        self.clue('Farm', ['Well'], self.now)
        evaluation = self.store().start('well-to-bed', self.run_id, 'reverse-a')
        self.clue('House', [], self.now + 1, graph_kinds=['Bed'])
        failed = self.store().finish(evaluation['id'])
        self.assertEqual(failed['status'], 'fail')

        self.run_id = self.runs.start(
            'live-route-reverse', 'well to bed', os.path.join(self.tmp.name, 'run-reverse'))
        self.clue('Farm', ['Well'], self.now + 2)
        evaluation = self.store().start('well-to-bed', self.run_id, 'reverse-b')
        self.clue('House', ['Bed'], self.now + 3)
        passed = self.store().finish(evaluation['id'])
        self.assertEqual(passed['status'], 'pass')
        self.assertEqual(passed['result']['scene'], 'House')
        self.assertEqual(passed['result']['destination'], 'Bed')

    def test_fresh_positioned_interaction_can_prove_destination_without_visual_candidate(self):
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO experiences(id,run_id,turn_id,observation_id,payload_json,created_at) "
                "VALUES (?,?,?,?,?,?)", ('positioned-well', self.run_id, 2,
                evaluation['start_observation_id'], json.dumps({'evidence': {'state': [
                    ['region', 'Garden'], ['regions', ['Farm', 'Garden']],
                    ['region_provenance', {'source': 'positioned_event', 'node': 'Well',
                                           'regions': ['Farm', 'Garden']}]]}}), evaluation['created_at']))
        finished = self.store().finish(evaluation['id'])
        self.assertEqual(finished['status'], 'pass')
        self.assertEqual(finished['result']['scene'], 'Farm')
        self.assertEqual(finished['result']['destination'], 'Well')

    def test_finished_evaluation_is_immutable_when_later_gameplay_adds_destination_proof(self):
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        first = self.store().finish(evaluation['id'], revision='first')
        with self.db.connect() as connection:
            checkpoints = connection.execute(
                'SELECT count(*) FROM live_eval_checkpoints WHERE eval_id=?',
                (evaluation['id'],)).fetchone()[0]
        self.clue('Farm', ['Well'], self.now + 1)
        second = self.store().finish(evaluation['id'], revision='second')
        with self.db.connect() as connection:
            later_checkpoints = connection.execute(
                'SELECT count(*) FROM live_eval_checkpoints WHERE eval_id=?',
                (evaluation['id'],)).fetchone()[0]
        self.assertEqual(second, first)
        self.assertEqual(second['status'], 'fail')
        self.assertEqual(second['finished_revision'], 'first')
        self.assertEqual(later_checkpoints, checkpoints)

    def test_report_is_idempotent_and_counts_persisted_inputs_and_no_moves(self):
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO intents(run_id,turn_id,status,payload_json,created_at,updated_at) "
                "VALUES (?,1,'performed','{}',?,?)", (self.run_id, self.now - 2, self.now - 2))
        self.clue('House', ['Bed'], self.now)
        evaluation = self.store().start('bed-to-well', self.run_id, 'abc123')
        within = evaluation['created_at']
        with self.db.transaction(immediate=True) as connection:
            for turn_id, payload in enumerate((
                    {'action': {'kind': 'read'}, 'provenance': {'preparation': 'prepared', 'refusal': None}},
                    {'action': {'kind': 'waypoint'}, 'provenance': {'preparation': 'refused', 'refusal': 'guard'}},
                    {'action': {'kind': 'waypoint'}, 'provenance': {'preparation': 'prepared', 'refusal': None}}), 2):
                connection.execute(
                    "INSERT INTO intents(run_id,turn_id,status,payload_json,created_at,updated_at) "
                    "VALUES (?,?,'settled',?,?,?)",
                    (self.run_id, turn_id, json.dumps(payload), within, within))
            connection.execute(
                "INSERT INTO experiences(id,run_id,turn_id,payload_json,created_at) VALUES (?,?,?,?,?)",
                ('no-move', self.run_id, 4, json.dumps({
                    'action': {'kind': 'waypoint'},
                    'before': {'state': [['navigation', {'next_edge': {'transition': 'Garden'}}]]},
                    'evidence': {'moved': False, 'state': [['region', 'Farm']]},
                    'verdict': {'value': 'miss'}, 'discrepancy': {'kind': 'mismatch'}}), within))
        self.clue('Farm', [], within)
        self.clue('Farm', ['Well'], within)
        self.store().finish(evaluation['id'])
        first = self.store().report(evaluation['id'])
        second = self.store().report(evaluation['id'])
        self.assertEqual(first, second)
        self.assertEqual(first['inputs'], 1)
        self.assertEqual(first['no_moves'], 1)
        self.assertEqual(first['observations'], 3)
        self.assertEqual(first['wrong_transitions'], 1)
        self.assertEqual(first['surprises'], 1)
        self.assertGreaterEqual(first['elapsed_real_seconds'], 0)
        self.assertIn('elapsed_game_seconds', first)
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
        self.clue('Farm', ['Well'], self.now + 1)
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
