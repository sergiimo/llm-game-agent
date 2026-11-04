"""Offline tests for tools/objects (per-kind example store). Run: .venv/bin/python tools/test_objects.py"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects import store as S  # noqa: E402

DIM = 64


def unit(seed):
    v = np.random.RandomState(seed).randn(DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def near(v, eps, seed=99):
    """A unit vector at roughly cosine distance ~eps^2/2 from v."""
    n = np.random.RandomState(seed).randn(DIM).astype(np.float32)
    n -= n.dot(v) * v
    n /= np.linalg.norm(n)
    w = v + eps * n
    return w / np.linalg.norm(w)


def crop():
    return Image.new('RGB', (8, 8), (10, 200, 30))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.s = S.Store(self.root)

    def test_add_match_round_trip(self):
        v = unit(1)
        ex = self.s.add('bush', crop(), v, state='ripe', light='day')
        self.assertEqual((ex.kind, ex.state, ex.light, ex.source), ('bush', 'ripe', 'day', 'model'))
        kind, dist, found = self.s.match(v)
        self.assertEqual(kind, 'bush')
        self.assertLess(dist, 1e-4)
        self.assertEqual(found.id, ex.id)
        self.assertTrue(os.path.exists(os.path.join(self.root, 'bush', ex.id + '.png')))

    def test_duplicate_skipped(self):
        v = unit(1)
        self.assertIsNotNone(self.s.add('bush', crop(), v))
        self.assertIsNone(self.s.add('bush', crop(), near(v, 0.1)))
        self.assertEqual(self.s.count('bush'), 1)
        self.assertIsNotNone(self.s.add('bush', crop(), near(v, 0.8)))
        self.assertEqual(self.s.count('bush'), 2)

    def test_remove(self):
        a = self.s.add('bush', crop(), unit(1))
        b = self.s.add('bush', crop(), unit(2))
        self.assertTrue(self.s.remove('bush', a.id))
        self.assertFalse(os.path.exists(os.path.join(self.root, 'bush', a.id + '.png')))
        self.assertEqual(S.Store(self.root).count('bush'), 1)
        self.assertFalse(self.s.remove('bush', a.id))
        self.assertTrue(self.s.remove('bush', b.id))
        self.assertEqual(self.s.kinds(), [])
        self.assertFalse(os.path.exists(os.path.join(self.root, 'bush')))
        self.assertEqual(S.Store(self.root).kinds(), [])
        self.assertFalse(self.s.remove('nokind', 'x'))

    def test_nearest(self):
        v = unit(1)
        ex = self.s.add('bush', crop(), v)
        d, e = self.s.nearest(v, 'bush')
        self.assertLess(d, 1e-4)
        self.assertEqual(e.id, ex.id)
        self.assertIsNone(self.s.nearest(v, 'none'))

    def test_bad_kind_name(self):
        for k in ('../x', 'a/b', '', 'a b'):
            with self.assertRaises(ValueError):
                self.s.add(k, crop(), unit(1))

    def test_remove_saves_index_before_png(self):
        a = self.s.add('bush', crop(), unit(1))
        self.s.add('bush', crop(), unit(2))
        order = []
        real_save, real_rm = self.s._save, os.remove
        self.s._save = lambda k: (order.append('save'), real_save(k))[1]
        import unittest.mock as mock
        with mock.patch('os.remove', side_effect=lambda p: (order.append('rm'), real_rm(p))[1]):
            self.s.remove('bush', a.id)
        self.assertEqual(order[:2], ['save', 'rm'])

    def test_light_preference(self):
        v = unit(1)
        a = near(v, 0.5, 5)
        b = near(v, 0.5, 6)
        # make equal distances to q = v
        da, db = 1 - float(a @ v), 1 - float(b @ v)
        self.assertAlmostEqual(da, db, places=4)
        self.s.add('rock', crop(), a, light='night')
        self.s.add('tree', crop(), b, light='day')
        self.assertEqual(self.s.match(v, light='day')[0], 'tree')
        self.assertEqual(self.s.match(v, light='night')[0], 'rock')

    def test_kinds_filter(self):
        v = unit(1)
        self.s.add('rock', crop(), v)
        self.assertIsNone(self.s.match(v, kinds=['tree']))
        self.assertEqual(self.s.match(v, kinds=['rock'])[0], 'rock')

    def test_cap_keeps_last_example(self):
        old = S.CAP
        S.CAP = 1
        try:
            a = self.s.add('bush', crop(), unit(1))
            self.assertEqual(self.s.count('bush'), 1)  # a single example is kept
            b = self.s.add('bush', crop(), unit(50))
            self.assertEqual(self.s.count('bush'), 1)  # capped: the older one went
            self.assertEqual(self.s._ex['bush'][0].id, b.id)
            self.assertFalse(os.path.exists(os.path.join(self.root, 'bush', a.id + '.png')))
        finally:
            S.CAP = old

    def test_cap_drops_closest_to_others(self):
        old = S.CAP
        S.CAP = 3
        try:
            base = unit(1)
            a = self.s.add('bush', crop(), base)
            b = self.s.add('bush', crop(), near(base, 0.9, 2))
            c = self.s.add('bush', crop(), unit(50))
            d = self.s.add('bush', crop(), unit(60))
            self.assertIsNotNone(d)
            self.assertEqual(self.s.count('bush'), 3)
            ids = {e.id for e in self.s._ex['bush']}
            self.assertIn(d.id, ids)
            self.assertEqual(len(ids), 3)
            gone = [e for e in (a, b, c) if e.id not in ids]
            self.assertEqual(len(gone), 1)
            self.assertFalse(os.path.exists(os.path.join(self.root, 'bush', gone[0].id + '.png')))
        finally:
            S.CAP = old

    def test_reload_from_disk(self):
        v = unit(3)
        ex = self.s.add('fish', crop(), v, state='x', light='day', weather='rain', source='human')
        s2 = S.Store(self.root)
        self.assertEqual(s2.kinds(), ['fish'])
        self.assertEqual(s2.count('fish'), 1)
        kind, dist, found = s2.match(v)
        self.assertEqual((kind, found.id, found.state, found.light, found.weather, found.source),
                         ('fish', ex.id, 'x', 'day', 'rain', 'human'))
        self.assertLess(dist, 1e-4)

    def test_nothing_close_is_none(self):
        self.s.add('bush', crop(), unit(1))
        self.assertIsNone(self.s.match(unit(2)))
        self.assertIsNone(S.Store(tempfile.mkdtemp()).match(unit(2)))


FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'frames')
REAL_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'objects_db')  # frozen snapshot of tools/objects/db (2026-10-31, after objects-relabel), with its calibrated thresholds
LABELS = json.load(open(os.path.join(FIX, 'labels.json')))
FRAMES = [f for f in LABELS if not f.startswith('_')]


def inside(pt, boxes, pad=0):
    return any(b[0] - pad <= pt[0] <= b[2] + pad and b[1] - pad <= pt[1] <= b[3] + pad for b in boxes)


class DetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from objects import detect as D
        cls.D = D
        cls.root = tempfile.mkdtemp()
        shutil.copytree(REAL_DB, cls.root, dirs_exist_ok=True)   # real db is read-only here
        cls.store = S.Store(cls.root)
        cls.imgs = {f: Image.open(os.path.join(FIX, f + '.jpg')).convert('RGB').resize((1920, 1080)) for f in FRAMES}
        cls.dets = {f: D.detect(cls.imgs[f], cls.store) for f in FRAMES}   # also warms model + kind vectors

    def has(self, frame, kind):
        return LABELS[frame].get(kind) and self.store.count(kind)

    def top(self, frame, kind):
        reg = 'Garden' if frame.startswith('zoom') else None   # zoomed frames are the Garden region's (its calibrated thresholds)
        ds = [d for d in self.D.detect(self.imgs[frame], self.store, kinds=[kind], region=reg) if d.kind == kind]
        return ds[0] if ds else None

    def check_found(self, kind, frames):
        for f in frames:
            if not self.has(f, kind):
                continue
            with self.subTest(frame=f, kind=kind):
                d = self.top(f, kind)
                self.assertIsNotNone(d, 'no detection')
                self.assertTrue(inside(d.point, LABELS[f][kind]), f'{d.point} not in {LABELS[f][kind]} z={d.dist:.1f}')

    def test_tara_found(self):
        self.check_found('Tara', ['normal-1', 'normal-2', 'zoom-1', 'zoom-2'])

    def test_beehive_found(self):
        self.check_found('BeeHive', FRAMES)

    def test_gardenbed_found(self):
        self.check_found('GardenBed', ['normal-2', 'zoom-1', 'zoom-2', 'zoom-3'])

    @unittest.expectedFailure   # relabel, plan Task 3 (normal-1 GardenBed)
    def test_gardenbed_normal_1(self):
        self.check_found('GardenBed', ['normal-1'])

    def test_mailbox_found(self):
        self.check_found('Mailbox', FRAMES)

    @unittest.expectedFailure   # relabel, plan Task 3 (Well examples are zoomed only)
    def test_well_found(self):
        self.check_found('Well', ['normal-1', 'normal-2', 'zoom-2', 'zoom-3'])

    @unittest.expectedFailure   # relabel, plan Task 3 (bad Gate example)
    def test_gate_found(self):
        self.check_found('Gate', FRAMES)

    @unittest.expectedFailure   # relabel, plan Task 3 (windows win over the door)
    def test_housedoor_found(self):
        self.check_found('HouseDoor', FRAMES)

    def test_gate_absent_zoom(self):
        for f in ('zoom-2', 'zoom-3'):
            with self.subTest(frame=f):
                self.assertIsNone(self.top(f, 'Gate'), 'Gate detected in a frame without it')

    def test_absent_not_detected(self):
        for f, kind in (('zoom-3', 'Tara'), ('zoom-1', 'Well'), ('zoom-1', 'Gate'), ('zoom-1', 'Mailbox')):
            with self.subTest(frame=f, kind=kind):
                self.assertIn(kind, LABELS[f]['absent'])
                ds = [d for d in self.dets[f] if d.kind == kind]
                self.assertEqual(ds, [], ds)

    @unittest.expectedFailure   # zoomed hives fill the frame → their z drops below the Farm-calibrated 4.05 (only 2 of 8);
    # fix: thresholds per region scope (Garden calibrated on zoomed frames) — plan step 2 Task 2
    def test_several_hives(self):
        hives = [d for d in self.dets['zoom-3'] if d.kind == 'BeeHive']
        self.assertGreaterEqual(len(hives), 3, hives)

    def test_several_hives_garden_thresholds(self):
        from objects import calib as C
        root = tempfile.mkdtemp()
        shutil.copytree(REAL_DB, root, dirs_exist_ok=True)
        st = S.Store(root)
        th, _ = C.calibrate(st)
        C.write_thresholds(st, th)
        self.assertEqual(set(th), {'Farm', 'Garden'})
        hives = [d for d in self.D.detect(self.imgs['zoom-3'], st, region='Garden') if d.kind == 'BeeHive']
        self.assertGreaterEqual(len(hives), 3, hives)

    def test_exclude_container_kind_from_the_competition(self):
        root = tempfile.mkdtemp()
        shutil.copytree(REAL_DB, root, dirs_exist_ok=True)
        with open(os.path.join(root, 'thresholds.json'), 'w') as f:
            json.dump({'Window': 2.5}, f)
        st = S.Store(root)
        img = self.imgs['normal-1']
        self.assertEqual([d for d in self.D.detect(img, st, kinds=['Window']) if d.kind == 'Window' and abs(d.point[0] - 1030) < 60 and abs(d.point[1] - 170) < 60], [])
        got = self.D.detect(img, st, kinds=['Window'], exclude=['Garden'])   # Garden's crops contain it and used to win the patch
        self.assertTrue([d for d in got if abs(d.point[0] - 1030) < 60 and abs(d.point[1] - 170) < 60], got)
        self.assertEqual(self.D.detect(img, st, kinds=['Garden'], exclude=['Garden']), [])

    def test_raw_path_rescues_beds_when_the_frame_median_is_high(self):
        """live3-garden: beds fill the frame, the frame median is high, z collapses (max 2.65 < 2.88); the raw cosine path
        (z OR raw >= the region's `_raw` threshold) finds them."""
        root = tempfile.mkdtemp()
        shutil.copytree(REAL_DB, root, dirs_exist_ok=True)
        st = S.Store(root)
        from objects import calib as C
        th, _ = C.calibrate(st)
        self.assertTrue(0.7 <= th['Garden']['_raw']['GardenBed'] <= 0.8, th['Garden'])
        C.write_thresholds(st, th)
        img = Image.open(os.path.join(FIX, 'live3-garden.jpg')).convert('RGB').resize((1920, 1080))
        beds = [d for d in self.D.detect(img, st, kinds=['GardenBed'], region='Garden', exclude=['Garden']) if d.kind == 'GardenBed']
        self.assertGreaterEqual(len(beds), 3, beds)
        self.assertTrue(any(1385 <= d.point[0] <= 1672 and 600 <= d.point[1] <= 740 for d in beds), beds)
        self.assertTrue(all(d.raw is not None for d in beds))
        th['Garden'].pop('_raw'); th['Farm'].pop('_raw', None)
        C.write_thresholds(st, th)
        off = [d for d in self.D.detect(img, st, kinds=['GardenBed'], region='Garden', exclude=['Garden']) if d.kind == 'GardenBed']
        self.assertLess(len(off), len(beds))
        # normal view (beds small): the raw path adds nothing beyond the z detections
        C.write_thresholds(st, C.calibrate(st)[0])
        n1 = self.imgs['normal-1']
        on = self.D.detect(n1, st, kinds=['GardenBed'], region='Farm')
        th['Farm'].pop('_raw', None); th['Garden'].pop('_raw', None)
        C.write_thresholds(st, th)
        z_only = self.D.detect(n1, st, kinds=['GardenBed'], region='Farm')
        self.assertEqual([d.point for d in on], [d.point for d in z_only])

    def test_raw_threshold_rule(self):
        from objects import calib as C
        self.assertEqual(C.raw_threshold([0.8, 0.82], [0.6]), 0.7)          # separable: midpoint
        self.assertEqual(C.raw_threshold([0.76, 0.8], [0.78]), 0.75)        # overlap, few false above: lowest true - 0.01
        self.assertIsNone(C.raw_threshold([0.6], [0.65, 0.66, 0.62]))       # overlap with many false peaks: raw off
        self.assertIsNone(C.raw_threshold([], [0.6]))

    def test_detection_fields(self):
        d = self.dets['normal-1'][0]
        self.assertEqual(len(d.box), 4)
        self.assertTrue(d.box[0] <= d.point[0] <= d.box[2] and d.box[1] <= d.point[1] <= d.box[3])
        zs = [x.dist for x in self.dets['normal-1']]
        self.assertEqual(zs, sorted(zs, reverse=True))
        self.assertGreaterEqual(zs[-1], 2.78)   # lowest Farm threshold in the 2026-10-31 snapshot (Garden kind)

    def test_unknown_kind(self):
        self.assertEqual(self.D.detect(self.imgs['normal-1'], self.store, kinds=['Nope']), [])

    def test_empty_store(self):
        self.assertEqual(self.D.detect(self.imgs['normal-1'], S.Store(tempfile.mkdtemp())), [])

    def test_vectors_refresh_after_add(self):
        root = tempfile.mkdtemp()
        st = S.Store(root)
        img = self.imgs['normal-1']
        self.assertEqual(self.D.detect(img, st), [])
        tara = Image.open(os.path.join(REAL_DB, 'Tara', self.store.examples('Tara')[0].id + '.png')).convert('RGB')
        from objects import dino
        st.add('Tara', tara, dino.mean_vector(tara))
        self.assertIn('Tara', [d.kind for d in self.D.detect(img, st)])
        st.remove('Tara', st.examples('Tara')[0].id)
        self.assertEqual(self.D.detect(img, st), [])

    def test_mixed_dim_vectors_do_not_crash_add(self):
        st = S.Store(tempfile.mkdtemp())
        st.add('K', crop(), unit(1))                       # 64-d
        self.assertIsNotNone(st.add('K', crop(), np.ones(384, np.float32)))   # different dim: not a duplicate
        s2 = S.Store(st.root)                                                  # mixed dims survive a reload
        self.assertEqual(sorted(len(e.vec) for e in s2.examples('K')), [64, 384])

    def test_thresholds(self):
        th = self.D.thresholds(self.store)
        self.assertEqual(set(th), set(self.store.kinds()))
        self.assertEqual(th['Mailbox'], 3.32)           # snapshot's calibrated values
        self.assertEqual(th['Tara'], 5.34)
        root = tempfile.mkdtemp()
        st = S.Store(root)
        st.add('K', crop(), unit(1))
        self.assertEqual(self.D.thresholds(st), {'K': self.D.Z_MIN})            # file missing
        open(os.path.join(root, 'thresholds.json'), 'w').write('{nope')
        self.assertEqual(self.D.thresholds(st), {'K': self.D.Z_MIN})            # malformed: defaults + warning

    def test_thresholds_nested(self):
        root = tempfile.mkdtemp()
        st = S.Store(root)
        st.add('K', crop(), unit(1))
        st.add('L', crop(), unit(2))
        open(os.path.join(root, 'thresholds.json'), 'w').write('{"Farm": {"K": 4.0, "L": 5.0}, "Garden": {"K": 2.5}}')
        self.assertEqual(self.D.thresholds(st), {'K': 4.0, 'L': 5.0})
        self.assertEqual(self.D.thresholds(st, 'Garden'), {'K': 2.5, 'L': 5.0})   # region overrides, rest = default
        self.assertEqual(self.D.thresholds(st, 'House'), {'K': 4.0, 'L': 5.0})    # unknown region: default
        open(os.path.join(root, 'thresholds.json'), 'w').write('{"K": 3.5}')
        self.assertEqual(self.D.thresholds(st, 'Garden'), {'K': 3.5, 'L': self.D.Z_MIN})   # old flat form: every region

    def test_dino_shapes(self):
        from objects import dino
        f = dino.frame_features(self.imgs['normal-1'])
        self.assertEqual(f.shape, (54, 96, 384))
        self.assertAlmostEqual(float(np.linalg.norm(f[3, 4])), 1.0, places=4)
        tara = Image.open(self.store.example_path('Tara', self.store.examples('Tara')[0].id))
        self.assertEqual(dino.crop_vectors(tara).shape[1], 384)
        m = dino.mean_vector(tara)
        self.assertEqual(m.shape, (384,))
        self.assertAlmostEqual(float(np.linalg.norm(m)), 1.0, places=4)

    def test_speed(self):
        t0 = time.time()
        self.D.detect(self.imgs['zoom-1'], self.store, kinds=['Tara', 'BeeHive', 'GardenBed'])
        self.assertLess(time.time() - t0, 1.5)


class ObjectsCli(unittest.TestCase):
    """`wf objects` on a saved frame (WF_FRAME), with a throwaway db (WF_OBJECTS_DB)."""

    def run_cli(self, env, *args):
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        e = dict(os.environ, WF_NO_DAEMON='1', **env)
        r = subprocess.run([os.path.join(root, '.venv', 'bin', 'python'), os.path.join(root, 'tools', 'wfc.py'),
                            'objects'] + list(args), capture_output=True, text=True, env=e, timeout=300)
        return r.stdout + r.stderr

    def test_add_then_detect(self):
        tmp = tempfile.mkdtemp()
        fix = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'tara_open_crop.png')).convert('RGB')
        canvas = Image.new('RGB', (1920, 1080), fix.getpixel((5, 5)))
        canvas.paste(fix, (400, 400))
        frame = os.path.join(tmp, 'frame.png')
        canvas.save(frame)
        env = {'WF_FRAME': frame, 'WF_OBJECTS_DB': os.path.join(tmp, 'db')}
        out = self.run_cli(env, 'add', 'Tara', '569', '561', '635', '739')
        self.assertIn('added Tara', out)
        self.assertIn('Tara  1', self.run_cli(env, 'list'))
        out = self.run_cli(env, 'detect', 'Tara')
        self.assertIn('Tara box', out)
        self.assertIn('Tara box', self.run_cli(env, 'find', 'Tara'))

    def test_validation(self):
        tmp = tempfile.mkdtemp()
        canvas = Image.new('RGB', (1920, 1080), (10, 200, 30))
        frame = os.path.join(tmp, 'frame.png')
        canvas.save(frame)
        env = {'WF_FRAME': frame, 'WF_OBJECTS_DB': os.path.join(tmp, 'db')}
        for a in (['add', 'T', 'a', '1', '2', '3'], ['add', 'T', '1', '2', '3'], ['add', 'T', '1', '2', '3', '4', 's', 'x']):
            out = self.run_cli(env, *a)
            self.assertIn('usage', out.lower(), out)
            self.assertNotIn('Traceback', out)
        self.assertIn('box outside the frame (1920x1080)', self.run_cli(env, 'add', 'T', '0', '0', '2000', '50'))
        self.assertIn('box outside the frame', self.run_cli(env, 'add', 'T', '50', '0', '50', '50'))
        out = self.run_cli(env, 'add', '../x', '0', '0', '50', '50')
        self.assertIn('bad kind name', out)
        self.assertNotIn('Traceback', out)
        self.assertFalse(os.path.exists(os.path.join(tmp, 'x')))
        self.assertIn('no such kind', self.run_cli(env, 'list', 'Zed'))
        self.assertIn('unknown kind: Zed (known: ', self.run_cli(env, 'find', 'Zed'))
        self.assertIn('unknown kind: Zed (known: ', self.run_cli(env, 'detect', 'Zed'))

    def test_list_remove_duplicate(self):
        tmp = tempfile.mkdtemp()
        fix = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'tara_open_crop.png')).convert('RGB')
        canvas = Image.new('RGB', (1920, 1080), fix.getpixel((5, 5)))
        canvas.paste(fix, (400, 400))
        frame = os.path.join(tmp, 'frame.png')
        canvas.save(frame)
        env = {'WF_FRAME': frame, 'WF_OBJECTS_DB': os.path.join(tmp, 'db')}
        out = self.run_cli(env, 'add', 'Tara', '569', '561', '635', '739', 'open')
        ex_id = out.split('added Tara ')[1].split()[0]
        out = self.run_cli(env, 'add', 'Tara', '569', '561', '635', '739')
        self.assertIn(f'duplicate of {ex_id} (dist 0.', out)
        self.assertIn('skipped', out)
        out = self.run_cli(env, 'list', 'Tara')
        self.assertIn(f'{ex_id}  state=open light=', out)
        self.assertIn('source=model', out)
        self.assertIn(ex_id + '.png', out)
        self.assertIn(f'removed Tara {ex_id}', self.run_cli(env, 'remove', 'Tara', ex_id))
        self.assertIn('no such example', self.run_cli(env, 'remove', 'Tara', ex_id))
        self.assertNotIn('Tara', self.run_cli(env, 'list'))


