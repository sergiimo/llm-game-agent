"""Tests for tools/nav.py: python3 -I tools/test_nav.py (needs numpy: use .venv/bin/python)."""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nav  # noqa: E402

# The Farm fit from `wf calib` on D146 (tools/calib.json): a realistic ground homography to generate data with.
TRUE_H = None


def true_h():
    global TRUE_H
    if TRUE_H is None:
        clicks = [(1210, 690), (710, 690), (960, 870), (960, 510), (1160, 840), (760, 540), (760, 840), (1160, 540)]
        d = [(3.77, -0.73), (-3.77, -0.73), (0, -6.43), (0, 7.29), (2.65, -5.59), (-3.52, 5.73), (-2.65, -5.59),
             (3.52, 5.73)]
        TRUE_H = nav.fit_h([nav.norm(*c) for c in clicks], d)
    return TRUE_H


def seg(click, start=(0.0, 0.0), noise=0.0, short=1.0, **kw):
    dx, dz = nav.screen_to_ground(true_h(), *click)
    to = [start[0] + dx * short + random.gauss(0, noise), start[1] + dz * short + random.gauss(0, noise)]
    f = {'scene': 'Farm', 'from': list(start), 'to': to, 'clicks': [list(click)], 'result': 'arrived',
         'day': 146, 'hour': 10.0}
    f.update(kw)
    return f


class Calibration(unittest.TestCase):
    def test_recovers_homography_despite_outliers(self):
        random.seed(1)
        facts = [seg((random.randint(700, 1220), random.randint(480, 900)), noise=0.03) for _ in range(12)]
        facts += [seg((1200, 600), short=0.4), seg((720, 850), short=0.3)]  # walks that stopped short
        fit = nav.fit_robust(nav.calib_samples(facts, 'Farm'))
        self.assertEqual(fit['kept'], 12)
        for c in [(1100, 760), (800, 560), (960, 900)]:
            a, b = nav.screen_to_ground(fit['H'], *c), nav.screen_to_ground(true_h(), *c)
            self.assertLess(abs(a[0] - b[0]) + abs(a[1] - b[1]), 0.15)

    def test_too_few_or_dirty_samples(self):
        facts = [seg((1100, 700)) for _ in range(4)] + [seg((900, 700), dirty=True)]
        self.assertIsNone(nav.fit_robust(nav.calib_samples(facts, 'Farm')))

    def test_round_trip_and_predict(self):
        h = true_h()
        sx, sy = nav.ground_to_screen(h, 2.0, -3.0)
        dx, dz = nav.screen_to_ground(h, sx, sy)
        self.assertAlmostEqual(dx, 2.0, delta=0.05)
        self.assertAlmostEqual(dz, -3.0, delta=0.05)
        x, z = nav.predict(h, (10, 10), [(sx, sy), (sx, sy)])
        self.assertAlmostEqual(x, 14.0, delta=0.1)
        self.assertAlmostEqual(z, 4.0, delta=0.1)


