"""Offline tests for tools/objects/graph.py (object graph with nested regions). Run: .venv/bin/python tools/test_graph.py"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects import graph as G  # noqa: E402
from objects import query as Qm, regions as R  # noqa: E402
from objects.detect import Detection  # noqa: E402

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')   # seed without live states


class GraphTest(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def test_seed_loads(self):
        self.assertEqual(len(self.g.members('GardenBed')), 12)
        self.assertEqual(len(self.g.members('BeeHive')), 8)
        self.assertEqual(self.g.parent('Garden'), 'Farm')
        self.assertEqual(self.g.parent('House'), 'Farm')
        self.assertIsNone(self.g.parent('Farm'))
        self.assertEqual(self.g.node('Garden').type, 'region')
        self.assertEqual(self.g.node('GardenBed').pattern['rows'], 3)
        self.assertEqual(self.g.node('Farm').signal, 'scene')
        self.assertEqual(self.g.node('Garden').signal, 'view')
        self.assertIn(('HouseDoor', 'House'), [(e['a'], e['b']) for e in self.g.edges(rel='leads_to')])
        self.assertEqual({e['b'] for e in self.g.edges('GardenBed', 'offers')}, {'plant', 'water', 'harvest', 'unplant'})
        self.assertEqual({n.id for n in self.g.children('House')}, {'Bed', 'Stove', 'HouseExit'})
        self.assertEqual(self.g.node('House').exit, 'HouseExit')
        self.assertIn(('HouseExit', 'Farm'), [(e['a'], e['b']) for e in self.g.edges(rel='leads_to')])
        self.assertIn('Well', {n.id for n in self.g.children('Garden')})

    def test_chain(self):
        self.assertEqual(self.g.chain('GardenBed#7'), ['Farm', 'Garden', 'GardenBed', 'GardenBed#7'])
        self.assertEqual(self.g.chain('Farm'), ['Farm'])

    def test_members_order(self):
        ids = [n.id for n in self.g.members('GardenBed')]
        self.assertEqual(ids, ['GardenBed#%d' % i for i in range(1, 13)])
        self.assertEqual(self.g.node('GardenBed#5').index, 5)

    def test_state_age_roundtrip(self):
        self.g.set_state('GardenBed#3', 'crop', 'tulip', 1234, 'log')
        self.assertEqual(self.g.state_value('GardenBed#3', 'crop'), 'tulip')
        self.assertIsNone(self.g.state_value('GardenBed#3', 'nope'))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'x.json')
            self.g.save(p)
            h = G.Graph()
            h.load(p)
        self.assertEqual(h.node('GardenBed#3').state['crop'], {'value': 'tulip', 'game_time': 1234, 'source': 'log'})
        self.assertEqual(h.chain('GardenBed#7'), self.g.chain('GardenBed#7'))
        self.assertEqual(len(h.edges()), len(self.g.edges()))

    def test_unknown_keys_preserved(self):
        with open(SEED) as f:
            data = json.load(f)
        data['future'] = {'a': 1}
        data['nodes'][0]['note'] = 'keep'
        with tempfile.TemporaryDirectory() as d:
            p, q = os.path.join(d, 'a.json'), os.path.join(d, 'b.json')
            with open(p, 'w') as f:
                json.dump(data, f)
            g = G.Graph()
            g.load(p)
            g.save(q)
            with open(q) as f:
                out = json.load(f)
        self.assertEqual(out['future'], {'a': 1})
        self.assertEqual(out['nodes'][0]['note'], 'keep')

    def test_missing(self):
        self.assertIsNone(self.g.node('Nope'))
        self.assertEqual(self.g.children('Nope'), [])
        self.assertEqual(self.g.chain('Nope'), [])
        self.assertEqual(self.g.members('Nope'), [])


LABELS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'frames', 'labels.json')))


def fake_dets(frame):
    """Detections built from the labels (one per boxed kind, at the box centre)."""
    out = []
    for k, boxes in LABELS[frame].items():
        if k in ('absent', 'region') or k.startswith('_'):
            continue
        for b in boxes:
            c = ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
            out.append(Detection(k, tuple(b), 6.0, None, c))
    return out


class QueryTest(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def ids(self, nodes):
        return [n.id for n in nodes]

    def test_query_bed_for_seed(self):
        for i in range(1, 13):
            if i not in (3, 9):
                self.g.set_state('GardenBed#%d' % i, 'crop', 'tulip', 1, 'log')
        q = Qm.Q(kind='GardenBed').where(crop=None)
        self.assertEqual(self.ids(q.run(self.g, 'Garden')), ['GardenBed#3', 'GardenBed#9'])
        self.assertEqual(self.ids(q.run(self.g, 'Garden', visible={'GardenBed#9'})), ['GardenBed#9', 'GardenBed#3'])

    def test_query_offers_and_none(self):
        self.assertEqual(self.ids(Qm.Q(offers='sleep').run(self.g, 'Farm')), ['Bed'])
        self.assertEqual(len(Qm.Q(offers='water').run(self.g, 'Farm')), 12)
        self.assertEqual(Qm.Q(kind='Nope').run(self.g, 'Farm'), [])
        self.assertEqual(Qm.Q(kind='GardenBed').where(crop='x').run(self.g, 'Farm'), [])
        self.assertEqual(Qm.Q(kind='GardenBed').run(self.g, 'Nowhere')[0].id, 'GardenBed#1')

    def test_query_region_distance_first(self):
        self.g.add_edge('Well', 'cook', 'offers')   # a second offerer in another region
        q = Qm.Q(offers='cook')
        self.assertEqual(self.ids(q.run(self.g, 'House')), ['Stove', 'Well'])
        self.assertEqual(self.ids(q.run(self.g, 'Garden')), ['Well', 'Stove'])
        self.assertEqual(self.ids(q.run(self.g, 'House', visible={'Well'})), ['Well', 'Stove'])

    def test_query_pattern_index_tiebreak(self):
        self.g.nodes = dict(reversed(list(self.g.nodes.items())))   # insertion order must not matter
        got = self.ids(Qm.Q(kind='GardenBed').run(self.g, 'House'))   # same distance (> 0) for all
        self.assertEqual(got, ['GardenBed#%d' % i for i in range(1, 13)])

    def test_path_house_to_bed(self):
        steps = Qm.path(self.g, 'House', 'GardenBed#3')
        self.assertEqual([(s.action, s.node.id) for s in steps],
                         [('exit', 'HouseExit'), ('enter', 'Garden'), ('reach', 'GardenBed#3')])

    def test_path_to_region(self):
        f = lambda a, b: [(s.action, s.node.id) for s in Qm.path(self.g, a, b)]  # noqa: E731
        self.assertEqual(f('Farm', 'House'), [('enter', 'House')])
        self.assertEqual(f('House', 'Garden'), [('exit', 'HouseExit'), ('enter', 'Garden')])
        self.assertEqual(f('Garden', 'Garden'), [])
        self.assertEqual(f('House', 'House'), [])
        self.assertEqual(f('Garden', 'Farm'), [('exit', 'Garden')])

    def test_path_inside_garden(self):
        steps = Qm.path(self.g, 'Garden', 'GardenBed#3')
        self.assertEqual([(s.action, s.node.id) for s in steps], [('reach', 'GardenBed#3')])
        self.assertEqual([s.action for s in Qm.path(self.g, 'Farm', 'GardenBed#3')], ['enter', 'reach'])
        self.assertEqual([(s.action, s.node.id) for s in Qm.path(self.g, 'Garden', 'Bed')],
                         [('exit', 'Garden'), ('enter', 'House'), ('reach', 'Bed')])

    def test_scope(self):
        self.assertEqual(sorted(R.scope(self.g, 'Farm')), ['Garden', 'HouseDoor', 'Mailbox'])
        self.assertEqual(sorted(R.scope(self.g, 'Garden')), ['BeeHive', 'GardenBed', 'Well'])
        self.assertEqual(sorted(R.scope(self.g, 'House')), ['Bed', 'HouseExit', 'Stove'])
        self.assertEqual(R.scope(self.g, 'Nope'), [])

    def test_inside_coverage(self):
        hive = [d for d in fake_dets('zoom-1') if d.kind == 'BeeHive'][0]
        bed = Detection('GardenBed', (0, 0, 1, 1), 5.0, None, (0, 0))
        self.assertTrue(R.inside(self.g, 'Garden', [hive] * 8))
        self.assertTrue(R.inside(self.g, 'Garden', [hive] * 7))
        self.assertFalse(R.inside(self.g, 'Garden', [hive] * 6))
        self.assertFalse(R.inside(self.g, 'Garden', [bed] * 12))     # GardenBed is cover:false in the seed (noisy)
        self.g.node('GardenBed').extra.pop('cover')                  # a group that counts: 3 x 4 = 12
        self.assertTrue(R.inside(self.g, 'Garden', [bed] * 12))
        self.assertTrue(R.inside(self.g, 'Garden', [bed] * 11))      # 11/12 = 0.92
        self.assertFalse(R.inside(self.g, 'Garden', [bed] * 10))     # 10/12 = 0.83
        self.assertTrue(R.inside(self.g, 'Garden', [bed] * 30))      # counted up to the group size
        self.assertFalse(R.inside(self.g, 'Garden', []))
        self.assertFalse(R.inside(self.g, 'Garden', [hive] * 3 + [bed] * 5))   # groups are not pooled

    def test_inside_view_is_only_evidence(self):
        hive = [d for d in fake_dets('zoom-1') if d.kind == 'BeeHive'][0]
        self.assertTrue(R.inside(self.g, 'Garden', [hive] * 8, view='Garden'))
        self.assertTrue(R.inside(self.g, 'Garden', [hive] * 8, view='Farm'))   # coverage wins
        self.assertFalse(R.inside(self.g, 'Garden', [hive] * 2, view='Garden'))
        self.assertEqual(R.inside_check(self.g, 'Garden', [hive] * 8, view='Farm'), (True, True))
        self.assertEqual(R.inside_check(self.g, 'Garden', [hive] * 8, view='Garden'), (True, False))
        self.assertEqual(R.inside_check(self.g, 'Garden', [hive] * 8), (True, False))
        self.assertEqual(R.inside_check(self.g, 'Garden', [hive] * 2, view='Garden'), (False, True))

    def test_current_region(self):
        hives = [d for d in fake_dets('zoom-3') if d.kind == 'BeeHive'] * 8
        self.assertEqual(R.current_region(self.g, None, []), ('Farm', True))
        self.assertEqual(R.current_region(self.g, 'House', []), ('House', False))
        self.assertEqual(R.current_region(self.g, 'Farm', hives, view='Garden'), ('Garden', False))
        self.assertEqual(R.current_region(self.g, 'Farm', hives, view='Farm'), ('Garden', True))   # disagreement: coverage wins, uncertain
        self.assertEqual(R.current_region(self.g, 'Farm', hives), ('Garden', False))
        self.assertEqual(R.current_region(self.g, 'Farm', hives[:3], view='Garden'), ('Farm', True))


class ApplyLogTest(unittest.TestCase):
    T = os.path.dirname(os.path.abspath(__file__))

    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)
        self.beds = json.load(open(os.path.join(self.T, 'fixtures', 'beds.json')))['beds']
        self.lines = open(os.path.join(self.T, 'fixtures', 'game_log_actions.txt')).read().splitlines()

    def test_plant_and_water_bed_12(self):
        ch = G.apply_log(self.g, self.lines[:2], self.beds)
        n = self.g.node('GardenBed#12')
        self.assertEqual(n.state['crop'], {'value': 'planted', 'game_time': 'D148 9:36:36 PM', 'source': 'log'})
        self.assertEqual(self.g.state_value('GardenBed#12', 'watered'), 148)
        self.assertEqual(n.state['watered']['game_time'], 'D148 9:40:16 PM')
        self.assertEqual(len(ch), 2)

    def test_well_and_unplant(self):
        ln = ['[D148 7:57:24 PM] > full_watering_can me=Player target=Well',
              '[D148 8:00:00 PM] > plant me=Player target=GardenBed (4) at (5.84, 0.10, -31.59)',
              '[D148 8:10:00 PM] > unplant_impl me=Player target=GardenBed (4) at (5.84, 0.10, -31.59)',
              '[D148 8:11:00 PM] > water me=Player target=GardenBed(Clone) at (50.0, 0.10, 50.0)',
              '[D148 8:12:00 PM] > beehive_progress me=Player target=BeeHive(Clone) at (1.47, 0.10, -23.46)']
        ch = G.apply_log(self.g, ln, self.beds)
        self.assertEqual(self.g.state_value('Well', 'can'), 'full')
        self.assertIsNone(self.g.state_value('GardenBed#12', 'crop'))
        self.assertIn('crop', self.g.node('GardenBed#12').state)       # explicitly None, with a time
        self.assertEqual(len(ch), 3)                                    # unknown bed / beehive lines change nothing

    def test_sync_mark_survives_save(self):
        self.g.extra['_sync'] = 123
        p = os.path.join(tempfile.mkdtemp(), 'g.json')
        self.g.save(p)
        g2 = G.Graph()
        g2.load(p)
        self.assertEqual(g2.extra['_sync'], 123)


class RegionFrames(unittest.TestCase):
    """Real frames, the region's own (calibrated) thresholds: inside = >= 85 % of a group detected."""
    FR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'frames')
    LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'runs', '20261031-1311-graph-garden', 'img')
    DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'objects_db')

    @classmethod
    def setUpClass(cls):
        import shutil
        from PIL import Image
        from objects import calib as C, detect as D, store as S
        cls.D = D
        cls.root = tempfile.mkdtemp()
        shutil.copytree(cls.DB, cls.root, dirs_exist_ok=True)
        cls.st = S.Store(cls.root)
        th, _ = C.calibrate(cls.st)
        C.write_thresholds(cls.st, th)
        cls.g = G.Graph()
        cls.g.load(SEED)
        cls.Image = Image

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.root, ignore_errors=True)

    def check(self, path):
        img = self.Image.open(path).convert('RGB').resize((1920, 1080))
        dets = self.D.detect(img, self.st, kinds=R.scope(self.g, 'Garden'), region='Garden')
        return R.inside(self.g, 'Garden', dets), sum(1 for d in dets if d.kind == 'BeeHive')

    def test_fixture_frames(self):
        for f, want in (('zoom-1', True), ('zoom-2', True), ('zoom-3', True), ('normal-1', False), ('normal-2', False)):
            with self.subTest(frame=f):
                ins, n = self.check(os.path.join(self.FR, f + '.jpg'))
                self.assertEqual(ins, want, f'{f}: hives {n}')

    def test_live_frames(self):
        for f, want in (('s3', True), ('s4b', True), ('s4a', False), ('s1', False)):
            with self.subTest(frame=f):
                ins, n = self.check(os.path.join(self.LIVE, f + '.jpg'))
                self.assertEqual(ins, want, f'{f}: hives {n}')


