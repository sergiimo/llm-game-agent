"""Offline tests for tools/objects/chain.py. Run: .venv/bin/python tools/test_chain.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import core  # noqa: E402
from objects import chain as C, graph as G  # noqa: E402
from objects.detect import Detection  # noqa: E402

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')
B = 'GardenBed@Garden#r%dc%d'


def det(r, c, ox=960, oy=540):
    """Tile (r, c) of a 3x4 grid drawn so that r2c2 sits at the frame centre."""
    x, y = ox + (c - 2) * 200, oy + (r - 2) * 120
    return Detection('GardenBed', (x - 40, y - 30, x + 40, y + 30), 1.0, None, (x, y))


class Locate(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def full(self):
        return [det(r, c) for r in (1, 2, 3) for c in (1, 2, 3, 4)]

    def test_east_neighbour_on_full_grid(self):
        d = C.locate(self.g, B % (2, 2), B % (2, 3), self.full())
        self.assertEqual(d.point, (1160, 540))

    def test_two_steps_south_east(self):
        d = C.locate(self.g, B % (2, 2), B % (3, 3), self.full())
        self.assertEqual(d.point, (1160, 660))

    def test_only_one_tile_visible_is_unexpected(self):
        with self.assertRaises(C.Unexpected) as cm:
            C.locate(self.g, B % (2, 2), B % (2, 3), [det(2, 2)])
        self.assertIn('pattern fit', cm.exception.why)

    def test_target_out_of_view_is_unexpected(self):
        dets = [det(r, c) for r in (2, 3) for c in (2, 3)]
        with self.assertRaises(C.Unexpected) as cm:
            C.locate(self.g, B % (2, 2), B % (1, 4), dets)
        self.assertIn('pattern fit', cm.exception.why)

    def test_partial_view_uses_cluster_offsets(self):
        dets = [det(r, c) for r in (2, 3) for c in (2, 3)]
        self.assertEqual(C.locate(self.g, B % (2, 2), B % (3, 3), dets).point, (1160, 660))

    def test_single_row_with_jitter(self):
        jy = [-3, 3, 0, 2]
        dets = []
        for c, j in zip((1, 2, 3, 4), jy):
            d = det(2, c)
            dets.append(d._replace(point=(d.point[0] + j, d.point[1] + j)))
        d = C.locate(self.g, B % (2, 2), B % (2, 3), dets)
        self.assertEqual(d.point[0], 1160 + 0)

    def test_full_grid_with_jitter_matches_clean(self):
        import random
        rnd = random.Random(1)
        dets = [d._replace(point=(d.point[0] + rnd.randint(-5, 5), d.point[1] + rnd.randint(-5, 5))) for d in self.full()]
        clean = self.full()
        for tgt in (B % (2, 3), B % (3, 3), B % (1, 1), B % (3, 4)):
            got = C.locate(self.g, B % (2, 2), tgt, dets)
            r, c = G.cell(tgt)
            self.assertEqual(clean[(r - 1) * 4 + c - 1].box, got.box)

    def test_click_tile_avoids_bubble(self):
        d = det(2, 2)
        self.assertEqual(C.click_tile(d, []), (960, 540))
        x, y = C.click_tile(d, [(960, 540)])
        self.assertGreaterEqual(((x - 960) ** 2 + (y - 540) ** 2) ** .5, 0)

    def test_no_positions_imported(self):
        src = open(C.__file__).read()
        for bad in ('calib_load', 'checkpoint', 'world()', 'log_pos'):
            self.assertNotIn(bad, src)


class Expect(unittest.TestCase):
    def setUp(self):
        from game.affordances import Affordance
        self.A = Affordance
        self.g = G.Graph()
        self.g.load(SEED)
        self.id = B % (2, 2)

    def aff(self, kind='plant', drop=False, pt=(0, 0)):
        return self.A(kind, None, pt, False, 0, drop)

    def phase(self, ph, watered=None):
        self.g.set_state(self.id, 'phase', ph, 0, 'event')
        if watered is not None:
            self.g.set_state(self.id, 'watered_today', watered, 0, 'event')
        return C.expected_bubble(self.g, self.id)

    def test_wilted_expects_drop(self):
        f = self.phase('wilted')
        self.assertTrue(f(self.aff('water', drop=True)))
        self.assertFalse(f(self.aff('plant')))

    def test_growing_dry_expects_drop_wet_does_not(self):
        self.assertTrue(self.phase('growing', False)(self.aff('water', drop=True)))
        self.assertFalse(self.phase('growing', True)(self.aff('water', drop=True)))

    def test_empty_expects_plant_bubble(self):
        f = self.phase('empty')
        self.assertTrue(f(self.aff('plant')))
        self.assertFalse(f(self.aff('pickup')))

    def test_ripe_expects_pickup(self):
        f = self.phase('ripe')
        self.assertTrue(f(self.aff('pickup')))
        self.assertFalse(f(self.aff('plant')))

    def test_unknown_phase_accepts_any(self):
        f = C.expected_bubble(self.g, self.id)
        self.assertTrue(f(self.aff('unknown')))

    def test_bubble_near_picks_the_one_above_the_tile(self):
        near, far = self.aff(pt=(1000, 420)), self.aff(pt=(1000, 140))
        self.assertIs(C.bubble_near([far, near], (960, 540)), near)
        self.assertIsNone(C.bubble_near([far], (960, 540)))
        self.assertIsNone(C.bubble_near([self.aff(pt=(1300, 420))], (960, 540)))

    def test_event_ignores_position(self):
        from game import core
        class Fake:
            def log_since(s, m): return '12:00 > water Tulip at (99.0, 0.0, -5.5)'
            def _unhash(s, t): return t
        core.bind(Fake())
        self.assertIn('> water', C.event(0, 'water', 0))
        self.assertIsNone(C.event(0, 'pickup', 0))


class FakeGarden:
    """The 3x4 garden as the runner sees it: a frame (tile points with Tara's tile at the centre, bubbles above tiles),
    clicks that move Tara / fire bubbles, a stamped game log, a Remove card and a seed panel. Counts position reads."""
    POS = ('calib_load', 'checkpoint', 'pos', 'world')

    def __init__(self, states=None, can=True):
        self.st = {(r, c): {'phase': 'growing', 'crop': 'Tulip', 'wet': True} for r in (1, 2, 3) for c in (1, 2, 3, 4)}
        for rc, v in (states or {}).items():
            self.st[rc] = {'phase': 'growing', 'crop': 'Tulip', 'wet': True, **v}
        self.tara, self.can, self.log, self.screen = (2, 2), can, [], 'gameplay'
        self.cur, self.picked, self.seed_limit = None, None, 99
        self.position_reads, self.closed, self.asked, self.fills, self.save_override = 0, 0, [], 0, None
        self.save_n, self.move = 1, 'ok'   # move: 'ok' | 'none' (click does not move Tara) | 'far' (moves her two tiles)
        for n in self.POS:
            setattr(self, n, self._pos_reader)

    def _pos_reader(self, *a, **k):
        self.position_reads += 1

    # --- the frame
    def tile_pt(self, rc):
        t = self.tara or (2, 2)
        return 960 + (rc[1] - t[1]) * 200, 540 + (rc[0] - t[0]) * 120

    def detect(self, img):
        return [Detection('GardenBed', (x - 40, y - 30, x + 40, y + 30), 1.0, None, (x, y))
                for x, y in (self.tile_pt(rc) for rc in sorted(self.st))]

    def kind_of(self, rc):
        s = self.st[rc]
        return {'wilted': ('unplant', True), 'empty': ('plant', False), 'ripe': ('pickup', False)}.get(
            s['phase'], ('water', True) if not s['wet'] else ('unknown', False))

    def scan(self):
        from game.affordances import Affordance
        out = []
        for rc in sorted(self.st):
            x, y = self.tile_pt(rc)
            k, drop = self.kind_of(rc)
            out.append(Affordance(k, None, (x, y - 150), False, 0, drop))
        return out

    # --- the game / wf surface
    def grab(self, crop=True):
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (1920, 1080), (40, 40, 40))
        dr = ImageDraw.Draw(img)
        for rc in self.st:   # identical tiles: only geometry can prove a move
            x, y = self.tile_pt(rc)
            dr.rectangle((x - 40, y - 30, x + 40, y + 30), fill=(90, 120, 90))
        return img

    def save_stamp(self):
        return self.save_n

    def wait_settle(self):
        pass

    def log_mark(self):
        return len(self.log)

    def log_since(self, mark):
        return '\n'.join(self.log[mark:])

    def _unhash(self, t):
        return t

    def game_stamp(self):
        return 'D5 10:00:00 AM'

    def ask_vision(self, kind, q, img, **ctx):
        self.asked.append(q)
        return f'NEED_VISION {kind}: {q}'

    def emit(self, act, target='GardenBed'):
        self.log.append(f'[D5 10:00:00 AM] > {act} Thing target={target} at (12.5, 0.0, -3.5)')

    def run_action(self, a):
        x, y = (int(v) for v in a.split(':')[1:])
        for rc in sorted(self.st):
            tx, ty = self.tile_pt(rc)
            if abs(x - tx) < 25 and abs(y - (ty - 150)) < 25:
                return self.bubble(rc)
        for rc in sorted(self.st):
            tx, ty = self.tile_pt(rc)
            if abs(x - tx) < 45 and abs(y - ty) < 45:
                if self.move == 'ok':
                    self.tara = rc
                elif self.move == 'far':
                    self.tara = (rc[0], min(4, rc[1] + 1)) if rc[1] >= self.tara[1] else (rc[0], max(1, rc[1] - 1))
                return

    def bubble(self, rc):
        s = self.st[rc]
        self.cur = rc
        if s['phase'] == 'wilted':
            self.emit('unplant')
            self.screen = 'card'
        elif s['phase'] == 'empty':
            self.screen = 'panel'
        elif s['phase'] == 'ripe':
            self.emit('grab_item')
            s.update(phase='growing', wet=False)
        elif not s['wet']:
            if self.can:
                self.emit('water')
                s['wet'] = True
            else:
                self.emit('out_of_water')

    def farm_status(self):
        pst = {'wilted': '##growing', 'empty': '##0', 'ripe': '##produced', 'growing': '##growing'}
        return {'crops': [{'plantState': pst[v['phase']], 'isWilted': 'true' if v['phase'] == 'wilted' else 'false',
                           'isWatered': 'true' if v['wet'] else 'false'} for v in self.st.values()]}

    def save_bed_counts(self, crops):
        import wf
        return self.save_override or wf.save_bed_counts(crops)

    # --- patched ui / well
    def texts(self):
        return {'card': [(self.st[self.cur]['crop'] if self.cur else None) or 'Green Bean', 'This plant has wilted', 'Remove'], 'panel': ['Inventory', 'Seeds'],
                'detail': ['Tulip Bulbs', 'Select']}.get(self.screen, [])

    def shows(self, word, wait=2.0):
        return any(word.lower() in t.lower() for t in self.texts())

    def press(self, label):
        s = self.st[self.cur]
        if label == 'Remove' and self.screen == 'card':
            self.emit('unplant_impl')
            s.update(phase='empty', crop=None)
        elif label == 'Select' and self.screen == 'detail':
            self.emit('plant')
            self.log.append('[D5 10:00:01 AM] [STATS] totalPlanted.' + self.picked)
            s.update(phase='growing', crop=self.picked, wet=False)
        else:
            raise core.Failed(f'no "{label}"')
        self.screen = 'gameplay'

    def pick_card(self, name):
        if self.seed_limit <= 0:
            raise core.Failed(f'no "{name}" among 3 cards')
        self.seed_limit -= 1
        self.picked, self.screen = name, 'detail'

    def close(self):
        self.closed += 1
        self.screen = 'gameplay'

    def fill_can(self):
        self.fills += 1
        self.can = True

    # --- scripted anchor answer from the truth
    def truth_answer(self, pending):
        pts = {rc: self.tile_pt(rc) for rc in self.st}
        words = []
        for l, d in pending['labels'].items():
            rc = next(rc for rc, p in pts.items() if tuple(p) == tuple(d['point']))
            s = self.st[rc]
            w = f'{l}=r{rc[0]}c{rc[1]} {s["phase"]}'
            if s['crop'] and s['phase'] in ('wilted', 'ripe', 'growing'):
                w += f'({s["crop"]})'
            if s['phase'] == 'growing':
                w += ' watered' if s['wet'] else ' dry'
            words.append(w)
        at = next(l for l, d in pending['labels'].items() if tuple(d['point']) == tuple(pts[self.tara]))
        return f'group: GardenBed@Garden   at: {at}=r{self.tara[0]}c{self.tara[1]}   ' + '   '.join(words)


class Runner(unittest.TestCase):
    GB = 'GardenBed@Garden'

    def setUp(self):
        import tempfile
        from unittest import mock
        from game import core, ui, well, affordances
        from objects import anchor, loop
        self.core, self.anchor, self.loop = core, anchor, loop
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, core, 'WF', core.WF)
        self.addCleanup(setattr, anchor, 'PENDING', anchor.PENDING)
        anchor.PENDING = os.path.join(self.tmp.name, 'anchor-pending.json')
        self.g = G.Graph()
        self.g.load(SEED)
        self.gpath = os.path.join(self.tmp.name, 'g.json')
        self.mock = mock
        self.mods = (ui, well, affordances)

    def fake(self, **kw):
        f = FakeGarden(**kw)
        self.core.bind(f)
        p = self.mock
        for obj, name, fn in ((self.mods[0], 'texts', f.texts), (self.mods[0], 'shows', f.shows),
                              (self.mods[0], 'press', f.press), (self.mods[0], 'pick_card', f.pick_card),
                              (self.mods[0], 'close', f.close), (self.mods[1], 'fill_can', f.fill_can),
                              (self.mods[2], 'scan', f.scan)):
            pa = p.patch.object(obj, name, fn)
            pa.start()
            self.addCleanup(pa.stop)
        self.f = f
        return f

    def preset(self, at, hints=None):
        """Graph already anchored: Tara.at and the same states the fake holds (no vision needed)."""
        self.g.set_state('Tara', 'at', at, 'D5 9:00:00 AM', 'vision')
        self.f.tara = G.cell(at)
        for rc, v in self.f.st.items():
            n = f'{self.GB}#r{rc[0]}c{rc[1]}'
            self.g.set_state(n, 'phase', v['phase'], 'D5 9:00:00 AM', 'vision')
            self.g.set_state(n, 'watered_today', v['wet'], 'D5 9:00:00 AM', 'vision')
            self.g.set_state(n, 'crop', v['crop'], 'D5 9:00:00 AM', 'vision')
        for rc, v in (hints or {}).items():
            for k, val in v.items():
                self.g.set_state(f'{self.GB}#r{rc[0]}c{rc[1]}', k, val, 'D5 9:00:00 AM', 'vision')

    def run_(self, task, **kw):
        return C.run(task, self.GB, self.g, detect_fn=self.f.detect, wf=self.f, **kw)

    def drive(self, task, max_visions=6, **kw):
        """Call run, answering every anchor question from the fake's truth; returns (summary, visions)."""
        import json
        from objects.loop import NeedVision
        n = 0
        while True:
            try:
                return self.run_(task, **kw), n
            except NeedVision:
                n += 1
                self.assertLessEqual(n, max_visions, 'too many vision questions')
                pend = json.load(open(self.anchor.PENDING))
                self.anchor.answer(self.f.truth_answer(pend), graph=self.g, gpath=self.gpath)

    def node(self, r, c):
        return f'{self.GB}#r{r}c{c}'

    def test_first_call_asks_anchor(self):
        self.fake()
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertTrue(os.path.exists(self.anchor.PENDING))

    def test_replant_all_fixes_every_wilted_bed(self):
        f = self.fake(states={(1, 1): {'phase': 'wilted', 'crop': 'Green Bean'}, (2, 3): {'phase': 'wilted', 'crop': 'Carrot'},
                              (3, 4): {'phase': 'wilted', 'crop': 'Tulip'}})
        res, visions = self.drive('replant')
        self.assertEqual(visions, 1)
        self.assertEqual(res['vision'], 1)
        self.assertEqual(sorted(res['done']), sorted([self.node(1, 1), self.node(2, 3), self.node(3, 4)]))
        for rc, crop in (((1, 1), 'Green Bean'), ((2, 3), 'Carrot'), ((3, 4), 'Tulip')):
            self.assertEqual(f.st[rc]['phase'], 'growing')
            self.assertEqual(f.st[rc]['crop'], crop)
            self.assertTrue(f.st[rc]['wet'])
            n = self.node(*rc)
            self.assertEqual(self.g.phase(n), 'growing')
            self.assertIs(self.g.state_value(n, 'watered_today'), True)
            self.assertEqual(self.g.state_value(n, 'crop'), crop)
        self.assertEqual(f.position_reads, 0)

    def test_stale_hint_triggers_one_vision_then_continues(self):
        f = self.fake(states={(r, c): {'wet': False} for r in (1, 2, 3) for c in (1, 2, 3, 4)})
        f.st[(1, 2)].update(phase='empty', crop=None, wet=False)
        self.preset(self.node(2, 2))
        self.g.set_state(self.node(1, 2), 'phase', 'growing', 'D5 9:00:00 AM', 'vision')   # the stale hint
        self.g.set_state(self.node(1, 2), 'crop', 'Tulip', 'D5 9:00:00 AM', 'vision')
        res, visions = self.drive('water')
        self.assertEqual(visions, 1)
        self.assertNotIn(self.node(1, 2), res['done'])
        self.assertEqual(len(res['done']), 10)   # r2c2 was done in the first call, r1c2 needs nothing
        self.assertTrue(all(v['wet'] for rc, v in f.st.items() if rc != (1, 2)))
        self.assertEqual(self.g.phase(self.node(1, 2)), 'empty')

    def test_seeds_run_out_marks_bed_empty_and_stops(self):
        f = self.fake(states={(1, 1): {'phase': 'wilted'}, (1, 2): {'phase': 'wilted'}, (1, 3): {'phase': 'wilted'}})
        f.seed_limit = 1
        self.preset(self.node(1, 1))
        res = self.run_('replant')
        self.assertEqual([i for i, _ in res['skipped']], [self.node(1, 2)])
        self.assertIn('no seeds', res['skipped'][0][1])
        self.assertEqual(self.g.phase(self.node(1, 2)), 'empty')
        self.assertIsNone(self.g.state_value(self.node(1, 2), 'crop'))
        self.assertEqual(self.g.phase(self.node(1, 3)), 'wilted')   # the run stopped
        self.assertEqual(res['done'], [self.node(1, 1)])
        self.assertGreaterEqual(f.closed, 2)

    def test_out_of_water_fills_and_returns_once(self):
        f = self.fake(states={(2, 2): {'wet': False}}, can=False)
        self.preset(self.node(2, 2))
        res, visions = self.drive('water')
        self.assertEqual(f.fills, 1)
        self.assertTrue(f.st[(2, 2)]['wet'])
        self.assertEqual(res['done'], [self.node(2, 2)])
        self.assertEqual(visions, 1)           # the re-anchor after the well
        self.assertEqual(res['vision'], 1)

    def test_water_all_after_day_change(self):
        f = self.fake(states={(r, c): {'wet': False} for r in (1, 2, 3) for c in (1, 2, 3, 4)})
        self.preset(self.node(2, 2))
        for rc in f.st:
            self.g.set_state(self.node(*rc), 'watered_today', True, 'D4 10:00:00 AM', 'event')
        self.g.new_day(5)
        res = self.run_('water')
        self.assertEqual(len(res['done']), 12)
        self.assertTrue(all(v['wet'] for v in f.st.values()))
        self.assertEqual(f.position_reads, 0)

    def test_enters_region_before_anchoring(self):
        self.fake()
        self.g.set_state('Tara', 'at', 'House', 'D5 9:00:00 AM', 'vision')
        from objects.loop import NeedVision
        with self.mock.patch.object(self.loop, 'goto') as go:
            with self.assertRaises(NeedVision):
                self.run_('water')
        self.assertEqual(go.call_count, 1)
        self.assertEqual(go.call_args.args[0].kind, 'GardenBed')
        self.assertIsNone(self.g.state_value('Tara', 'at'))

    def test_count_mismatch_asks_once(self):
        f = self.fake()
        res, visions = self.drive('water')     # nothing to water: only the anchor
        self.assertEqual(visions, 1)
        f.save_override = {'wilted': 1, 'ripe': 0, 'empty': 0, 'dry': 0}
        f.save_n = 2   # a newer save than the run's last action
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertIn('wilted', f.asked[-1])
        self.assertEqual(len([q for q in f.asked if 'wilted=' in q]), 1)

    def test_garden_wrappers_run_the_tasks(self):
        from game import garden
        f = self.fake(states={(2, 2): {'wet': False}})
        self.preset(self.node(2, 2))
        gp = os.path.join(self.tmp.name, 'saved.json')
        with self.mock.patch.object(C, 'run', wraps=C.run) as r:
            res = garden.water_all(graph=self.g, gpath=gp, detect_fn=f.detect)
        self.assertEqual(r.call_args.args[:2], ('water', self.GB))
        self.assertEqual(res['done'], [self.node(2, 2)])
        self.assertTrue(os.path.exists(gp))
        self.assertTrue(callable(garden.replant_all) and callable(garden.harvest_all))

    def test_harvest_picks_ripe(self):
        f = self.fake(states={(1, 4): {'phase': 'ripe'}})
        self.preset(self.node(2, 2))
        res = self.run_('harvest')
        self.assertEqual(res['done'], [self.node(1, 4)])
        self.assertEqual(f.st[(1, 4)]['phase'], 'growing')

    def test_click_that_does_not_move_is_one_question_and_no_action(self):
        f = self.fake(states={(r, c): {'wet': False} for r in (1, 2, 3) for c in (1, 2, 3, 4)})
        f.st[(2, 2)]['wet'] = True
        self.preset(self.node(2, 2))
        f.move = 'none'
        from objects.loop import NeedVision
        n = len(f.log)
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertEqual(f.log[n:], [])
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 2))

    def test_overshoot_to_wrong_neighbour_is_one_question_and_no_action(self):
        f = self.fake(states={(r, c): {'wet': False} for r in (1, 2, 3) for c in (1, 2, 3, 4)})
        self.preset(self.node(2, 1))
        f.st[(2, 1)]['wet'] = True
        self.g.set_state(self.node(2, 1), 'watered_today', True, 'D5 9:00:00 AM', 'vision')
        f.move = 'far'
        from objects.loop import NeedVision
        n = len(f.log)
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertEqual(f.log[n:], [])
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 1))

    def test_stale_save_skips_count_check(self):
        f = self.fake(states={(2, 2): {'wet': False}})
        self.preset(self.node(2, 2))
        f.save_override = {'wilted': 5, 'ripe': 0, 'empty': 0, 'dry': 0}   # would mismatch, but the save is old
        res = self.run_('water')
        self.assertEqual(res['count_check'], 'skipped (save older than run)')
        self.assertEqual(f.asked, [])

    def test_newer_save_checks_once_per_stamp(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        f.save_override = {'wilted': 1, 'ripe': 0, 'empty': 0, 'dry': 0}
        f.save_n = 2
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        res = self.run_('water')                       # same save stamp: no second question
        self.assertEqual(len(f.asked), 1)
        self.assertIn('already checked', res['count_check'])
        f.save_n = 3                                   # a newer save is checked again
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 2)

    def test_replant_interrupted_by_dry_can_waters_first_next_run(self):
        f = self.fake(states={(2, 2): {'phase': 'wilted', 'crop': 'Tulip'}, (2, 3): {'wet': False}}, can=False)
        self.preset(self.node(2, 2))
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('replant')
        self.assertEqual(f.fills, 1)
        self.assertEqual(self.g.state_value('Tara', 'pending_water'), self.node(2, 2))
        self.assertFalse(f.st[(2, 2)]['wet'])
        import json
        self.anchor.answer(f.truth_answer(json.load(open(self.anchor.PENDING))), graph=self.g, gpath=self.gpath)
        res = self.run_('water')                       # any task: the pending bed first
        self.assertEqual(res['done'][0], self.node(2, 2))
        self.assertTrue(f.st[(2, 2)]['wet'])
        self.assertIsNone(self.g.state_value('Tara', 'pending_water'))
        self.assertEqual(f.fills, 1)

    def test_identical_beds_one_tile_move_proceeds(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        f.st[(2, 2)]['wet'] = True
        self.preset(self.node(2, 2))
        res = self.run_('water')
        self.assertEqual(res['done'], [self.node(2, 3)])
        self.assertTrue(f.st[(2, 3)]['wet'])

    def test_two_tile_overshoot_in_identical_row_is_rejected(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        f.st[(2, 2)]['wet'] = True
        f.st[(2, 1)]['wet'] = True
        self.preset(self.node(2, 1))
        f.move = 'far'
        from objects.loop import NeedVision
        n = len(f.log)
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertEqual(f.log[n:], [])
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 1))


class NoPositionCode(unittest.TestCase):
    FORBIDDEN = ('log_pos', '_bed_at', '_WATER_AT', 'member_from_log', 'calib_load', 'checkpoint(', '.world()')
    # walk.py is the old position walker, removed in the follow-up plan (spec 2026-11-02 §7); nothing here calls it
    EXEMPT = {os.path.join('game', 'walk.py')}

    def test_game_and_objects_have_no_position_code(self):
        root = os.path.dirname(os.path.abspath(__file__))
        bad = []
        for sub in ('game', 'objects'):
            for dp, _, fs in os.walk(os.path.join(root, sub)):
                for f in fs:
                    path = os.path.join(dp, f)
                    if not f.endswith('.py') or os.path.relpath(path, root) in self.EXEMPT:
                        continue
                    text = open(path).read()
                    bad += [f'{os.path.relpath(path, root)}: {w}' for w in self.FORBIDDEN if w in text]
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
