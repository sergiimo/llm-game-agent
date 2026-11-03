"""Offline tests for the interaction-laws framework pieces (observe/act/nav/ask; L124-L134). Goals and the engine:
tools/test_engine.py. Run: .venv/bin/python tools/test_laws.py"""
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import act, affordances, ask, core, laws, learn, nav, observe, ui, well  # noqa: E402
from game.affordances import Affordance  # noqa: E402
from objects.loop import NeedVision  # noqa: E402

core.LOG_WAIT = 0.0
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')



class Fake:
    """A garden seen from Tara (frame centre). Beds: state wilted|dry|wet|ripe|empty, a bubble point when in reach and a
    body point (where vision says to click). Clicking a far bed's body walks there: its zone comes in reach."""

    def __init__(self, beds, can=True, seeds=None):
        self.beds = beds   # name -> dict(state, crop, zone, bubble, body)
        self.zone, self.can = 'near', can
        self.seeds = {'Tulip': 4, 'Green Bean': 2, 'Carrot': 10} if seeds is None else seeds
        self.log, self.screen, self.card_bed, self.asks, self.clicks = [], 'gameplay', None, [], []
        self.save_left = None

    # -- WF
    def grab(self):
        """Frames: a walk makes the first burst frame differ from the next ones (moved=True); otherwise all equal."""
        from PIL import Image
        if getattr(self, 'walk_frames', 0):
            self.walk_frames -= 1
            return Image.new('L', (8, 8), 0)
        return Image.new('L', (8, 8), 200)

    def _walk(self, zone):
        self.zone, self.walk_frames = zone, 1

    def log_mark(self):
        return len(self.log)

    def log_since(self, m):
        return '\n'.join(self.log[m:])

    def _unhash(self, t):
        return t

    def wait_settle(self):
        pass

    def run_log(self, *a, **k):
        pass

    def run_dir(self):
        return None

    def farm_status(self):
        return {'crops': []}

    def save_bed_counts(self, crops):
        if self.save_left is None:
            raise KeyError('no save')
        return {'wilted': self.save_left, 'dry': self.save_left, 'ripe': self.save_left}

    def ask_vision(self, kind, q, img, **ctx):
        self.asks.append((kind, q + ' ' + str(ctx)))
        return f'NEED_VISION {kind}: {q}'

    def state(self):
        return {'mode': 'gameplay' if self.screen == 'gameplay' else 'overlay',
                'text': [f'{i}) {t}' for i, t in enumerate(self.texts())]}

    def emit(self, ev, b):
        self.log.append(f'21:00 > {ev} {self.beds[b]["crop"]} at (1.0, 0.0, 2.0) target=GardenBed')

    def event_kind(self, lines):
        m = next((re.search(r'> (\w+)', l) for l in lines if re.search(r'> (\w+)', l)), None)
        return m.group(1) if m else None

    def learn_bubble(self, crop, kind, seen):
        self.learned = getattr(self, 'learned', []) + [(kind, seen)]
        return True

    def bubble_crop(self, img, b):
        return ('crop', b)

    WELL = (1500, 260)   # the well's can bubble (in reach from every zone of the fake garden)

    def run_action(self, a):
        x, y = (int(v) for v in re.match(r'click:(-?\d+):(-?\d+)', a).groups())
        self.clicks.append((x, y))
        if abs(x - self.WELL[0]) < 30 and abs(y - self.WELL[1]) < 30:
            self.log.append('21:00 > fill_watering_can me=Player target=Well')
            self.can = True
            if getattr(self, 'well_zone', None):
                self._walk(self.well_zone)   # she walked to the well: the beds are out of reach
            return
        for hx, hy in getattr(self, 'hives', ()):   # a hive (its body or its honey bubble) in reach
            if abs(hx - x) < 40 and abs(hy - y) < 40:
                self.log.append('21:00 > beehive_progress me=Player target=BeeHive(Clone) at (0.2, 0.1, -23.5)')
                return
        for n, b in self.beds.items():
            if b['zone'] == self.zone and abs(b['bubble'][0] - x) < 30 and abs(b['bubble'][1] - y) < 30:
                return self.interact(n)
        for n, b in self.beds.items():
            if abs(b['body'][0] - x) < 100 and abs(b['body'][1] - y) < 80:
                if b['zone'] == self.zone:
                    return self.interact(n)
                self._walk(b['zone'])   # walked there
                return
        if getattr(self, 'walk_always', False):
            self._walk(self.zone)
            return
        if getattr(self, 'step_zone', None) and getattr(self, 'step_ok', lambda x, y: True)(x, y):
            self._walk(self.step_zone)   # a few steps on the road bring the garden into reach

    def interact(self, n):
        b = self.beds[n]
        st = b['state']
        if st == 'wilted':
            self.emit('unplant', n)
            self.screen, self.card_bed = 'card', n
        elif st == 'dry':
            if self.can:
                self.emit('water', n)
                b['state'] = 'wet'
            else:
                self.emit('out_of_water', n)
        elif st == 'wet':
            self.emit('plant_growing', n)
        elif st == 'ripe':
            self.emit('grab_item', n)
            b['state'] = 'wet'
        elif st == 'empty':
            self.screen, self.card_bed = 'panel', n

    def scan(self):
        if self.screen != 'gameplay':   # a card/panel hides the bubbles (game D184: 'gone' after the wilted card)
            return []
        kind = {'wilted': 'unplant', 'dry': 'water', 'wet': 'water', 'ripe': 'pickup', 'empty': 'plant'}
        learned = dict(getattr(self, 'learned', []))
        honey = [Affordance('beehive_progress' if 'beehive_progress' in learned else 'unknown', None, p, False, 0.0, False)
                 for p in getattr(self, 'honey', ()) if self.zone == 'near']
        ko = getattr(self, 'kind_of', {})
        well_b = [Affordance('fill_can', None, self.WELL, False, 0.0, False)] if not self.can else []
        return well_b + honey + [Affordance(ko.get(b['bubble'], kind[b['state']]), None, b['bubble'], False, 0.0,
                                   b['state'] in ('wilted', 'dry'))
                        for b in self.beds.values() if b['zone'] == self.zone]

    # -- ui
    def texts(self):
        b = self.beds.get(self.card_bed)
        # the real wilted card has no Remove text, only a ⃠ icon (live run D184): Space opens the confirmation
        return {'card': [f'{b["crop"] if b else "?"}', 'This plant has wilted.'],
                'prompt': [f'Are you sure you want to remove {b["crop"] if b else "?"}?', 'Remove', 'Cancel'],
                'panel': ['Inventory', 'Seeds'], 'detail': ['Seeds', 'Select']}.get(self.screen, [])

    def shows(self, word, wait=2.0):
        return any(word.lower() in t.lower() for t in self.texts())

    def press(self, label):
        b = self.card_bed
        if label == 'Remove' and self.screen == 'prompt':
            self.log.append(f'21:00 > unplant_impl {self.beds[b]["crop"]}')
            self.beds[b].update(state='empty', crop=None)
            self.screen = 'gameplay'
        elif label == 'Select' and self.screen == 'detail':
            self.log.append(f'[STATS] totalPlanted.{self.picked}Seed')
            self.log.append('21:00 > plant')
            self.beds[b].update(state='dry', crop=self.picked)
            self.seeds[self.picked] -= 1
            self.screen = 'gameplay'
        else:
            raise core.Failed(f'no {label} on {self.screen}')

    def press_bubble(self):
        if self.screen == 'card':
            self.screen = 'prompt'

    def pick_card(self, name):
        assert self.screen == 'panel', self.screen
        if not self.seeds.get(name):
            raise core.Failed(f'no "{name}" among 3 cards')
        self.picked, self.screen = name, 'detail'

    def close(self):
        if self.screen != 'gameplay':
            if self.screen == 'panel':
                self.log.append('21:00 > plant')
            self.screen = 'gameplay'

    def fill_can(self, graph=None):
        self.can = True


