"""Offline tests for tools/objects/anchor.py. Run: .venv/bin/python tools/test_anchor.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

    def test_unnamed_labels_follow_pattern(self):
        # 2x3 grid of tiles, only B (row 1, col 0) named r2c1
        dets = {}
        for i, l in enumerate('ABCDEF'):
            r, c = divmod(i, 3)
            dets[l] = Detection('GardenBed', (0, 0, 1, 1), 1.0, None, (100 + 100 * c, 100 + 100 * r))
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
            msg = A.answer(f'group: {GB}   at: A=r1c1   A=r1c1 ripe', graph=self.g, gpath=gp, save_counts={'wilted': 2})
            self.assertIn('anchored Tara at GardenBed@Garden#r1c1', msg)
            self.assertIn('wilted=(0, 2)', msg)
            self.assertEqual(self.g.phase('GardenBed@Garden#r1c1'), 'ripe')


if __name__ == '__main__':
    unittest.main()
