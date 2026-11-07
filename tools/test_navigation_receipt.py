import json
import os
import tempfile
import unittest
from unittest import mock

from game import experience as X
from game import navigation
from game.task_state import TaskState
import nav


class NavigationReceipts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, 'Town'))
        with open(os.path.join(self.root, 'facts.jsonl'), 'w') as stream:
            stream.write(json.dumps({'scene': 'Town', 'goal': 'fountain-square', 'result': 'arrived',
                                     'to': [10.0, -10.0]}) + '\n')
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {},
                       'aliases': {'supermarket': 'fountain-square'}}, stream)
        with open(os.path.join(self.root, 'Town', 'calib.json'), 'w') as stream:
            json.dump({'H': [[1, 0, 0], [0, -1, 0], [0, 0, 1]],
                       'n': 6, 'kept': 6, 'err': 0.05, 'tara': [960, 540]}, stream)
        patches = [mock.patch.object(nav, 'ROOT', self.root),
                   mock.patch.object(nav, 'FACTS', os.path.join(self.root, 'facts.jsonl')),
                   mock.patch.object(nav, 'MAP', os.path.join(self.root, 'map.json'))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.task = TaskState('t', 'navigate', params={'destination': 'supermarket'})
        self.observation = {'scene': 'Town', 'region': 'Town', 'position': [0.0, 0.0],
                            'state_provenance': {'position': {'source': 'save'}}}

    def test_receipt_resolves_destination_and_exposes_next_graph_compass(self):
        result = navigation.receipt(self.task, self.observation)

        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['requested'], 'supermarket')
        self.assertEqual(result['goal']['node'], 'Town:fountain-square')
        self.assertEqual(result['route']['next_node'], 'Town:fountain-square')
        self.assertEqual(result['route']['edge'], 'walk')
        self.assertEqual(result['route']['compass'], 'SE')
        self.assertAlmostEqual(result['route']['distance'], 14.14, places=2)
        self.assertEqual(result['position']['source'], 'save')

    def test_unknown_destination_stays_explicitly_unresolved(self):
        self.task.params['destination'] = 'mystery shop'

        result = navigation.receipt(self.task, self.observation)

        self.assertEqual(result['status'], 'unresolved_destination')
        self.assertIsNone(result['route'])

    def test_assess_rejects_waypoint_over_one_compass_sector_from_graph_route(self):
        result = navigation.assess({'kind': 'waypoint', 'point': [1460, 40]},
                                   navigation.receipt(self.task, self.observation))

        self.assertEqual(result['world']['compass'], 'NE')
        self.assertEqual(result['world']['delta'], [1.0, 1.0])
        self.assertEqual(result['graph_compass'], 'SE')
        self.assertEqual(result['alignment'], 'mismatch')
        self.assertFalse(result['allowed'])

    def test_assess_accepts_waypoint_within_graph_compass_sector(self):
        result = navigation.assess({'kind': 'waypoint', 'point': [1460, 1040]},
                                   navigation.receipt(self.task, self.observation))

        self.assertEqual(result['world']['compass'], 'SE')
        self.assertEqual(result['alignment'], 'aligned')
        self.assertTrue(result['allowed'])

    def test_missing_calibration_keeps_assessment_unknown_and_does_not_refuse(self):
        os.unlink(os.path.join(self.root, 'Town', 'calib.json'))

        result = navigation.assess({'kind': 'waypoint', 'point': [1460, 40]},
                                   navigation.receipt(self.task, self.observation))

        self.assertEqual(result['screen_compass'], 'NE')
        self.assertIsNone(result['world'])
        self.assertEqual(result['alignment'], 'unknown')
        self.assertTrue(result['allowed'])

    def test_proved_waypoint_advances_durable_calibrated_position(self):
        before = {'scene': 'Town', 'navigation': navigation.receipt(self.task, self.observation)}
        experience = X.Experience.new(
            before=X.Observation('gameplay', state=tuple(before.items())),
            action=X.Action('click', 'step', (1460, 1040), context=(('primitive', 'waypoint'),)),
            evidence=X.Evidence(mode='gameplay', moved=True),
            verdict=X.Verdict('hit'))

        navigation.advance(self.task, experience)

        self.assertEqual(self.task.params['_nav_estimate']['scene'], 'Town')
        self.assertEqual(self.task.params['_nav_estimate']['position'], [1.0, -1.0])
        self.assertEqual(self.task.params['_nav_estimate']['source'], 'calibrated_waypoint')

    def test_estimate_from_another_scene_is_replaced_by_observed_position(self):
        self.task.params['_nav_estimate'] = {'scene': 'Farm', 'position': [99, 99],
                                             'source': 'calibrated_waypoint'}
        self.observation['position'] = [-82.1, 53.0]

        result = navigation.receipt(self.task, self.observation)

        self.assertEqual(result['position']['value'], [-82.1, 53.0])
        self.assertEqual(result['position']['source'], 'save')


if __name__ == '__main__':
    unittest.main()