class Views(unittest.TestCase):
    def test_place_median(self):
        facts = [{'scene': 'Farm', 'goal': 'gate', 'result': 'arrived', 'to': [1.0 + i * 0.1, 2.0]} for i in range(3)]
        facts.append({'scene': 'Farm', 'goal': 'gate', 'result': 'short', 'to': [9.0, 9.0]})
        x, z, n, _ = nav.places(facts)['Farm']['gate']
        self.assertEqual((round(x, 2), z, n), (1.1, 2.0, 3))

    def test_block_expires(self):
        facts = [{'scene': 'Farm', 'result': 'no_move', 'target': [3, 4], 'day': 146, 'hour': 10.0}]
        self.assertEqual(nav.blocks(facts, 'Farm', {'day': 146, 'hour': 10.5}), [(3, 4)])
        self.assertEqual(nav.blocks(facts, 'Farm', {'day': 146, 'hour': 11.5}), [])
        self.assertEqual(nav.blocks(facts, 'Town', {'day': 146, 'hour': 10.5}), [])

    def test_edge_status(self):
        e = 'A>B'
        ok = {'edge': e, 'result': 'arrived'}
        fail = {'edge': e, 'result': 'still'}
        now = {'day': 150, 'hour': 12}
        st = lambda fs: nav.edge_status(fs, now)[e]['status']
        self.assertEqual(st([dict(ok, day=d, hour=9) for d in range(140, 146)]), 'ok')
        self.assertEqual(st([dict(ok, day=149, hour=9), dict(fail, day=150, hour=11.5)]), 'blocked-now')
        walls = [dict(ok, day=140, hour=9)] + [dict(fail, day=d, hour=9) for d in (147, 148, 149)]
        self.assertEqual(st(walls), 'suspect-wall')
        self.assertEqual(st(walls + [dict(ok, day=150, hour=11)]), 'flaky')

    def test_pred_error_trend(self):
        facts = [{'scene': 'Farm', 'pred': [0, 0], 'to': [e, 0]} for e in (1.0, 0.8, 0.2, 0.1)]
        self.assertEqual(nav.pred_error(facts)['Farm'], (0.9, 0.15, 4))


class Units(unittest.TestCase):
    def test_map_fit_and_places(self):
        # true map: x = 0.2*mx - 150, z = -0.25*my + 120
        pins = [(700, 480), (600, 470), (780, 660)]
        facts = [{'scene': 'Farm', 'pin': list(p), 'to': [0.2 * p[0] - 150, -0.25 * p[1] + 120]} for p in pins]
        fit = nav.map_fit(facts, 'Farm')
        self.assertLess(fit['err'], 0.01)
        w = nav.map_places_world(facts, {'gate': (712, 530), 'beach': (360, 820)})
        self.assertAlmostEqual(w['Farm']['gate'][0], 0.2 * 712 - 150, places=3)
        self.assertNotIn('beach', w['Farm'])  # too far from any Farm pin pair

    def test_map_layer_is_outdoor_only_and_coarse(self):
        pins = [(700, 480), (600, 470), (780, 660)]
        facts = [{'scene': 'Farm', 'pin': list(p), 'to': [0.2 * p[0] - 150, -0.25 * p[1] + 120]} for p in pins]
        indoor = [dict(f, scene='Farm/House') for f in facts]
        self.assertEqual(nav.map_pairs(indoor, 'Farm/House'), [])
        ns = nav.nodes(facts + indoor, {'gate': (712, 530)})
        self.assertEqual(ns['Farm:gate']['src'], 'map')
        self.assertEqual(ns['Farm:gate']['r'], nav.MAP_RADIUS)  # a perfect fit still gets the least radius
        self.assertNotIn('Farm/House:gate', ns)
        arrived = facts + [{'scene': 'Farm', 'goal': 'gate', 'result': 'arrived', 'to': [1, 2]}]
        self.assertNotIn('r', nav.nodes(arrived, {'gate': (712, 530)})['Farm:gate'])  # an arrival overrides it

    def test_map_fit_needs_spread(self):
        facts = [{'scene': 'Farm', 'pin': [700, 480], 'to': [0, 0]}, {'scene': 'Farm', 'pin': [702, 600], 'to': [1, 1]}]
        self.assertIsNone(nav.map_fit(facts, 'Farm'))