class ThresholdTests(unittest.TestCase):
    def test_non_finite_ignored(self):
        import contextlib
        import io
        from objects import detect as D
        root = tempfile.mkdtemp()
        shutil.copytree(REAL_DB, root, dirs_exist_ok=True)
        with open(os.path.join(root, 'thresholds.json'), 'w') as fh:
            fh.write('{"Tara": NaN, "BeeHive": Infinity, "Mailbox": 3.3}')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            th = D.thresholds(S.Store(root))
        self.assertEqual(th['Tara'], D.Z_MIN)
        self.assertEqual(th['BeeHive'], D.Z_MIN)
        self.assertEqual(th['Mailbox'], 3.3)
        self.assertIn('warning', err.getvalue())


class CalibRules(unittest.TestCase):
    def test_rules(self):
        from objects import calib as C
        self.assertEqual(C.threshold([5.0, 6.0], [3.0, 2.5]), (4.0, False))
        t, ov = C.threshold([4.0], [4.5])
        self.assertTrue(ov)
        self.assertAlmostEqual(t, 3.9)
        self.assertEqual(C.threshold([], []), (4.5, False))
        self.assertEqual(C.threshold([4.0], []), (3.0, False))   # midpoint to the 2.0 floor


class CalibCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        shutil.copytree(REAL_DB, cls.root, dirs_exist_ok=True)
        cls.counts = {k: S.Store(cls.root).count(k) for k in S.Store(cls.root).kinds()}

    def run_cli(self, *args):
        return ObjectsCli.run_cli(self, {'WF_OBJECTS_DB': self.root}, *args)

    def test_a_eval_rows(self):
        out = self.run_cli('eval')
        for k in self.counts:
            self.assertTrue(any(l.startswith(k) for l in out.splitlines()), f'{k} row missing:\n{out}')
        self.assertIn('hits', out)
        self.assertNotIn('Traceback', out)

    def test_b_calibrate_writes(self):
        out = self.run_cli('calibrate')
        self.assertNotIn('Traceback', out)
        with open(os.path.join(self.root, 'thresholds.json')) as fh:
            th = json.load(fh)
        self.assertEqual(sorted(th), ['Farm', 'Garden'])
        for reg, d in th.items():
            self.assertTrue(set(d) - {'_raw'} <= set(self.counts) and d, reg)   # `_raw`: the raw-cosine section
            self.assertTrue(all(isinstance(v, float) and v > 0 for k, v in d.items() if k != '_raw'))
        self.assertIn('stolen', out)

    def test_c_reembed_keeps_counts(self):
        out = self.run_cli('reembed')
        self.assertNotIn('Traceback', out)
        st = S.Store(self.root)
        for k, n in self.counts.items():
            self.assertEqual(st.count(k), n)
            self.assertTrue(all(len(e.vec) == 384 for e in st.examples(k)))


if __name__ == '__main__':
    unittest.main()
