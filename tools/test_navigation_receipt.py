"""Qualitative navigation receipts: graph topology, one-frame bearings, and proof-only progress."""
import json
import os
import tempfile
import unittest
from unittest import mock

from game import experience as X
from game import navigation, play, world
from game.task_state import Subgoal, TaskState
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
        graph.nodes['House'] = OG.Node('House', 'region', region='Farm')
        graph.nodes['Bed'] = OG.Node('Bed', 'unique', region='House')
        graph.nodes['HouseExit'] = OG.Node('HouseExit', 'unique', region='House', navigation_only=True)
        graph.nodes['Farm'] = OG.Node('Farm', 'region')
        graph.nodes['Garden'] = OG.Node('Garden', 'region', region='Farm')
        graph.nodes['Well'] = OG.Node('Well', 'unique', region='Garden')
        graph.add_edge('House', 'HouseExit', 'nav', compass='S', range='far', source='test')
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
        self.assertEqual((result['next_edge']['compass'], result['next_edge']['range']), ('S', 'far'))
        self.assertNotIn('position', result)
        self.assertNotIn('calibration', result)
        self.assertNotIn('route', result)

    def test_sleep_spawn_anchor_starts_house_route_at_bed(self):
        self.graph.nodes['BedroomPassage'] = OG.Node(
            'BedroomPassage', 'unique', region='House', navigation_only=True)
        self.graph.add_edge('Bed', 'BedroomPassage', 'nav', compass='E', range='far', source='stable house layout')
        self.graph.add_edge(
            'BedroomPassage', 'HouseExit', 'nav', compass='SE', range='far', source='stable house layout')

        result = navigation.receipt(self.task, {
            'scene': 'House', 'region': 'House', 'position_node': 'Bed',
            'position_node_provenance': {'source': 'sleep_spawn'},
        }, self.graph)

        self.assertEqual(result['graph']['current_node'], 'Bed')
        self.assertEqual(result['graph']['current_source'], 'sleep_spawn')
        self.assertEqual(result['graph']['path'][:3], ['Bed', 'BedroomPassage', 'HouseExit'])
        self.assertEqual(result['next_edge']['compass'], 'E')
        self.assertEqual(result['localization']['stage'], 'graph')
        self.assertEqual(result['localization']['current'], 'Bed')
        self.assertEqual(result['localization']['next'], 'follow_graph_route')

    def test_live_house_graph_has_bidirectional_compass_route_from_bed_to_exit(self):
        graph = OG.Graph()
        graph.load(os.path.join(os.path.dirname(__file__), 'objects', 'graph', 'Farm.json'))
        expected = {
            ('Bed', 'House/BedroomPassage'): ('E', 'far'),
            ('House/BedroomPassage', 'Bed'): ('W', 'far'),
            ('House/BedroomPassage', 'HouseExit'): ('SE', 'far'),
            ('HouseExit', 'House/BedroomPassage'): ('NW', 'far'),
        }

        actual = {(edge['a'], edge['b']): (edge.get('compass'), edge.get('range'))
                  for edge in graph.edges(rel='nav') if (edge['a'], edge['b']) in expected}

        self.assertEqual(actual, expected)
        self.assertFalse(any(edge['rel'] == 'nav' and {edge['a'], edge['b']} == {'House', 'Bed'}
                             for edge in graph.edges()))

    def test_unmarked_well_uses_nearest_map_labeled_garden_ancestor(self):
        graph = OG.Graph()
        graph.load(os.path.join(os.path.dirname(__file__), 'objects', 'graph', 'Farm.json'))

        result = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm'}, graph)

        self.assertEqual(result['goal']['node'], 'Well')
        self.assertEqual(result['goal']['map_anchor'], {
            'node': 'Garden', 'kind': 'MapGarden', 'label': 'farm-garden', 'exact': False})
        self.assertEqual(navigation.map_target(result), 'Garden')

    def test_current_map_hint_overrides_coarse_scene_compass(self):
        self.task.params.update(destination='House', _route_hint={
            'region': 'Farm', 'target': 'House', 'compass': 'E', 'range': 'mid',
            'set_turn': 47, 'expires_turn': 53, 'remaining_steps': 6,
            'source': 'model_map', 'frame_path': '/tmp/current-map.jpg',
        })
        self.graph.add_edge('Farm', 'HouseExit', 'nav', compass='N', range='far',
                            source='coarse scene topology')
        self.graph.add_edge('HouseExit', 'House', 'nav', compass='N', range='near',
                            source='house approach')

        result = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm'}, self.graph)

        self.assertEqual(result['graph']['path'], ['Farm', 'HouseExit', 'House'])
        self.assertEqual(result['next_edge']['to'], 'HouseExit')
        self.assertEqual((result['next_edge']['compass'], result['next_edge']['range']), ('E', 'mid'))
        self.assertEqual(result['next_edge']['source'], 'model_map')

    def test_unknown_destination_is_explicitly_unresolved(self):
        self.task.params['destination'] = 'teleporter'
        result = navigation.receipt(self.task, {'scene': 'House', 'region': 'House'}, self.graph)
        self.assertEqual(result['status'], 'unresolved_destination')

    def test_numeric_position_cannot_choose_a_deeper_graph_origin(self):
        result = navigation.receipt(self.task, {'scene': 'Farm', 'region': 'Farm',
                                                 'position': [0.84, -25.34]}, self.graph)
        self.assertEqual(result['graph']['current_node'], 'Farm')
        self.assertEqual(result['next_edge']['to'], 'Garden')

    def test_vector_landmark_localizes_relative_to_tara_and_keeps_route_slice(self):
        observation = {
            'scene': 'Farm', 'region': 'Farm',
            'candidates': [
                {'id': 'vector-0', 'source': 'vector', 'kind': 'Well',
                 'point': [1200, 540], 'view_id': 'view-1'},
                {'id': 'tara-feet', 'source': 'tracker', 'kind': 'Tara',
                 'point': [960, 620], 'view_id': 'view-1'},
            ],
        }

        result = navigation.receipt(self.task, observation, self.graph)

        localization = result['localization']
        self.assertEqual(localization['stage'], 'vectors')
        self.assertEqual(localization['current'], 'unknown')
        self.assertEqual(localization['likely_region'], 'Farm')
        self.assertIsNone(localization['prior_hint'])
        self.assertNotIn('vision', localization)
        self.assertEqual(localization['next'], 'localize_from_vectors_and_graph')
        self.assertEqual(localization['landmarks'], [{
            'candidate': 'vector-0', 'kind': 'Well', 'node': 'Well',
            'point': [1200, 540], 'landmark_from_tara': 'E', 'tara_from_landmark': 'W',
            'region': 'Garden',
        }])
        self.assertEqual(localization['graph_slice']['route_nodes'], ['Farm', 'Garden', 'Well'])
        self.assertEqual(localization['graph_slice']['route_edges'][0], {
            'from': 'Farm', 'to': 'Garden', 'compass': 'W', 'range': 'far',
            'source': 'test', 'transition': None,
        })

    def test_context_landmark_uses_only_the_strongest_hit_for_one_unique_node(self):
        observation = {
            'scene': 'Farm', 'region': 'Farm',
            'candidates': [
                {'id': 'weak', 'source': 'vector', 'kind': 'Well', 'score': 4.2,
                 'point': [500, 500]},
                {'id': 'strong', 'source': 'vector', 'kind': 'Well', 'score': 7.1,
                 'point': [1200, 540]},
            ],
        }

        landmarks = navigation.receipt(self.task, observation, self.graph)['localization']['landmarks']

        self.assertEqual([row['candidate'] for row in landmarks], ['strong'])
        self.assertEqual(landmarks[0]['point'], [1200, 540])

    def test_no_vectors_requests_vision_and_vector_creation_before_map(self):
        result = navigation.receipt(self.task, {
            'scene': 'Farm', 'region': 'Farm',
            'candidates': [{'id': 'tara-feet', 'source': 'tracker', 'kind': 'Tara',
                            'point': [960, 620]}],
        }, self.graph)

        localization = result['localization']
        self.assertEqual(localization['stage'], 'vision')
        self.assertEqual(localization['current'], 'unknown')
        self.assertEqual(localization['landmarks'], [])
        self.assertEqual(localization['next'], 'identify_unique_object_and_create_vector')
        self.assertEqual(localization['after_vision'], 'map_if_still_unresolved')
        self.assertEqual(localization['graph_slice']['route_nodes'], ['Farm', 'Garden', 'Well'])

    def test_region_container_vector_is_not_a_localization_landmark(self):
        result = navigation.receipt(self.task, {
            'scene': 'Farm', 'region': 'Farm',
            'candidates': [{'id': 'vector-0', 'source': 'vector', 'kind': 'Garden',
                            'point': [1200, 700]}],
        }, self.graph)

        self.assertEqual(result['localization']['stage'], 'vision')
        self.assertEqual(result['localization']['landmarks'], [])
        self.assertEqual(result['localization']['next'], 'identify_unique_object_and_create_vector')

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

    def test_nested_navigate_progress_is_stored_on_the_active_child_and_used_by_next_receipt(self):
        task = TaskState('route', 'garden', params={'region': 'Garden'},
                         stack=[Subgoal('navigate', {'destination': 'Well'})])
        proof = {'source': 'positioned_event', 'node': 'Well', 'regions': ['Farm', 'Garden']}
        before = {'scene': 'Farm', 'region': 'Farm', 'navigation': {
            'next_edge': {'from': 'Farm', 'to': 'Garden'}}}
        after = {'scene': 'Farm', 'region': 'Farm', 'regions': ['Farm', 'Garden'],
                 'region_provenance': proof}

        navigation.advance(task, self.experience(before, after))

        self.assertNotIn('_nav_current', task.params)
        self.assertEqual(task.stack[-1].params['_nav_current'], 'Garden')
        result = navigation.receipt(task.stack[-1], {'scene': 'Farm', 'region': 'Farm'}, self.graph)
        self.assertEqual(result['graph']['current_node'], 'Garden')
        self.assertEqual(result['next_edge']['to'], 'Well')

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

    def test_spawn_anchor_recovers_nested_region_until_an_explicit_exit(self):
        lines = ['[D5 7:16:57 PM] [GAME] ChangeScene Farm/Bed',
                 '[D5 7:16:57 PM] [MODE] Spawning player at Farm/Bed']
        self.assertEqual(world.graph_scope(lines, self.graph, 'Farm', 'Farm'), 'House')
        anchor = getattr(world, 'graph_position_anchor', lambda *_: None)(lines, self.graph, 'Farm')
        self.assertEqual(anchor, 'Bed')
        lines.append('[D6 8:10:00 AM] [GAME] OnExitBuilding House')
        self.assertEqual(world.graph_scope(lines, self.graph, 'Farm', 'Farm'), 'Farm')
        anchor = getattr(world, 'graph_position_anchor', lambda *_: None)(lines, self.graph, 'Farm')
        self.assertIsNone(anchor)


if __name__ == '__main__':
    unittest.main()
