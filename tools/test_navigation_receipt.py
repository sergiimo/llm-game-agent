"""Qualitative navigation receipts: graph topology, one-frame bearings, and proof-only progress."""
import json
import os
import tempfile
import unittest
from unittest import mock

from game import experience as X
from game import navigation, play
from game.task_state import TaskState
import nav
from objects import graph as OG


class NavigationReceipts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        map_path = os.path.join(self.tmp.name, 'map.json')
        with open(map_path, 'w') as stream:
            json.dump({'aliases': {'well': 'Well'}}, stream)
        patch = mock.patch.object(nav, 'MAP', map_path)
        patch.start()
        self.addCleanup(patch.stop)
        self.graph = self.farm_graph()
        self.task = TaskState('route', 'navigate', params={'destination': 'Well'})

    @staticmethod
    def farm_graph():
        graph = OG.Graph()
        graph.nodes['House'] = OG.Node('House', 'region')
        graph.nodes['HouseExit'] = OG.Node('HouseExit', 'unique', region='House', navigation_only=True)
        graph.nodes['Farm'] = OG.Node('Farm', 'region')
        graph.nodes['Garden'] = OG.Node('Garden', 'region', region='Farm')
        graph.nodes['Well'] = OG.Node('Well', 'unique', region='Garden')
        graph.add_edge('House', 'HouseExit', 'nav', compass='E', range='far', source='test')
        graph.add_edge('HouseExit', 'Farm', 'nav', compass='S', range='near', transition='Farm', source='test')
        graph.add_edge('Farm', 'Garden', 'nav', compass='W', range='far', source='test')
        graph.add_edge('Garden', 'Well', 'nav', compass='NW', range='near', source='test')
        return graph

    @staticmethod
    def experience(before, after, moved=True, verdict='hit'):
        return X.Experience.new(
            before=X.Observation('gameplay', state=tuple(before.items())),
            action=X.Action('click', 'step', (1200, 700), context=(('primitive', 'waypoint'),)),
            evidence=X.Evidence(mode='gameplay', moved=moved, state=tuple(after.items())),
            verdict=X.Verdict(verdict))

    def test_receipt_resolves_nested_path_without_metric_route_data(self):
        result = navigation.receipt(self.task, {'scene': 'House', 'region': 'House',
                                                 'position': [999, -999]}, self.graph)

        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['graph']['path'], ['House', 'HouseExit', 'Farm', 'Garden', 'Well'])
        self.assertEqual(result['next_edge']['to'], 'HouseExit')
        self.assertEqual((result['next_edge']['compass'], result['next_edge']['range']), ('E', 'far'))
        self.assertNotIn('position', result)
        self.assertNotIn('calibration', result)
        self.assertNotIn('route', result)

    def test_unknown_destination_is_explicitly_unresolved(self):
        self.task.params['destination'] = 'teleporter'
        result = navigation.receipt(self.task, {'scene': 'House', 'region': 'House'}, self.graph)
        self.assertEqual(result['status'], 'unresolved_destination')

    def test_numeric_position_cannot_choose_a_deeper_graph_origin(self):
        result = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm',
                                                 'position': [0.84, -25.34]}, self.graph)
        self.assertEqual(result['graph']['current_node'], 'Farm')
        self.assertEqual(result['next_edge']['to'], 'Garden')

    def test_positioned_object_ancestry_keeps_nested_current_under_physical_scene(self):
        self.task.params.update(_nav_current='Garden', _nav_current_proof={
            'source': 'positioned_event', 'node': 'Well', 'regions': ['Farm', 'Garden']})
        result = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm'}, self.graph)
        self.assertEqual(result['graph']['current_node'], 'Garden')
        self.assertEqual(result['next_edge']['to'], 'Well')

    def test_conflicting_observed_scene_rejects_stale_nested_current(self):
        self.task.params.update(_nav_current='Garden', _nav_current_proof={
            'source': 'positioned_event', 'node': 'Well', 'regions': ['Farm', 'Garden']})
        result = navigation.receipt(self.task, {'scene': 'House', 'region': 'House'}, self.graph)
        self.assertEqual(result['graph']['current_node'], 'House')

    def test_assess_accepts_matching_compass_and_range(self):
        receipt = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm'}, self.graph)
        result = navigation.assess({'kind': 'waypoint', 'point': [460, 540]}, receipt)
        self.assertEqual((result['screen_compass'], result['range']), ('W', 'far'))
        self.assertTrue(result['allowed'])

    def test_assess_rejects_wrong_range_even_when_compass_matches(self):
        receipt = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm'}, self.graph)
        result = navigation.assess({'kind': 'waypoint', 'point': [760, 540]}, receipt)
        self.assertEqual(result['alignment'], 'range_mismatch')
        self.assertFalse(result['allowed'])

    def test_transition_proof_advances_current_node(self):
        before = {'scene': 'House', 'region': 'House', 'navigation': {
            'next_edge': {'from': 'HouseExit', 'to': 'Farm', 'transition': 'Farm'}}}
        navigation.advance(self.task, self.experience(before, {'scene': 'Farm', 'region': 'Farm'}))
        self.assertEqual(self.task.params['_nav_current'], 'Farm')
        self.assertEqual(self.task.params['_nav_current_proof']['source'], 'transition')

    def test_positioned_ancestry_advances_nested_current_node(self):
        proof = {'source': 'positioned_event', 'node': 'Well', 'regions': ['Farm', 'Garden']}
        before = {'scene': 'Farm', 'region': 'Farm', 'navigation': {
            'next_edge': {'from': 'Farm', 'to': 'Garden'}}}
        after = {'scene': 'Farm', 'region': 'Farm', 'regions': ['Farm', 'Garden'],
                 'region_provenance': proof}
        navigation.advance(self.task, self.experience(before, after))
        self.assertEqual(self.task.params['_nav_current'], 'Garden')
        self.assertEqual(self.task.params['_nav_current_proof'], proof)

    def test_waypoint_motion_alone_never_advances_graph_node(self):
        before = {'scene': 'Farm', 'region': 'Farm', 'navigation': {
            'next_edge': {'from': 'Farm', 'to': 'Garden'}}}
        navigation.advance(self.task, self.experience(before, {'scene': 'Farm', 'region': 'Farm'}))
        self.assertNotIn('_nav_current', self.task.params)

    def test_navigation_destination_can_complete_from_positioned_node_proof(self):
        state = {'scene': 'Farm', 'region': 'Farm', 'regions': ['Farm', 'Garden'],
                 'region_provenance': {'source': 'positioned_event', 'node': 'Well',
                                       'regions': ['Farm', 'Garden']}}
        self.assertTrue(play.region_matches(state, 'Well'))


if __name__ == '__main__':
    unittest.main()
