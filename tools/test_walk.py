"""Offline tests for game.walk (M3): walking through the world model against a simulated farm where clicks move a
"true" Tara the way the game does. Run: .venv/bin/python tools/test_walk.py"""
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nav  # noqa: E402

nav.OBJECTS = os.path.join(tempfile.mkdtemp(), 'none.json')
import game  # noqa: E402
from game import core, walk  # noqa: E402
from world import model  # noqa: E402

H_FARM = [[8.659732, -0.005814, -0.001597], [0.074748, -21.414692, 5.617554], [-0.005491, 0.509604, 1.0]]
HIVES = [-2.28 + 1.25 * i for i in range(8)]


class Sim:
    """The parts of wf that walk uses; the truth moves to the clicked ground point unless it is inside a solid."""

    def __init__(self, truth, belief=None, menu=False):
        from evals import store
        store.PATH = os.path.join(tempfile.mkdtemp(), 'p.jsonl')
        self.w = model.World(facts=[], cache=os.devnull)
        self.w.scene = 'Farm'
        for x in HIVES:
            self.w.ents.add('BeeHive', 'Farm', x, -23.46, 'test')
        self.truth, self.clicks, self.readings, self.menu = list(truth), [], 0, menu
        self.w.belief.scene('Farm')
        if belief:
            self.w.belief._set(belief[0], belief[1], 0.2)

    def world(self):
        return self.w

    def world_sync(self):
        pass

    def calib_load(self, area):
        return {'H': H_FARM}

    def checkpoint(self, *a, **k):
        self.readings += 1
        self.w.reading('Farm', *self.truth)
        return {'scene': 'Farm', 'x': self.truth[0], 'z': self.truth[1]}, {}

    def go_to(self, sx, sy):
        if self.menu:
            return 'MENU OPEN (overlay: Game Paused): close it first'
        self.clicks.append((sx, sy))
        dx, dz = nav.screen_to_ground(H_FARM, sx, sy)
        _, bx, bz, _ = self.w.tara()
        gx, gz = self.truth[0] + dx, self.truth[1] + dz      # the game measures from where she really is
        if any(math.dist((gx, gz), (h, -23.46)) < 0.6 for h in HIVES):
            return 'NO MOVE (clicked a hive)'
        self.truth = [gx, gz]
        self.w.clicked(dx, dz)
        return None

    def run_log(self, *a, **k):
        pass

    def state(self):
        return {'mode': 'gameplay', 'text': []}

    def goto_point(self, *a, **k):
        raise AssertionError('walk should not fall back here in these tests')


class Target:
    def __init__(self, x, z):
        self.x, self.z, self.scene = x, z, 'Farm'

    def __str__(self):
        return f'target ({self.x}, {self.z})'


class Walk(unittest.TestCase):
    def setUp(self):
        game.track.LINES.clear()

    def test_in_reach_no_click(self):
        s = Sim((0.0, -30.0), belief=(0.0, -30.0))
        game.bind(s)
        self.assertTrue(walk.walk(Target(1.0, -30.0)).startswith('ARRIVED'))
        self.assertEqual((s.clicks, s.readings), ([], 0))

    def test_on_screen_one_click(self):
        s = Sim((0.0, -30.0), belief=(0.0, -30.0))
        game.bind(s)
        walk.walk(Target(4.0, -31.0))
        self.assertEqual(len(s.clicks), 1)
        self.assertLess(math.dist(s.truth, (4.0, -31.0)), walk.REACH)

    def test_domain_target_may_have_scalar_state(self):
        s = Sim((0.0, -30.0), belief=(0.0, -30.0))
        game.bind(s)
        t = Target(4.0, -31.0)
        t.state = 'growing'  # garden.Bed uses this field; it is not an Entity.state mapping
        walk.walk(t)
        self.assertEqual(len(s.clicks), 1)
        self.assertLess(math.dist(s.truth, (4.0, -31.0)), walk.REACH)

    def test_unknown_belief_reads_first(self):
        s = Sim((0.0, -30.0))                               # belief unknown (u 99)
        game.bind(s)
        walk.walk(Target(3.0, -30.0))
        self.assertGreaterEqual(s.readings, 1)
        self.assertEqual(s.readings, 2)    # one to start, one to confirm arrival (SURE 0.3: day-walk wrong "arrived")

    def test_round_the_hive_row(self):
        s = Sim((-1.3, -21.7), belief=(-1.3, -21.7))
        game.bind(s)
        walk.walk(Target(-1.7, -25.3))
        self.assertLess(math.dist(s.truth, (-1.7, -25.3)), walk.REACH)
        self.assertLessEqual(len(s.clicks), 6)

    def test_covered_target_on_screen_walks_the_route(self):   # world-walk: "no clickable point" at bed 7
        s = Sim((3.34, -27.34), belief=(3.34, -27.34))
        game.bind(s)
        try:                                                       # the well, behind the hive row
            walk.walk(Target(-1.09, -21.05))
            self.assertLess(math.dist(s.truth, (-1.09, -21.05)), walk.REACH)
        except game.Failed as e:                                   # the sim's sprite size is a guess (unverified):
            self.assertRegex(str(e), 'no clickable point|no progress')  # then it must ask, never dead-end
            self.assertLess(s.truth[0], -2.9)                      # … after getting round the west end

    def test_no_progress_asks_instead_of_clicking_on(self):  # world-walk: 8 clicks on hives, no alarm
        s = Sim((3.34, -27.34), belief=(3.34, -27.34))
        game.bind(s)
        s.go_to = lambda sx, sy: (s.clicks.append((sx, sy)), 'NO MOVE (clicked a hive sprite)')[1]
        with self.assertRaises(game.Failed) as e:
            walk.walk(Target(-1.09, -21.05))
        self.assertIn('no progress', str(e.exception))
        self.assertLessEqual(len(s.clicks), 3)

    def test_arrived_when_the_targets_bubble_is_up(self):     # zoom-walk-2: walk never saw arrival at the well
        s = Sim((0.0, -30.0), belief=(9.0, -30.0))              # belief 9 units off
        game.bind(s)
        s.find_bubbles = lambda img: [(960, 480)]
        s.bubble_kind = lambda img, b: ('fill_can', 0.1)
        s.bubble_highlighted = lambda img, b: True
        s.grab = lambda: None
        t = Target(-1.09, -21.05)
        t.kind = 'Well'
        self.assertTrue(walk.walk(t).startswith('ARRIVED'))
        self.assertEqual(s.clicks, [])

    def test_unknown_bubble_near_the_target_is_not_arrival(self):   # obj-walk-2: honey bubbles "were" the well
        s = Sim((3.0, -22.5), belief=(3.0, -22.5))
        game.bind(s)
        from game import affordances
        well = s.w.ents.add('Well', 'Farm', -1.09, -21.05, 'test')
        orig = affordances.scan
        affordances.scan = lambda: [affordances.Affordance('unknown', well, (944, 512), True, 0.9)]
        try:
            self.assertFalse(walk._bubble_up(well))
        finally:
            affordances.scan = orig

    def test_menu_open_fails_without_clicking(self):
        s = Sim((0.0, -30.0), belief=(0.0, -30.0), menu=True)
        game.bind(s)
        with self.assertRaises(game.Failed) as e:
            walk.walk(Target(4.0, -31.0))
        self.assertIn('MENU OPEN', str(e.exception))


if __name__ == '__main__':
    unittest.main()
