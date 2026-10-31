"""Offline tests for tools/world (entities, scene graph, costmap, belief, view; M2). Run: .venv/bin/python tools/test_world.py"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime.log import Ev  # noqa: E402
import nav  # noqa: E402
from runtime import log as rlog  # noqa: E402
from world import belief, costmap, entities, graph, model, view, zoom  # noqa: E402

H_FARM = [[8.659732, -0.005814, -0.001597], [0.074748, -21.414692, 5.617554], [-0.005491, 0.509604, 1.0]]

nav.OBJECTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nav', '_no_objects_in_tests.json')

HIVES = [-2.28 + 1.25 * i for i in range(8)]   # the D149 hive row, z -23.46


def act(target, x, z, name='beehive_progress'):
    return Ev('action', 149, 9.0, '', {'name': name, 'target': target, 'x': x, 'z': z})


class Entities(unittest.TestCase):
    def test_two_hives_not_merged(self):
        es = entities.Entities()
        es.observe(act('BeeHive', 0.22, -23.46), 'Farm')
        es.observe(act('BeeHive', 1.47, -23.46), 'Farm')
        self.assertEqual(len(es.find(kind='BeeHive')), 2)

    def test_same_hive_merged_sources(self):
        es = entities.Entities()
        a = es.observe(act('BeeHive', 0.22, -23.46), 'Farm')
        b = es.observe(Ev('action', 149, 9.5, '', {'name': 'beehive_progress', 'target': 'BeeHive', 'x': 0.25,
                                                   'z': -23.40}), 'Farm')   # another line, another time
        self.assertIs(a, b)
        self.assertEqual(len(a.sources), 2)
        self.assertTrue(a.solid)

    def test_beds_walkable(self):
        es = entities.Entities()
        bed = es.observe(act('GardenBed', 5.84, -31.59, 'water'), 'Farm')
        self.assertFalse(bed.solid)

    def test_no_area_held(self):
        es = entities.Entities()
        self.assertIsNone(es.observe(act('BeeHive', 0.22, -23.46), None))
        self.assertEqual(es.find(), [])
        self.assertEqual(len(es.pending), 1)

    def test_pathfail_target_is_an_entity(self):
        es = entities.Entities()
        e = es.observe(Ev('pathfail', 148, 23.0, '', {'x': -1.09, 'z': -21.05, 'tx': 2.72, 'tz': -23.46,
                                                     'target': 'BeeHive'}), 'Farm')
        self.assertEqual((e.kind, e.x, e.z), ('BeeHive', 2.72, -23.46))


class Graph(unittest.TestCase):
    FACTS = [
        {'scene': 'Farm', 'goal': 'home', 'result': 'arrived', 'to': [0, 0]},
        {'scene': 'Farm', 'result': 'moved', 'from': [0, 0], 'to': [0, -20]},
        {'scene': 'RuralBeach', 'goal': 'RuralBeach/LinkFarm', 'result': 'scene', 'to': [-40, 0], 'from_scene': 'Farm',
         'exit': [0, -25]},
        {'scene': 'RuralBeach', 'result': 'moved', 'from': [-40, 0], 'to': [-30, -10]},
    ]

    def test_map_places_excluded(self):
        G = graph.build(entities.Entities(), self.FACTS, {'ruined-ranch': [430, 540]})
        self.assertFalse(any('ruined-ranch' in n for n in G.nodes))

    def test_route_farm_to_beach_via_exit(self):
        G = graph.build(entities.Entities(), self.FACTS, {})
        r = graph.route(G, ('Farm', 0, 0), 'RuralBeach:RuralBeach/LinkFarm')
        self.assertIsNotNone(r)
        self.assertEqual(r[-1], 'RuralBeach:RuralBeach/LinkFarm')
        self.assertTrue(any('exit>' in n for n in r))


def hive_row():
    cm = costmap.Costmap('Farm', (-12, -40, 20, -10))
    for x in HIVES:
        cm.add_solid(x, -23.46, 0.6)
    return cm


class Costmap(unittest.TestCase):
    def test_path_goes_round_the_row(self):
        cm = hive_row()
        path = costmap.astar(cm, (-1.3, -21.7), (-1.7, -25.3), now_hour=10.0, reach=1.0)
        self.assertIsNotNone(path)
        for x, z in path:
            self.assertTrue(all(math.dist((x, z), (h, -23.46)) >= 0.6 for h in HIVES), (x, z))
        self.assertTrue(any(x < -2.9 for x, z in path))          # west, round the end of the row
        self.assertLess(math.dist(path[-1], (-1.7, -25.3)), 1.0 + cm.cell)

    def test_no_path_when_enclosed(self):
        cm = costmap.Costmap('Farm', (-10, -10, 10, 10))
        for i in range(36):
            a = math.radians(i * 10)
            cm.add_solid(3 * math.cos(a), 3 * math.sin(a), 0.6)
        self.assertIsNone(costmap.astar(cm, (0, 0), (6, 6), now_hour=10.0))

    def test_refused_fades(self):                          # absolute game hours (day*24+h): yesterday doesn't block
        cm = costmap.Costmap('Farm', (-10, -10, 10, 10))
        cm.add_refused(0, 0, game_hour=148 * 24 + 10.0)
        self.assertTrue(math.isinf(cm.cost(148 * 24 + 10.5)[cm.cell_of(0, 0)]))
        self.assertFalse(math.isinf(cm.cost(148 * 24 + 11.1)[cm.cell_of(0, 0)]))
        self.assertFalse(math.isinf(cm.cost(149 * 24 + 10.2)[cm.cell_of(0, 0)]))

    def test_astar_expansion_cap(self):                    # review I6: no 1-2 s scans before every walk
        cm = costmap.Costmap('Town', (-60, -60, 60, 60))
        cm.add_solid(50, 50, 2.0)
        self.assertIsNone(costmap.astar(cm, (-55, -55), (50, 50), now_hour=10.0, max_expand=500))
        self.assertTrue(cm.capped)

    def test_walked_is_cheaper(self):
        cm = costmap.Costmap('Farm', (-10, -10, 10, 10))
        cm.add_walked(-5, 0, 5, 0)
        self.assertLess(cm.cost(10.0)[cm.cell_of(0, 0)], cm.cost(10.0)[cm.cell_of(0, 5)])

    def test_waypoints_spacing(self):
        pts = [(x * 0.5, 0.0) for x in range(41)] + [(20.0, z * 0.5) for z in range(1, 21)]
        wps = costmap.waypoints(pts, hop=8.0)
        self.assertEqual(wps[-1], (20.0, 10.0))
        self.assertTrue(all(math.dist(a, b) <= 8.0 + 1e-6 for a, b in zip([pts[0]] + wps, wps)))
        self.assertIn((20.0, 0.0), wps)                            # the turn is kept


class Belief(unittest.TestCase):
    def test_uncertainty_grows_then_fix(self):
        b = belief.Belief('Farm', 0.0, 0.0, u=0.05)
        for _ in range(10):
            b.click(2.0, 0.0)
        self.assertTrue(b.needs_fix())
        area, x, z, u = b.predicted()
        self.assertAlmostEqual(x, 20.0, places=6)
        b.fix(18.0, 0.5, belief.SIGMA_LOG)
        area, x, z, u = b.predicted()
        self.assertLess(u, 0.1)
        self.assertLess(math.dist((x, z), (18.0, 0.5)), 0.05)
        self.assertFalse(b.needs_fix())

    def test_new_scene_unknown(self):
        b = belief.Belief('Farm', 0.0, 0.0, u=0.05)
        b.scene('RuralBeach')
        self.assertEqual(b.predicted()[0], 'RuralBeach')
        self.assertTrue(b.needs_fix())
        b.scene('Farm', -1.2, -108.3)
        self.assertFalse(b.needs_fix())


class View(unittest.TestCase):
    def test_on_screen(self):
        b = belief.Belief('Farm', 0.0, 0.0, u=0.1)
        self.assertTrue(view.on_screen(H_FARM, b, 1.0, -1.0))
        self.assertFalse(view.on_screen(H_FARM, b, 60.0, 0.0))
        self.assertFalse(view.on_screen(None, b, 1.0, -1.0))

    def test_click_point_is_the_target_itself(self):        # no guessed occlusion (S21-S25)
        es = entities.Entities()
        bed = es.add('GardenBed', 'Farm', -1.7, -25.3, 'test')
        b = belief.Belief('Farm', -1.3, -21.7, u=0.2)
        pt = view.click_point(H_FARM, b, bed)
        self.assertEqual(pt, tuple(int(v) for v in view._scr(H_FARM, b, -1.7, -25.3)))

    def test_click_point_prefers_the_objects_learned_click_spot(self):   # the well's roof, not its use point
        es = entities.Entities()
        well = es.add('Well', 'Farm', -1.09, -21.05, 'test')
        well.state['click_xz'] = [-6.5, -17.0]
        b = belief.Belief('Farm', -5.53, -19.33, u=0.05)
        self.assertEqual(view.click_point(H_FARM, b, well), tuple(int(v) for v in view._scr(H_FARM, b, -6.5, -17.0)))

    def test_object_near_the_screen_edge_is_clickable(self):   # obj-walk-2: the well's roof at x 190
        from world import zoom as zm
        H = zm.apply(H_FARM, 1.82)
        well = entities.Entities().add('Well', 'Farm', -1.09, -21.05, 'test')
        well.state['click_xz'] = [-7.12, -10.61]
        pt = view.click_point(H, belief.Belief('Farm', 2.91, -22.51, u=0.05), well)
        self.assertIsNotNone(pt)
        self.assertLess(pt[0], 200)

    def test_no_calibration_no_point(self):
        es = entities.Entities()
        bed = es.add('GardenBed', 'Farm', 1.0, 1.0, 'test')
        self.assertIsNone(view.click_point(None, belief.Belief('Farm', 0, 0), bed, []))


FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'game_log.txt')


class WorldModel(unittest.TestCase):
    def world(self):
        w = model.World(facts=[], cache=os.devnull)
        w.observe(Ev('scene', 149, 7.0, '', {'scene': 'Farm', 'link': 'Bed'}))
        return w

    def test_world_from_log_fixture(self):
        w = self.world()
        for l in open(FIX).read().splitlines():
            if 'BeeHive' in l or 'GardenBed' in l:
                e = rlog.parse_line(l)
                if e:
                    w.observe(e)
        self.assertEqual(len(w.entities(kind='BeeHive', area='Farm')), 4)
        self.assertEqual(len(w.entities(kind='GardenBed', area='Farm')), 3)

    def test_world_tara_follows_actions(self):
        w = self.world()
        w.observe(rlog.parse_line(next(l for l in open(FIX) if '> water me=Player' in l)))
        area, x, z, u = w.tara()
        self.assertEqual(area, 'Farm')
        self.assertLess(math.dist((x, z), (5.84, -31.59)), 1.0)
        self.assertLessEqual(u, 1.0)

    def test_passing_card_is_not_a_position_fix(self):      # world-shadow S19
        w = self.world()
        w.belief.scene('Farm', 1.6, -22.8)
        for _ in range(4):
            w.clicked(-2.0, 3.0)                              # she walks away north-west
        w.observe(Ev('action', 149, 17.0, '', {'name': 'beehive_progress', 'target': 'BeeHive', 'x': 1.47,
                                               'z': -23.46}))  # a card she passed earlier, read late
        area, x, z, u = w.tara()
        self.assertLess(math.dist((x, z), (-6.4, -10.8)), 0.01)   # not yanked back to the hive
        self.assertEqual(len(w.entities(kind='BeeHive')), 1)       # still learned as an entity

    def test_sources_not_duplicated_and_capped(self):     # review I3: daemon restarts replay the log
        es = entities.Entities()
        for _ in range(3):
            es.observe(act('BeeHive', 0.22, -23.46), 'Farm')
        self.assertEqual(len(es.find()[0].sources), 1)
        for i in range(60):
            es.observe(Ev('action', 149, 9.0 + i / 60, '', {'name': 'beehive_progress', 'target': 'BeeHive',
                                                             'x': 0.22, 'z': -23.46}), 'Farm')
        self.assertLessEqual(len(es.find()[0].sources), entities.MAX_SOURCES)

    def test_spawn_inside_building(self):                  # review I9: waking in bed = inside the House
        w = model.World(facts=[], cache=os.devnull, spawn_inside={'Farm/Bed': 'House'})
        w.observe(Ev('spawn', 149, 7.0, '', {'scene': 'Farm', 'point': 'Bed'}))
        self.assertEqual(w.tara()[0], 'Farm/House')

    def test_unknown_position_no_queries(self):           # review minor: no searching around (0, 0)
        w = model.World(facts=[], cache=os.devnull)
        self.assertIsNone(w.in_reach())
        self.assertEqual(w.route_status(('Farm', 1.0, 1.0))[0], 'unknown')

    def test_route_goal_outside_known_extent(self):        # review I5: bounds include start and goal
        w = self.world()
        w.ents.add('BeeHive', 'Farm', 0.0, 0.0, 'test')
        w.belief.scene('Farm', 0.0, 3.0)
        status, wps = w.route_status(('Farm', 40.0, 3.0), reach=1.0)
        self.assertEqual(status, 'way')
        self.assertLess(math.dist(wps[-1], (40.0, 3.0)), 1.5)

    def test_route_bed_from_strip(self):
        w = self.world()
        for x in HIVES:
            w.ents.add('BeeHive', 'Farm', x, -23.46, 'test')
        w.belief.scene('Farm', -1.3, -21.7)
        wps = w.route(('Farm', -1.7, -25.3), reach=1.0)
        self.assertTrue(wps)
        self.assertTrue(all(all(math.dist(p, (h, -23.46)) > 0.6 for h in HIVES) for p in wps))

    def test_reading_scores_world_belief(self):
        import tempfile
        from evals import store
        store.PATH = os.path.join(tempfile.mkdtemp(), 'p.jsonl')
        import evals
        w = self.world()
        w.belief.scene('Farm', 0.0, 0.0)
        w.clicked(1.0, 0.0)
        w.reading('Farm', 1.2, 0.1)
        self.assertEqual(evals.report()['world_belief']['hits'], 1)

    def test_use_points_give_the_objects_position(self):  # the well: no logged position, used from two sides
        w = self.world()
        w.observe(Ev('action', 150, 9.6, '', {'name': 'full_watering_can', 'target': 'Well'}))
        w.reading('Farm', -1.09, -21.05)                      # the use point = where she stood
        w.observe(Ev('action', 150, 9.7, '', {'name': 'fill_watering_can', 'target': 'Well'}))
        w.reading('Farm', -5.53, -19.33)
        wells = w.entities(kind='Well')
        self.assertEqual(len(wells), 1)
        self.assertAlmostEqual(wells[0].x, -3.31, places=2)   # between the two sides
        self.assertAlmostEqual(wells[0].z, -20.19, places=2)
        self.assertEqual(len(wells[0].state['use_points']), 2)

    def test_a_click_cancels_the_pending_use(self):        # obj-walk: the use at the well must not land at bed 8
        w = self.world()
        w.belief.scene('Farm', -1.0, -21.0)
        w.observe(Ev('action', 150, 9.6, '', {'name': 'full_watering_can', 'target': 'Well'}))
        w.clicked(5.0, -7.0)
        w.reading('Farm', 5.8, -29.1)
        self.assertEqual(w.entities(kind='Well'), [])

    def test_replayed_use_is_not_pending(self):            # obj-walk-2: a replayed old use landed far away
        w = self.world()
        w.observe(Ev('action', 150, 9.6, '', {'name': 'full_watering_can', 'target': 'Well'}))
        w.end_replay()
        w.reading('Farm', 2.9, -22.5)
        self.assertEqual(w.entities(kind='Well'), [])

    def test_reading_without_a_pending_use_adds_nothing(self):
        w = self.world()
        w.reading('Farm', 1.0, 1.0)
        self.assertEqual(w.entities(kind='Well'), [])

    def test_entities_cache_roundtrip(self):
        import tempfile
        w = self.world()
        w.ents.add('BeeHive', 'Farm', 0.22, -23.46, 'test')
        p = os.path.join(tempfile.mkdtemp(), 'entities.json')
        w.save(p)
        w2 = model.World(facts=[], cache=p)
        self.assertEqual(len(w2.entities(kind='BeeHive')), 1)


class Zoom(unittest.TestCase):
    def test_apply_scales_ground(self):
        dx, dz = nav.screen_to_ground(H_FARM, 1200, 700)
        zx, zz = nav.screen_to_ground(zoom.apply(H_FARM, 2.0), 1200, 700)
        self.assertAlmostEqual(zx, dx / 2, places=6)
        self.assertAlmostEqual(zz, dz / 2, places=6)
        sx, sy = nav.ground_to_screen(zoom.apply(H_FARM, 2.0), zx, zz)   # round trip
        self.assertLess(math.dist((sx, sy), (1200, 700)), 1.5)

    def test_reference_height_store(self):
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), 'zoom.json')
        self.assertIsNone(zoom.ref_load('Farm', path=p))
        zoom.ref_save('Farm', 178, 'test', path=p)
        self.assertEqual(zoom.ref_load('Farm', path=p), 178)

    def test_tara_mask_on_open_farm_frame(self):          # crop of a real frame: Tara 178 px tall (eye: ~177)
        from PIL import Image
        img = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'tara_open_crop.png'))
        box = zoom.tara_mask(img, centre=(200, 250))
        self.assertIsNotNone(box)
        self.assertAlmostEqual(box[3] - box[1], 178, delta=6)

    def test_implausible_mask_rejected(self):              # zoom-walk: Tara behind hives -> box 1288x818 -> "4.6"
        self.assertTrue(zoom.plausible((930, 500, 989, 678), 178))
        self.assertTrue(zoom.plausible((900, 400, 1010, 720), 178))      # zoomed in 1.8x, same shape
        self.assertFalse(zoom.plausible((1, 221, 1289, 1039), 178))
        self.assertFalse(zoom.plausible((900, 600, 1010, 640), 178))     # a flat blob, not her

    def test_nearest_measured_zoom_when_hidden(self):     # day-walk rev 4: hidden behind hives -> fell back to 1.0
        import tempfile
        p = os.path.join(tempfile.mkdtemp(), 'zoom.json')
        zoom.ref_save('Farm', 178, 'test', path=p)
        zoom.sample_add('Farm', 8.3, -30.1, 1.82, 'test', path=p)
        self.assertEqual(zoom.nearest('Farm', 4.16, -22.51, path=p), 1.82)   # 8.6 units away: same garden zone
        self.assertIsNone(zoom.nearest('Farm', -7.0, -44.0, path=p))         # open farm, far: no evidence
        self.assertEqual(zoom.ref_load('Farm', path=p), 178)                  # the reference survives

    def test_gauge_is_tara_height_ratio(self):
        self.assertAlmostEqual(zoom.gauge(340, 200), 1.7)
        self.assertEqual(zoom.gauge(None, 200), 1.0)
        self.assertEqual(zoom.gauge(340, None), 1.0)


if __name__ == '__main__':
    unittest.main()
