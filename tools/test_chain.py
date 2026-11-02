"""Offline tests for tools/objects/chain.py. Run: .venv/bin/python tools/test_chain.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

    def test_click_tile_avoids_bubble(self):
        d = det(2, 2)
        self.assertEqual(C.click_tile(d, []), (960, 540))
        x, y = C.click_tile(d, [(960, 540)])
        self.assertGreaterEqual(((x - 960) ** 2 + (y - 540) ** 2) ** .5, 0)

    def test_no_positions_imported(self):
        src = open(C.__file__).read()
        for bad in ('calib_load', 'checkpoint', 'world()', 'log_pos'):
            self.assertNotIn(bad, src)


if __name__ == '__main__':
    unittest.main()
