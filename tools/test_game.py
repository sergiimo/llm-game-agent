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
        texts = {'card': ['This plant has wilted. You should remember to water plants every day'],
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
        if spec == 'key:space':
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
            self.log.append('> fill_watering_can me=Player target=Well')
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

    def _click(self, text):
        c = self._crop()
        if self.screen == 'prompt' and text == 'Remove':
            self.log.append('> unplant_impl me=Player target=GardenBed' + self._pos())
            c.update(plantState='##0', isWilted='false')
            self.screen = 'gameplay'
        elif self.screen == 'detail' and text == 'Select' and self.detail.startswith('Tulip'):
            self.log.append('[STATS] totalPlanted.TulipSeed = 65')
            c.update(plantState='##growing')
            self.screen = 'gameplay'


class Game(unittest.TestCase):
    def setUp(self):
        self.g = FakeGame()
        game.bind(self.g)
        track.LINES.clear()
        import tempfile
        from game import items
        items.ITEM_DIR, items._REFS = tempfile.mkdtemp(), []

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
        self.assertEqual(self.g.crops[0]['isWatered'], 'true')
        names = [(e['depth'], e['name']) for e in self.g.events if e['type'] == 'action']
        self.assertIn((0, 'garden.replant'), names)
        self.assertIn((1, 'garden.unplant'), names)
        self.assertIn((2, 'garden.water'), names)                 # plant() waters its bed
        self.assertTrue(all(e['ok'] for e in self.g.events if e['type'] == 'action'))

    def test_water_refills_at_the_well(self):
        self.g.can_full = False
        game.water(2)
        self.assertIn('target=Well', '\n'.join(self.g.log))
        self.assertEqual(self.g.crops[1]['isWatered'], 'true')

    def test_unplant_refuses_healthy_plant(self):
        with self.assertRaises(game.Failed) as e:
            game.unplant(2)
        self.assertIn('not wilted', str(e.exception))
        self.assertTrue(track.LINES[-1].startswith('✗ garden.unplant'))

    def test_failure_names_the_missing_proof(self):
        self.g.crops[0].update(isWilted='false', plantState='##produced')   # a ripe bed won't open a panel
        with self.assertRaises(game.Failed) as e:
            game.plant(1)
        self.assertIn('planting panel did not open', str(e.exception))

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
