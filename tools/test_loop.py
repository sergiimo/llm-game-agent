"""Offline tests for objects identity + bubbles. Run: .venv/bin/python tools/test_loop.py"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects import bubbles as B, graph as G, identity as I, loop as L  # noqa: E402
from objects.detect import Detection  # noqa: E402

T = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(T, 'fixtures', 'graph_seed.json')   # the seed without live states (objects/graph/Farm.json is the live graph)
BEDS = json.load(open(os.path.join(T, 'fixtures', 'beds.json')))['beds']


def det(x, y, z=5.0, kind='GardenBed'):
    return Detection(kind, (x - 5, y - 5, x + 5, y + 5), z, None, (x, y))


def grid(skip_col=None):
    return [det(100 + 150 * c + 10 * r, 300 + 120 * r) for r in range(3) for c in range(4) if c != skip_col]


class IdentityTest(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)
        self.grp = self.g.node('GardenBed')
        self.mem = self.g.members('GardenBed')

    def test_assign_full(self):
        dets = grid()
        out, unc = I.assign(self.grp, self.mem, dets)
        self.assertFalse(unc)
        self.assertEqual(len(out), 12)
        for i in range(12):
            self.assertIs(out['GardenBed#%d' % (i + 1)], dets[i])

    def test_assign_shuffled(self):
        dets = grid()[::-1]
        out, unc = I.assign(self.grp, self.mem, dets)
        self.assertEqual(out['GardenBed#1'].point, (100, 300))
        self.assertEqual(out['GardenBed#12'].point, (100 + 450 + 20, 540))

    def test_missing_column_always_uncertain(self):
        dets = grid(skip_col=3)
        out, unc = I.assign(self.grp, self.mem, dets)
        self.assertTrue(unc)
        out, unc = I.assign(self.grp, self.mem, dets, anchor_y=190)
        self.assertTrue(unc)                                    # partial columns stay uncertain even anchored
        self.assertEqual(out['GardenBed#1'].point, (100, 300))

    def test_missing_row_anchored_by_hive_row(self):
        dets = grid()[:8]   # north two rows only
        out, unc = I.assign(self.grp, self.mem, dets, anchor_y=190)
        self.assertFalse(unc)
        self.assertEqual(out['GardenBed#5'].point, (110, 420))
        out, unc = I.assign(self.grp, self.mem, grid()[4:], anchor_y=190)   # south rows only: anchor is too far
        self.assertTrue(unc)

    def test_dedupe_for(self):
        pairs = [det(100 + 160 * i + 15 * j, 700 - 100 * j, 4 - j / 10, 'BeeHive') for i in range(4) for j in (0, 1)]
        self.assertEqual(len(I.dedupe_for(self.g.node('BeeHive'), pairs)), 4)
        self.assertEqual(len(I.dedupe_for(self.grp, pairs)), 8)

    def test_member_from_log(self):
        lines = open(os.path.join(T, 'fixtures', 'game_log_actions.txt')).read().splitlines()
        self.assertEqual(I.member_from_log(lines[0], BEDS), 'GardenBed#12')
        self.assertEqual(I.member_from_log(lines[2], BEDS), 'GardenBed#11')
        self.assertIsNone(I.member_from_log('[D1 1:00:00 AM] > plant me=Player target=GardenBed(Clone) at (50.0, 0.10, 50.0)', BEDS))
        self.assertEqual(I.member_from_log('[D1 1:00:00 AM] > water me=Player target=GardenBed(Clone) at (-1.60, 0.10, -25.30)', BEDS), 'GardenBed#1')
        self.assertIsNone(I.member_from_log(lines[-1] if 'BeeHive' in lines[-1] else
                                            '[D1 1:00:00 AM] > beehive_progress me=Player target=BeeHive(Clone) at (1.47, 0.10, -23.46)', BEDS))
        self.assertIsNone(I.member_from_log('nothing', BEDS))

    def test_dedupe_synthetic(self):
        dets = [det(100, 100, 6), det(105, 102, 5), det(300, 100, 5), det(500, 100, 5)]
        out = I.dedupe(dets)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0].dist, 6)
        pairs = [det(100 + 160 * i + 15 * j, 700 - 100 * j, 4 - j / 10, 'BeeHive') for i in range(4) for j in (0, 1)]
        self.assertEqual(len(I.dedupe(pairs)), 8)                  # vertical pairs 100 apart, euclid can't merge
        self.assertEqual(len(I.dedupe(pairs, axis='x')), 4)


class RealFrameTest(unittest.TestCase):
    def test_zoom3_hives(self):
        from PIL import Image
        from objects import detect as D, store as S
        root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(T, 'fixtures', 'objects_db'), root, dirs_exist_ok=True)
        st = S.Store(root)
        from objects import calib as C
        th, _ = C.calibrate(st)
        C.write_thresholds(st, th)
        hives = [d for d in D.detect(Image.open(os.path.join(T, 'fixtures', 'frames', 'zoom-3.jpg')).convert('RGB'),
                                     st, kinds=['BeeHive'], region='Garden')]
        out = I.dedupe(hives, axis='x')   # BeeHive is a one-row group
        print(f'zoom-3 hives: {len(hives)} -> {len(out)}')
        self.assertGreaterEqual(len(out), 6)
        self.assertLessEqual(len(out), 8)


class BubbleTest(unittest.TestCase):
    def test_owner(self):
        a, b = det(200, 400), det(400, 400)
        self.assertIs(B.owner((205, 250), [a, b]), a)
        self.assertIs(B.owner((395, 260), [a, b]), b)
        self.assertIsNone(B.owner((300, 250), [a, b]))          # between: dx > 90
        self.assertIsNone(B.owner((200, 390), [a, b]))          # det not below enough
        self.assertIsNone(B.owner((200, 100), [a, b]))          # too far up
        c = det(210, 330)
        self.assertIs(B.owner((205, 250), [a, c]), c)           # nearest




WELL = Detection('Well', (790, 110, 900, 210), 6.0, None, (845, 160))


class FakeWf:
    """A scripted game: frames advance on each click (the last one stays); bubbles/scene scripted per frame."""

    def __init__(self, frames, bubbles=None, scenes=None, run_dir=None):
        self.frames, self.bub, self.scenes = frames, bubbles or {}, scenes or {}
        self.i, self.clicks, self.run_dir = 0, [], run_dir

    def grab(self):
        return self.frames[min(self.i, len(self.frames) - 1)]

    def _k(self):
        return min(self.i, len(self.frames) - 1)

    def find_bubbles(self, img):
        return [p for p, _ in self.bub.get(self._k(), [])]

    def bubble_kind(self, img, b):
        return next((k, 0.0) for p, k in self.bub.get(self._k(), []) if p == tuple(b))

    def run_action(self, a):
        _, x, y = a.split(':')
        self.clicks.append((int(x), int(y)))
        self.i += 1

    def wait_settle(self):
        pass

    def current_scene(self):
        return self.scenes.get(self._k(), 'Farm')

    def run_path(self):
        return self.run_dir


class LoopTest(unittest.TestCase):
    FR = os.path.join(T, 'fixtures', 'frames')

    @classmethod
    def setUpClass(cls):
        from PIL import Image
        from objects import calib as C, detect as D, store as S
        cls.D = D
        cls.root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(T, 'fixtures', 'objects_db'), cls.root, dirs_exist_ok=True)
        cls.st = S.Store(cls.root)
        th, _ = C.calibrate(cls.st)
        C.write_thresholds(cls.st, th)
        cls.img = {f: Image.open(os.path.join(cls.FR, f + '.jpg')).convert('RGB').resize((1920, 1080))
                   for f in ('normal-1', 'zoom-2')}
        cls.cache = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)
        self.tmp = tempfile.mkdtemp()
        L.STATE.update(goal=None, asks=0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fn(self, hide=None):
        """Real detection cached per (frame, region, kinds); `hide` = {id(img): kinds not detected}."""
        hide = hide or {}
        def detect(img, store, kinds=None, region=None, exclude=()):
            key = (id(img), region, tuple(kinds or ()), tuple(exclude))
            if key not in self.cache:
                self.cache[key] = self.D.detect(img, store, kinds=kinds, region=region, exclude=exclude)
            out = [d for d in self.cache[key] if d.kind not in hide.get(id(img), ())]
            if 'Well' in (kinds or ()) and id(img) == id(self.img['normal-1']):   # the fixtures lack a detectable well
                out = out + [WELL]
            return out
        return detect

    def dets(self, frame, kind, region='Farm'):
        return [d for d in self.D.detect(self.img[frame], self.st, kinds=[kind], region=region)]

    def run_goto(self, q, wf, **kw):
        return L.goto(q, wf, graph=self.g, store=self.st, detect_fn=kw.pop('detect_fn', self.fn()), **kw)

    def test_visible_from_outside_one_click(self):
        well = WELL
        wf = FakeWf([self.img['normal-1']] * 2, {1: [((well.point[0], well.point[1] - 100), 'fill_can')]},
                    run_dir=self.tmp)
        arr = self.run_goto(L.Q(kind='Well'), wf)
        self.assertEqual(len(wf.clicks), 1)
        x, y = wf.clicks[0]
        b = well.box
        self.assertTrue(b[0] <= x <= b[2] and b[1] <= y <= b[3])
        self.assertEqual((arr.node.id, arr.region), ('Well', 'Farm'))
        self.assertEqual(L.ACTIVE, ('Well', 'Farm'))

    def test_enter_garden_then_bed(self):
        n1, z2 = self.img['normal-1'], self.img['zoom-2']
        beds = self.dets('zoom-2', 'GardenBed', 'Garden')
        self.assertTrue(beds)
        tb = min(beds, key=lambda d: (d.point[1], d.point[0]))   # the loop's pick: the first-indexed visible bed
        bub = {2: [((tb.point[0], tb.point[1] - 120), 'plant')]}
        wf = FakeWf([n1, z2, z2], bub, run_dir=self.tmp)
        arr = self.run_goto(L.Q(kind='GardenBed', offers='plant'), wf, detect_fn=self.fn({id(n1): ('GardenBed',)}))
        self.assertEqual(len(wf.clicks), 2)
        hives = self.dets('normal-1', 'BeeHive', 'Garden')
        gard = self.dets('normal-1', 'Garden', 'Farm')   # snapshot 2026-10-31: Farm's Garden threshold dropped to 2.78, the
        # 'Garden' kind itself is detected from outside and clicked (the enter step) as well as the hives
        self.assertTrue(any(h.box[0] <= wf.clicks[0][0] <= h.box[2] and h.box[1] <= wf.clicks[0][1] <= h.box[3]
                            for h in hives + gard), wf.clicks)
        x, y = wf.clicks[1]
        self.assertTrue(any(b.box[0] <= x <= b.box[2] and b.box[1] <= y <= b.box[3] for b in beds), wf.clicks)
        self.assertEqual((arr.node.kind, arr.region), ('GardenBed', 'Garden'))

    def first_click(self, frame, q):
        wf = FakeWf([self.img[frame]] * 3, run_dir=tempfile.mkdtemp())
        with self.assertRaises(L.Failed):
            self.run_goto(q, wf, max_clicks=1)
        return wf.clicks[0]

    def test_still_frames_ask_then_fail(self):
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision) as cm:
            self.run_goto(L.Q(kind='Well'), wf, max_clicks=12)
        png = cm.exception.path
        self.assertTrue(os.path.exists(png) and os.path.exists(png[:-4] + '.json'))
        self.assertEqual(len(wf.clicks), 4)
        # a second call after an answer: the answer is clicked first, still no progress -> a second ask
        L.answer(1, 960, 540, directory=self.tmp)
        wf2 = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Well'), wf2, max_clicks=12)
        self.assertEqual(wf2.clicks[0], (960, 540))
        # the third: two asks for this goal did not help -> Failed (escalate)
        wf3 = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.Failed) as cm:
            self.run_goto(L.Q(kind='Well'), wf3, max_clicks=12)
        self.assertIn('escalate', str(cm.exception))

    def test_not_detected_three_calls_ask_ask_fail(self):
        hide = {id(self.img['normal-1']): ('HouseDoor',)}
        for want in (L.NeedVision, L.NeedVision, L.Failed):
            wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
            L.STATE.update(goal='other')      # a goal change in between must not reset the counter
            with self.assertRaises(want) as cm:
                self.run_goto(L.Q(kind='Stove'), wf, detect_fn=self.fn(hide))
        self.assertIn('escalate', str(cm.exception))
        L.STATE.update(goal=None)

    def test_arrival_clears_the_ask_count(self):
        hide = {id(self.img['normal-1']): ('Well',)}
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Well'), wf, max_clicks=12)
        self.assertEqual(json.load(open(os.path.join(self.tmp, 'asks.json'))), {L.goal_key(L.Q(kind='Well')): 1})
        wf = FakeWf([self.img['normal-1']] * 2, {1: [((WELL.point[0], WELL.point[1] - 100), 'fill_can')]}, run_dir=self.tmp)
        self.run_goto(L.Q(kind='Well'), wf)
        self.assertEqual(json.load(open(os.path.join(self.tmp, 'asks.json'))), {})

    def test_answer_only_for_its_goal(self):
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Stove'), wf, detect_fn=self.fn({id(self.img['normal-1']): ('HouseDoor',)}))
        L.answer(1, 960, 540, directory=self.tmp)
        wf2 = FakeWf([self.img['normal-1']] * 2, {1: [((WELL.point[0], WELL.point[1] - 100), 'fill_can')]}, run_dir=self.tmp)
        self.run_goto(L.Q(kind='Well'), wf2)                      # another goal: the Stove answer is not clicked
        self.assertNotIn((960, 540), wf2.clicks)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, 'ask-1.answer.json')))

    def test_neighbours_bubble_is_not_arrival_and_is_avoided(self):
        q = L.Q(kind='GardenBed', offers='plant')
        cp = self.first_click('zoom-2', q)
        nb = [d for d in self.dets('zoom-2', 'GardenBed', 'Garden') if 100 < d.point[1] - cp[1] <= 260 and abs(d.point[0] - cp[0]) <= 80]
        self.assertTrue(nb)
        bub = (cp[0], cp[1] + 50)          # 50 px below the target's point, above its southern neighbour: owned by the neighbour
        wf = FakeWf([self.img['zoom-2']] * 3, {i: [(bub, 'plant')] for i in range(3)}, run_dir=self.tmp)
        with self.assertRaises(L.Failed):                          # never "arrived" at the target
            self.run_goto(q, wf, max_clicks=2)
        self.assertEqual(len(wf.clicks), 2)
        self.assertLess(L._dist(wf.clicks[0], cp), 25)             # still the target bed
        self.assertGreaterEqual(L._dist(wf.clicks[0], bub), 60)

    def test_bubble_kind_names_map_to_offers(self):
        well = WELL
        wf = FakeWf([self.img['normal-1']] * 2, {1: [((well.point[0], well.point[1] - 100), 'full_watering_can')]},
                    run_dir=self.tmp)
        arr = self.run_goto(L.Q(kind='Well'), wf)
        self.assertEqual(arr.node.id, 'Well')

    def test_click_avoids_other_bubble(self):
        well = WELL
        bub = (well.point[0], well.point[1] - 30)
        wf = FakeWf([self.img['normal-1']] * 2, {0: [(bub, 'water')]}, run_dir=self.tmp)
        with self.assertRaises(L.Failed):   # no bubble ever shows; we only look at the first click
            self.run_goto(L.Q(kind='Well'), wf, max_clicks=2)
        self.assertGreaterEqual(L._dist(wf.clicks[0], bub), 60)
        b = well.box
        self.assertTrue(b[0] <= wf.clicks[0][0] <= b[2] and b[1] <= wf.clicks[0][1] <= b[3])

    def test_door_click_arrives_on_scene_change(self):
        door = Detection('HouseDoor', (400, 300, 440, 360), 6.0, None, (420, 330))
        fn = lambda img, store, kinds=None, region=None, exclude=(): [door] if 'HouseDoor' in (kinds or ()) else []  # noqa: E731
        wf = FakeWf([self.img['normal-1']] * 3, run_dir=self.tmp)
        polls = []
        def scene():
            polls.append(1)
            return 'House' if len(polls) > 4 else 'Farm'       # the scene changes a moment after the click
        wf.current_scene = scene
        old = (L.SCENE_POLL, L.SCENE_WAIT)
        L.SCENE_POLL, L.SCENE_WAIT = 0.01, 3
        try:
            arr = self.run_goto(L.Q(kind='HouseDoor'), wf, detect_fn=fn)
        finally:
            L.SCENE_POLL, L.SCENE_WAIT = old
        self.assertEqual(wf.clicks, [(420, 330)])
        self.assertEqual((arr.node.id, arr.region), ('HouseDoor', 'House'))

    def test_door_without_scene_change_keeps_going(self):
        door = Detection('HouseDoor', (400, 300, 440, 360), 6.0, None, (420, 330))
        fn = lambda img, store, kinds=None, region=None, exclude=(): [door] if 'HouseDoor' in (kinds or ()) else []  # noqa: E731
        wf = FakeWf([self.img['normal-1']] * 3, run_dir=self.tmp)
        old = (L.SCENE_POLL, L.SCENE_WAIT)
        L.SCENE_POLL, L.SCENE_WAIT = 0.01, 0.05
        try:
            with self.assertRaises(L.Failed):
                self.run_goto(L.Q(kind='HouseDoor'), wf, detect_fn=fn, max_clicks=2)
        finally:
            L.SCENE_POLL, L.SCENE_WAIT = old
        self.assertEqual(len(wf.clicks), 2)

    def test_enter_garden_clicks_a_member_not_the_garden_peak(self):
        peak = Detection('Garden', (540, 170, 580, 210), 5.0, None, (560, 190))
        hive = Detection('BeeHive', (680, 280, 720, 320), 4.0, None, (700, 300))
        def fn(img, store, kinds=None, region=None, exclude=()):
            return [d for d in (peak, hive) if d.kind in (kinds or ())]
        wf = FakeWf([self.img['normal-1']] * 3, run_dir=self.tmp)
        with self.assertRaises(L.Failed):
            self.run_goto(L.Q(kind='GardenBed', offers='plant'), wf, detect_fn=fn, max_clicks=1)
        self.assertEqual(wf.clicks[0], (700, 300))
        fn2 = lambda img, store, kinds=None, region=None, exclude=(): [peak] if 'Garden' in (kinds or ()) else []  # noqa: E731
        wf = FakeWf([self.img['normal-1']] * 3, run_dir=self.tmp)
        with self.assertRaises(L.Failed):
            self.run_goto(L.Q(kind='GardenBed', offers='plant'), wf, detect_fn=fn2, max_clicks=1)
        self.assertEqual(wf.clicks[0], (560, 190))                  # no member detected: the region's own peak

    def test_detect_excludes_container_kinds(self):
        seen = []
        def fn(img, store, kinds=None, region=None, exclude=()):
            seen.append((region, tuple(exclude)))
            return []
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Well'), wf, detect_fn=fn)
        self.assertIn(('Garden', ('Farm', 'Garden')), seen)                # a region's own kind never competes inside it

    def test_ask_saves_clean_frame_and_label_teaches(self):
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Stove'), wf, detect_fn=self.fn({id(self.img['normal-1']): ('HouseDoor',)}))
        clean = os.path.join(self.tmp, 'ask-1.frame.png')
        self.assertTrue(os.path.exists(clean))
        from PIL import Image
        self.assertEqual(Image.open(clean).size, (1920, 1080))
        root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(T, 'fixtures', 'objects_db'), root, dirs_exist_ok=True)
        from objects import store as S
        st = S.Store(root)
        n0 = st.count('Mailbox')
        msg = L.label(1, 'Mailbox', 1400, 300, 1480, 400, state='closed', directory=self.tmp, store=st)
        self.assertEqual(st.count('Mailbox'), n0 + 1)
        ex = st.examples('Mailbox')[-1]
        self.assertEqual((ex.source, ex.state), ('model', 'closed'))
        self.assertIn('re-run', msg)
        self.assertIn('re-run', L.answer(1, 5, 5, directory=self.tmp))

    def test_label_makes_the_kind_detectable_on_that_frame(self):
        from objects import store as S
        root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(T, 'fixtures', 'objects_db'), root, dirs_exist_ok=True)
        st = S.Store(root)
        st.remove_kind('Well') if hasattr(st, 'remove_kind') else [st.remove('Well', e.id) for e in list(st.examples('Well'))]
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Stove'), wf, detect_fn=self.fn({id(self.img['normal-1']): ('HouseDoor',)}))
        L.label(1, 'Well', 800, 120, 900, 220, directory=self.tmp, store=st)
        dets = self.D.detect(self.img['normal-1'], st, kinds=['Well'], exclude=['Garden'])
        self.assertTrue([d for d in dets if d.kind == 'Well' and 780 < d.point[0] < 920 and 100 < d.point[1] < 240], dets)

    def test_label_always_stored_even_when_a_near_duplicate(self):
        from objects import store as S
        root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(T, 'fixtures', 'objects_db'), root, dirs_exist_ok=True)
        st = S.Store(root)
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Stove'), wf, detect_fn=self.fn({id(self.img['normal-1']): ('HouseDoor',)}))
        n0 = st.count('Mailbox')
        L.label(1, 'Mailbox', 1400, 300, 1480, 400, directory=self.tmp, store=st)
        msg = L.label(1, 'Mailbox', 1400, 300, 1480, 400, directory=self.tmp, store=st)   # identical crop
        self.assertEqual(st.count('Mailbox'), n0 + 2)
        self.assertNotIn('duplicate', msg)

    def test_label_a_false_box_as_a_rival_kind(self):
        from PIL import Image
        from objects import store as S
        root = tempfile.mkdtemp()
        shutil.copytree(os.path.join(T, 'fixtures', 'objects_db'), root, dirs_exist_ok=True)
        st = S.Store(root)
        img = self.img['zoom-2']
        bad = min(self.D.detect(img, st, kinds=['GardenBed'], region='Garden'), key=lambda d: d.dist)   # a weak peak = the false box
        img.save(os.path.join(self.tmp, 'ask-1.frame.png'))
        self.assertNotIn('Grass', st.kinds())
        px, py = bad.point
        msg = L.label(1, 'Grass', px - 70, py - 50, px + 70, py + 50, directory=self.tmp, store=st)   # the false box and its surroundings
        self.assertIn('added Grass (new kind)', msg)
        self.assertIn('Grass', st.kinds())
        again = [d for d in self.D.detect(img, st, kinds=['GardenBed'], region='Garden')
                 if abs(d.point[0] - bad.point[0]) < 30 and abs(d.point[1] - bad.point[1]) < 30]
        self.assertEqual(again, [])

    def test_unknown_bubble_owned_by_the_target_arrives_when_no_action_is_wanted(self):
        q = L.Q(kind='GardenBed').where(crop=None)
        cp = self.first_click('zoom-2', q)
        bub = (cp[0], cp[1] - 120)         # a growing bed's tulip bubble: kind unknown, owned by the bed
        wf = FakeWf([self.img['zoom-2']] * 2, {0: [(bub, 'unknown')], 1: [(bub, 'unknown')]}, run_dir=self.tmp)
        arr = self.run_goto(q, wf)
        self.assertEqual(arr.point, bub)

    def test_not_detected_asks(self):
        wf = FakeWf([self.img['normal-1']], run_dir=self.tmp)
        with self.assertRaises(L.NeedVision):
            self.run_goto(L.Q(kind='Stove'), wf, detect_fn=self.fn({id(self.img['normal-1']): ('HouseDoor',)}))
        self.assertEqual(wf.clicks, [])


if __name__ == '__main__':
    unittest.main()
