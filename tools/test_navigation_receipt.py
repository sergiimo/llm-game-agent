import json
import os
import tempfile
import unittest
from unittest import mock

from game import experience as X
from game import navigation
from game.task_state import TaskState
import nav
from objects import graph as OG
from game import world


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
        self.task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_near': 'Blacksmith'})
        self.observation = {'scene': 'Town', 'region': 'Town', 'position': [0.0, 0.0],
                            'state_provenance': {'position': {'source': 'save'}}}

    def test_receipt_resolves_destination_and_exposes_next_graph_compass(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        result = navigation.receipt(self.task, self.observation, graph=graph)

        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['requested'], 'supermarket')
        self.assertEqual(result['goal']['node'], 'DahlGeneralStore')
        self.assertEqual(result['next_edge']['to'], 'TownHall')
        self.assertEqual(result['next_edge']['compass'], 'E')
        self.assertTrue(result['next_edge']['walkable'])
        self.assertNotIn('route', result)
        self.assertEqual(result['graph']['path'], ['Blacksmith', 'TownHall', 'DahlGeneralStore'])
        self.assertTrue(result['graph']['current_navigation_only'])
        self.assertFalse(result['graph']['current_enterable'])
        self.assertEqual(result['position']['source'], 'save')

    @staticmethod
    def town_graph():
        graph = OG.Graph()
        graph.nodes['Town'] = OG.Node('Town', 'region')
        graph.nodes['Blacksmith'] = OG.Node('Blacksmith', 'unique', region='Town', pos=[0, 0], navigation_only=True)
        graph.nodes['TownHall'] = OG.Node('TownHall', 'unique', region='Town', pos=[5, 0], navigation_only=True)
        graph.nodes['DahlGeneralStore'] = OG.Node('DahlGeneralStore', 'unique', region='Town', pos=[10, -10], enterable=True)
        graph.nodes['Tara'] = OG.Node('Tara', 'unique', region='Town', pos=[0, 0])
        graph.add_edge('Blacksmith', 'TownHall', 'nav', compass='E')
        graph.add_edge('TownHall', 'DahlGeneralStore', 'nav', compass='SE')
        graph.add_edge('Tara', 'Blacksmith', 'near')
        return graph

    def test_unknown_destination_stays_explicitly_unresolved(self):
        self.task.params['destination'] = 'mystery shop'

        result = navigation.receipt(self.task, self.observation)

        self.assertEqual(result['status'], 'unresolved_destination')
        self.assertNotIn('route', result)

    def test_assess_uses_next_edge_for_heading(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_near': 'Blacksmith'})
        result = navigation.assess({'kind': 'waypoint', 'point': [460, 40]},
                                   navigation.receipt(task, self.observation, self.town_graph()))
        self.assertEqual(result['graph_compass'], 'E')
        self.assertEqual(result['alignment'], 'mismatch')

    def test_assess_rejects_waypoint_over_one_compass_sector_from_graph_edge(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_near': 'Blacksmith'})
        result = navigation.assess({'kind': 'waypoint', 'point': [460, 40]},
                                   navigation.receipt(task, self.observation, self.town_graph()))

        self.assertEqual(result['world']['compass'], 'NW')
        self.assertEqual(result['graph_compass'], 'E')
        self.assertEqual(result['alignment'], 'mismatch')
        self.assertFalse(result['allowed'])

    def test_assess_uses_fixed_camera_screen_compass_when_homography_reverses_axis(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_near': 'Blacksmith'})
        receipt = navigation.receipt(task, self.observation, self.town_graph())
        receipt['calibration'] = {'available': True, 'H': [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]}
        result = navigation.assess({'kind': 'waypoint', 'point': [1460, 540]}, receipt)
        self.assertEqual(result['screen_compass'], 'E')
        self.assertEqual(result['world']['compass'], 'W')
        self.assertEqual(result['alignment'], 'aligned')
        self.assertTrue(result['allowed'])

    def test_graph_nav_edges_are_intrinsically_walkable(self):
        graph = OG.Graph()
        graph.add_edge('a', 'b', 'nav')
        self.assertTrue(graph.edges('a', 'nav')[0]['walkable'])
        with self.assertRaises(ValueError):
            graph.add_edge('a', 'c', 'nav', walkable=False)

    def test_stale_near_node_is_rejected_in_favor_of_spatially_current_landmark(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        graph.nodes['TownFarmExit'] = OG.Node('TownFarmExit', 'unique', region='Town', pos=[-20, 0], navigation_only=True)
        graph.add_edge('TownFarmExit', 'Blacksmith', 'nav', compass='E')
        graph._edges = [e for e in graph._edges if not (e['a'] == 'Tara' and e['rel'] == 'near')]
        graph.add_edge('Tara', 'TownFarmExit', 'near')
        graph.nodes['Tara'].extra['pos'] = [-20, 0]
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_near': 'TownFarmExit'})
        result = navigation.receipt(task, self.observation, graph=graph)
        self.assertEqual(result['graph']['current_node'], 'Blacksmith')
        self.assertEqual(result['next_edge']['to'], 'TownHall')
        self.assertEqual(result['next_edge']['compass'], 'E')

    def test_wrong_dead_reckoning_estimate_cannot_move_durable_current_node(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        graph.nodes['TownFarmExit'] = OG.Node('TownFarmExit', 'unique', region='Town', pos=[-20, 0], navigation_only=True)
        graph.add_edge('TownFarmExit', 'Blacksmith', 'nav', compass='E')
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_current': 'Blacksmith',
                                                   '_nav_current_proof': {'source': 'save', 'path': '/save',
                                                                          'save_count': 1, 'game_time': 'D1 9:00:00 AM'},
                                                   '_nav_estimate': {'scene': 'Town', 'position': [-20, 0]}})
        result = navigation.receipt(task, self.observation, graph=graph)
        self.assertEqual(result['graph']['current_node'], 'Blacksmith')

    def test_initial_current_uses_fresh_observation_not_dead_reckoned_estimate(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        graph.nodes['TownFarmExit'] = OG.Node('TownFarmExit', 'unique', region='Town', pos=[-20, 0], navigation_only=True)
        graph.add_edge('TownFarmExit', 'Blacksmith', 'nav', compass='E')
        task = TaskState('t', 'navigate', params={'destination': 'supermarket',
                                                   '_nav_estimate': {'scene': 'Town', 'position': [-20, 0]}})
        result = navigation.receipt(task, self.observation, graph=graph)
        self.assertEqual(result['graph']['current_node'], 'Blacksmith')

    def test_map_pin_selects_nearest_map_landmark_and_close_persists_current(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        graph.nodes['FountainSquare'] = OG.Node('FountainSquare', 'region', region='Town', pos=[12, -8])
        graph._edges = [e for e in graph._edges
                        if not (e['a'] == 'TownHall' and e['b'] == 'DahlGeneralStore' and e['rel'] == 'nav')]
        graph.add_edge('TownHall', 'FountainSquare', 'nav', compass='S')
        graph.add_edge('FountainSquare', 'DahlGeneralStore', 'nav', compass='W')
        for name, point in (('Blacksmith', [400, 400]), ('TownHall', [1000, 500]),
                            ('FountainSquare', [1040, 650]), ('DahlGeneralStore', [1100, 700])):
            graph.nodes[name].extra['map'] = {'scene': 'Town', 'point': point}
        task = TaskState('t', 'navigate', params={'destination': 'supermarket'})
        map_observation = dict(self.observation, screen={'kind': 'map'}, map_pin=[1005, 505])
        receipt = navigation.receipt(task, map_observation, graph=graph)
        self.assertEqual(receipt['graph']['current_node'], 'TownHall')
        self.assertEqual(receipt['graph']['current_source'], 'map_pin')
        self.assertEqual(receipt['next_edge']['to'], 'FountainSquare')
        self.assertEqual(receipt['next_edge']['compass'], 'S')
        experience = X.Experience.new(
            before=X.Observation('map', state=tuple({'navigation': receipt, 'scene': 'Town',
                'state_provenance': {'position': {'source': 'save', 'path': '/save', 'save_count': 7,
                                                  'game_time': 'D7 9:00:00 AM'}}}.items())),
            action=X.Action('close', None), evidence=X.Evidence(mode='gameplay'), verdict=X.Verdict('hit'))
        navigation.advance(task, experience)
        self.assertEqual(task.params['_nav_current'], 'TownHall')
        self.assertEqual(task.params['_nav_current_proof']['save_count'], 7)

    def test_distant_map_pin_does_not_select_or_persist_a_landmark(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        for name, point in (('Blacksmith', [400, 400]), ('TownHall', [1000, 500]),
                            ('DahlGeneralStore', [1100, 700])):
            graph.nodes[name].extra['map'] = {'scene': 'Town', 'point': point}
        task = TaskState('t', 'navigate', params={'destination': 'supermarket'})
        receipt = navigation.receipt(task, dict(self.observation, screen={'kind': 'map'}, map_pin=[1500, 900]), graph)
        self.assertEqual(receipt['status'], 'unresolved_graph_position')
        self.assertIsNone(receipt['graph']['current_node'])

    def test_ambiguous_map_pin_does_not_select_or_persist_a_landmark(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        for name, point in (('Blacksmith', [400, 400]), ('TownHall', [1000, 500]),
                            ('DahlGeneralStore', [1010, 500])):
            graph.nodes[name].extra['map'] = {'scene': 'Town', 'point': point}
        task = TaskState('t', 'navigate', params={'destination': 'supermarket'})
        receipt = navigation.receipt(task, dict(self.observation, screen={'kind': 'map'}, map_pin=[1005, 500]), graph)
        self.assertEqual(receipt['status'], 'unresolved_graph_position')
        self.assertIsNone(receipt['graph']['current_node'])

    def test_newer_external_save_invalidates_durable_graph_current(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = self.town_graph()
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_current': 'TownHall',
            '_nav_current_proof': {'source': 'save', 'path': '/save', 'save_count': 1,
                                   'game_time': 'D1 9:00:00 AM'}})
        observation = dict(self.observation, position=[0, 0], state_provenance={'position': {
            'source': 'save', 'path': '/save', 'save_count': 2, 'game_time': 'D1 9:10:00 AM'}})
        receipt = navigation.receipt(task, observation, graph)
        self.assertEqual(receipt['graph']['current_node'], 'Blacksmith')
        self.assertEqual(receipt['graph']['current_source'], 'observed_position')

    def test_successful_waypoint_refreshes_durable_current_proof_without_advancing_node(self):
        task = TaskState('t', 'navigate', params={'destination': 'supermarket'})
        before = {'scene': 'Town', 'navigation': {'graph': {'current_node': 'Blacksmith'},
            'position': {'value': [0, 0]}, 'calibration': {'available': True,
            'H': [[1, 0, 0], [0, -1, 0], [0, 0, 1]]}},
            'state_provenance': {'position': {'source': 'save', 'path': '/save', 'save_count': 1,
                                              'game_time': 'D1 9:00:00 AM'}}}
        after = {'state_provenance': {'position': {'source': 'save', 'path': '/save', 'save_count': 2,
                                                   'game_time': 'D1 9:10:00 AM'}}}
        experience = X.Experience.new(before=X.Observation('gameplay', state=tuple(before.items())),
            action=X.Action('click', 'step', (1460, 1040), context=(('primitive', 'waypoint'),)),
            evidence=X.Evidence(mode='gameplay', moved=True, state=tuple(after.items())), verdict=X.Verdict('hit'))
        navigation.advance(task, experience)
        self.assertEqual(task.params['_nav_current'], 'Blacksmith')
        self.assertEqual(task.params['_nav_current_proof']['save_count'], 2)

    def test_waypoint_does_not_advance_durable_graph_node(self):
        task = TaskState('t', 'navigate', params={'destination': 'supermarket'})
        before = {'scene': 'Town', 'navigation': {'graph': {'current_node': 'Blacksmith'},
                  'position': {'value': [0, 0]},
                  'calibration': {'available': True, 'H': [[1, 0, 0], [0, -1, 0], [0, 0, 1]]}}}
        experience = X.Experience.new(
            before=X.Observation('gameplay', state=tuple(before.items())),
            action=X.Action('click', 'step', (1460, 1040), context=(('primitive', 'waypoint'),)),
            evidence=X.Evidence(mode='gameplay', moved=True), verdict=X.Verdict('hit'))
        navigation.advance(task, experience)
        self.assertEqual(task.params['_nav_current'], 'Blacksmith')

    def test_town_landmarks_and_edges_load_from_config_and_calibration(self):
        graph = OG.Graph()
        graph.nodes['Tara'] = OG.Node('Tara', 'unique', region='Town', pos=[-3, 7])
        graph.nodes['Blacksmith'] = OG.Node('Blacksmith', 'unique', region='Town', pos=[0, 0])
        graph.add_edge('Tara', 'Blacksmith', 'near')
        world.landmarks(graph)
        self.assertIn('Blacksmith', graph.nodes)
        self.assertTrue(graph.nodes['Blacksmith'].extra['navigation_only'])
        self.assertFalse(graph.nodes['Blacksmith'].extra.get('enterable', False))
        self.assertTrue(graph.edges('Blacksmith', 'nav'))
        self.assertEqual(graph.nodes['Tara'].extra['pos'], [-3, 7])

    def test_farm_linktown_loads_at_global_boundary_with_walkable_cross_scene_edges(self):
        graph = OG.Graph()
        world.landmarks(graph)
        self.assertIn('Farm/LinkTown', graph.nodes)
        self.assertEqual(graph.nodes['Farm/LinkTown'].kind, 'LinkTown')
        self.assertEqual(graph.nodes['Farm/LinkTown'].region, 'Farm')
        self.assertTrue(graph.nodes['Farm/LinkTown'].extra['navigation_only'])
        outward = next(edge for edge in graph.edges('TownFarmExit', 'nav') if edge['b'] == 'Farm/LinkTown')
        inward = next(edge for edge in graph.edges('Farm/LinkTown', 'nav') if edge['b'] == 'TownFarmExit')
        self.assertEqual(outward['compass'], 'NW')
        self.assertEqual(inward['compass'], 'SE')
        self.assertTrue(outward['walkable'])
        self.assertTrue(inward['walkable'])

    def test_navigation_bfs_can_cross_town_farm_boundary_to_linktown(self):
        fit = {'a': .4108944907915737, 'b': -419.5982028457263,
               'c': -.34785643564361113, 'd': 270.8327425742876}
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {'Town': fit, 'Farm': fit},
                       'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        graph = OG.Graph()
        world.landmarks(graph)
        town_exit = graph.nodes['TownFarmExit'].extra['pos']
        task = TaskState('t', 'navigate', params={'destination': 'Farm/LinkTown'})
        observation = {'scene': 'Town', 'region': 'Town', 'position': list(town_exit)}
        result = navigation.receipt(task, observation, graph)
        self.assertEqual(result['graph']['current_node'], 'TownFarmExit')
        self.assertEqual(result['graph']['path'], ['TownFarmExit', 'Farm/LinkTown'])
        self.assertEqual(result['next_edge']['to'], 'Farm/LinkTown')
        self.assertEqual(result['next_edge']['compass'], 'NW')
        self.assertTrue(result['next_edge']['walkable'])

    def test_assess_accepts_waypoint_within_graph_compass_sector(self):
        with open(os.path.join(self.root, 'map.json'), 'w') as stream:
            json.dump({'places': {}, 'fits': {}, 'aliases': {'supermarket': 'DahlGeneralStore'}}, stream)
        task = TaskState('t', 'navigate', params={'destination': 'supermarket', '_nav_near': 'Blacksmith'})
        result = navigation.assess({'kind': 'waypoint', 'point': [1460, 1040]},
                                   navigation.receipt(task, self.observation, self.town_graph()))

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

    def test_advance_prefers_observed_post_action_position_over_homography(self):
        before = {'scene': 'Town', 'position': [-46.9, 3.0],
                  'state_provenance': {'position': {'source': 'save', 'path': '/save', 'save_count': 8021,
                                                    'game_time': 'D213 9:00:00 AM'}},
                  'navigation': {'position': {'value': [-46.9, 3.0]},
                                 'calibration': {'available': True,
                                                 'H': [[1, 0, 0], [0, -1, 0], [0, 0, 1]]}}}
        experience = X.Experience.new(
            before=X.Observation('gameplay', state=tuple(before.items())),
            action=X.Action('click', 'step', (1750, 650), context=(('primitive', 'waypoint'),)),
            evidence=X.Evidence(mode='gameplay', moved=True,
                                state=(('scene', 'Town'), ('position', [-57.66, 3.4]),
                                       ('state_provenance', {'position': {'source': 'save', 'path': '/save',
                                                                          'save_count': 8023,
                                                                          'game_time': 'D213 9:10:00 AM'}}))),
            verdict=X.Verdict('hit'))
        navigation.advance(self.task, experience)
        self.assertEqual(self.task.params['_nav_estimate']['position'], [-57.66, 3.4])
        self.assertEqual(self.task.params['_nav_estimate']['source'], 'observed_position')

    def test_advance_ignores_post_position_from_same_save_revision(self):
        before = {'scene': 'Town', 'position': [-46.9, 3.0],
                  'state_provenance': {'position': {'source': 'save', 'path': '/save', 'save_count': 8023,
                                                    'game_time': 'D213 9:10:00 AM'}},
                  'navigation': {'position': {'value': [-46.9, 3.0]},
                                 'calibration': {'available': True,
                                                 'H': [[1, 0, 0], [0, -1, 0], [0, 0, 1]]}}}
        experience = X.Experience.new(
            before=X.Observation('gameplay', state=tuple(before.items())),
            action=X.Action('click', 'step', (1750, 650), context=(('primitive', 'waypoint'),)),
            evidence=X.Evidence(mode='gameplay', moved=True,
                                state=(('scene', 'Town'), ('position', [-57.66, 3.4]),
                                       ('state_provenance', {'position': {'source': 'save', 'path': '/save',
                                                                          'save_count': 8023,
                                                                          'game_time': 'D213 9:10:00 AM'}}))),
            verdict=X.Verdict('hit'))
        navigation.advance(self.task, experience)
        self.assertEqual(self.task.params['_nav_estimate']['position'], [-45.32, 2.78])
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
