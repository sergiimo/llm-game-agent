"""Offline tests for tools/game (game functions, L77) against a fake game. Run: .venv/bin/python tools/test_game.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game  # noqa: E402
from game import core, track  # noqa: E402

core.LOG_WAIT = 0.0


class FakeImg:
    def __init__(self, box=None):
        self.box = box

    def crop(self, box):
        return FakeImg(box)

    def save(self, path):
        pass


class FakeGame:
    """A garden with beds, a can and a well, reacting to Space/clicks the way the real game does (D148 logs)."""

    def __init__(self, can_full=True):
        self.log, self.events = [], []
        self.screen, self.buttons = 'gameplay', []
        self.can_full = can_full
        self.crops = [{'x': '0.84', 'z': '-29.09', 'plantState': '##growing', 'isWilted': 'true', 'isWatered': 'false'},
                      {'x': '3.34', 'z': '-29.09', 'plantState': '##growing', 'isWilted': 'false', 'isWatered': 'false'}]
        self.at = None  # the bed or 'well' Tara stands at
        self.planted = set()

    # --- what game functions use
    def log_mark(self):
        return len(self.log)

    def log_since(self, mark):
        return '\n'.join(self.log[mark:])

    def _unhash(self, t):
        return t

    def state(self):
        texts = {'card': ['Tulip', 'This plant has wilted. You should remember to water plants every day'],
                 'prompt': ['Are you sure you want to remove Tulip?', 'Remove', 'Cancel'],
                 'panel': ['Inventory', 'Seeds'],  # detail screens also say Seeds (the description)
                 'detail': [self.detail, 'Plant these seeds', 'Select'] if getattr(self, 'detail', None) else []
                 }.get(self.screen, [])
        return {'mode': 'gameplay' if self.screen == 'gameplay' else 'overlay',
                'text': [f'{i}) {t}' for i, t in enumerate(texts)]}

    def find_text(self, label, exact=False):
        hits = []
        for i, t in enumerate(self.state()['text']):
            t = t.split(') ', 1)[1]
            if (t.lower() == label.lower()) if exact else (label.lower() in t.lower()):
                hits.append({'text': t, 'cx': 100, 'cy': 100 + i})
        return hits

    CARDS = {118: 'Green Bean Seeds', 260: 'Carrot Seeds', 400: 'Tulip Bulbs'}

    def grab(self):
        return FakeImg()

    def ocr_image(self, img, scale=None, offset=(0, 0)):
        if self.screen == 'detail':
            return [{'text': self.detail, 'cx': 300, 'cy': 350}]
        if self.screen != 'panel':
            return []
        return [{'text': n, 'cx': x, 'cy': 592} for x, n in zip(self.CARDS, ('26', '10', '22'))]

    def _featureprint(self, img):
        v = [0.0, 0.0, 0.0]
        cx = (img.box[0] + img.box[2]) / 2 if img.box else 0
        if cx in self.CARDS:
            v[list(self.CARDS).index(cx)] = 1.0
        return v

    def wait_settle(self):
        pass

    def world(self):
        g = self

        class W:
            belief = None

            def needs_fix(self):
                return False

            def tara(self):
                return ('Farm', *g.at, 0.1) if isinstance(g.at, tuple) else ('Farm', 99.0, 99.0, 0.1)
        return W()

    def world_sync(self):
        pass

    def grab(self, crop=True):
        return FakeImg()

    def find_bubbles(self, img):                    # the well shows its can bubble when she is there
        return [(500, 300)] if self.at == 'well' else []

    def bubble_kind(self, img, b):
        return getattr(self, 'bubble_name', 'fill_can'), 0.1

    def bubble_highlighted(self, img, b):
        return True

    def calib_load(self, area):
        return None                                   # no projection in the fake: walk uses goto_point

    def goto_point(self, scene, x, z, r=None):
        return self.go_world(x, z, radius=r)

    def go_world(self, x, z, max_rounds=2, radius=None):
        self.at = (x, z)
        return f'ARRIVED ({x}, {z})'

    def goto(self, name):
        self.at = name
        return f'ARRIVED {name}'

    def places(self):
        return {'well': (0, 0)}

    def graph_route(self, name):
        return None

    def farm_status(self):
        return {'crops': self.crops}

    def run_log(self, type_, **kw):
        self.events.append({'type': type_, **kw})

    def run_action(self, spec):
        kind, _, arg = spec.partition(':')
        if spec == 'key:space' or (spec == 'click:500:300' and self.at == 'well'):
            self._space()
        elif kind == 'click':
            x, y = (int(v) for v in arg.split(':'))
            if self.screen == 'panel' and x in self.CARDS:
                self.detail, self.screen = self.CARDS[x], 'detail'
            else:
                self._click(self.state()['text'][y - 100].split(') ', 1)[1])
        elif spec == 'key:escape':
            self.screen = 'panel' if self.screen == 'detail' else 'gameplay'
        return None

    # --- game behaviour
    def _crop(self):
        return next((c for c in self.crops if (float(c['x']), float(c['z'])) == self.at), None)

    def _pos(self):
        return f' at ({self.at[0]}, 0.10, {self.at[1]})'

    def _space(self):
        if self.at == 'well':
            self.clicks_at_well = getattr(self, 'clicks_at_well', 0) + 1
            if getattr(self, 'says_full', False):
                self.log.append(getattr(self, 'says_text', '[D148 8:00:00 PM] My watering can is already full!'))
                return
            self.log.append('[D148 7:57:24 PM] > full_watering_can me=Player target=Well')
            self.can_full = True
            return
        c = self._crop()
        if self.screen == 'card':
            self.screen = 'prompt'
        elif self.screen == 'gameplay' and c and c['isWilted'] == 'true':
            self.log.append('> unplant me=Player target=GardenBed' + self._pos())
            self.screen = 'card'
        elif self.screen == 'gameplay' and c and c['plantState'] == '##0':
            self.log.append('> plant me=Player target=GardenBed' + self._pos())
            self.screen, self.detail = 'detail', 'Green Bean Seeds'   # opens on the first card's detail (D148)
        elif self.screen == 'gameplay' and c and self.can_full:
            self.log.append('> water me=Player target=GardenBed' + self._pos())
            c['isWatered'], self.can_full = 'true', False
        elif self.screen == 'gameplay' and c:
            self.log.append('> out_of_water me=Player target=GardenBed' + self._pos())

    def _click(self, text):
        c = self._crop()
        if self.screen == 'prompt' and text == 'Remove':
            self.log.append('> unplant_impl me=Player target=GardenBed' + self._pos())
            c.update(plantState='##0', isWilted='false')
            self.screen = 'gameplay'
        elif self.screen == 'detail' and text == 'Select' and self.detail.startswith(('Tulip', 'Green Bean')):
            self.log.append('[STATS] totalPlanted.TulipSeed = 65' if self.detail.startswith('Tulip')
                            else '[STATS] totalPlanted.#-145752244 = 52')   # D183: Green Bean's stat is a hash
            self.log.append('> plant me=Player target=GardenBed' + self._pos())   # logged as the panel closes
            c.update(plantState='##growing')
            self.screen = 'gameplay'


class Game(unittest.TestCase):
    def setUp(self):
        self.g = FakeGame()
        game.bind(self.g)
        self.graph_copy()                      # skills save the graph: never the live one
        track.LINES.clear()
        import tempfile
        from game import items
        items.ITEM_DIR, items._REFS = tempfile.mkdtemp(), []
        from evals import store
        store.PATH = os.path.join(tempfile.mkdtemp(), 'predictions.jsonl')   # never the real store

    def fake_goto(self, calls=None):
        from objects import loop
        from game import well
        g = self.g

        def goto(q, wf, **kw):
            if calls is not None:
                calls.append(q)
            g.at = 'well'
            return loop.Arrival(None, 'Farm', (500, 300), 1)
        self.old_goto, well.loop.goto = well.loop.goto, goto
        self.addCleanup(setattr, well.loop, 'goto', self.old_goto)
        return goto

    def graph_copy(self):
        import shutil
        import tempfile
        from game import well
        from objects import graph as OG
        p = os.path.join(tempfile.mkdtemp(), 'Farm.json')
        shutil.copy(os.path.join(OG.DEFAULT_DIR, 'Farm.json'), p)
        self.old_graph, well.GRAPH = well.GRAPH, p
        self.addCleanup(setattr, well, 'GRAPH', self.old_graph)
        return p

    def test_fill_can_bubble_already_on_screen_one_click(self):
        from objects import graph as OG
        p = self.graph_copy()
        calls = []
        self.fake_goto(calls)
        self.g.at = 'well'                                   # the can bubble shows: no goto
        line = game.fill_can()
        self.assertEqual(calls, [])
        self.assertEqual(self.g.clicks_at_well, 1)
        self.assertIn('target=Well', line)
        g = OG.Graph()
        g.load(p)
        self.assertEqual(g.state_value('Well', 'can'), 'full')
        self.assertEqual(g.node('Well').state['can']['source'], 'log')

    def test_fill_can_goes_to_the_well_then_clicks_its_bubble(self):
        p = self.graph_copy()
        calls = []
        self.fake_goto(calls)
        self.g.at = None
        game.fill_can()
        self.assertEqual([(q.kind) for q in calls], ['Well'])
        self.assertEqual(self.g.clicks_at_well, 1)

    def test_fill_can_already_full_counts_as_done(self):
        p = self.graph_copy()
        self.fake_goto()
        self.g.says_full = True
        line = game.fill_can()
        self.assertIn('already full', line)

    def test_fill_can_full_can_bubble_named_full_watering_can(self):
        self.graph_copy()
        calls = []
        self.fake_goto(calls)
        self.g.at = 'well'
        self.g.bubble_name, self.g.says_full = 'full_watering_can', True
        self.g.says_text = 'Player: My watering can is already full!'
        line = game.fill_can()
        self.assertEqual(calls, [])
        self.assertIn('already full', line)

    def test_fill_can_need_vision_propagates(self):
        from objects import loop
        from game import well
        self.graph_copy()
        old = well.loop.goto
        def boom(q, wf, **kw):
            raise loop.NeedVision('/x/ask-1.png')
        well.loop.goto = boom
        self.addCleanup(setattr, well.loop, 'goto', old)
        with self.assertRaises(loop.NeedVision):
            game.fill_can()

    def test_goto_bed_queries_the_state_and_returns_the_arrival(self):
        from objects import loop
        from game import garden
        seen = []
        arr = loop.Arrival(None, 'Garden', (1, 2), 1)
        old = garden.loop.goto
        garden.loop.goto = lambda q, wf, **kw: (seen.append(q), arr)[1]
        self.addCleanup(setattr, garden.loop, 'goto', old)
        self.assertIs(game.goto_bed(crop=None), arr)
        self.assertEqual((seen[0].kind, seen[0].state), ('GardenBed', {'crop': None}))

    def test_beds_numbered_and_filtered(self):
        bs = game.beds()
        self.assertEqual([b.id for b in bs], [1, 2])
        self.assertEqual([b.id for b in game.beds(wilted=True)], [1])
        self.g.crops[1]['plantState'] = '##0'
        self.assertEqual([b.id for b in game.beds(empty=True)], [2])
        self.assertEqual(str(bs[0]), 'bed 1 (0.8, -29.1) growing wilted')

    def test_replant_with_confirmation_inside(self):
        game.replant(1)
        self.assertIn('> unplant_impl', '\n'.join(self.g.log))   # the "Remove?" confirmation was answered inside
        self.assertIn('totalPlanted.TulipSeed', '\n'.join(self.g.log))
        self.assertEqual(self.g.crops[0]['isWatered'], 'false')    # M3: replant doesn't water (one job each)
        names = [(e['depth'], e['name']) for e in self.g.events if e['type'] == 'action']
        self.assertIn((0, 'garden.replant'), names)
        self.assertIn((1, 'garden.unplant'), names)
        self.assertNotIn('garden.water', [n for _, n in names])
        self.assertTrue(all(e['ok'] for e in self.g.events if e['type'] == 'action'))

    def test_water_refills_at_the_well(self):
        self.g.can_full = False
        self.loop_goto = self.fake_goto()
        game.water(2)
        log = '\n'.join(self.g.log)
        self.assertIn('> out_of_water', log)                       # the game said the can is empty …
        self.assertIn('target=Well', log)                           # … so it filled the can
        self.assertEqual(self.g.crops[1]['isWatered'], 'true')

    def test_water_does_not_go_to_the_well_without_cause(self):
        self.g.can_full = True
        game.water(2)
        self.assertNotIn('target=Well', '\n'.join(self.g.log))

    def test_water_next_consumes_the_bed_the_active_bubble_actually_used(self):
        from game import affordances, garden
        from types import SimpleNamespace
        self.g.crops[0]['isWilted'] = 'false'
        old_scan, old_run = affordances.scan, self.g.run_action

        affordances.scan = lambda: [affordances.Affordance(
            'water', SimpleNamespace(x=3.34, z=-29.09), (500, 300), False, 0.1)]

        def run_action(spec):
            self.assertEqual(spec, 'click:500:300')
            self.g.at = (3.34, -29.09)  # another simultaneously active bed, not beds_due()[0]
            self.g._space()

        self.g.run_action = run_action
        self.addCleanup(setattr, affordances, 'scan', old_scan)
        self.addCleanup(setattr, self.g, 'run_action', old_run)
        actual = game.water_next()
        self.assertEqual(actual.id, 2)
        self.assertIn('> water', '\n'.join(self.g.log))
        self.g.crops[1]['isWatered'] = 'false'  # simulate a save that has not caught up with the exact log yet
        self.assertEqual([b.id for b in garden.beds_due()], [1])

    def test_due_water_bubble_rejects_an_owner_not_in_the_due_set(self):
        from game import affordances, garden
        from types import SimpleNamespace
        old_scan = affordances.scan
        affordances.scan = lambda: [affordances.Affordance(
            'water', SimpleNamespace(x=3.34, z=-29.09), (500, 300), False, 0.1)]
        self.addCleanup(setattr, affordances, 'scan', old_scan)
        self.assertFalse(garden._click_due_water_bubble([game.bed(1)]))

    def test_unplant_refuses_healthy_plant(self):
        with self.assertRaises(game.Failed) as e:
            game.unplant(2)
        self.assertIn('not wilted', str(e.exception))
        self.assertTrue(track.LINES[-1].startswith('✗ garden.unplant'))

    def test_unplant_does_not_press_an_incompatible_neighbour_bubble(self):
        from game import affordances, walk
        from types import SimpleNamespace
        old_use, old_scan, old_click = affordances.use, affordances.scan, walk.click_object
        affordances.use = lambda action, target: False
        affordances.scan = lambda: [affordances.Affordance(
            'beehive_progress', SimpleNamespace(x=5.22, z=-23.46), (500, 300), True, 0.1)]
        walk.click_object = lambda target: False
        self.addCleanup(setattr, affordances, 'use', old_use)
        self.addCleanup(setattr, affordances, 'scan', old_scan)
        self.addCleanup(setattr, walk, 'click_object', old_click)
        with self.assertRaises(game.Failed) as e:
            game.unplant(1)
        self.assertIn('other bubbles are visible', str(e.exception))
        self.assertNotIn('beehive_progress', '\n'.join(self.g.log))

    def _visible(self, healthy_first=True):
        """Screen bubbles from the beds' state (no geometry): empty → plant; planted and dry/wilted → drop sub-icon."""
        from game import affordances
        pts = {0: (500, 300), 1: (600, 300)}
        def scan():
            out = []
            for i, c in enumerate(self.g.crops):
                empty = c['plantState'] == '##0'
                out.append(affordances.Affordance('plant' if empty else 'unknown', None, pts[i], i == 1, 0.8,
                                                  not empty and c['isWatered'] == 'false'))
            return sorted(out, key=lambda a: a.pt[0], reverse=healthy_first)
        def run_action(spec):
            for i, pt in pts.items():
                if spec == f'click:{pt[0]}:{pt[1]}':
                    c = self.g.crops[i]
                    self.g.at = (float(c['x']), float(c['z']))
                    self.g.can_full = True               # a can with enough water for the test
                    self.g._space()
                    return
            old_run(spec)
        old_scan, old_run = affordances.scan, self.g.run_action
        affordances.scan, self.g.run_action = scan, run_action
        self.addCleanup(setattr, affordances, 'scan', old_scan)
        self.addCleanup(setattr, self.g, 'run_action', old_run)

    def test_drop_sub_icon_on_real_bubbles(self):            # user, D183: the drop goes with any crop icon
        from game import affordances
        from PIL import Image
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bubbles')
        drop = {'water/water-20261030-185207.png', 'water/water-20261031-155650.png',
                'unplant/unplant-20261101-183642.png', 'unplant/unplant-20261030-184236.png'}
        none = {'plant/plant-20261030-184926.png', 'unplant/unplant-20261030-184331.png',
                'water/water-20261030-184954.png', 'fill_can/fill_can-20261029-094417.png', 'talk/talk-live1.png'}
        for f in drop | none:
            self.assertEqual(affordances.has_drop(Image.open(os.path.join(d, f))), f in drop, f)

    def test_replant_visible_waters_dry_beds_then_fixes_the_wilted_one(self):
        self._visible()
        b = game.replant_visible()
        log = '\n'.join(self.g.log)
        self.assertEqual((b.x, b.z), (0.84, -29.09))
        self.assertIn('> water me=Player target=GardenBed at (3.34, 0.10, -29.09)', log)   # dry bed on the way
        self.assertIn('> unplant_impl', log)
        self.assertIn('totalPlanted.TulipSeed', log)
        self.assertIn('> water me=Player target=GardenBed at (0.84, 0.10, -29.09)', log)   # the replanted bed
        self.assertEqual(self.g.crops[0]['isWatered'], 'true')

    def test_replant_visible_same_crop_by_log_not_geometry(self):
        from game import garden
        old_goto = garden.goto
        garden.goto = lambda b: self.fail('visible bed must not navigate')
        self.addCleanup(setattr, garden, 'goto', old_goto)
        self._visible()
        b = game.replant_visible()                       # seed=None: the crop the wilted card names (Tulip)
        log = '\n'.join(self.g.log)
        self.assertEqual((b.x, b.z), (0.84, -29.09))     # the bed the log named
        self.assertIn('> unplant_impl', log)
        self.assertIn('totalPlanted.TulipSeed', log)
        self.assertEqual(log.count('> unplant '), 1)     # the healthy bed was only looked at

    def test_crop_name_from_card(self):
        from game import garden
        self.assertEqual(garden.crop_name('Green Bean / The unripe fruit of the / This plant has wilted.'),
                         'Green Bean')

    def test_plant_visible_needs_exactly_one_plant_bubble(self):
        for c in self.g.crops:
            c.update(plantState='##0', isWilted='false')
        self._visible()
        with self.assertRaises(game.Failed) as e:
            game.plant_visible('Tulip')
        self.assertIn('2 plant bubbles', str(e.exception))
        self.assertEqual(self.g.log, [])

    def test_press_refuses_space_when_only_foreign_bubbles_are_visible(self):
        from game import affordances
        from types import SimpleNamespace
        old_scan = affordances.scan
        affordances.scan = lambda: [affordances.Affordance(
            'unplant', SimpleNamespace(kind='GardenBed', x=5.84, z=-29.09), (500, 300), True, 0.1)]
        self.addCleanup(setattr, affordances, 'scan', old_scan)
        with self.assertRaises(game.Failed) as e:
            affordances.press('plant', game.bed(1))
        self.assertIn('no plant bubble', str(e.exception))
        self.assertEqual(self.g.log, [])

    def test_plant_stops_when_the_click_opened_another_bed(self):
        from game import affordances
        old_press = affordances.press
        def wrong(action, target):
            self.g.log.append('> unplant me=Player target=GardenBed at (5.84, 0.10, -29.09)')
            self.g.screen = 'card'
        affordances.press = wrong
        self.addCleanup(setattr, affordances, 'press', old_press)
        self.g.crops[0].update(isWilted='false', plantState='##0')
        with self.assertRaises(game.Failed) as e:
            game.plant(1)
        self.assertIn('another bed', str(e.exception))
        self.assertEqual(self.g.screen, 'gameplay')        # the wrong bed's card was closed, nothing removed

    def test_failure_names_the_missing_proof(self):
        self.g.crops[0].update(isWilted='false', plantState='##produced')   # a ripe bed won't open a panel
        with self.assertRaises(game.Failed) as e:
            game.plant(1)
        self.assertIn('planting panel did not open', str(e.exception))

    def test_pick_card_accepts_the_detail_it_opened_on_when_the_title_band_misses(self):
        # D183: panel opened on "Green Bean Seeds"; the fixed title band read '' and count "6" was missed → 2 cards
        self.g.crops[0].update(isWilted='false', plantState='##0')
        self._visible()
        self.g.ocr_image = lambda img, scale=None, offset=(0, 0): []    # the band OCR and the counts both miss
        b = game.plant_visible('Green Bean', at=(0.84, -29.09))
        self.assertEqual((b.x, b.z), (0.84, -29.09))
        self.assertIn('totalPlanted.#-145752244', '\n'.join(self.g.log))

    def test_pick_card_opens_the_highlighted_first_card(self):
        # D183 (user): the panel opens with the first card HIGHLIGHTED (its name on screen, no Select yet) and its
        # count "6" isn't read → it must still click the first slot (planting-panel.md ≈110,540)
        self.g.crops[0].update(isWilted='false', plantState='##0')
        self._visible()
        self.g.CARDS = {110: 'Green Bean Seeds', 260: 'Carrot Seeds', 400: 'Tulip Bulbs'}
        old_space, old_state = self.g._space, self.g.state
        def space():
            if self.g.screen == 'gameplay' and self.g._crop()['plantState'] == '##0':
                self.g.log.append('> plant_open')       # not a real log line; the real `> plant` comes on close
                self.g.screen = 'panel'
            else:
                old_space()
        def state():
            st = old_state()
            if self.g.screen == 'panel':
                st['text'].append('9) Green Bean Seeds')  # the highlighted card's name
            return st
        self.g._space, self.g.state = space, state
        self.g.ocr_image = lambda img, scale=None, offset=(0, 0): (
            [{'text': n, 'cx': x, 'cy': 600} for x, n in ((260, '10'), (400, '4'))]
            if self.g.screen == 'panel' else [])        # counts: "6" missed, 10 and 4 read
        b = game.plant_visible('Green Bean', at=(0.84, -29.09))
        self.assertEqual((b.x, b.z), (0.84, -29.09))
        self.assertIn('totalPlanted.#-145752244', '\n'.join(self.g.log))

    def test_any_failure_asks_vision_once_with_the_innermost_frame(self):   # user, D183: uncertainty → vision
        from game import core
        n = len(core.VISION_ASKS)
        self.g.crops[0].update(isWilted='false', plantState='##produced')   # a ripe bed won't open a panel
        with self.assertRaises(game.Failed) as e:
            game.replant(1)                                                   # replant → unplant fails inside
        self.assertEqual(str(e.exception).count('NEED_VISION'), 1)
        self.assertEqual(len(core.VISION_ASKS), n + 1)

    def test_press_prefers_the_exact_button(self):
        self.g.screen = 'prompt'
        self.g.at = (0.84, -29.09)
        game.press('Remove')
        self.assertIn('> unplant_impl', '\n'.join(self.g.log))   # not the question "…remove Tulip?"

    def test_item_icons_learned_then_used(self):
        from game import items
        self.g.crops[1].update(plantState='##0', isWilted='false')
        game.plant(2)                                         # 1st time: clicks through, learns every card opened
        self.assertEqual(sorted(n for n, _, _ in items._REFS), ['Carrot_Seeds', 'Green_Bean_Seeds', 'Tulip_Bulbs'])
        clicks = []
        orig = self.g.run_action
        self.g.run_action = lambda spec: (clicks.append(spec), orig(spec))[1]
        self.g.crops[1].update(plantState='##0', isWatered='false')
        self.g.can_full = True
        game.plant(2)                                         # 2nd time: the Tulip card is known by its icon
        self.assertEqual([c for c in clicks if c.startswith('click:') and c.split(':')[1] in ('118', '260', '400')],
                         ['click:400:532'])

    def test_stuck_asks_for_the_next_step(self):
        class Stuck(Exception):
            pass

        def stuck(*a, **k):
            raise Stuck('STUCK (L75): position within 2 units')
        self.g.goto_point = stuck
        self.g.seg_estimate = lambda: ('Farm', -1.3, -21.7)
        asked = []
        self.g.stuck_vision = lambda place, d, why: (asked.append((place, d)), 'NEED_VISION step: GOAL …')[1]
        with self.assertRaises(game.Failed) as e:
            game.unplant(1)
        self.assertIn('NEED_VISION step', str(e.exception))
        self.assertEqual(len(asked), 1)

    def test_skills_hook_records_hit_and_miss(self):
        import evals
        from evals import store
        store.PATH = os.path.join(__import__('tempfile').mkdtemp(), 'p.jsonl')
        game.replant(1)
        with self.assertRaises(game.Failed):
            game.unplant(2)                                   # healthy plant: refused = a miss
        r = evals.report()['skills']
        self.assertEqual((r['hits'], r['misses']), (1, 1))    # nested actions are not counted



    def test_waits(self):
        ev = [{'type': 'call', 'start': 0, 'end': 2, 'cmd': 'py replant'},
              {'type': 'action', 'name': 'garden.replant', 'start': 0, 'end': 2, 'depth': 0, 'ok': True,
               'after': 'overlay: Tulip Bulbs'},
              {'type': 'call', 'start': 7, 'end': 8, 'cmd': 'py water'}]
        w = track.waits(ev)
        self.assertEqual(w['actions']['garden.replant'], [1, 2, 0])
        self.assertEqual(w['thinking'], [(5.0, 'overlay: Tulip Bulbs')])


if __name__ == '__main__':
    unittest.main()
