"""Offline tests for game.affordances (bubbles as actions): `scan()` lists every visible bubble from the frame only
(kind, point, highlight, water-drop sub-icon; no positions); `no_click_zones` / `in_reach` build on it.
Run: .venv/bin/python tools/test_affordances.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game  # noqa: E402
from game import affordances as aff  # noqa: E402


class Fake:
    """Bubbles given as (point, kind, highlighted)."""

    def __init__(self, shown):
        self.bubbles = list(shown)
        self.clicks = []

    def grab(self):
        return 'img'

    def find_bubbles(self, img):
        return [b for b, _, _ in self.bubbles]

    def bubble_kind(self, img, b):
        return next(k for p, k, _ in self.bubbles if p == b), 0.1

    def bubble_highlighted(self, img, b):
        return next(h for p, _, h in self.bubbles if p == b)

    def run_action(self, spec):
        self.clicks.append(spec)

    def log_mark(self):
        return len(self.clicks)

    def wait_settle(self):
        pass


class Affordances(unittest.TestCase):
    def test_scan_lists_kind_point_highlight_and_no_owner(self):
        game.bind(Fake([((500, 300), 'water', True), ((700, 320), 'fill_can', False)]))
        got = aff.scan()
        self.assertEqual([(a.kind, a.pt, a.highlighted, a.entity, a.drop) for a in got],
                         [('water', (500, 300), True, None, False), ('fill_can', (700, 320), False, None, False)])

    def test_scan_without_bubble_finder_is_empty(self):
        game.bind(object())
        self.assertEqual(aff.scan(), [])

    def test_click_clicks_the_point_and_returns_the_mark(self):
        f = Fake([((500, 300), 'water', True)])
        game.bind(f)
        self.assertEqual(aff.click(aff.scan()[0]), 0)
        self.assertEqual(f.clicks, ['click:500:300'])

    def test_bubble_points_to_avoid_when_walking(self):
        game.bind(Fake([((500, 300), 'plant', True), ((700, 320), 'fill_can', False)]))
        self.assertEqual(aff.no_click_zones(), [(500, 300), (700, 320)])

    def test_unique_kind_means_its_object_is_in_reach(self):   # zoom-walk-2: at the well, can bubble up
        game.bind(Fake([((500, 300), 'fill_can', True)]))
        self.assertTrue(aff.in_reach('Well'))
        self.assertFalse(aff.in_reach('Bed'))


if __name__ == '__main__':
    unittest.main()


class BubbleTruth(unittest.TestCase):
    """Real bubbles whose click result proved the truth (tools/fixtures/bubble_truth, user D188: "icons that should
    and should not fire"). Every stored case must read as the game proved it."""

    def test_every_proven_bubble_reads_as_the_game_said(self):
        import json
        from PIL import Image
        from game import affordances as AF
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'bubble_truth')
        cases = json.load(open(os.path.join(root, 'labels.json')))['cases']
        self.assertTrue(cases)
        wrong = []
        for c in cases:
            crop = Image.open(os.path.join(root, c['file'])).convert('RGB')
            got = {'ready': AF.has_ready(crop), 'drop': AF.has_drop(crop)}
            for k in ('ready', 'drop'):
                if k in c and got[k] != c[k]:
                    wrong.append(f"{c['file']}: {k} read {got[k]}, the game proved {c[k]} ({c.get('proof')})")
        self.assertEqual(wrong, [])
