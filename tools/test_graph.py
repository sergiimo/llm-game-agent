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


if __name__ == '__main__':
    unittest.main()
