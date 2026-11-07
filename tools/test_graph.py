"""Offline tests for tools/objects/graph.py: the graph store under the engine's world (load/save, chain, state, frame
state, unknown keys) and directions between nodes. Run: .venv/bin/python -m unittest tools/test_graph.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects import graph as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, 'tools', 'fixtures', 'graph_seed.json')   # seed without live states


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def test_seed_has_the_frame_nodes_and_no_hand_made_members(self):
        for n in ('Farm', 'Garden', 'House', 'Well', 'Tara', 'GardenBed@Garden', 'BeeHive'):
            self.assertIn(n, self.g.nodes)
        self.assertFalse([n for n in self.g.nodes if '#r' in n or n.startswith('BeeHive#')])

    def test_chain(self):
        self.assertEqual(self.g.chain('GardenBed@Garden'), ['Farm', 'Garden', 'GardenBed@Garden'])

    def test_state_roundtrip(self):
        self.g.set_state('Well', 'can', 'full', 'D186 9:00:00 AM', 'event')
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.json')
            self.g.save(p)
            h = G.Graph()
            h.load(p)
        self.assertEqual(h.node('Well').state['can'], {'value': 'full', 'game_time': 'D186 9:00:00 AM',
                                                       'source': 'event', 'conf': 1.0})
        self.assertEqual(len(h.edges()), len(self.g.edges()))

    def test_frame_state_is_available_now_but_not_persisted(self):
        self.g.set_state('Well', 'bubble', {'kind': 'fill_can'}, 7, 'frame')
        self.g.nodes['Probe'] = G.Node('Probe', 'unique', 'Probe', 'Garden', transient=True)
        self.g.add_edge('Tara', 'Well', 'near', source='frame')
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.json')
            self.g.save(p)
            h = G.Graph()
            h.load(p)
        self.assertIsNone(h.state_value('Well', 'bubble'))
        self.assertIsNone(h.node('Probe'))
        self.assertEqual(h.edges('Tara', 'near'), [])
        self.g.clear_frame()
        self.assertIsNone(self.g.state_value('Well', 'bubble'))

    def test_unknown_keys_preserved(self):
        data = json.load(open(SEED))
        data['future'] = {'a': 1}
        data['nodes'][0]['note'] = 'keep'
        with tempfile.TemporaryDirectory() as d:
            p, q = os.path.join(d, 'a.json'), os.path.join(d, 'b.json')
            json.dump(data, open(p, 'w'))
            g = G.Graph()
            g.load(p)
            g.save(q)
            out = json.load(open(q))
        self.assertEqual((out['future'], out['nodes'][0]['note']), ({'a': 1}, 'keep'))

    def test_missing(self):
        self.assertIsNone(self.g.node('Nope'))
        self.assertEqual(self.g.children('Nope'), [])

    def test_load_normalizes_legacy_navigation_edge_walkability(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'graph.json')
            with open(p, 'w') as stream:
                json.dump({'nodes': [], 'edges': [{'a': 'A', 'b': 'B', 'rel': 'nav'}]}, stream)
            graph = G.Graph()
            graph.load(p)
        self.assertTrue(graph.edges(rel='nav')[0]['walkable'])

    def test_load_rejects_non_walkable_navigation_edge(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'graph.json')
            with open(p, 'w') as stream:
                json.dump({'nodes': [], 'edges': [{'a': 'A', 'b': 'B', 'rel': 'nav', 'walkable': False}]}, stream)
            with self.assertRaises(ValueError):
                G.Graph().load(p)


class Directions(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def test_seeded_direction_then_learned(self):
        d0 = G.toward(self.g, 'Well', 'GardenBed@Garden')
        self.assertEqual(d0, G.TOWARD[('Well', 'GardenBed@Garden')])
        G.learn_toward(self.g, 'Well', 'GardenBed@Garden', (1.0, 0.0))
        dx, dy = G.toward(self.g, 'Well', 'GardenBed@Garden')
        self.assertGreater(dx, d0[0])

    def test_direction_from_positions(self):
        self.g.nodes['Garden'].extra['pos'] = [2.09, -26.59]
        self.g.nodes['GardenSouth'] = G.Node('GardenSouth', 'region', 'Garden', 'Farm', pos=[8.27, -63.11])
        dx, dy = G.toward(self.g, 'Garden', 'GardenSouth')
        self.assertGreater(dy, 0.9)   # south = screen down

    def test_node_of_line(self):
        self.assertEqual(G.node_of_line('> water me=Player target=GardenBed (4) at (5.84, 0.10, -31.59)'),
                         'GardenBed@Garden')
        self.assertEqual(G.node_of_line('> fill_watering_can me=Player target=Well'), 'Well')


class GraphCli(unittest.TestCase):
    def test_show(self):
        r = subprocess.run([os.path.join(ROOT, 'wf'), 'graph', 'show', 'Garden'], capture_output=True, text=True,
                           timeout=120, env=dict(os.environ, WF_NO_DAEMON='1', WF_GRAPH=SEED))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('GardenBed@Garden', r.stdout)


class Compass(unittest.TestCase):
    """User D188: "graph as before should store compass direction for nodes connections"."""

    def test_a_way_between_nodes_keeps_its_compass_direction(self):
        from objects import graph as OG
        g = OG.Graph()
        OG.learn_toward(g, 'Mine', 'Garden', (0.0, 1.0))
        e, = g.edges('Mine', 'toward')
        self.assertEqual(e['compass'], 'S')
        g.add_edge('Well', 'BeeHive', 'toward', dir=[0.83, 0.55])
        self.assertEqual(g.edges('Well', 'toward')[0]['compass'], 'SE')
        self.assertEqual(OG.compass((-0.7, -0.7)), 'NW')
        self.assertEqual(OG.compass_dir('W'), (-1.0, 0.0))

    def test_a_compass_only_edge_gives_the_direction(self):
        from objects import graph as OG
        g = OG.Graph()
        g.add_edge('Mine', 'Garden', 'toward', compass='SW', source='vision')
        d = OG.toward(g, 'Mine', 'Garden')
        self.assertAlmostEqual(d[0], -0.707, 2)
        self.assertAlmostEqual(d[1], 0.707, 2)

    def test_a_relative_vision_observation_persists_and_points_back_to_the_region(self):
        from objects import graph as OG
        g = OG.Graph()
        OG.observe_relative(g, 'Tara', 'Garden', 'NW', 'near', 'D202 12:34:56 PM')
        e = OG.relative_to(g, 'Tara', 'Garden')
        self.assertEqual((e['compass'], e['distance'], e['source'], e['game_time']),
                         ('NW', 'near', 'vision', 'D202 12:34:56 PM'))
        dx, dy = OG.toward(g, 'Tara', 'Garden')
        self.assertGreater(dx, 0.7)
        self.assertGreater(dy, 0.7)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'relative.json')
            g.save(p)
            h = OG.Graph()
            h.load(p)
        self.assertEqual(OG.relative_to(h, 'Tara', 'Garden')['distance'], 'near')

    def test_relative_vision_observation_rejects_unknown_values(self):
        from objects import graph as OG
        with self.assertRaisesRegex(ValueError, 'compass'):
            OG.observe_relative(OG.Graph(), 'Tara', 'Garden', 'left-ish', 'near', 'D202')
        with self.assertRaisesRegex(ValueError, 'distance'):
            OG.observe_relative(OG.Graph(), 'Tara', 'Garden', 'NW', '17m', 'D202')


if __name__ == '__main__':
    unittest.main()
