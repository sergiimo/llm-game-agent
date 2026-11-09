"""Native owner bridge contracts; real task/SQLite loop with only physical I/O substituted."""
import contextlib
import importlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import wf
from game import experience as X, native_bridge, primitives, task_state as S, turn
from runtime.run_store import RunStore
from test_turn import Port


class OutcomePort(Port):
    def __init__(self):
        super().__init__()
        self.snapshot.update(frame_path='before.jpg', view_id='view-before', hour=10.0)
        self._outcome = None

    def capture(self, intent, before, expected):
        evidence = X.Evidence(mode='gameplay', moved=True)
        if intent.action.get('kind') == 'read':
            self._outcome = dict(self.snapshot)
            return primitives.experience(intent, before, expected, evidence, (self.snapshot['frame_path'],))
        self._outcome = dict(self.snapshot, frame_path='after.jpg', view_id='view-after')
        return primitives.experience(intent, before, expected, evidence, ('after.jpg',))

    def preflight(self, action, _observation):
        return action

    def take_outcome_observation(self, _experience_id):
        outcome, self._outcome = self._outcome, None
        return outcome


class NativeBridgeContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = S.TaskStore(os.path.join(self.tmp.name, 'task.json'))
        self.port = OutcomePort()

    def test_observe_is_zero_input_and_returns_the_exact_frame_identity(self):
        receipt = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)

        self.assertEqual(self.port.inputs, [])
        self.assertEqual(receipt['turn_id'], 1)
        self.assertEqual(receipt['frame_path'], 'before.jpg')
        self.assertEqual(receipt['view']['id'], 'view-before')

    def test_observe_refreshes_a_cached_turn_without_input(self):
        first = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)
        self.port.snapshot.update(frame_path='fresh.jpg', view_id='view-fresh')

        refreshed = native_bridge.observe(store=self.store, adapter=self.port)

        self.assertGreater(refreshed['turn_id'], first['turn_id'])
        self.assertEqual(refreshed['observation_freshness'], 'fresh')
        self.assertEqual(refreshed['frame_path'], 'fresh.jpg')
        self.assertEqual(refreshed['view']['id'], 'view-fresh')
        self.assertEqual(self.port.inputs, [])

    def test_waypoint_act_issues_once_and_returns_its_outcome_observation(self):
        observed = mock.Mock(wraps=self.port.observe)
        self.port.observe = observed
        first = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)

        receipt = native_bridge.act(
            first['turn_id'], {'kind': 'waypoint', 'point': [1070, 835]},
            objective='follow visible passage', store=self.store, adapter=self.port)

        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(self.port.inputs[0]['kind'], 'waypoint')
        self.assertTrue(self.port.inputs[0]['walkable'])
        self.assertEqual(self.store.load().last_experience['prediction']['moved'], True)
        self.assertEqual(receipt['frame_path'], 'after.jpg')
        self.assertEqual(receipt['view']['id'], 'view-after')
        observed.assert_called_once_with()

    def test_stale_turn_cannot_repeat_a_delivered_input(self):
        first = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)
        native_bridge.act(first['turn_id'], {'kind': 'waypoint', 'point': [1070, 835]},
                          store=self.store, adapter=self.port)

        with self.assertRaises(turn.StaleTurn):
            native_bridge.act(first['turn_id'], {'kind': 'waypoint', 'point': [1070, 835]},
                              store=self.store, adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1)

    def test_unknown_delivery_is_reconciled_without_repeating_input(self):
        first = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)
        self.port.fail = True

        with self.assertRaises(RuntimeError):
            native_bridge.act(first['turn_id'], {'kind': 'waypoint', 'point': [1070, 835]},
                              store=self.store, adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1)

        self.port.fail = False
        native_bridge.observe(store=self.store, adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1)

    def test_omitted_location_does_not_become_confirmed_localization(self):
        first = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)

        native_bridge.act(first['turn_id'], {'kind': 'waypoint', 'point': [1070, 835]},
                          store=self.store, adapter=self.port)

        belief = self.store.load().params['_navigation_belief']
        self.assertEqual(belief['current'], 'unknown')
        self.assertNotIn('current_source', belief)
        self.assertNotIn('localization_proof', belief)

    def test_note_is_zero_input_and_does_not_consume_the_turn(self):
        first = native_bridge.observe(
            'navigate', {'destination': 'Well'}, store=self.store, adapter=self.port)

        result = native_bridge.note(first['turn_id'], 'compass conflicts with visible passage',
                                    ['before.jpg'], store=self.store)
        persisted_turn = self.store.load().current_turn['turn_id']
        again = native_bridge.observe(store=self.store, adapter=self.port)

        self.assertEqual(result['status'], 'recorded')
        self.assertEqual(persisted_turn, first['turn_id'])
        self.assertGreater(again['turn_id'], first['turn_id'])
        self.assertEqual(again['observation_freshness'], 'fresh')
        self.assertEqual(self.port.inputs, [])
        rows = RunStore(self.store.db).events(self.store.run_id)
        self.assertTrue(any(row.get('phase') == 'native.note' for row in rows))

    def test_host_package_contains_bounded_text_and_the_same_image(self):
        native_tools = importlib.import_module('native_tools')
        receipt = {'turn_id': 7, 'frame_path': 'frame-7.jpg',
                   'image': {'path': 'frame-7.jpg', 'mime_type': 'image/jpeg'},
                   'task': {'goal': 'navigate'}, 'navigation': {'next_edge': {'to': 'Well'}}}

        result = native_tools.package(receipt)

        self.assertEqual(result['content'][1], {
            'type': 'image', 'path': 'frame-7.jpg', 'mime_type': 'image/jpeg'})
        text = json.loads(result['content'][0]['text'])
        self.assertEqual(text['turn_id'], 7)
        self.assertEqual(text['navigation']['next_edge']['to'], 'Well')
        self.assertNotIn('image', text)

    def test_registered_native_cli_routes_data_without_eval_or_extra_capture(self):
        receipt = {'turn_id': 7, 'frame_path': 'frame-7.jpg',
                   'image': {'path': 'frame-7.jpg', 'mime_type': 'image/jpeg'}}
        with mock.patch.object(native_bridge, 'observe', return_value=receipt) as observe, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            wf.main(['native', 'observe', 'goal=navigate', 'destination=Well'])

        observe.assert_called_once_with('navigate', {'destination': 'Well'})
        result = json.loads(out.getvalue())
        self.assertEqual(result['content'][1]['path'], 'frame-7.jpg')


if __name__ == '__main__':
    unittest.main()