class GraphCli(unittest.TestCase):
    """`wf graph` as a subprocess on saved frames (no daemon, no game)."""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @classmethod
    def setUpClass(cls):
        import shutil
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, 'db')
        cls.views = os.path.join(cls.tmp, 'views')
        shutil.copytree(os.path.join(cls.ROOT, 'tools', 'objects', 'db'), cls.db)
        shutil.copytree(os.path.join(cls.ROOT, 'tools', 'objects', 'views'), cls.views)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_wf(self, frame, *args, scene='Farm'):
        import subprocess
        env = dict(os.environ, WF_NO_DAEMON='1', WF_SCENE=scene, WF_OBJECTS_DB=self.db, WF_VIEWS=self.views)
        if frame:
            env['WF_FRAME'] = os.path.join(self.ROOT, 'tools', 'fixtures', 'frames', frame + '.jpg')
        r = subprocess.run([os.path.join(self.ROOT, 'wf'), 'graph', *args], env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_where_garden(self):
        self.assertIn('region Garden', self.run_wf('zoom-2', 'where'))

    def test_where_farm(self):
        self.assertIn('region Farm', self.run_wf('normal-1', 'where'))

    def test_path_from_farm(self):
        out = self.run_wf('normal-1', 'path', 'GardenBed')
        self.assertIn('enter Garden', out)
        self.assertIn('reach GardenBed#', out)
        self.assertLess(out.index('enter Garden'), out.index('reach GardenBed#'))
        self.assertRegex(out, r'click \d+,\d+')

    def test_show(self):
        out = self.run_wf('normal-1', 'show')
        self.assertIn('GardenBed#12', out)
        self.assertIn('Garden', out)

    def test_view_add_bad_region(self):
        self.assertIn('region', self.run_wf('normal-1', 'view-add', 'Nope').lower())


if __name__ == '__main__':
    unittest.main()
