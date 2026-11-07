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
from game.world_store import WorldStore, classify_seed  # noqa: E402
from game.observations import ObservationStore  # noqa: E402
from runtime.db import Database  # noqa: E402
from runtime.run_store import RunStore  # noqa: E402
from runtime.save_lineage import LogEpoch, SaveCandidate  # noqa: E402

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


class WorldOverlay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(os.path.join(self.tmp.name, 'wf.sqlite3'))

    def profile(self, name, count=1):
        directory = os.path.join(self.tmp.name, name)
        os.makedirs(directory, exist_ok=True)
        run_id = RunStore(self.db).start(name, 'overlay', directory)
        game_time = 4 * 86400 + count
        candidate = SaveCandidate(name, os.path.join(directory, '1.local'), name, 'digest-' + name,
                                  count, game_time, 'Farm', {})
        observation = ObservationStore(self.db).capture(
            run_id, [candidate], LogEpoch('log-' + name, game_time, game_time))
        return run_id, observation

    def test_seed_classification_rejects_dynamic_fields_and_local_paths(self):
        with open(os.path.join(ROOT, 'tools', 'objects', 'graph', 'Farm.json')) as stream:
            cleaned = json.load(stream)
        self.assertEqual(classify_seed(cleaned), [])
        dirty = {'area': 'Farm', '_refresh_conflicts': [{'x': 1}], 'unnamed': 3, 'nodes': [{
            'id': 'Bed', 'type': 'unique', 'kind': 'Bed', 'region': 'House',
            'state': {'ready': True}, 'vec': [1], 'seen': 4, 'exps': ['e'],
            'interaction_hint': {'frame_path': '/tmp/run/frame.jpg'},
            'appearance_needed': True, 'appearance_sample': {'frame_path': '/tmp/a.jpg'}}], 'edges': []}
        fields = {(owner, field) for owner, field, _ in classify_seed(dirty)}
        self.assertTrue({('root', '_refresh_conflicts'), ('root', 'unnamed'), ('Bed', 'state'),
                         ('Bed', 'vec'), ('Bed', 'seen'), ('Bed', 'exps'),
                         ('Bed', 'interaction_hint'), ('Bed', 'appearance_needed'),
                         ('Bed', 'appearance_sample')} <= fields)

    def test_overlay_is_profile_scoped_cut_off_by_observation_and_keeps_provenance(self):
        _, first = self.profile('p1', 1)
        store = WorldStore(self.db, first.profile_id)
        store.upsert_local_node(G.Node('Local', 'unique', 'Local', 'Farm'), {'source': 'vision'}, first.observation_id)
        store.upsert_edge('Tara', 'Local', 'toward', {'compass': 'E'}, {'source': 'vision'}, first.observation_id)
        store.append_fact('Well', 'can', 'empty', 'save', first.observation_id, game_time=first.candidate.game_time)
        candidate = SaveCandidate('p1', '/p1/2.local', 'slot2', 'digest2', 2,
                                  first.candidate.game_time + 1, 'Farm', {})
        second = ObservationStore(self.db).capture(
            RunStore(self.db).active()['id'], [candidate],
            LogEpoch('log-p1', first.candidate.game_time, candidate.game_time))
        store.append_fact('Well', 'can', 'full', 'event', second.observation_id,
                          game_time=second.candidate.game_time)
        old = store.load(SEED, first.observation_id)
        new = store.load(SEED, second.observation_id)
        self.assertEqual(old.state_value('Well', 'can'), 'empty')
        self.assertEqual(new.state_value('Well', 'can'), 'full')
        self.assertEqual(new.nodes['Local'].extra['local_provenance'], {'source': 'vision'})
        self.assertEqual(new.edges('Tara', 'toward')[-1]['provenance'], {'source': 'vision'})
        _, other = self.profile('p2', 1)
        isolated = WorldStore(self.db, other.profile_id).load(SEED, other.observation_id)
        self.assertNotIn('Local', isolated.nodes)
        self.assertIsNone(isolated.state_value('Well', 'can'))

    def test_local_node_and_edge_updates_preserve_as_of_observation_history(self):
        run_id, first = self.profile('versions', 1)
        store = WorldStore(self.db, first.profile_id)
        store.upsert_local_node(G.Node('Local', 'unique', 'Local', 'Farm', pos=[1., 1.]),
                                {'source': 'vision', 'version': 1}, first.observation_id)
        store.upsert_edge('Tara', 'Local', 'toward', {'compass': 'E'},
                          {'source': 'vision', 'version': 1}, first.observation_id)
        candidate = SaveCandidate('versions', '/versions/2.local', 'slot2', 'digest2', 2,
                                  first.candidate.game_time + 1, 'Farm', {})
        second = ObservationStore(self.db).capture(
            run_id, [candidate], LogEpoch('log-versions', first.candidate.game_time, candidate.game_time))
        store.upsert_local_node(G.Node('Local', 'unique', 'Local', 'Farm', pos=[2., 2.]),
                                {'source': 'vision', 'version': 2}, second.observation_id)
        store.upsert_edge('Tara', 'Local', 'toward', {'compass': 'W'},
                          {'source': 'vision', 'version': 2}, second.observation_id)
        old, new = store.load(SEED, first.observation_id), store.load(SEED, second.observation_id)
        self.assertEqual(old.nodes['Local'].extra['pos'], [1., 1.])
        self.assertEqual(new.nodes['Local'].extra['pos'], [2., 2.])
        self.assertEqual(old.edges('Tara', 'toward')[-1]['compass'], 'E')
        self.assertEqual(new.edges('Tara', 'toward')[-1]['compass'], 'W')

    def test_capture_does_not_restamp_a_stale_fact_over_newer_evidence(self):
        run_id, first = self.profile('facts', 1)
        store = WorldStore(self.db, first.profile_id)
        store.append_fact('Well', 'can', 'empty', 'save', first.observation_id,
                          first.candidate.game_time, 'D4 12:00:01 AM')
        candidate2 = SaveCandidate('facts', '/facts/2.local', 'slot2', 'digest2', 2,
                                   first.candidate.game_time + 1, 'Farm', {})
        second = ObservationStore(self.db).capture(
            run_id, [candidate2], LogEpoch('log-facts', first.candidate.game_time, candidate2.game_time))
        store.append_fact('Well', 'can', 'full', 'event', second.observation_id,
                          second.candidate.game_time, 'D4 12:00:02 AM')
        candidate3 = SaveCandidate('facts', '/facts/3.local', 'slot3', 'digest3', 3,
                                   first.candidate.game_time + 2, 'Farm', {})
        third = ObservationStore(self.db).capture(
            run_id, [candidate3], LogEpoch('log-facts', first.candidate.game_time, candidate3.game_time))
        stale = G.Graph()
        stale.load(SEED)
        stale.set_state('Well', 'can', 'empty', 'D4 12:00:01 AM', 'save')
        store.capture_graph(stale, SEED, third.observation_id, third.candidate.game_time, run_id)
        self.assertEqual(store.load(SEED, third.observation_id).state_value('Well', 'can'), 'full')

    def test_promotion_is_dry_run_by_default_and_rejects_dynamic_payloads(self):
        _, observation = self.profile('promotion', 1)
        store = WorldStore(self.db, observation.profile_id)
        node = G.Node('StableLandmark', 'unique', 'StableLandmark', 'Farm', pos=[3., 4.])
        store.upsert_local_node(node, {'review': 'candidate'}, observation.observation_id)
        seed = os.path.join(self.tmp.name, 'seed.json')
        with open(SEED) as source, open(seed, 'w') as target:
            target.write(source.read())
        before = open(seed, 'rb').read()
        preview = store.promote(['StableLandmark'], seed)
        self.assertIn('StableLandmark', preview)
        self.assertEqual(open(seed, 'rb').read(), before)
        store.promote(['StableLandmark'], seed, write=True)
        self.assertIn('StableLandmark', {row['id'] for row in json.load(open(seed))['nodes']})
        store.upsert_local_node({'id': 'Dirty', 'type': 'unique', 'kind': 'Dirty', 'region': 'Farm',
                                 'state': {'ready': True}}, {'review': 'bad'}, observation.observation_id)
        with self.assertRaisesRegex(ValueError, 'dynamic'):
            store.promote(['Dirty'], seed)

    def test_runtime_graph_capture_writes_overlay_without_touching_seed(self):
        run_id, observation = self.profile('capture', 1)
        store = WorldStore(self.db, observation.profile_id)
        graph = G.Graph()
        graph.load(SEED)
        graph.set_state('Well', 'can', 'full', 'D4 9:00:01 AM', 'event')
        graph.nodes['Discovered'] = G.Node('Discovered', 'unique', 'Discovered', 'Farm', pos=[7., 8.])
        graph.add_edge('Tara', 'Discovered', 'toward', compass='E', source='learned')
        with open(SEED, 'rb') as stream:
            before = stream.read()
        store.capture_graph(graph, SEED, observation.observation_id, observation.candidate.game_time, run_id)
        with open(SEED, 'rb') as stream:
            self.assertEqual(stream.read(), before)
        restored = store.load(SEED, observation.observation_id)
        self.assertEqual(restored.state_value('Well', 'can'), 'full')
        self.assertIn('Discovered', restored.nodes)
        self.assertEqual(restored.edges('Tara', 'toward')[-1]['b'], 'Discovered')

class GraphPersistence(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

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