class Storage(unittest.TestCase):
    def test_per_area_files(self):
        import tempfile
        import numpy as np
        with tempfile.TemporaryDirectory() as root:
            nav.calib_save('Farm/House', {'H': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'n': 5, 'kept': 5, 'err': 0.1},
                           root=root)
            self.assertEqual(nav.calib_load('Farm/House', root=root)['kept'], 5)
            self.assertIsNone(nav.calib_load('Farm', root=root))  # the scene's own camera is separate
            self.assertTrue(os.path.exists(os.path.join(root, 'Farm', 'House', 'calib.json')))
            nav.print_append('Town', 7.0, np.ones(4), root=root)
            self.assertEqual(list(nav.prints_load('Town', root=root)), [7.0])
            self.assertEqual(nav.prints_load('Farm', root=root), {})
            mp = os.path.join(root, 'map.json')
            pins = [(700, 480), (600, 470), (780, 660)]
            facts = [{'scene': 'Farm', 'pin': list(p), 'to': [0.2 * p[0], -0.25 * p[1]]} for p in pins]
            self.assertIn('Farm', nav.map_refit(facts, path=mp))
            self.assertIn('Farm', nav.map_load(mp)['fits'])

    def test_outdoor_scene_borrows_camera(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(nav.calib_load('Town', root=root))
            nav.calib_save('Farm', {'H': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'n': 5, 'kept': 5, 'err': 0.1}, root=root)
            self.assertEqual(nav.calib_load('Town', root=root)['borrowed'], 'Farm')
            self.assertIsNone(nav.calib_load('Town/Cafe', root=root))  # indoor cameras differ

    def test_layers_line(self):
        facts = [{'scene': 'Farm/House', 'goal': 'bed', 'result': 'arrived', 'to': [1, 1]}]
        line = nav.layers(facts, {}, nav.nodes(facts), {'Farm/House': 2})[0]
        self.assertIn('L4 map — (indoor)', line)
        self.assertIn('1 arrived', line)
        self.assertIn('prints 2', line)


class Walls(unittest.TestCase):
    def test_wall_stop_reroutes_via_detour(self):
        facts = [{'scene': 'Town', 'goal': 'fountain', 'result': 'arrived', 'to': [0, -10]},
                 {'scene': 'Town', 'result': 'stuck', 'to': [0, -2]},        # the planter, straight south
                 {'scene': 'Town', 'result': 'via', 'to': [-6, -2]}]         # the stairs beside it
        ns = nav.nodes(facts)
        steps = nav.plan(ns, nav.edges_graph(facts, ns), ('Town', 0, 0), 'fountain', nav.walls(facts))
        self.assertEqual([k for _, k in steps], ['Town:via(-6,-2)', 'Town:fountain'])
        self.assertEqual(nav.walk_cost((0, -2), (0, -10), [(0, -2)]), 8)  # walking away from the wall is fine


class Exits(unittest.TestCase):
    def test_untraced_door_has_no_position_but_an_aim(self):
        facts = [{'scene': 'Farm', 'goal': 'House:out', 'result': 'scene', 'to': [17.3, -27.7],
                  'from_scene': 'Farm/House'},                                 # crossed, exit not traced
                 {'scene': 'Farm/House', 'goal': 'bed', 'result': 'arrived', 'to': [18, -17]}]
        ns = nav.nodes(facts)
        e = ns['Farm/House:exit>House:out']
        self.assertIsNone(e['x'])
        self.assertEqual(e['aim'], (17.3, -27.7))  # walk toward the porch: same coordinates
        steps = nav.plan(ns, nav.edges_graph(facts, ns), ('Farm/House', 18, -17), 'House:out')
        self.assertEqual([k for k, _ in steps], ['walk', 'link'])

    def test_untraced_scene_link_needs_exploring(self):
        facts = [{'scene': 'Town', 'goal': 'Town/LinkFarm', 'result': 'scene', 'to': [-71, 50], 'from_scene': 'Farm'}]
        e = nav.nodes(facts)['Farm:exit>Town/LinkFarm']
        self.assertIsNone(nav.target_of(e))  # different coordinates: no direction either

    def test_log_position_real_lines(self):
        self.assertEqual(nav.log_position('[D147 4:15:31 PM] Player locomotion failed at Town (-0.75, 7.21, 46.77): '
                                          'Stopped against barrier while pathfinding'), ('Town', -0.75, 46.77))
        self.assertEqual(nav.log_position('[D147 4:12:28 PM] Player Path blocked timeout exceeded at '
                                          '(-10.14, 6.32, 47.60)'), (None, -10.14, 47.6))
        self.assertIsNone(nav.log_position('[GAME] ChangeScene Farm/LinkTown'))


class Coverage(unittest.TestCase):
    def test_cells_and_layers(self):
        fits = {'Farm': {'a': 0.2, 'b': -150, 'c': -0.25, 'd': 120, 'err': 1}}
        x, z = 0.2 * 700 - 150, -0.25 * 500 + 120          # map (700, 500)
        facts = [{'t': 1, 'scene': 'Farm', 'to': [x, z], 'pin': [700, 500], 'pred': [x + 0.3, z], 'result': 'moved'},
                 {'t': 2, 'scene': 'Farm/House', 'to': [1.0, 1.0]}]
        cov = nav.coverage(facts, fits, {1})
        cell = ('map', 700 // nav.COVER_CELL, 500 // nav.COVER_CELL)
        self.assertEqual(cov[cell], {'L1', 'L2', 'L3', 'L4'})
        self.assertEqual(nav.missing(('Farm/House', 0, 0), cov), ['L2', 'L1'])
        m = nav.coverage_matrix(cov, 'map', roads={(cell[1] + 1, cell[2])}, here=None)
        self.assertIn('4·', m)


class Graph(unittest.TestCase):
    def facts(self):
        return [
            {'scene': 'Farm', 'goal': 'barn', 'result': 'arrived', 'to': [10, 0]},
            {'scene': 'Town', 'goal': 'Town/LinkFarm', 'result': 'scene', 'to': [0, 0], 'from_scene': 'Farm',
             'exit': [20, 5]},
            {'scene': 'Town', 'goal': 'hall', 'result': 'arrived', 'to': [5, 5]},
        ]

    def test_plan_across_scenes(self):
        ns = nav.nodes(self.facts())
        self.assertIn('Farm:exit>Town/LinkFarm', ns)
        es = nav.edges_graph(self.facts(), ns)
        steps = nav.plan(ns, es, ('Farm', 0, 0), 'hall')
        self.assertEqual([k for k, _ in steps], ['walk', 'link', 'walk'])
        self.assertEqual(steps[-1][1], 'Town:hall')

    def test_failures_raise_cost(self):
        f = self.facts() + [{'scene': 'Farm', 'goal': 'barn', 'result': 'short', 'to': [9, 0]}] * 3
        es = {(a, b): c for a, b, c, _ in nav.edges_graph(f, nav.nodes(f))}
        self.assertGreater(es[('Farm:exit>Town/LinkFarm', 'Farm:barn')], 25)

    def test_unknown_goal(self):
        ns = nav.nodes(self.facts())
        self.assertIsNone(nav.plan(ns, nav.edges_graph(self.facts(), ns), ('Farm', 0, 0), 'moon'))


class Vectors(unittest.TestCase):
    def test_knn_and_gate(self):
        import numpy as np
        rng = np.random.default_rng(0)
        base = {i: rng.normal(size=16).astype(np.float32) for i in range(6)}
        facts = [{'t': i, 'scene': 'Farm', 'to': [float(i), 0.0]} for i in range(6)]
        r = nav.img_predict(facts, base, 'Farm', base[3] + 0.01)
        self.assertLess(abs(r['pred'][0] - 3), 0.5)
        self.assertIsNone(nav.img_predict(facts[:4], base, 'Farm', base[3]))  # too few prints
        good = [{'scene': 'Farm', 'to': [0, 0], 'img': {'pred': [0.2, 0], 'd': 0.1}}] * 20
        self.assertTrue(nav.img_trusted(good, 'Farm', 0.1))
        bad = good[:10] + [{'scene': 'Farm', 'to': [0, 0], 'img': {'pred': [5, 0], 'd': 0.1}}] * 10
        self.assertFalse(nav.img_trusted(bad, 'Farm', 0.1))


if __name__ == '__main__':
    unittest.main()
