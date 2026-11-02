"""Offline tests for tools/objects/anchor.py. Run: .venv/bin/python tools/test_anchor.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ['x']   # wf parses argv on import
from objects import anchor as A, graph as G  # noqa: E402
from objects.detect import Detection  # noqa: E402

GB = 'GardenBed@Garden'
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')
SPEC = (f'group: {GB}   at: B=r2c1\n'
        'A=r1c1 empty   B=r2c1 wilted(Green Bean)   C=r2c2 growing dry   D=r2c3 ripe   E=?')
LABELS = set('ABCDE')


class AnchorTest(unittest.TestCase):
    def setUp(self):
        self.g = G.Graph()
        self.g.load(SEED)

    def test_parse_spec_example(self):
        a = A.parse(SPEC, LABELS, self.g)
        self.assertEqual(a.at, ('B', 'GardenBed@Garden#r2c1'))
        self.assertEqual(a.states['B']['phase'], 'wilted')
        self.assertEqual(a.states['B']['crop'], 'Green Bean')
        self.assertIs(a.states['C']['watered_today'], False)
        self.assertEqual(a.states['D']['member'], 'GardenBed@Garden#r2c3')
        self.assertIsNone(a.states['E']['phase'])

    def test_rejects_unknown_label(self):
        with self.assertRaises(A.AnchorError) as cm:
            A.parse(SPEC.replace('E=?', 'Z=?'), LABELS, self.g)
        self.assertIn('at: <L>=r<R>c<C>', str(cm.exception))

    def test_rejects_cell_outside_pattern(self):
        with self.assertRaises(A.AnchorError):
            A.parse(f'group: {GB}   at: B=r4c1   B=r4c1 empty', LABELS, self.g)

    def test_rejects_unknown_state_and_group(self):
        with self.assertRaises(A.AnchorError):
            A.parse(f'group: {GB}   at: B=r2c1   A=r1c1 soggy', LABELS, self.g)
        with self.assertRaises(A.AnchorError):
            A.parse('group: Nope   at: B=r2c1', LABELS, self.g)

    def test_apply_sets_tara_and_states(self):
        a = A.parse(SPEC, LABELS, self.g)
        A.apply(self.g, a, {}, 'D3 10:00')
        self.assertEqual(self.g.state_value('Tara', 'at'), 'GardenBed@Garden#r2c1')
        s = self.g.node('GardenBed@Garden#r2c1').state['phase']
        self.assertEqual((s['value'], s['source'], s['conf']), ('wilted', 'vision', 1.0))
        self.assertIs(self.g.state_value('GardenBed@Garden#r2c2', 'watered_today'), False)

    def complete(self):
        """Every bed group has members/pattern and every phase is known (the farm-wide count check is meaningful)."""
        far = 'GardenBed@FarGarden'
        self.g.nodes[far].extra['pattern'] = {'rows': 1, 'cols': 1}
        self.g.nodes[far + '#r1c1'] = G.Node(far + '#r1c1', 'member', kind='GardenBed', region=far)
        for m in self.g.members(far) + self.g.members(GB):
            if self.g.phase(m.id) is None:
                self.g.set_state(m.id, 'phase', 'empty', 'D1', 'vision')

    def test_unnamed_labels_follow_pattern(self):
        # 2x3 grid of tiles, only B (row 1, col 0) named r2c1
        dets = {}
        for i, l in enumerate('ABCDEF'):
            r, c = divmod(i, 3)
            dets[l] = Detection('GardenBed', (0, 0, 1, 1), 1.0, None, (960 + 100 * c - 0, 440 + 100 * r))
        a = A.Anchor(GB, ('D', 'GardenBed@Garden#r2c1'), {'D': {'member': 'GardenBed@Garden#r2c1', 'phase': 'ripe',
                                                              'crop': None, 'watered_today': None}})
        A.apply(self.g, a, dets, 'D1')
        self.assertEqual(self.g.state_value('Tara', 'at'), 'GardenBed@Garden#r2c1')
        # unnamed labels: ids mapped relative to D; states stay unset (no state words), but mapping must not raise
        a.states.update({'B': {'member': None, 'phase': 'empty', 'crop': None, 'watered_today': None},
                         'F': {'member': None, 'phase': 'growing', 'crop': None, 'watered_today': None}})
        A.apply(self.g, a, dets, 'D1')
        self.assertEqual(self.g.phase('GardenBed@Garden#r1c2'), 'empty')    # B is one row up, one col right of D
        self.assertEqual(self.g.phase('GardenBed@Garden#r2c3'), 'growing')  # F is two cols right of D
        self.assertEqual(self.g.phase('GardenBed@Garden#r2c1'), 'ripe')

    def test_count_mismatch(self):
        for i in (1, 2, 3):
            self.g.set_state(f'GardenBed@Garden#r1c{i}', 'phase', 'wilted', 'D1', 'vision')
        self.assertEqual(A.count_mismatch(self.g, GB, {'wilted': 4}), {'wilted': (3, 4)})
        self.assertEqual(A.count_mismatch(self.g, GB, {'wilted': 3}), {})

    def test_question_and_answer_roundtrip(self):
        from PIL import Image
        asked = {}

        class W:
            @staticmethod
            def ask_vision(kind, q, img, **ctx):
                asked.update(kind=kind, q=q, size=img.size)
                return 'NEED_VISION anchor'

        class Core:
            WF = W
        dets = [Detection('GardenBed', (0, 0, 1, 1), 1.0, None, (300, 100)),
                Detection('GardenBed', (0, 0, 1, 1), 1.0, None, (100, 100))]
        img = Image.new('RGB', (400, 300), (255, 255, 255))
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'anchor-pending.json')
            prompt, labels = A.question(img, dets, 'water', self.g, 'bubble missing', core=Core)
            self.assertEqual(asked['kind'], 'anchor')
            self.assertEqual(labels['A'].point, (100, 100))   # left -> right
            self.assertEqual(img.getpixel((100, 100)), (255, 255, 255))   # labels drawn on a copy
            gp = os.path.join(d, 'g.json')
            self.complete()
            msg = A.answer(f'group: {GB}   at: A=r1c1   A=r1c1 ripe', graph=self.g, gpath=gp, save_counts={'wilted': 2})
            self.assertIn('anchored Tara at GardenBed@Garden#r1c1', msg)
            self.assertIn('wilted=(0, 2)', msg)
            self.assertEqual(self.g.phase('GardenBed@Garden#r1c1'), 'ripe')

    def test_answer_stamps_pending_game_time_and_new_day_keeps_it(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'anchor-pending.json')
            json.dump({'labels': {'A': {'point': [1, 1], 'box': [0, 0, 1, 1], 'kind': 'GardenBed'}},
                       'game_time': 'D183 1:30:00 PM'}, open(A.PENDING, 'w'))
            A.answer(f'group: {GB}   at: A=r1c1   A=r1c1 growing watered', graph=self.g, gpath=os.path.join(d, 'g.json'))
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
            json.dump({'labels': {'A': {'point': [1, 1], 'box': [0, 0, 1, 1], 'kind': 'GardenBed'}}, 'game_time': 'D1 1:00:00 PM'},
                      open(A.PENDING, 'w'))
            A.answer(f'group: {GB}   at: A=r1c1   A=r1c1 growing', graph=self.g, gpath=os.path.join(d, 'g.json'))
            with self.assertRaises(A.AnchorError):
                A.answer(f'group: {GB}   at: A=r1c1   A=r1c1 growing', graph=self.g, gpath=os.path.join(d, 'g.json'))

    def test_clear_pending_makes_stale_answer_rejected(self):
        import json
        self.addCleanup(setattr, A, 'PENDING', A.PENDING)
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'anchor-pending.json')
            json.dump({'labels': {}, 'game_time': 'x'}, open(A.PENDING, 'w'))
            A.clear_pending()
            with self.assertRaises(A.AnchorError):
                A.answer(f'group: {GB}   at: A=r1c1', graph=self.g, gpath=os.path.join(d, 'g.json'))

    def test_grid_one_jittered_row_stays_one_row(self):
        dets = {l: Detection('GardenBed', (0, 0, 80, 60), 1.0, None, (100 + 200 * i, 300 + j))
                for i, (l, j) in enumerate(zip('ABCD', (-3, 3, 0, 2)))}
        grid = A._grid(dets)
        self.assertEqual({r for r, _ in grid.values()}, {0})
        self.assertEqual(sorted(c for _, c in grid.values()), [0, 1, 2, 3])

    def test_tara_at_is_the_member_nearest_the_centre_whatever_was_named(self):
        dets = {}
        for i, l in enumerate('ABCDEF'):
            r, c = divmod(i, 3)
            dets[l] = Detection('GardenBed', (0, 0, 80, 60), 1.0, None, (760 + 200 * c, 480 + 120 * r))
        # centre (960,540) is nearest B (960,480). The answer names A (r2c1) as `at`: B is then r2c2.
        a = A.Anchor(GB, ('A', 'GardenBed@Garden#r2c1'), {})
        A.apply(self.g, a, dets, 'D1')
        self.assertEqual(self.g.state_value('Tara', 'at'), 'GardenBed@Garden#r2c2')

    def test_question_marks_centre_with_large_labels(self):
        from PIL import Image
        seen = {}

        class W:
            @staticmethod
            def ask_vision(kind, q, img, **ctx):
                seen['q'], seen['img'] = q, img
                return 'x'

        class Core:
            WF = W
        img = Image.new('RGB', (1920, 1080), (0, 0, 0))
        with tempfile.TemporaryDirectory() as d:
            A.PENDING = os.path.join(d, 'p.json')
            A.question(img, [Detection('GardenBed', (0, 0, 80, 60), 1.0, None, (400, 300))], 'water', self.g, 'x', core=Core)
        self.assertIn('nearest this marker', seen['q'])
        self.assertEqual(seen['img'].getpixel((960, 540 - 26)), (255, 0, 255))      # marker ring at the CENTRE
        yellow = sum(1 for x in range(360, 440) for y in range(270, 330) if seen['img'].getpixel((x, y)) == (255, 255, 0))
        self.assertGreater(yellow, 150)   # a big letter, not a speck

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
            json.dump({'labels': {'A': {'point': [960, 540], 'box': [0, 0, 1, 1], 'kind': 'GardenBed'}}, 'game_time': 'D1'}, open(A.PENDING, 'w'))
            msg = A.answer(f'group: {GB}   at: A=r1c1   A=r1c1 ripe', graph=self.g, gpath=os.path.join(d, 'g.json'), save_counts={'wilted': 9})
        self.assertIn('count check skipped (graph incomplete)', msg)
        self.assertNotIn('MISMATCH', msg)


class RealAskVision(unittest.TestCase):
    """The real wf.ask_vision / game_cmd (SHOT paths redirected to a temp dir)."""

    def test_anchor_kind_is_full_size_ungridded_with_the_anchor_answer_format(self):
        import json
        from unittest import mock
        from PIL import Image
        import wf
        img = Image.new('RGB', (1920, 1080), (10, 20, 30))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(wf, 'ASK_FRAME', os.path.join(d, 'f.png')), \
                mock.patch.object(wf, 'ASK_IMG', os.path.join(d, 'a.jpg')), mock.patch.object(wf, 'ASK_CTX', os.path.join(d, 'c.json')), \
                mock.patch.object(wf, 'run_log'):
            out = wf.ask_vision('anchor', 'Task: water. Unexpected: x', img)
            self.assertEqual(Image.open(os.path.join(d, 'f.png')).size, (1920, 1080))
            self.assertEqual(Image.open(os.path.join(d, 'f.png')).getpixel((100, 100)), (10, 20, 30))   # no grid drawn
            self.assertFalse(os.path.exists(os.path.join(d, 'a.jpg')))
            self.assertEqual(json.load(open(os.path.join(d, 'c.json')))['kind'], 'anchor')
        self.assertIn('./wf anchor "group: GardenBed@Garden', out)
        self.assertIn('B=r2c1 wilted(Green Bean)', out)
        self.assertNotIn('teach', out)
        self.assertIn(os.path.join(d, 'f.png'), out)
        self.assertNotIn('grid A-L', out)

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
