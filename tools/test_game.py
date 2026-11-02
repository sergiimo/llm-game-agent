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

    def grab(self, crop=True):
        return FakeImg()

    def find_bubbles(self, img):                    # the well shows its can bubble when she is there
        return [(500, 300)] if self.at == 'well' else []

    def bubble_kind(self, img, b):
        return getattr(self, 'bubble_name', 'fill_can'), 0.1

    def bubble_highlighted(self, img, b):
        return True

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
        self.assertEqual(g.node('Well').state['can']['source'], 'event')

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

    def test_fill_can_goto_fills_then_asks_counts_as_done(self):
        """L126 live: the click on the well walked there and filled the can (log event), but goto still waited for the
        bubble and asked vision; the log event is the proof, no NeedVision, no extra clicks."""
        from objects import loop
        from game import well
        self.graph_copy()
        old = well.loop.goto
        def fills_then_asks(q, wf, **kw):
            self.g.log.append('[D184 8:45:20 AM] > fill_watering_can me=Player target=Well')
            raise loop.NeedVision('/x/ask-1.png')
        well.loop.goto = fills_then_asks
        self.addCleanup(setattr, well.loop, 'goto', old)
        line = game.fill_can()
        self.assertIn('fill_watering_can', line)
        self.assertEqual(getattr(self.g, 'clicks_at_well', 0), 0)

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

    def test_crop_name_from_card(self):
        from game import garden
        self.assertEqual(garden.crop_name('Green Bean / The unripe fruit of the / This plant has wilted.'),
                         'Green Bean')

    def test_pick_card_accepts_the_detail_it_opened_on_when_the_title_band_misses(self):
        # D183: panel opened on "Green Bean Seeds"; the fixed title band read '' and count "6" was missed → 2 cards
        self.g.screen, self.g.detail = 'detail', 'Green Bean Seeds'
        self.g.ocr_image = lambda img, scale=None, offset=(0, 0): []    # the band OCR and the counts both miss
        self.assertEqual(game.ui.pick_card('Green Bean'), 'Green Bean')
        self.assertEqual(self.g.log, [])

    def test_pick_card_opens_the_highlighted_first_card(self):
        # D183 (user): the panel opens with the first card HIGHLIGHTED (its name on screen, no Select yet) and its
        # count "6" isn't read → it must still click the first slot (planting-panel.md ≈110,540)
        self.g.screen = 'panel'
        self.g.CARDS = {110: 'Green Bean Seeds', 260: 'Carrot Seeds', 400: 'Tulip Bulbs'}
        old_state = self.g.state
        def state():
            st = old_state()
            if self.g.screen == 'panel':
                st['text'].append('9) Green Bean Seeds')  # the highlighted card's name
            return st
        self.g.state = state
        self.g.ocr_image = lambda img, scale=None, offset=(0, 0): (
            [{'text': n, 'cx': x, 'cy': 600} for x, n in ((260, '10'), (400, '4'))]
            if self.g.screen == 'panel' else [])        # counts: "6" missed, 10 and 4 read
        self.assertEqual(game.ui.pick_card('Green Bean'), 'Green Bean Seeds')

    def test_any_failure_asks_vision_once_with_the_innermost_frame(self):   # user, D183: uncertainty → vision
        from game import core
        n = len(core.VISION_ASKS)

        @core.action
        def inner():
            raise game.Failed('no proof')

        @core.action
        def outer():
            inner()
        with self.assertRaises(game.Failed) as e:
            outer()                                                           # inner fails; outer must not ask again
        self.assertEqual(str(e.exception).count('NEED_VISION'), 1)
        self.assertEqual(len(core.VISION_ASKS), n + 1)

    def test_press_prefers_the_exact_button(self):
        self.g.screen = 'prompt'
        self.g.at = (0.84, -29.09)
        game.press('Remove')
        self.assertIn('> unplant_impl', '\n'.join(self.g.log))   # not the question "…remove Tulip?"

    def test_item_icons_learned_then_used(self):
        from game import items
        self.g.screen, self.g.detail = 'detail', 'Green Bean Seeds'
        game.ui.pick_card('Tulip')                            # 1st time: clicks through, learns every card opened
        self.assertEqual(sorted(n for n, _, _ in items._REFS), ['Carrot_Seeds', 'Green_Bean_Seeds', 'Tulip_Bulbs'])
        clicks = []
        orig = self.g.run_action
        self.g.run_action = lambda spec: (clicks.append(spec), orig(spec))[1]
        self.g.screen, self.g.detail = 'detail', 'Green Bean Seeds'
        game.ui.pick_card('Tulip')                            # 2nd time: the Tulip card is known by its icon
        self.assertEqual([c for c in clicks if c.startswith('click:') and c.split(':')[1] in ('118', '260', '400')],
                         ['click:400:532'])

    def test_stuck_asks_for_the_next_step(self):
        class Stuck(Exception):
            pass

        def stuck(*a, **k):
            raise Stuck('STUCK (L75): position within 2 units')
        self.g.goto = stuck
        self.g.seg_estimate = lambda: ('Farm', -1.3, -21.7)
        asked = []
        self.g.stuck_vision = lambda place, d, why: (asked.append((place, d)), 'NEED_VISION step: GOAL …')[1]
        with self.assertRaises(game.Failed) as e:
            game.goto('Garden')
        self.assertIn('NEED_VISION step', str(e.exception))
        self.assertEqual(len(asked), 1)

    def test_skills_hook_records_hit_and_miss(self):
        import evals
        from evals import store
        store.PATH = os.path.join(__import__('tempfile').mkdtemp(), 'p.jsonl')

        @core.action
        def good():
            return 1

        @core.action
        def bad():
            raise game.Failed('refused')
        good()
        with self.assertRaises(game.Failed):
            bad()                                             # refused = a miss
        r = evals.report()['skills']
        self.assertEqual((r['hits'], r['misses']), (1, 1))

    def test_waits(self):
        ev = [{'type': 'call', 'start': 0, 'end': 2, 'cmd': 'py replant_all'},
              {'type': 'action', 'name': 'garden.replant_all', 'start': 0, 'end': 2, 'depth': 0, 'ok': True,
               'after': 'overlay: Tulip Bulbs'},
              {'type': 'call', 'start': 7, 'end': 8, 'cmd': 'py water'}]
        w = track.waits(ev)
        self.assertEqual(w['actions']['garden.replant_all'], [1, 2, 0])
        self.assertEqual(w['thinking'], [(5.0, 'overlay: Tulip Bulbs')])


if __name__ == '__main__':
    unittest.main()
