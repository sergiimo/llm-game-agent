"""Offline tests for game.affordances (bubbles as actions, M3/M4): every visible bubble is matched to its entity and
kind; a skill clicks the bubble relevant to its goal (a click works on any bubble; the highlight only marks Space).
Run: .venv/bin/python tools/test_affordances.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nav  # noqa: E402

nav.OBJECTS = os.path.join(tempfile.mkdtemp(), 'none.json')
import game  # noqa: E402
from game import affordances as aff  # noqa: E402
from world import model, view  # noqa: E402

H_FARM = [[8.659732, -0.005814, -0.001597], [0.074748, -21.414692, 5.617554], [-0.005491, 0.509604, 1.0]]


class Fake:
    """Bubbles drawn BUBBLE_UP px above each listed entity's ground point."""

    def __init__(self, tara, shown):
        from evals import store
        store.PATH = os.path.join(tempfile.mkdtemp(), 'p.jsonl')
        self.w = model.World(facts=[], cache=os.devnull)
        self.w.belief.scene('Farm', *tara)
        self.ents = {}
        for name, kind, x, z in (('well', 'Well', -1.09, -21.05), ('bed7', 'GardenBed', 3.34, -29.09),
                                 ('bed8', 'GardenBed', 5.84, -29.09)):
            self.ents[name] = self.w.ents.add(kind, 'Farm', x, z, 'test')
        self.bubbles = []
        for name, kind, hl in shown:
            e = self.ents[name]
            sx, sy = view._scr(H_FARM, self.w.belief, e.x, e.z)
            self.bubbles.append(((int(sx), int(sy) - 120), kind, hl))
        self.clicks = []

    def world(self):
        return self.w

    def world_sync(self):
        pass

    def calib_load(self, area):
        return {'H': H_FARM}

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

    def wait_settle(self):
        pass

    def run_log(self, *a, **k):
        pass

    def state(self):
        return {'mode': 'gameplay', 'text': []}


class Affordances(unittest.TestCase):
    def test_scan_matches_bubbles_to_entities(self):
        f = Fake((3.34, -27.34), [('bed7', 'water', True), ('bed8', 'water', False), ('well', 'fill_can', False)])
        game.bind(f)
        got = {(a.kind, a.entity.kind if a.entity else None, round(a.entity.x, 2) if a.entity else None)
               for a in aff.scan()}
        self.assertEqual(got, {('water', 'GardenBed', 3.34), ('water', 'GardenBed', 5.84), ('fill_can', 'Well', -1.09)})

    def test_use_clicks_the_relevant_bubble_not_the_highlighted_one(self):
        f = Fake((3.34, -27.34), [('bed7', 'water', True), ('bed8', 'water', False)])
        game.bind(f)
        self.assertTrue(aff.use('water', f.ents['bed8']))
        b8 = next(b for b, _, _ in f.bubbles if not _ is None and b == f.bubbles[1][0])
        self.assertEqual(f.clicks, [f'click:{b8[0]}:{b8[1]}'])

    def test_use_the_well_bubble_already_shown(self):   # the case that blocked M3: no walking needed
        f = Fake((3.34, -27.34), [('well', 'fill_can', False)])
        game.bind(f)
        self.assertTrue(aff.use('fill_can', f.ents['well']))
        self.assertEqual(len(f.clicks), 1)

    def test_no_relevant_bubble(self):
        f = Fake((3.34, -27.34), [('bed7', 'plant', True)])
        game.bind(f)
        self.assertFalse(aff.use('water', f.ents['bed8']))
        self.assertEqual(f.clicks, [])

    def test_bubble_points_to_avoid_when_walking(self):
        f = Fake((3.34, -27.34), [('bed7', 'plant', True), ('well', 'fill_can', False)])
        game.bind(f)
        self.assertEqual(len(aff.no_click_zones()), 2)

    def test_unique_kind_means_its_object_is_in_reach(self):   # zoom-walk-2: at the well, can bubble up, belief off
        f = Fake((-7.0, -30.0), [('well', 'fill_can', True)])      # belief 9 units off: geometry can't match
        game.bind(f)
        self.assertTrue(aff.in_reach('Well'))
        self.assertFalse(aff.in_reach('Bed'))
        self.assertTrue(aff.use('fill_can'))                     # no target needed: only the well offers it
        self.assertEqual(len(f.clicks), 1)

    def test_unknown_bubble_is_not_used_without_a_target(self):   # day-walk rev 3: hive's honey bubble = "unknown"
        f = Fake((4.16, -22.51), [('bed7', 'unknown', True)])
        game.bind(f)
        self.assertFalse(aff.use('fill_can'))
        self.assertEqual(f.clicks, [])


if __name__ == '__main__':
    unittest.main()