def bed(state, crop='Tulip', zone='near', bubble=(0, 0), body=(0, 0)):
    return {'state': state, 'crop': crop, 'zone': zone, 'bubble': bubble, 'body': body}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from game import where
        where._WALK.clear()
        self.addCleanup(where._WALK.clear)
        ps = [mock.patch.object(ask, 'STATE', os.path.join(self.tmp.name, 'ask.json')),
              mock.patch.object(where, 'WALK', os.path.join(self.tmp.name, 'where-walk.json')),
              mock.patch.object(learn, 'GRAPH', self._graph_copy()),
              mock.patch.object(act, 'BURST', (0.0, 0.0)), mock.patch.object(act, 'EVENT_WAIT', 0.0),
              # default: no vector match on screen and no map (the vision path); Seek tests override these
              mock.patch.object(observe, 'see', lambda kind, tried=(): []),
              mock.patch.object(nav, 'map_direction', lambda node: None)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def _graph_copy(self):
        import shutil
        p = os.path.join(self.tmp.name, 'Farm.json')
        shutil.copy(SEED, p)
        return p

    def use(self, f):
        self.f = f
        old = core.WF
        core.bind(f)
        self.addCleanup(core.bind, old)
        for mod, name, fn in ((affordances, 'scan', f.scan), (ui, 'texts', f.texts), (ui, 'shows', f.shows),
                              (ui, 'press', f.press), (ui, 'press_bubble', f.press_bubble), (ui, 'pick_card', f.pick_card), (ui, 'close', f.close),
                              (well, 'fill_can', f.fill_can)):
            p = mock.patch.object(mod, name, fn)
            p.start()
            self.addCleanup(p.stop)
        return f


class Mechanics(unittest.TestCase):
    """User D185 mechanics on real pixels (tools/fixtures): the "!" sub-icon and the soil tone."""
    FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

    def test_ready_badge_is_told_from_the_selection_ring(self):
        from PIL import Image
        self.assertTrue(affordances.has_ready(Image.open(os.path.join(self.FX, 'bubble_ready.png'))))
        self.assertFalse(affordances.has_ready(Image.open(os.path.join(self.FX, 'bubble_ring.png'))))

    def test_dry_soil_spots_are_the_light_beds_not_the_watered_ones(self):
        from PIL import Image
        img = Image.open(os.path.join(self.FX, 'soil_d185.jpg')).resize((1920, 1080))
        spots = [(x, y) for x, y, n in affordances.dry_spots(img)]
        self.assertTrue(any(abs(x - 433) < 60 and abs(y - 684) < 60 for x, y in spots))   # row 1, left beds: light
        for wet in ((370, 865), (650, 865), (955, 1030)):                                 # row 2 b2/b3, row 3 b4: dark
            self.assertFalse(any(abs(x - wet[0]) < 50 and abs(y - wet[1]) < 40 for x, y in spots), wet)
        dry, wet = affordances.soil_counts(img)
        self.assertGreater(wet, 300)
        self.assertGreater(dry, 300)


class Reach(Base):
    """L133: the low-level navigation - any node of a kind whose bubble fits, not a particular member."""
    def test_returns_the_fitting_bubble_in_reach_without_clicking_it(self):
        f = self.use(Fake({'a': bed('empty', bubble=(900, 400)), 'b': bed('dry', bubble=(1100, 400))}))
        a = laws.reach(lambda a: a.kind == 'plant')
        self.assertEqual(a.pt, (900, 400))
        self.assertEqual(f.clicks, [])

    def test_walks_until_one_fits(self):
        f = self.use(Fake({'a': bed('empty', zone='far', bubble=(700, 300), body=(5000, 5000))}))
        f.step_zone = 'far'
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            a = laws.reach(lambda a: a.kind == 'plant')
        self.assertEqual(a.pt, (700, 300))
        self.assertEqual(f.clicks[0], (960 + laws.STEP_R[0], 540))

    def test_nothing_found_asks_vision_with_the_trace(self):
        f = self.use(Fake({}))
        f.step_zone = None
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            with self.assertRaises(core.Failed) as e:
                laws.reach(lambda a: a.kind == 'plant')
        self.assertIn('STUCK', str(e.exception))


class Framework(Base):
    """L134: observe / act / learn / nav (goals on top: game/engine.py)."""
    def test_closest_node_is_the_owner_of_the_bubble_nearest_tara(self):
        A = Affordance
        affs = [A('fill_can', None, (1000, 500), False, 0.0), A('water', None, (1400, 800), False, 0.0, True)]
        self.assertEqual(observe.closest_node(affs), 'Well')
        affs = [A('beehive_progress', None, (1500, 300), False, 0.0), A('plant', None, (980, 560), False, 0.0)]
        self.assertEqual(observe.closest_node(affs), 'GardenBed@Garden')

    def test_a_graph_direction_that_reached_the_target_is_learned(self):
        from objects import graph as OG
        g = OG.Graph()
        g.load(learn.GRAPH)
        OG.learn_toward(g, 'Well', 'GardenBed@Garden', (1.0, 0.0))
        dx, dy = OG.toward(g, 'Well', 'GardenBed@Garden')
        self.assertGreater(dx, OG.TOWARD[('Well', 'GardenBed@Garden')][0])
        self.assertLess(dy, OG.TOWARD[('Well', 'GardenBed@Garden')][1])


class Points(unittest.TestCase):
    def test_grid_cell_is_its_centre(self):
        self.assertEqual(laws.parse_point('Q14'), (1320, 911))
        self.assertEqual(laws.parse_point(' m9 '), (1000, 574))

    def test_xy_tuple(self):
        self.assertEqual(laws.parse_point((812, 640)), (812, 640))

    def test_bad_answers_rejected(self):
        for bad in ('Z3', 'Q17', 'Q0', 'hello', (2000, 10), (-5, 500)):
            with self.assertRaises(ValueError, msg=bad):
                laws.parse_point(bad)

    def test_hud_rejected(self):
        for hud in ('B2', 'W2', (100, 100), (1700, 150)):
            with self.assertRaises(ValueError, msg=hud):
                laws.parse_point(hud)

    def test_tara_is_the_centre(self):
        self.assertEqual(laws.CENTRE, (960, 540))

    def test_draw_grid_marks_tara(self):
        from PIL import Image
        pic = laws.draw_grid(Image.new('RGB', (1920, 1080), (0, 0, 0)))
        self.assertEqual(pic.getpixel((960, 540 - 26)), (255, 0, 255))


class Record(Base):
    def test_click_record_has_events_bubbles_and_screen(self):
        f = self.use(Fake({'a': bed('wilted', 'Tulip', bubble=(1100, 600))}))
        c = laws.record_click((1100, 600), 'bubble')
        self.assertEqual(c.events, ['unplant'])
        self.assertEqual(c.mode, 'overlay')
        self.assertIn('Tulip', c.texts)
        self.assertEqual([a.kind for a in c.before], ['unplant'])
        self.assertIn('unplant', c.describe())

    def test_nothing_needs_a_known_unchanged_view(self):
        f = self.use(Fake({}))
        c = laws.record_click((900, 900))
        self.assertIs(c.moved, False)   # the burst frames are equal: she did not move
        self.assertTrue(c.nothing())
        c.moved = None                  # view change unknown: not claimed as nothing
        self.assertFalse(c.nothing())
        del f

    def test_burst_frames_catch_a_view_change(self):
        from PIL import Image
        a, b = Image.new('RGB', (1920, 1080), (10, 10, 10)), Image.new('RGB', (1920, 1080), (200, 200, 200))
        self.assertTrue(observe.view_changed(a, b))
        self.assertFalse(observe.view_changed(a, a.copy()))


if __name__ == '__main__':
    unittest.main()
