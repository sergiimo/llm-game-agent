"""Offline tests for tools/objects/chain.py. Run: .venv/bin/python tools/test_chain.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import core  # noqa: E402
from objects import chain as C, graph as G  # noqa: E402

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')
B = 'GardenBed@Garden#r%dc%d'


PX, PY, OFF = 240, 135, (40, 33.75)   # the fake garden's true layout: bed pitch and where Tara's bed sits vs the frame centre
LAYOUT = {'pitch': [PX, PY], 'ref_offset': list(OFF)}
_WORLD = []


def world():
    """A deterministic textured world (blocky seeded noise), bigger than the frame by the camera travel."""
    if not _WORLD:
        import numpy as np
        rng = np.random.default_rng(7)
        small = rng.integers(0, 256, (1080 // 6 + 90, 1920 // 6 + 200)).astype('uint8')
        _WORLD.append(np.kron(small, np.ones((6, 6), dtype='uint8')))
    return _WORLD[0]


def frame_at(cx, cy):
    from PIL import Image
    w = world()
    return Image.fromarray(w[cy:cy + 1080, cx:cx + 1920]).convert('RGB')


class Layout(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)
        self.g.nodes['GardenBed@Garden'].extra['layout'] = dict(LAYOUT)

    def test_layout_point_east_neighbour(self):
        self.assertEqual(C.layout_point(self.g, B % (2, 2), B % (2, 3)), (960 + 40 + PX, 540 + 33.75))

    def test_layout_point_south_west_two_steps(self):
        self.assertEqual(C.layout_point(self.g, B % (2, 2), B % (3, 1)), (960 + 40 - PX, 540 + 33.75 + PY))

    def test_layout_point_same_bed_is_the_tile_point(self):
        self.assertEqual(C.layout_point(self.g, B % (2, 2), B % (2, 2)), (1000, 573.75))

    def test_no_layout_is_unexpected(self):
        del self.g.nodes['GardenBed@Garden'].extra['layout']
        with self.assertRaises(C.Unexpected) as cm:
            C.layout_point(self.g, B % (2, 2), B % (2, 3))
        self.assertEqual(cm.exception.why, 'no layout')

    def test_bad_pitch_is_unexpected_and_dropped(self):
        for pitch in ([0, 135], [-240, 135], [240, 30], [39, 135]):
            with self.subTest(pitch=pitch):
                self.g.nodes['GardenBed@Garden'].extra['layout'] = {'pitch': pitch, 'ref_offset': [0, 0]}
                with self.assertRaises(C.Unexpected) as cm:
                    C.layout_point(self.g, B % (2, 2), B % (2, 3))
                self.assertIn('bad layout', cm.exception.why)
                self.assertNotIn('layout', self.g.nodes['GardenBed@Garden'].extra)

    def test_camera_shift_measures_scroll(self):
        dx, dy, peak = C.camera_shift(frame_at(0, 0), frame_at(480, 0))
        self.assertAlmostEqual(dx, -480, delta=8)
        self.assertAlmostEqual(dy, 0, delta=8)
        self.assertGreaterEqual(peak, 0.1)
        dx, dy, peak = C.camera_shift(frame_at(100, 120), frame_at(0, 0))
        self.assertAlmostEqual(dx, 100, delta=8)
        self.assertAlmostEqual(dy, 120, delta=8)

    def test_uniform_frame_is_unexpected(self):
        from PIL import Image
        flat = Image.new('RGB', (1920, 1080), (12, 12, 20))
        shift = C.camera_shift(flat, flat.copy())
        self.assertLess(shift[2], 0.1)
        with self.assertRaises(C.Unexpected) as cm:
            C.prove_move(LAYOUT, shift, 'E')
        self.assertIn('move not proved', cm.exception.why)

    def test_near_uniform_noise_frame_has_no_peak(self):
        import numpy as np
        from PIL import Image
        rng = np.random.default_rng(3)
        a = Image.fromarray((14 + rng.integers(0, 2, (1080, 1920))).astype('uint8')).convert('RGB')
        b = Image.fromarray((14 + rng.integers(0, 2, (1080, 1920))).astype('uint8')).convert('RGB')
        self.assertLess(C.camera_shift(a, b)[2], 0.1)

    def test_prove_move_accepts_one_pitch_opposite(self):
        for d, sh in (('E', (-PX, 0)), ('W', (PX, 0)), ('S', (0, -PY)), ('N', (0, PY))):
            C.prove_move(LAYOUT, (sh[0] + 20, sh[1] - 20, .5), d)

    def test_overshoot_two_pitches_rejected(self):
        with self.assertRaises(C.Unexpected) as cm:
            C.prove_move(LAYOUT, (-2 * PX, 0, .5), 'E')
        self.assertIn('move not proved', cm.exception.why)

    def test_no_move_rejected(self):
        with self.assertRaises(C.Unexpected):
            C.prove_move(LAYOUT, (0, 0, .9), 'E')

    def test_wrong_direction_and_other_axis_rejected(self):
        with self.assertRaises(C.Unexpected):
            C.prove_move(LAYOUT, (PX, 0, .5), 'E')
        with self.assertRaises(C.Unexpected):
            C.prove_move(LAYOUT, (-PX, PY * .5, .5), 'E')

    def test_click_tile_avoids_bubble(self):
        self.assertEqual(C.click_tile((960, 540), []), (960, 540))
        x, y = C.click_tile((960, 540), [(960, 540)])
        self.assertGreaterEqual(((x - 960) ** 2 + (y - 540) ** 2) ** .5, 45)

    def test_no_positions_imported(self):
        src = open(C.__file__).read()
        for bad in ('calib_load', 'checkpoint', 'world()', 'log_pos'):
            self.assertNotIn(bad, src)

    def test_removed_detection_code(self):
        for name in ('detect_fn', 'locate', '_pitch', '_prove_shift', '_centre', '_default_detect'):
            self.assertFalse(hasattr(C, name), name)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(C.__file__), 'lines.py')))


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
        self.fill_graph, self.flat, self.events = None, False, []
        self.reach, self.clicks = False, []   # reach: a click on a bed next to Tara interacts instead of walking
        self.save_n, self.move = 1, 'ok'   # move: 'ok' | 'none' (click does not move Tara) | 'far' (moves her two tiles)
        for n in self.POS:
            setattr(self, n, self._pos_reader)

    def _pos_reader(self, *a, **k):
        self.position_reads += 1

    # --- the frame
    def tile_pt(self, rc):
        t = self.tara or (2, 2)
        return 960 + OFF[0] + (rc[1] - t[1]) * PX, 540 + OFF[1] + (rc[0] - t[0]) * PY

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
            out.append(Affordance(k, None, (round(x), round(y - 150)), False, 0, drop))
        return out

    # --- the game / wf surface
    def grab(self, crop=True):
        from PIL import Image, ImageDraw
        if self.flat:
            return Image.new('RGB', (1920, 1080), (12, 12, 20))
        t = self.tara or (2, 2)
        img = frame_at(t[1] * PX, t[0] * PY)   # the camera follows Tara: one bed step = one pitch of scroll
        dr = ImageDraw.Draw(img)
        for rc in self.st:
            x, y = self.tile_pt(rc)
            dr.rectangle((x - 80, y - 45, x + 80, y + 45), fill=(90, 120, 90))
        return img

    def state(self, save=False):
        return {'mode': self.screen}

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
        self.events.append('ask')
        return f'NEED_VISION {kind}: {q}'

    def emit(self, act, target='GardenBed'):
        self.log.append(f'[D5 10:00:00 AM] > {act} Thing target={target} at (12.5, 0.0, -3.5)')

    def run_action(self, a):
        x, y = (int(v) for v in a.split(':')[1:])
        self.clicks.append((x, y))
        for rc in sorted(self.st):
            tx, ty = self.tile_pt(rc)
            if abs(x - tx) < 25 and abs(y - (ty - 150)) < 25:
                return self.bubble(rc)
        rc = min(self.st, key=lambda r: (x - self.tile_pt(r)[0]) ** 2 + (y - self.tile_pt(r)[1]) ** 2)
        tx, ty = self.tile_pt(rc)
        if abs(x - tx) < PX / 2 and abs(y - ty) < PY / 2:
            if self.reach and rc != self.tara and max(abs(rc[0] - self.tara[0]), abs(rc[1] - self.tara[1])) <= 1:
                return self.interact(rc)
            if self.move == 'opens':
                self.cur, self.screen = rc, 'panel'
            elif self.move == 'ok':
                self.tara = rc
            elif self.move == 'far':
                self.tara = (rc[0], min(4, rc[1] + 1)) if rc[1] >= self.tara[1] else (rc[0], max(1, rc[1] - 1))

    def interact(self, rc):
        """A click on a bed in reach: Space on it (wilted card, water, pickup, plant_growing info, planting panel)."""
        s = self.st[rc]
        if s['phase'] == 'growing' and s['wet']:
            self.emit('plant_growing')
            self.cur = rc
        else:
            self.bubble(rc)

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
        self.events.append('close')
        self.screen = 'gameplay'

    def fill_can(self, graph=None):
        self.fills += 1
        self.can = True
        self.fill_graph = graph

    # --- scripted anchor answer from the truth (the grid cell nearest each bed centre)
    @staticmethod
    def cell_of(pt):
        return f'{chr(65 + int(pt[0] // 80))}{int(pt[1] // 67.5) + 1}'

    def truth_answer(self, pending=None):
        words = []
        for rc in sorted(self.st):
            s = self.st[rc]
            w = f'r{rc[0]}c{rc[1]}@{self.cell_of(self.tile_pt(rc))} {s["phase"]}'
            if s['crop'] and s['phase'] in ('wilted', 'ripe', 'growing'):
                w += f'({s["crop"]})'
            if s['phase'] == 'growing':
                w += ' watered' if s['wet'] else ' dry'
            words.append(w)
        t = self.tara
        return (f'group: GardenBed@Garden   ref: r{t[0]}c{t[1]}@{self.cell_of(self.tile_pt(t))}\n' + '   '.join(words))


class RunnerBase(unittest.TestCase):
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
        from objects import chain_step
        for name, val in (('ARRIVE_WAIT', 0.0), ('POLL', 0.0)):   # the fake settles at once: do not really wait 8 s
            self.addCleanup(setattr, chain_step, name, getattr(chain_step, name))
            setattr(chain_step, name, val)
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
        pg = p.patch.object(self.loop, 'goto', side_effect=lambda *a, **k: f.events.append('goto'))
        self.go = pg.start()
        self.addCleanup(pg.stop)
        return f

    def preset(self, at, hints=None):
        """Graph already anchored: Tara.at and the same states the fake holds (no vision needed)."""
        self.g.set_state('Tara', 'at', at, 'D5 9:00:00 AM', 'vision')
        self.g.nodes[self.GB].extra['layout'] = dict(LAYOUT)
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
        return C.run(task, self.GB, self.g, wf=self.f, **kw)

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

    def complete(self):
        """Make the graph cover every bed (the farm-wide count check needs it): a FarGarden member with a known phase."""
        far = 'GardenBed@FarGarden'
        self.g.nodes[far].extra['pattern'] = {'rows': 1, 'cols': 1, 'order': 'x'}
        self.g.nodes[far + '#r1c1'] = G.Node(far + '#r1c1', 'member', kind='GardenBed', region=far)
        self.g.set_state(far + '#r1c1', 'phase', 'empty', 'D5 9:00:00 AM', 'vision')


class Runner(RunnerBase):
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
        self.complete()
        f.save_n = 0   # no newer save yet: the first call only anchors
        res, visions = self.drive('water')     # nothing to water: only the anchor
        self.assertEqual(visions, 1)
        f.save_override = {'wilted': 1, 'ripe': 0, 'empty': 0, 'dry': 0}
        f.save_n = 2   # a newer save than the run's last action
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertIn('wilted', f.asked[-1])
        self.assertEqual(len([q for q in f.asked if 'wilted=' in q]), 1)
        self.assertIn('Run so far: done 0', f.asked[-1])   # the summary is not lost

    def test_garden_wrappers_run_the_tasks(self):
        from game import garden
        f = self.fake(states={(2, 2): {'wet': False}})
        self.preset(self.node(2, 2))
        gp = os.path.join(self.tmp.name, 'saved.json')
        with self.mock.patch.object(C, 'run', wraps=C.run) as r:
            res = garden._chain('water', graph=self.g, gpath=gp)
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
        self.complete()
        f.save_override = {'wilted': 5, 'ripe': 0, 'empty': 0, 'dry': 0}   # would mismatch, but the save is old
        res = self.run_('water')
        self.assertEqual(res['count_check'], 'skipped (save older than run)')
        self.assertEqual(f.asked, [])

    def test_newer_save_checks_once_per_stamp(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.complete()
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

    # ---- final-review fixes
    def test_incomplete_graph_skips_count_check(self):
        f = self.fake()
        self.preset(self.node(2, 2))                    # FarGarden has no members: incomplete
        f.save_override = {'wilted': 5, 'ripe': 0, 'empty': 0, 'dry': 0}
        f.save_n = 2
        res = self.run_('water')
        self.assertEqual(res['count_check'], 'skipped (graph incomplete)')
        self.assertEqual(f.asked, [])

    def test_unknown_phase_member_skips_check_and_is_listed(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.complete()
        self.g.set_state(self.node(1, 1), 'phase', None, 'D5 9:00:00 AM', 'event', 0.0)
        f.save_n = 2
        res = self.run_('water')
        self.assertEqual(res['unknown'], [self.node(1, 1)])
        self.assertEqual(res['count_check'], 'skipped (graph incomplete)')

    def test_stale_at_other_day_is_dropped_and_asks_once(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'at', self.node(2, 2), 'D4 9:00:00 AM', 'vision')   # yesterday
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIsNone(self.g.state_value('Tara', 'at'))

    def test_stale_at_other_scene_is_dropped(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'at_scene', 'Farm', 'D5 9:00:00 AM', 'event')
        f.current_scene = lambda: 'House'
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIsNone(self.g.state_value('Tara', 'at'))

    def test_fresh_at_with_tiles_does_not_walk(self):
        f = self.fake(states={(2, 2): {'wet': False}})
        self.preset(self.node(2, 2))
        with self.mock.patch.object(self.loop, 'goto') as go:
            self.run_('water')
        self.assertEqual(go.call_count, 0)

    def test_click_that_opens_a_card_is_one_question_and_closes_it(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        self.preset(self.node(2, 2))
        f.move = 'opens'
        from objects.loop import NeedVision
        n, closed = len(f.log), f.closed
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('opened', f.asked[0])
        self.assertGreater(f.closed, closed)
        self.assertEqual(f.log[n:], [])
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 2))

    def test_failed_action_is_one_question(self):
        f = self.fake(states={(2, 2): {'phase': 'wilted', 'crop': 'Tulip'}})
        self.preset(self.node(2, 2))
        def boom(label):
            raise core.Failed('no "Remove"; NEED_VISION game: what now')
        self.mock.patch.object(self.mods[0], 'press', boom).start()
        self.addCleanup(self.mock.patch.stopall)
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('replant')
        self.assertEqual(len(f.asked), 1)
        self.assertNotIn('NEED_VISION game', f.asked[0])
        self.assertGreater(f.closed, 0)

    def test_no_layout_is_one_question(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        self.preset(self.node(2, 2))
        del self.g.nodes[self.GB].extra['layout']
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('no layout', f.asked[0])
        self.assertEqual(f.log, [])

    def test_bad_layout_is_one_question_and_dropped(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        self.preset(self.node(2, 2))
        self.g.nodes[self.GB].extra['layout']['pitch'] = [30, 135]
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('bad layout', f.asked[0])
        self.assertNotIn('layout', self.g.nodes[self.GB].extra)

    def test_uniform_frames_are_one_question_and_no_action(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        self.preset(self.node(2, 2))
        f.flat = True
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('move not proved', f.asked[0])
        self.assertEqual(f.log, [])
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 2))
        self.assertNotIn('layout', self.g.nodes[self.GB].extra)

    def test_open_card_closed_before_asking(self):
        f = self.fake()
        f.screen = 'card'
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(f.events[:3], ['close', 'goto', 'ask'])
        self.assertEqual(f.screen, 'gameplay')

    def test_stale_at_walks_to_garden_once_before_the_question(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'at', self.node(2, 2), 'D4 9:00:00 AM', 'vision')
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(self.go.call_count, 1)
        self.assertEqual(self.go.call_args.args[0].kind, 'GardenBed')
        self.assertEqual(f.events, ['goto', 'ask'])

    def test_after_fill_can_goto_before_the_reanchor_question(self):
        f = self.fake(states={(2, 2): {'wet': False}}, can=False)
        self.preset(self.node(2, 2))
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(f.fills, 1)
        self.assertEqual(self.go.call_count, 1)
        self.assertLess(f.events.index('goto'), f.events.index('ask'))

    def test_none_answer_sets_need_goto_and_next_run_walks_first(self):
        f = self.fake()
        self.g.set_state(self.node(1, 1), 'phase', 'wilted', 'D5 9:00:00 AM', 'vision')
        before = self.g.node(self.node(1, 1)).state['phase']['value']
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        msg = self.anchor.answer(f'group: {self.GB}   none', graph=self.g, gpath=self.gpath)
        self.assertIn('no beds visible', msg)
        self.assertIs(self.g.state_value('Tara', 'need_goto'), True)
        self.assertIsNone(self.g.state_value('Tara', 'at'))
        self.assertEqual(self.g.node(self.node(1, 1)).state['phase']['value'], before)
        self.assertNotIn('layout', self.g.nodes[self.GB].extra)
        self.go.reset_mock()
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(self.go.call_count, 1)   # once, although Tara.at is unknown too
        self.assertIsNone(self.g.state_value('Tara', 'need_goto'))

    def test_need_goto_with_known_at_walks_first_and_clears(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'need_goto', True, 'D5 9:00:00 AM', 'vision')
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(self.go.call_count, 1)
        self.assertIsNone(self.g.state_value('Tara', 'need_goto'))
        self.assertIsNone(self.g.state_value('Tara', 'at'))
        self.assertEqual(len(f.asked), 1)

    def test_unclosable_card_at_start_with_unknown_at_goes_then_asks_once(self):
        f = self.fake()
        f.screen = 'card'

        def stuck(*a, **k):
            raise core.Failed('Escape did not close the card')
        self.mock.patch.object(self.mods[0], 'close', stuck).start()
        self.addCleanup(self.mock.patch.stopall)
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(self.go.call_count, 1)
        self.assertEqual(len(f.asked), 1)
        self.assertIn('Escape did not close', f.asked[0])

    def test_open_card_closed_before_a_step(self):
        f = self.fake(states={(2, 2): {'wet': False}})
        self.preset(self.node(2, 2))
        f.screen = 'panel'
        res = self.run_('water')
        self.assertEqual(f.events[0], 'close')
        self.assertEqual(res['done'], [self.node(2, 2)])

    def test_unreadable_card_crop_does_not_remove_the_bed(self):
        f = self.fake(states={(2, 2): {'phase': 'wilted', 'crop': 'Tulip'}})
        self.preset(self.node(2, 2))
        f.texts = lambda: ['', 'This plant has wilted', 'Remove'] if f.screen == 'card' else []
        self.mock.patch.object(self.mods[0], 'texts', f.texts).start()
        self.addCleanup(self.mock.patch.stopall)
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('replant')
        self.assertEqual(f.st[(2, 2)]['phase'], 'wilted')
        self.assertFalse(any('unplant_impl' in l for l in f.log))
        self.assertEqual(len(f.asked), 1)
        self.assertIsNone(f.picked)

    def test_chain_passes_its_graph_to_fill_can(self):
        f = self.fake(states={(2, 2): {'wet': False}}, can=False)
        self.preset(self.node(2, 2))
        try:
            self.run_('water')
        except Exception:   # noqa: BLE001 (the re-anchor question)
            pass
        self.assertIs(f.fill_graph, self.g)

    def test_harvest_leaves_phase_unknown(self):
        f = self.fake(states={(1, 4): {'phase': 'ripe'}})
        self.preset(self.node(2, 2))
        res = self.run_('harvest')
        s = self.g.node(self.node(1, 4)).state['phase']
        self.assertEqual((s['value'], s['conf']), (None, 0.0))
        self.assertEqual(res['unknown'], [self.node(1, 4)])

    def test_answer_ref_sets_tara_and_layout(self):
        f = self.fake()
        f.tara = (3, 2)
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.anchor.answer(f.truth_answer(), graph=self.g, gpath=self.gpath)
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(3, 2))
        lay = self.g.nodes[self.GB].extra['layout']
        self.assertAlmostEqual(lay['pitch'][0], PX, delta=1)
        self.assertAlmostEqual(lay['pitch'][1], PY, delta=1)
        self.assertAlmostEqual(lay['ref_offset'][0], OFF[0], delta=1)
        self.assertAlmostEqual(lay['ref_offset'][1], OFF[1], delta=1)


class EventsAreTruth(RunnerBase):
    """Live run B (L123): vision misread growing beds as wilted; the click's event is ground truth - correct the node
    from it and move on, no vision question, no CHAIN_STUCK count."""

    def test_growing_misread_as_wilted_is_corrected_and_the_run_continues(self):
        f = self.fake(states={(2, 3): {'phase': 'growing', 'wet': True}, (2, 1): {'phase': 'wilted', 'crop': 'Carrot'}})
        f.reach = True
        self.preset(self.node(2, 2), hints={(2, 3): {'phase': 'wilted', 'crop': 'Tulip'}})   # vision got r2c3 wrong
        res = self.run_('replant')
        self.assertEqual(f.asked, [])
        self.assertEqual(self.g.phase(self.node(2, 3)), 'growing')
        self.assertEqual(self.g.nodes[self.node(2, 3)].state['phase']['source'], 'event')
        self.assertIn(self.node(2, 1), res['done'])
        self.assertNotIn(self.node(2, 3), res['done'])
        self.assertEqual(res['corrected'], [self.node(2, 3)])
        self.assertEqual(f.st[(2, 3)]['phase'], 'growing')            # nothing removed there

    def test_dry_bed_misread_as_wilted_is_watered_by_the_click_and_recorded(self):
        f = self.fake(states={(2, 3): {'phase': 'growing', 'wet': False}})
        f.reach = True
        self.preset(self.node(2, 2), hints={(2, 3): {'phase': 'wilted', 'crop': 'Tulip'}})
        res = self.run_('replant')
        self.assertEqual(f.asked, [])
        self.assertEqual(self.g.phase(self.node(2, 3)), 'growing')
        self.assertIs(self.g.state_value(self.node(2, 3), 'watered_today'), True)
        self.assertEqual(res['corrected'], [self.node(2, 3)])
        self.assertEqual(self.g.state_value('Tara', 'asks') or 0, 0)


    def test_pending_water_on_a_bed_that_turns_out_watered_is_corrected(self):
        f = self.fake(states={(2, 3): {'phase': 'growing', 'wet': True}})
        f.reach = True
        self.preset(self.node(2, 2), hints={(2, 3): {'watered_today': False}})
        self.g.set_state('Tara', 'pending_water', self.node(2, 3), 'D5 9:00:00 AM', 'event')
        res = self.run_('water')
        self.assertEqual((f.asked, res['corrected']), ([], [self.node(2, 3)]))
        self.assertIsNone(self.g.state_value('Tara', 'pending_water'))


class Reach(RunnerBase):
    """Ruling 28-31: the click goes straight to the target; a bed in reach interacts (that is the arrival)."""

    def test_wilted_in_reach_target_arrives_by_interaction_and_uses_the_card(self):
        f = self.fake(states={(2, 3): {'phase': 'wilted', 'crop': 'Carrot'}})
        f.reach = True
        self.preset(self.node(2, 2))
        lay = dict(self.g.nodes[self.GB].extra['layout'])
        res = self.run_('replant')
        self.assertEqual(res['done'], [self.node(2, 3)])
        self.assertEqual((f.st[(2, 3)]['phase'], f.st[(2, 3)]['crop'], f.st[(2, 3)]['wet']), ('growing', 'Carrot', True))
        self.assertEqual(f.closed, 0)                  # the Remove card the click opened was used, not closed
        self.assertEqual(f.asked, [])
        self.assertEqual(len([l for l in f.log if 'unplant ' in l]), 1)   # one click, one unplant
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 2))   # she did not move
        self.assertEqual(self.g.nodes[self.GB].extra['layout'], lay)          # ruling 30: unchanged
        self.assertEqual(self.g.state_value(self.node(2, 3), 'crop'), 'Carrot')

    def test_dry_in_reach_target_is_watered_by_the_click(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        f.reach = True
        self.preset(self.node(2, 2))
        res = self.run_('water')
        self.assertEqual(res['done'], [self.node(2, 3)])
        self.assertTrue(f.st[(2, 3)]['wet'])
        self.assertIs(self.g.state_value(self.node(2, 3), 'watered_today'), True)
        self.assertEqual(len([l for l in f.log if '> water ' in l]), 1)
        self.assertEqual((f.asked, f.clicks.__len__()), ([], 1))

    def test_in_reach_out_of_water_takes_the_refill_path(self):
        f = self.fake(states={(2, 3): {'wet': False}}, can=False)
        f.reach = True
        self.preset(self.node(2, 2))
        res, visions = self.drive('water')
        self.assertEqual((f.fills, visions), (1, 1))
        self.assertEqual(res['done'], [self.node(2, 3)])
        self.assertTrue(f.st[(2, 3)]['wet'])

    def test_in_reach_ripe_target_is_picked_by_the_click(self):
        f = self.fake(states={(1, 2): {'phase': 'ripe'}})
        f.reach = True
        self.preset(self.node(2, 2))
        res = self.run_('harvest')
        self.assertEqual(res['done'], [self.node(1, 2)])
        self.assertEqual(f.asked, [])

    def test_far_target_walks_with_shift_proof_then_acts_and_remeasures_ref_offset(self):
        f = self.fake(states={(2, 4): {'wet': False}})
        f.reach = True
        self.preset(self.node(2, 2))
        self.g.nodes[self.GB].extra['layout']['pitch'] = [PX + 10, PY]   # a slightly wrong pitch, still inside 0.4 pitch
        res = self.run_('water')
        self.assertEqual(res['done'], [self.node(2, 4)])
        self.assertEqual(f.asked, [])
        self.assertEqual(len(f.clicks) - 1, 1)         # one click to walk (plus the bubble click)
        self.assertEqual(self.g.state_value('Tara', 'at'), self.node(2, 4))
        off = self.g.nodes[self.GB].extra['layout']['ref_offset']
        self.assertAlmostEqual(off[0], OFF[0] + 20, delta=6)   # ruling 30: layout point (2 x 250) + shift (2 x -240) - CENTRE
        self.assertAlmostEqual(off[1], OFF[1], delta=6)

    def test_event_with_no_known_meaning_is_one_question(self):
        # a known contradicting event corrects the bed (EventsAreTruth); one with no meaning for a bed still asks
        f = self.fake(states={(2, 3): {'phase': 'wilted', 'crop': 'Tulip'}})
        f.reach = True
        self.preset(self.node(2, 2))
        from objects.loop import NeedVision
        with self.mock.patch.object(C, 'click_target', lambda *a, **k: ('event', 'beehive_progress', 0)):
            with self.assertRaises(NeedVision):
                self.run_('replant')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('logged beehive_progress', f.asked[0])

    def test_no_event_and_no_shift_is_one_question(self):
        f = self.fake(states={(2, 3): {'phase': 'empty', 'crop': None, 'wet': False}})   # in reach: opens the planting panel
        f.reach = True
        self.preset(self.node(2, 2), hints={(2, 3): {'phase': 'wilted'}})
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('replant')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('opened', f.asked[0])

    def test_shift_that_is_not_the_target_is_one_question(self):
        f = self.fake(states={(2, 3): {'wet': False}})
        f.reach = True
        f.move = 'far'                                  # walks one bed too far
        self.preset(self.node(2, 1))
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(len(f.asked), 1)
        self.assertIn('move not proved', f.asked[0])
        self.assertNotIn('layout', self.g.nodes[self.GB].extra)


class Stuck(RunnerBase):
    def test_fifth_question_is_chain_stuck(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'asks', 4, 'D5 9:00:00 AM', 'event')
        self.g.set_state('Tara', 'ask_whys', [['x', 'w1'], ['x', 'w2'], ['x', 'w3'], ['x', 'w4']], 'D5 9:00:00 AM', 'event')
        f.move = 'none'
        self.g.set_state(self.node(2, 3), 'watered_today', False, 'D5 9:00:00 AM', 'vision')
        with self.assertRaises(C.ChainStuck) as cm:
            self.run_('water')
        self.assertTrue(str(cm.exception).startswith('CHAIN_STUCK:'))
        self.assertIn('w4', str(cm.exception))
        self.assertEqual(f.asked, [])
        self.assertEqual(self.g.state_value('Tara', 'asks'), 0)          # reset: a fresh task may ask again
        self.assertIsNone(self.g.state_value('Tara', 'ask_whys'))

    def test_four_questions_are_allowed(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'asks', 3, 'D5 9:00:00 AM', 'event')
        f.move = 'none'
        self.g.set_state(self.node(2, 3), 'watered_today', False, 'D5 9:00:00 AM', 'vision')
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertEqual(self.g.state_value('Tara', 'asks'), 4)

    def test_same_why_at_same_bed_is_chain_stuck(self):
        f = self.fake()
        self.preset(self.node(2, 2))
        f.move = 'none'
        self.g.set_state(self.node(2, 3), 'watered_today', False, 'D5 9:00:00 AM', 'vision')
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.g.nodes[self.GB].extra['layout'] = dict(LAYOUT)   # the answer re-fitted the layout; the click still does nothing
        self.g.set_state('Tara', 'at', self.node(2, 2), 'D5 9:00:00 AM', 'vision')
        with self.assertRaises(C.ChainStuck) as cm:
            self.run_('water')
        self.assertIn('the same one again', str(cm.exception))
        self.assertEqual(len(f.asked), 1)

    def test_completed_run_resets_ask_history(self):
        self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'asks', 2, 'D5 9:00:00 AM', 'event')
        self.g.set_state('Tara', 'ask_whys', [['a', 'b']], 'D5 9:00:00 AM', 'event')
        res = self.run_('water')
        self.assertEqual(res['vision'], 2)
        self.assertEqual(self.g.state_value('Tara', 'asks'), 0)
        self.assertIsNone(self.g.state_value('Tara', 'ask_whys'))

    def test_garden_wrapper_propagates_chain_stuck(self):
        from game import garden
        self.fake()
        with self.mock.patch.object(C, 'run', side_effect=C.ChainStuck('CHAIN_STUCK: x')):
            with self.assertRaises(C.ChainStuck):
                garden._chain('water', graph=self.g, gpath=os.path.join(self.tmp.name, 's.json'))

    def test_wf_py_prints_chain_stuck_plainly(self):
        import contextlib
        import io
        sys.argv = ['x']
        import game
        import wf
        def boom():
            raise C.ChainStuck('CHAIN_STUCK: replant stopped after 4 vision question(s)')
        buf = io.StringIO()
        with self.mock.patch.object(game, 'namespace', return_value={'boom': boom}), \
                self.mock.patch.object(game, 'bind'), contextlib.redirect_stdout(buf):
            code = wf.game_cmd('py', ['boom()'])
        self.assertEqual(code, 3)
        self.assertIn('CHAIN_STUCK: replant stopped', buf.getvalue())
        self.assertNotIn('FAILED', buf.getvalue())
        self.assertNotIn('Traceback', buf.getvalue())


class LayoutDropped(RunnerBase):
    def test_goto_garden_and_stale_at_drop_the_layout(self):
        self.fake()
        self.preset(self.node(2, 2))
        self.g.set_state('Tara', 'at', self.node(2, 2), 'D4 9:00:00 AM', 'vision')   # stale
        from objects.loop import NeedVision
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertNotIn('layout', self.g.nodes[self.GB].extra)
        self.g.nodes[self.GB].extra['layout'] = dict(LAYOUT)
        self.g.set_state('Tara', 'need_goto', True, 'D5 9:00:00 AM', 'vision')
        self.g.set_state('Tara', 'at', self.node(2, 2), 'D5 9:00:00 AM', 'vision')
        with self.assertRaises(NeedVision):
            self.run_('water')
        self.assertNotIn('layout', self.g.nodes[self.GB].extra)


class WellGraph(unittest.TestCase):
    def test_fill_can_with_graph_does_not_touch_farm_json(self):
        import tempfile
        from unittest import mock
        from game import well

        class WF:
            n = 0
            log = []

            def log_mark(self): return 0
            def log_since(self, m): return '[D5 10:00:00 AM] > fill_watering_can Thing target=Well at (1.0, 0.0, 2.0)'
            def _unhash(self, t): return t
            def run_action(self, a): pass
            def wait_settle(self): pass
        g = G.Graph()
        g.load(SEED)
        with tempfile.TemporaryDirectory() as d:
            core.bind(WF())
            with mock.patch.object(well, 'GRAPH', os.path.join(d, 'Farm.json')), \
                    mock.patch.object(well, '_can_bubble', return_value=(5, 5)):
                well.fill_can(graph=g)
                self.assertFalse(os.path.exists(os.path.join(d, 'Farm.json')))
        self.assertEqual(g.state_value('Well', 'can'), 'full')


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
