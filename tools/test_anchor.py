"""Offline tests for tools/objects/anchor.py. Run: .venv/bin/python tools/test_anchor.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ['x']   # wf parses argv on import
from objects import anchor as A, graph as G  # noqa: E402

GB = 'GardenBed@Garden'
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')
SPEC = (f'group: {GB}   ref: r1c2@L8\n'
        'r1c1@F8 ripe   r1c2@L8 ripe   r2c1@F12 wilted(Tulip)   r2c2@L12 wilted(Tulip)   r3c1@F15 ?')
ANS4 = f'group: {GB}   ref: r1c2@L8   r1c1@F8 ripe   r1c2@L8 growing dry   r2c1@F12 wilted(Green Bean)   r2c2@L12 empty'


class AnchorTest(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def test_parse_spec10_example(self):
        a = A.parse(SPEC, self.g)
        self.assertEqual(a.ref, 'GardenBed@Garden#r1c2')
        self.assertEqual(len(a.cells), 5)
        self.assertEqual(a.cells['GardenBed@Garden#r2c1'], 'F12')
        self.assertEqual(a.states['GardenBed@Garden#r2c1']['crop'], 'Tulip')
        self.assertNotIn('GardenBed@Garden#r3c1', a.states)   # `?` = unknown state (phase None)

    def test_parse_rejects_bad_input(self):
        for bad in (SPEC.replace('F15', 'Y15'), SPEC.replace('F15', 'F17'), SPEC.replace('r3c1@F15 ?', 'r4c1@F15 ?'),
                    SPEC.replace('ripe', 'soggy', 1), SPEC.replace(GB, 'Nope'), 'nonsense'):
            with self.assertRaises(A.AnchorError) as cm:
                A.parse(bad, self.g)
            self.assertIn('r1c2@L8', str(cm.exception))   # the spec 10 example in the message

    def test_parse_watered_words(self):
        a = A.parse(f'group: {GB}   ref: r1c1@F8   r1c1@F8 growing watered   r1c2@L8 growing dry', self.g)
        self.assertIs(a.states['GardenBed@Garden#r1c1']['watered_today'], True)
        self.assertIs(a.states['GardenBed@Garden#r1c2']['watered_today'], False)

    def test_cell_point(self):
        self.assertEqual(A.cell_point('F8'), (440, 506.25))
        self.assertEqual(A.cell_point('X16'), (1880, 1046.25))
        with self.assertRaises(A.AnchorError):
            A.cell_point('Y1')

    def four(self):
        return {'GardenBed@Garden#r1c1': A.cell_point('F8'), 'GardenBed@Garden#r1c2': A.cell_point('L8'),
                'GardenBed@Garden#r2c1': A.cell_point('F12'), 'GardenBed@Garden#r2c2': A.cell_point('L12')}

    def test_fit_layout_from_four_beds(self):
        lay = A.fit_layout(self.four(), 'GardenBed@Garden#r1c2', None)
        self.assertAlmostEqual(lay['pitch'][0], 480, delta=1)
        self.assertAlmostEqual(lay['pitch'][1], 270, delta=1)
        self.assertAlmostEqual(lay['ref_offset'][0], 920 - 960, delta=1)
        self.assertAlmostEqual(lay['ref_offset'][1], 506.25 - 540, delta=1)

    def test_single_bed_without_prev_rejected(self):
        with self.assertRaises(A.AnchorError):
            A.fit_layout({'GardenBed@Garden#r1c2': A.cell_point('R7')}, 'GardenBed@Garden#r1c2', None)

    def test_one_axis_only_uses_prev_pitch(self):
        beds = {'GardenBed@Garden#r1c1': A.cell_point('F8'), 'GardenBed@Garden#r1c2': A.cell_point('L8')}
        with self.assertRaises(A.AnchorError):
            A.fit_layout(beds, 'GardenBed@Garden#r1c1', None)
        lay = A.fit_layout(beds, 'GardenBed@Garden#r1c1', {'pitch': [480, 270]})
        self.assertAlmostEqual(lay['pitch'][0], 480, delta=1)
        self.assertEqual(lay['pitch'][1], 270)

    def test_implausible_pitch_rejected(self):
        b = 'GardenBed@Garden#r%dc%d'
        for name, pts in (('negative x', {(1, 1): (400, 200), (1, 2): (200, 200), (2, 1): (400, 450), (2, 2): (200, 450)}),
                          ('negative y', {(1, 1): (200, 450), (1, 2): (600, 450), (2, 1): (200, 200), (2, 2): (600, 200)}),
                          ('tiny x', {(1, 1): (200, 200), (1, 2): (220, 200), (2, 1): (200, 450), (2, 2): (220, 450)}),
                          ('tiny y', {(1, 1): (200, 200), (1, 2): (600, 200), (2, 1): (200, 220), (2, 2): (600, 220)})):
            with self.subTest(name), self.assertRaises(A.AnchorError) as cm:
                A.fit_layout({b % rc: p for rc, p in pts.items()}, b % (1, 1), None)
            self.assertIn('plausible', str(cm.exception))

    def test_inconsistent_beds_rejected(self):
        beds = {}
        for r in (1, 2, 3):
            for c in (1, 2, 3):
                beds[f'GardenBed@Garden#r{r}c{c}'] = (200 + 400 * (c - 1), 150 + 250 * (r - 1))
        A.fit_layout(beds, 'GardenBed@Garden#r1c1', None)   # consistent: fine
        beds['GardenBed@Garden#r2c2'] = (200 + 400 * 2, 150 + 250 * 2)   # one bed a full pitch off in both axes
        with self.assertRaises(A.AnchorError) as cm:
            A.fit_layout(beds, 'GardenBed@Garden#r1c1', None)
        self.assertIn('r1c2@L8', str(cm.exception))

    def test_apply_sets_layout_and_ref(self):
        a = A.parse(SPEC, self.g)
        A.apply(self.g, a, 'D3 10:00')
        self.assertEqual(self.g.state_value('Tara', 'at'), 'GardenBed@Garden#r1c2')
        lay = self.g.node(GB).extra['layout']
        self.assertAlmostEqual(lay['pitch'][0], 480, delta=40)
        self.assertEqual(self.g.node('GardenBed@Garden#r2c1').state['phase']['value'], 'wilted')
        self.assertEqual(self.g.node('GardenBed@Garden#r2c1').state['crop']['value'], 'Tulip')
        self.assertIsNone(self.g.phase('GardenBed@Garden#r3c1'))

    def test_inconsistent_answer_changes_nothing(self):
        bad = SPEC.replace('r2c2@L12', 'r2c2@X12')
        a = A.parse(bad, self.g)
        with self.assertRaises(A.AnchorError):
            A.apply(self.g, a, 'D3')
        self.assertIsNone(self.g.state_value('Tara', 'at'))
        self.assertNotIn('layout', self.g.node(GB).extra)

    def test_layout_survives_save_load(self):
        A.apply(self.g, A.parse(SPEC, self.g), 'D3')
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'g.json')
            self.g.save(p)
            g2 = G.Graph()
            g2.load(p)
        self.assertEqual(g2.node(GB).extra['layout'], self.g.node(GB).extra['layout'])

    def test_question_marks_centre_and_stores_pending(self):
        import json
        from PIL import Image
        seen = {}

        class W:
            @staticmethod
            def ask_vision(kind, q, img, **ctx):
                seen['q'], seen['img'] = q, img
                return 'NEED_VISION anchor'

        class Core:
            WF = W
        img = Image.new('RGB', (1920, 1080), (0, 0, 0))
        self.addCleanup(setattr, A, 'PENDING', A.PENDING)
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'p.json')
            prompt = A.question(img, 'water', self.g, 'x', core=Core)
            pend = json.load(open(A.PENDING))
            gp = os.path.join(d, 'g.json')
            self.complete()
            msg = A.answer(SPEC, graph=self.g, gpath=gp, save_counts={'wilted': 2})
        self.assertEqual(prompt, 'NEED_VISION anchor')
        self.assertEqual(pend['task'], 'water')
        self.assertIn('nearest the magenta marker', seen['q'])
        self.assertEqual(seen['img'].size, (1920, 1080))
        self.assertEqual(seen['img'].getpixel((960, 540 - 26)), (255, 0, 255))
        self.assertEqual(img.getpixel((960, 540 - 26)), (0, 0, 0))   # drawn on a copy
        self.assertIn('anchored Tara at GardenBed@Garden#r1c2', msg)

    def complete(self):
        """Every bed group has members/pattern and every phase is known (the farm-wide count check is meaningful)."""
        far = 'GardenBed@FarGarden'
        self.g.nodes[far].extra['pattern'] = {'rows': 1, 'cols': 1}
        self.g.nodes[far + '#r1c1'] = G.Node(far + '#r1c1', 'member', kind='GardenBed', region=far)
        for m in self.g.members(far) + self.g.members(GB):
            if self.g.phase(m.id) is None:
                self.g.set_state(m.id, 'phase', 'empty', 'D1', 'vision')

    def test_count_mismatch(self):
        for i in (1, 2, 3):
            self.g.set_state(f'GardenBed@Garden#r1c{i}', 'phase', 'wilted', 'D1', 'vision')
        self.assertEqual(A.count_mismatch(self.g, GB, {'wilted': 4}), {'wilted': (3, 4)})
        self.assertEqual(A.count_mismatch(self.g, GB, {'wilted': 3}), {})

    def test_answer_stamps_pending_game_time_and_new_day_keeps_it(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'anchor-pending.json')
            json.dump({
                       'game_time': 'D183 1:30:00 PM'}, open(A.PENDING, 'w'))
            A.answer(f'group: {GB}   ref: r1c2@L8   r1c1@F8 growing watered   r1c2@L8 empty   r2c1@F12 empty', graph=self.g, gpath=os.path.join(d, 'g.json'))
            s = self.g.node('GardenBed@Garden#r1c1').state['watered_today']
            self.assertEqual(s['game_time'], 'D183 1:30:00 PM')
            self.g.new_day(183)
            self.assertIs(self.g.state_value('GardenBed@Garden#r1c1', 'watered_today'), True)
            self.g.new_day(184)
            self.assertIs(self.g.state_value('GardenBed@Garden#r1c1', 'watered_today'), False)

    def test_clock_fallback(self):
        class Core:
            class WF:
                @staticmethod
                def game_stamp():
                    raise OSError
        self.assertEqual(A._clock(Core), 'vision')

    def test_farm_wide_count_mismatch_sums_groups(self):
        far_id = 'GardenBed@FarGarden#1'
        self.g.nodes[far_id] = G.Node(far_id, 'member', kind='GardenBed', region='GardenBed@FarGarden')
        self.assertIn(far_id, [m.id for m in self.g.members('GardenBed@FarGarden')])
        self.g.set_state('GardenBed@Garden#r1c1', 'phase', 'wilted', 'D1', 'vision')
        self.g.set_state(far_id, 'phase', 'wilted', 'D1', 'vision')
        self.g.set_state('GardenBed@Garden#r1c2', 'phase', 'growing', 'D1', 'vision')
        self.g.set_state('GardenBed@Garden#r1c2', 'watered_today', False, 'D1', 'vision')
        self.assertEqual(A.count_mismatch(self.g, None, {'wilted': 2, 'dry': 1, 'ripe': 0}), {})
        self.assertEqual(A.count_mismatch(self.g, None, {'wilted': 3}), {'wilted': (2, 3)})   # far member is in the sum

    def test_save_bed_counts_all_four_states(self):
        import wf
        crops = [{'plantState': '##0'}, {'plantState': ''},
                 {'plantState': '##produced', 'isWilted': 'false'},
                 {'plantState': '##produced', 'isWilted': 'true'},
                 {'plantState': '##growing', 'isWatered': 'false', 'isWilted': 'false'},
                 {'plantState': '##producing', 'isWatered': 'false'},
                 {'plantState': '##growing', 'isWatered': 'true'},
                 {'plantState': '##growing', 'isWatered': 'false', 'isWilted': 'true'}]
        self.assertEqual(wf.save_bed_counts(crops), {'wilted': 2, 'ripe': 1, 'empty': 2, 'dry': 2})

    def test_unknown_watered_counts_as_dry(self):
        self.g.set_state('GardenBed@Garden#r1c2', 'phase', 'growing', 'D1', 'vision')   # watered_today never set
        self.g.set_state('GardenBed@Garden#r1c3', 'phase', 'growing', 'D1', 'vision')
        self.g.set_state('GardenBed@Garden#r1c3', 'watered_today', True, 'D1', 'vision')
        self.assertEqual(A.count_mismatch(self.g, 'GardenBed@Garden', {'dry': 1}), {})
        self.assertEqual(A.count_mismatch(self.g, 'GardenBed@Garden', {'dry': 2}), {'dry': (1, 2)})

    def test_answer_consumes_pending_and_second_is_rejected(self):
        import json
        self.addCleanup(setattr, A, 'PENDING', A.PENDING)
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'anchor-pending.json')
            json.dump({'game_time': 'D1 1:00:00 PM'},
                      open(A.PENDING, 'w'))
            A.answer(f'group: {GB}   ref: r1c2@L8   r1c1@F8 growing   r1c2@L8 empty   r2c1@F12 empty   r2c2@L12 empty', graph=self.g, gpath=os.path.join(d, 'g.json'))
            with self.assertRaises(A.AnchorError):
                A.answer(f'group: {GB}   ref: r1c2@L8   r1c1@F8 growing   r1c2@L8 empty   r2c1@F12 empty   r2c2@L12 empty', graph=self.g, gpath=os.path.join(d, 'g.json'))

    def test_clear_pending_makes_stale_answer_rejected(self):
        import json
        self.addCleanup(setattr, A, 'PENDING', A.PENDING)
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'anchor-pending.json')
            json.dump({'game_time': 'x'}, open(A.PENDING, 'w'))
            A.clear_pending()
            with self.assertRaises(A.AnchorError):
                A.answer(ANS4, graph=self.g, gpath=os.path.join(d, 'g.json'))

    def test_clock_uses_today_log_day_when_stamp_missing(self):
        class Core:
            class WF:
                @staticmethod
                def game_stamp():
                    return None

                @staticmethod
                def today_log():
                    return [], '183'
        self.assertEqual(A._clock(Core), 'D183')

    def test_incomplete_graph_reasons(self):
        self.assertIsNotNone(A.incomplete(self.g))
        self.complete()
        self.assertIsNone(A.incomplete(self.g))
        self.g.set_state('GardenBed@Garden#r1c1', 'phase', None, 'D1', 'event', 0.0)
        self.assertIn('unknown phase', A.incomplete(self.g))

    def test_answer_skips_count_check_when_graph_incomplete(self):
        self.addCleanup(setattr, A, 'PENDING', A.PENDING)
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'p.json')
            import json
            json.dump({'game_time': 'D1'}, open(A.PENDING, 'w'))
            msg = A.answer(f'group: {GB}   ref: r1c2@L8   r1c1@F8 ripe   r1c2@L8 ripe   r2c1@F12 ripe   r2c2@L12 ripe', graph=self.g, gpath=os.path.join(d, 'g.json'), save_counts={'wilted': 9})
        self.assertIn('count check skipped (graph incomplete)', msg)
        self.assertNotIn('MISMATCH', msg)


class RealAskVision(unittest.TestCase):
    """The real wf.ask_vision / game_cmd (SHOT paths redirected to a temp dir)."""

    def test_real_ask_vision_anchor_grid(self):
        import json
        from unittest import mock
        from PIL import Image
        import wf
        img = Image.new('RGB', (1920, 1080), (10, 20, 30))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(wf, 'ASK_FRAME', os.path.join(d, 'f.png')), \
                mock.patch.object(wf, 'ASK_IMG', os.path.join(d, 'a.jpg')), mock.patch.object(wf, 'ASK_CTX', os.path.join(d, 'c.json')), \
                mock.patch.object(wf, 'run_log'):
            out = wf.ask_vision('anchor', 'Task: water. Unexpected: x', img)
            fr = Image.open(os.path.join(d, 'f.png'))
            self.assertEqual(fr.size, (1920, 1080))
            self.assertNotEqual(fr.getpixel((80, 500)), (10, 20, 30))   # a grid line between columns A and B
            self.assertEqual(fr.getpixel((40, 500)), (10, 20, 30))      # cell interior untouched
            lab = [fr.getpixel((x, y)) for x in range(83, 120) for y in range(2, 20)]   # cell label "B1"
            self.assertTrue(any(p != (10, 20, 30) for p in lab))
            self.assertFalse(os.path.exists(os.path.join(d, 'a.jpg')))
            self.assertEqual(json.load(open(os.path.join(d, 'c.json')))['kind'], 'anchor')
        self.assertIn('./wf anchor "group: GardenBed@Garden', out)
        self.assertIn('ref: r1c2@L8', out)
        self.assertIn('r2c1@F12 wilted(Tulip)', out)
        self.assertNotIn('teach', out)
        self.assertIn(os.path.join(d, 'f.png'), out)

    def test_other_kinds_keep_the_grid(self):
        from unittest import mock
        from PIL import Image
        import wf
        with tempfile.TemporaryDirectory() as d, mock.patch.object(wf, 'ASK_FRAME', os.path.join(d, 'f.png')), \
                mock.patch.object(wf, 'ASK_IMG', os.path.join(d, 'a.jpg')), mock.patch.object(wf, 'ASK_CTX', os.path.join(d, 'c.json')), \
                mock.patch.object(wf, 'run_log'):
            out = wf.ask_vision('road', 'q', Image.new('RGB', (1920, 1080)))
            self.assertEqual(Image.open(os.path.join(d, 'a.jpg')).size, (768, 432))
        self.assertIn('./wf teach road', out)

    def test_py_prints_just_the_prompt_of_a_need_vision(self):
        import io
        import contextlib
        from unittest import mock
        import game
        import wf
        from objects.loop import NeedVision

        def boom():
            raise NeedVision('NEED_VISION anchor: what is here?')
        buf = io.StringIO()
        with mock.patch.object(game, 'namespace', return_value={'boom': boom}), contextlib.redirect_stdout(buf):
            rc = wf.game_cmd('py', ['boom()'])
        self.assertEqual(rc, 2)
        self.assertIn('NEED_VISION anchor: what is here?', buf.getvalue())
        self.assertNotIn('Traceback', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
