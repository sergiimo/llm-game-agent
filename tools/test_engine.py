"""Offline tests for the generic gameplay engine (spec 2026-11-03): FakeGame + world, table, steps, ask, loop, learning.
Run: .venv/bin/python -m unittest tools/test_engine.py"""
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import act, affordances, ask, core, engine, icons, learn, nav, observe, plan, screen, smoke, steps, ui, where, world  # noqa: E402
from game.ask import NeedVision  # noqa: E402
from objects import graph as OG  # noqa: E402
from game.affordances import Affordance  # noqa: E402

core.LOG_WAIT = 0.0
SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')


def _fits(when, state):
    """A `when` dict ({key: value | "a|b"}) holds for `state` (missing key = None)."""
    for k, v in (when or {}).items():
        got = state.get(k)
        if isinstance(v, str) and '|' in v:
            if str(got) not in v.split('|'):
                return False
        elif got != v and not (isinstance(v, str) and str(got) == v):
            return False
    return True


class FakeGame:
    """A data-driven game seen from Tara (frame centre), independent of the engine's own table.

    objects: [{'id', 'kind', 'pos': (x, z), 'state': {...}, 'zone', 'bubble_pt', 'body_pt'?, 'save'?: {raw fields}}]
    behaviour: [{'kind', 'when', 'bubble': {'kind'}, 'event', 'effect', 'card'?: [screen, ...], 'click_event'?,
                 'needs'?: {'Tara.can': 'full'}, 'fail_event'?, 'stats'?}]
      a screen = {'texts': [...], 'next': 'space' | 'pick' | 'press:<Label>'}; the last screen's `next` completes it.
    Bubbles: the first behaviour whose `when` holds shows its bubble kind; drop = needs water or wilted; ready = produced.
    """

    def __init__(self, objects, behaviour, inventory=None, zone='near'):
        self.objects = {o['id']: dict(o, state=dict(o['state'])) for o in objects}
        self.behaviour = behaviour
        self.inventory = dict(inventory or {})
        self.zone, self.tara = zone, {'can': 'full'}
        self.log, self.clicks, self.asks, self.runlog = [], [], [], []
        self.card = None          # {'obj', 'beh', 'i'} while a card is open
        self.picked = None
        self.walk_frames, self.step_zone, self.step_ok = 0, None, (lambda x, y: True)
        self.hour, self.minute = 13.0, 0
        self.no_pos, self.steps_needed, self.steps_done = False, 1, 0
        self.light, self.relabel, self.hide_drop = 'day', {}, False   # dusk vision: wrong kinds, no drop
        self.hide_ready = False   # live D188: a ready bed's "!" not read
        self.flash = []   # a short-lived card (a few seconds): only the burst frames' OCR sees it
        self.paused, self.blank_overlay, self.menu_clicks = False, False, []   # Escape toggles the pause menu
        self.overlay_texts = []
        self.highlight = None   # the object whose bubble Space acts on
        self.learned = []

    # ---- world rules ---------------------------------------------------------------------------------------------
    def view(self, o):
        st = dict(o['state'])
        st.update({f'Tara.{k}': v for k, v in self.tara.items()})
        return st

    def beh_of(self, o):
        return next((b for b in self.behaviour if b['kind'] == o['kind'] and _fits(b.get('when'), self.view(o))), None)

    def stamp(self):
        self.minute += 1
        return f'[D185 9:{self.minute:02d}:00 AM]'

    def emit(self, event, o):
        x, z = o['pos']
        at = '' if self.no_pos else f' at ({x}, 0.10, {z})'
        self.log.append(f'{self.stamp()} > {event} me=Player target={o["kind"]}(Clone){at}')

    def complete(self, o, b):
        need = b.get('needs') or {}
        if any(self.tara.get(k.split('.', 1)[1]) != v for k, v in need.items()):
            if b.get('fail_event'):
                self.emit(b['fail_event'], o)
            for k in need:
                self.tara[k.split('.', 1)[1]] = 'empty'
            return
        if b.get('stats'):
            self.log.append(f'[STATS] {b["stats"].replace("$seed", self.picked or "")} = 1')
        for k, v in (b.get('effect') or {}).items():
            v = self.picked if v == '$seed' else v
            if k.startswith('Tara.'):
                self.tara[k.split('.', 1)[1]] = v
            else:
                o['state'][k] = v
        if self.picked and b.get('uses_seed'):
            self.inventory[self.picked + 'Seed'] -= 1
        if b.get('event'):
            self.emit(b['event'], o)
        self.card, self.picked, self.highlight = None, None, o

    def _walk(self, zone):
        self.zone, self.walk_frames = zone, 1

    # ---- WF API --------------------------------------------------------------------------------------------------
    _FRAMES = {}

    def grab(self):
        """Real-size frames (cached): a walk makes the next frame differ."""
        from PIL import Image
        v = 0 if self.walk_frames else 200
        if self.walk_frames:
            self.walk_frames -= 1
        if v not in FakeGame._FRAMES:
            FakeGame._FRAMES[v] = Image.new('L', (1920, 1080), v)
        return FakeGame._FRAMES[v]

    def log_mark(self):
        return len(self.log)

    def log_since(self, m):
        return '\n'.join(self.log[m:])

    def _unhash(self, t):
        return t

    def wait_settle(self):
        pass

    def run_log(self, *a, **k):
        self.runlog.append((a, k))

    def run_dir(self):
        return None

    def game_stamp(self):
        return 'D185 9:00:00 AM'

    def game_hour(self, img):
        return self.hour

    def light_period(self, h):
        return self.light

    def ask_vision(self, kind, q, img, **ctx):
        self.asks.append((kind, q))
        return f'NEED_VISION {kind}: {q}'

    def event_kind(self, lines):
        m = next((re.search(r'> (\w+)', l) for l in lines if re.search(r'> (\w+)', l)), None)
        return m.group(1) if m else None

    def learn_bubble(self, crop, kind, seen):
        self.learned.append((kind, seen))
        return True

    def bubble_crop(self, img, b):
        return ('crop', b)

    def ocr_image(self, img, **k):
        return [{'text': t, 'cx': 960, 'cy': 300 + 30 * i} for i, t in enumerate(self.flash)]

    def today_log(self):
        return list(self.log), '185', list(self.log)

    def farm_status(self):
        crops = []
        for o in self.objects.values():
            if o['kind'] == 'GardenBed':
                s = o['state']
                crops.append({'x': str(o['pos'][0]), 'z': str(o['pos'][1]),
                              'plantState': '##0' if s.get('stage') == 'empty' else '##' + s.get('stage', 'growing'),
                              'isWatered': str(bool(s.get('watered'))).lower(),
                              'isWilted': str(bool(s.get('wilted'))).lower(), 'lastTimeRefreshed': '1'})
        return {'crops': crops}

    def read_save(self):
        """The save as the game writes it: scene objects with positions and userState entries, inventory, time."""
        objs = []
        for c in self.farm_status()['crops']:
            objs.append({'prefabId': {'s': 'PBED'}, 'position': {'x': float(c['x']), 'y': 0.1, 'z': float(c['z'])},
                         'actorState': {'userState': {'entries': [{'name': k, 'value': v} for k, v in c.items()
                                                                  if k not in ('x', 'z')]}}})
        for o in self.objects.values():
            if o['kind'] != 'GardenBed' and o.get('save') is not None:
                objs.append({'prefabId': {'s': 'P' + o['kind']},
                             'position': {'x': o['pos'][0], 'y': 0.1, 'z': o['pos'][1]},
                             'actorState': {'userState': {'entries': [{'name': k, 'value': v}
                                                                      for k, v in o['save'].items()]}}})
        return 'fake.sav', {'scenes': [{'sceneName': 'Farm', 'addedObjects': objs, 'updatedObjects': []}],
                            'currentPlayerPosition': {'x': 1.5, 'y': 0.1, 'z': -28.5},
                            'gameState': {'time': {'day': 185, 'timeOfDay': {'totalSeconds': 8 * 3600}},
                                          'player': {'inventory': {'items': [{'nameHash': k, 'count': v}
                                                                             for k, v in self.inventory.items()]}}}}

    def state(self):
        if self.paused:
            return {'mode': 'overlay', 'text': ['0) Game Paused', '1) Resume Game', '2) Settings', '3) Exit Game']}
        if self.blank_overlay:
            return {'mode': 'overlay', 'text': [f'{i}) {t}' for i, t in enumerate(self.overlay_texts)]}
        ts = self.texts()
        return {'mode': 'gameplay' if not ts else 'overlay', 'text': [f'{i}) {t}' for i, t in enumerate(ts)]}

    def run_action(self, a):
        if a == 'resume':
            self.paused = False
            return None
        if a == 'key:escape':
            if self.card:
                return self.close()
            self.paused = not self.paused   # no card: Escape toggles the pause menu
            return None
        if self.paused:
            self.menu_clicks.append(a)   # a click on the pause menu (Resume / Settings / Exit Game)
            return None
        if a == 'key:space':
            return self.press_bubble()
        x, y = (int(v) for v in re.match(r'click:(-?\d+):(-?\d+)', a).groups())
        self.clicks.append((x, y))
        self.flash = []
        if self.card:
            return
        for o in self.objects.values():
            bp = o.get('bubble_pt')
            if o['zone'] == self.zone and bp and abs(bp[0] - x) < 30 and abs(bp[1] - y) < 30:
                return self.interact(o)
        for o in self.objects.values():
            b = o.get('body_pt')
            if b and abs(b[0] - x) < 60 and abs(b[1] - y) < 60:
                if o['zone'] == self.zone:
                    return self.interact(o)
                return self._walk(o['zone'])
        if self.step_zone and self.step_ok(x, y):
            self.steps_done += 1   # a long way: every step walks (frames move), the zone comes after steps_needed
            self._walk(self.step_zone if self.steps_done >= self.steps_needed else self.zone)

    def interact(self, o):
        b = self.beh_of(o)
        if b is None:
            return
        if b.get('click_event'):
            self.emit(b['click_event'], o)
        if b.get('flash'):
            self.flash = [str(o['state'].get('crop')) if t == '$crop' else t for t in b['flash']]
        if b.get('card'):
            self.card = {'obj': o, 'beh': b, 'i': 0}
        else:
            self.complete(o, b)

    def scan(self):
        if self.card:   # a card hides the bubbles (game D184)
            return []
        out = []
        for o in self.objects.values():
            b = self.beh_of(o) if o['zone'] == self.zone else None
            if b is None or not o.get('bubble_pt'):
                continue
            s = o['state']
            drop = bool(s.get('wilted')) or (s.get('watered') is False and s.get('stage') in ('growing', 'producing'))
            ready = s['ready'] if 'ready' in s else s.get('stage') == 'produced'
            out.append(Affordance(self.relabel.get(b['bubble']['kind'], b['bubble']['kind']), None, tuple(o['bubble_pt']),
                                  False, 0.0, drop and not self.hide_drop, bool(ready) and not self.hide_ready))
        return out

    # ---- ui ------------------------------------------------------------------------------------------------------
    def screen(self):
        return self.card['beh']['card'][self.card['i']] if self.card else None

    def texts(self):
        sc = self.screen()
        crop = self.card['obj']['state'].get('crop') if self.card else None
        return [str(crop) if t == '$crop' else t for t in sc['texts']] if sc else []

    def shows(self, word, wait=2.0):
        return any(word.lower() in t.lower() for t in self.texts())

    def _advance(self, how):
        sc = self.screen()
        if sc is None or sc['next'] != how:
            raise core.Failed(f'{how} does nothing on {sc and sc["texts"]}')
        if self.card['i'] + 1 < len(self.card['beh']['card']):
            self.card['i'] += 1
        else:
            self.complete(self.card['obj'], self.card['beh'])

    def press(self, label):
        self._advance(f'press:{label}')

    def press_bubble(self):
        sc = self.screen()
        if sc and (sc['next'] == 'space' or (self.card['beh'].get('space_confirms') and sc['next'].startswith('press:'))):
            return self._advance(sc['next'] if sc['next'] != 'space' else 'space')
        if not sc and self.highlight is not None:   # gameplay: Space acts on the highlighted bubble (the bed just planted)
            self.interact(self.highlight)

    def pick_card(self, name):
        if not self.inventory.get(name + 'Seed'):
            raise core.Failed(f'no "{name}" among {len(self.inventory)} cards')
        self.picked = name
        self._advance('pick')
        return name

    def close(self):
        self.card, self.picked = None, None


class GeoGame(FakeGame):
    """The fake game with geometry (strategy A walking): Tara has a world position; a bed's bubble shows only within
    SHOW units of her, just above the bed's screen point; a ground click walks her to the clicked world point (the
    game pathfinds); `blocked` = clicks that don't move her."""
    SHOW = 3.0

    def __init__(self, objects, behaviour, at, save_day=185, **kw):
        super().__init__(objects, behaviour, **kw)
        self.pos, self.save_day, self.blocked, self.walks = tuple(at), save_day, False, []
        self._place()

    def _pt(self, p):
        return (round(960 + (p[0] - self.pos[0]) * 57.6), round(540 - (p[1] - self.pos[1]) * 57.6) - 40)

    def _place(self):
        import math as _m
        for o in self.objects.values():
            o['zone'] = 'near'
            o['bubble_pt'] = self._pt(o['pos']) if _m.dist(o['pos'], self.pos) <= self.SHOW else None

    def scan(self):
        self._place()
        return super().scan()

    def run_action(self, a):
        self._place()
        m = re.match(r'click:(-?\d+):(-?\d+)', a)
        if m and not self.card and not self.paused:
            x, y = int(m.group(1)), int(m.group(2))
            hit = any(o['bubble_pt'] and abs(o['bubble_pt'][0] - x) < 30 and abs(o['bubble_pt'][1] - y) < 30
                      for o in self.objects.values())
            if not hit:
                self.clicks.append((x, y))
                self.walks.append((x, y))
                if not self.blocked:
                    self.pos = (self.pos[0] + (x - 960) / 57.6, self.pos[1] - (y - 540) / 57.6)
                    self.walk_frames = 1
                self._place()
                return None
        out = super().run_action(a)
        self._place()
        return out

    frozen = None   # a save written earlier (the game autosaves rarely): read_save returns it unchanged

    def read_save(self):
        if self.frozen is not None:
            return self.frozen
        name, save = super().read_save()
        save['gameState']['time']['day'] = self.save_day
        save['currentPlayerPosition'] = {'x': self.pos[0], 'y': 0.1, 'z': self.pos[1]}
        return name, save


# ---- the game's rules as the fake knows them (D148/D149/D183/D185) -----------------------------------------------
GAME = [
    {'kind': 'GardenBed', 'when': {'wilted': True}, 'bubble': {'kind': 'unplant'}, 'click_event': 'unplant',
     'card': [{'texts': ['$crop', 'This plant has wilted.'], 'next': 'space'},
              {'texts': ['Are you sure you want to remove it?', 'Remove', 'Cancel'], 'next': 'press:Remove'}],
     'event': 'unplant_impl', 'effect': {'stage': 'empty', 'wilted': False, 'watered': False, 'crop': None}},
    {'kind': 'GardenBed', 'when': {'stage': 'empty'}, 'bubble': {'kind': 'plant'},
     'card': [{'texts': ['Inventory', 'Seeds'], 'next': 'pick'}, {'texts': ['Seeds', 'Select'], 'next': 'press:Select'}],
     'space_confirms': True,
     'event': 'plant', 'stats': 'totalPlanted.$seedSeed', 'uses_seed': True,
     'effect': {'stage': 'growing', 'crop': '$seed', 'watered': False}},
    {'kind': 'GardenBed', 'when': {'stage': 'growing|producing', 'watered': False}, 'bubble': {'kind': 'water'},
     'needs': {'Tara.can': 'full'}, 'fail_event': 'out_of_water', 'event': 'water', 'effect': {'watered': True}},
    {'kind': 'GardenBed', 'when': {'stage': 'produced'}, 'bubble': {'kind': 'pickup'}, 'event': 'grab_item',
     'card': [{'texts': ['Collect'], 'next': 'space'}],   # live D188: a Collect prompt, confirmed with Space
     'effect': {'stage': 'growing', 'watered': False}},
    {'kind': 'GardenBed', 'when': {'stage': 'growing|producing', 'watered': True}, 'bubble': {'kind': 'plant_growing'},
     'event': 'plant_growing', 'effect': {},
     'flash': ['$crop', 'A crisp orange vegetable', 'that grows in Spring.', '4 days remaining']},
    {'kind': 'Well', 'when': {'Tara.can': 'empty'}, 'bubble': {'kind': 'fill_can'}, 'event': 'fill_watering_can',
     'effect': {'Tara.can': 'full'}},
]


def obj(id, kind='GardenBed', pos=(0.0, 0.0), zone='near', bubble=(900, 400), body=None, save=None, **state):
    o = {'id': id, 'kind': kind, 'pos': pos, 'state': state, 'zone': zone, 'bubble_pt': bubble, 'body_pt': body}
    if save is not None:
        o['save'] = save
    return o


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        g = os.path.join(self.tmp.name, 'Farm.json')
        shutil.copy(SEED, g)
        where._WALK.clear()
        self.addCleanup(where._WALK.clear)
        ps = [mock.patch.object(learn, 'GRAPH', g),
              mock.patch.object(ask, 'STATE', os.path.join(self.tmp.name, 'ask-state.json')),   # never the real one
              mock.patch.object(learn, 'TRUTH', os.path.join(self.tmp.name, 'truth')),
              mock.patch.object(where, 'WALK', os.path.join(self.tmp.name, 'where-walk.json')),
              mock.patch.object(act, 'SHOTS', self.tmp.name),   # click frames: never the real .shots/clicks
              mock.patch.object(act, 'BURST', (0.0, 0.0)), mock.patch.object(act, 'EVENT_WAIT', 0.0),
              mock.patch.object(observe, 'see', lambda kind, tried=(): []),
              mock.patch.object(observe, 'see_all', lambda: []),
              mock.patch.object(nav, 'map_direction', lambda node: None)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def use(self, f):
        self.f = f
        old = core.WF
        core.bind(f)
        self.addCleanup(core.bind, old)
        for mod, name, fn in ((affordances, 'scan', f.scan), (ui, 'texts', f.texts), (ui, 'shows', f.shows),
                              (ui, 'press', f.press), (ui, 'press_bubble', f.press_bubble),
                              (ui, 'pick_card', f.pick_card), (ui, 'close', f.close)):
            p = mock.patch.object(mod, name, fn)
            p.start()
            self.addCleanup(p.stop)
        return f


class Fake(Base):
    """The fake game behaves like the game, independent of the engine's table."""

    def test_a_dry_bed_shows_a_drop_and_watering_logs_its_position(self):
        f = self.use(FakeGame([obj('a', pos=(2.64, -59.36), stage='growing', watered=False)], GAME))
        a, = f.scan()
        self.assertEqual((a.kind, a.drop, a.ready), ('water', True, False))
        act.click(a.pt, 'bubble')
        self.assertIn('> water me=Player target=GardenBed(Clone) at (2.64, 0.10, -59.36)', f.log[-1])
        self.assertEqual(f.scan()[0].kind, 'plant_growing')

    def test_a_card_opens_and_a_button_finishes_it(self):
        f = self.use(FakeGame([obj('a', stage='empty')], GAME, inventory={'TulipSeed': 2}))
        act.click(f.scan()[0].pt, 'bubble')
        self.assertTrue(ui.shows('Seeds'))
        self.assertEqual(f.scan(), [])   # the card hides the bubbles
        ui.pick_card('Tulip')
        ui.press('Select')
        self.assertEqual(f.objects['a']['state'], {'stage': 'growing', 'crop': 'Tulip', 'watered': False})
        self.assertEqual(f.inventory['TulipSeed'], 1)
        self.assertTrue(any('totalPlanted.TulipSeed' in l for l in f.log))

    def test_walking_changes_frames(self):
        f = self.use(FakeGame([obj('a', zone='south', stage='empty')], GAME))
        f.step_zone = 'south'
        self.assertEqual(f.scan(), [])
        c = act.click((960, 860), 'step')
        self.assertTrue(c.moved)
        self.assertEqual(len(f.scan()), 1)

    def test_out_of_water_empties_the_can_and_the_well_refills_it(self):
        f = self.use(FakeGame([obj('a', stage='growing', watered=False),
                               obj('w', kind='Well', pos=(1.0, -27.0), bubble=(1500, 300))], GAME))
        f.tara['can'] = 'empty'
        act.click((900, 400), 'bubble')
        self.assertIn('> out_of_water', f.log[-1])
        self.assertEqual([a.kind for a in f.scan()], ['water', 'fill_can'])
        act.click((1500, 300), 'bubble')
        self.assertEqual(f.tara['can'], 'full')


class Table(unittest.TestCase):
    """The transition table (actions.json): seeded rows, fits, BFS paths over effects."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = os.path.join(tmp.name, 'actions.json')
        shutil.copy(plan.DB, db)
        p = mock.patch.object(plan, 'DB', db)
        p.start()
        self.addCleanup(p.stop)

    def test_every_seed_row_has_the_schema(self):
        for r in plan.rows():
            self.assertTrue({'id', 'kind', 'when', 'bubble', 'steps', 'effect', 'source', 'seen', 'ok',
                             'surprises'} <= set(r), r.get('id'))
            for s in r['steps']:
                self.assertIn(s['do'], plan.PRIMITIVES)

    def test_path_from_wilted_to_planted_and_watered(self):
        p = plan.path('GardenBed', {'stage': 'growing', 'wilted': True, 'crop': 'Tulip'},
                      {'crop': '$same', 'watered': True}, {})
        self.assertEqual([r['id'] for r in p], ['remove_wilted', 'plant', 'water'])
        self.assertEqual(p[1]['needs'], {'item': 'TulipSeed'})   # the seed bound by the goal ($same crop)

    def test_a_wilted_bed_has_no_one_step_water_path(self):
        p = plan.path('GardenBed', {'stage': 'growing', 'wilted': True, 'watered': False}, {'watered': True}, {})
        self.assertTrue(p is None or p[0]['id'] != 'water')

    def test_plant_needs_the_seed_item(self):
        p = plan.path('GardenBed', {'stage': 'empty'}, {'crop': 'Tulip'}, {'seed': 'Tulip'})
        self.assertEqual(p[0]['needs'], {'item': 'TulipSeed'})
        self.assertEqual(p[0]['steps'][1]['arg'], 'Tulip')

    def test_event_effects_and_unresolved_params(self):
        self.assertEqual(plan.effects_of_event('out_of_water'), {'Tara.can': 'empty'})
        proof = ['[STATS] totalPlanted.TulipSeed = 58']
        self.assertEqual(plan.effects_of_event('plant'), {})   # the panel closed: no proof, no planting
        self.assertEqual(plan.effects_of_event('plant', lines=proof), {'stage': 'growing', 'watered': False})
        self.assertEqual(plan.effects_of_event('plant', {'seed': 'Tulip'}, proof)['crop'], 'Tulip')
        self.assertEqual(plan.effects_of_event('unplant'), {})   # opens the card only: no effect

    def test_no_path_is_none(self):
        self.assertIsNone(plan.path('BeeHive', {'ready': True}, {'ready': False}, {}))

    def test_ready_rows_only_when_the_goal_asks_for_ready(self):
        st = {'stage': 'produced', 'ready': True}
        self.assertIsNone(plan.path('GardenBed', st, {'watered': True}, {}))
        self.assertEqual(plan.path('GardenBed', st, {'ready': False}, {})[0]['id'], 'pick')

    def test_fits_by_kind_and_sub_icons(self):
        water = next(r for r in plan.rows('GardenBed') if r['id'] == 'water')
        self.assertTrue(plan.fits(water)(Affordance('water', None, (0, 0), False, 0.0, True)))
        self.assertFalse(plan.fits(water)(Affordance('water', None, (0, 0), False, 0.0, False)))   # no drop
        self.assertFalse(plan.fits(next(r for r in plan.rows() if r['id'] == 'out_of_water'))(
            Affordance('water', None, (0, 0), False, 0.0, True)))   # event-only rows fit no bubble

    def test_counts_are_saved(self):
        plan.count('water', True)
        plan.count('water', False)
        r = next(r for r in plan.rows() if r['id'] == 'water')
        self.assertEqual((r['seen'], r['ok'], r['surprises']), (2, 1, 1))


NORTH = [obj(f'n{x}{z}', pos=(x, z), stage='growing', watered=True, wilted=False)
         for z in (-25.34, -29.09, -31.59) for x in (-1.66, 0.84, 3.34, 5.84)]
SOUTH = [obj(f's{x}{z}', pos=(x, z), zone='south', stage='empty', watered=False, wilted=False)
         for z in (-59.36, -63.11, -66.86) for x in (2.64, 6.39, 10.14, 13.89)]
HIVES = [obj(f'h{x}', kind='BeeHive', pos=(x, -23.5), save={'pollen': '0'}) for x in (-2.3, -1.0, 0.2, 1.5, 2.7, 4.0, 5.2, 6.5)]


def L(t, event, kind, x, z):
    return f'[D185 {t}] > {event} me=Player target={kind}(Clone) at ({x}, 0.10, {z})'


class World(unittest.TestCase):
    """The world graph from save + log: objects of any kind, areas by distance only, filters by kind/state."""

    def setUp(self):
        self.g = OG.Graph()
        self.g.load(SEED)

    def save(self, extra=(), inventory=None):
        return FakeGame(NORTH + SOUTH + HIVES + list(extra), GAME, inventory=inventory).read_save()[1]

    def test_refresh_adds_the_south_area_with_its_12_beds(self):
        out = world.refresh(self.g, self.save(), [], None)
        self.assertEqual(len(out['GardenSouth']), 1 + 12)   # the area + its 12 beds
        self.assertEqual(self.g.nodes['GardenSouth'].region, 'Farm')
        self.assertEqual(world.count(self.g, {'kind': 'GardenBed', 'region': 'GardenSouth', 'stage': 'empty'}), 12)
        self.assertEqual(world.count(self.g, {'kind': 'GardenBed', 'region': 'Garden', 'stage': 'empty'}), 0)
        dx, dy = OG.toward(self.g, 'Garden', 'GardenSouth')
        self.assertGreater(dy, 0.9)   # south = screen down

    def test_hives_next_to_the_beds_share_their_area(self):
        world.refresh(self.g, self.save(), [], None)
        hives = world.query(self.g, {'kind': 'BeeHive'})
        self.assertEqual(len(hives), 8)
        self.assertEqual({world.area_of(self.g, h) for h in hives}, {'Garden'})

    def test_a_lone_object_is_an_area_of_one(self):
        world.refresh(self.g, self.save([obj('far', kind='BeeHive', pos=(60.0, -100.0), save={'pollen': '0'})]), [], None)
        a = world.area_of(self.g, 'BeeHive#60.0,-100.0')
        self.assertNotIn(a, (None, 'Garden', 'GardenSouth'))
        self.assertEqual(world.query(self.g, {'region': a}), ['BeeHive#60.0,-100.0'])

    def test_refresh_is_idempotent_ids_stable_and_names_kept(self):
        world.refresh(self.g, self.save(), [], None)
        n, e = len(self.g.nodes), len(self.g.edges(rel='next_to'))
        self.assertFalse(any(world.refresh(self.g, self.save(), [], None).values()))
        self.assertEqual((len(self.g.nodes), len(self.g.edges(rel='next_to'))), (n, e))
        self.assertIn('GardenBed#2.6,-59.4', self.g.nodes)
        self.assertEqual(world.area_of(self.g, 'GardenBed#2.6,-59.4'), 'GardenSouth')

    def test_log_after_the_save_wins_in_order(self):
        log = [L('7:00:00 AM', 'plant', 'GardenBed', 6.39, -59.36),   # before the save: already in it
               L('9:00:00 AM', 'unplant_impl', 'GardenBed', 2.64, -59.36),
               '[STATS] totalPlanted.TulipSeed = 58', L('9:01:00 AM', 'plant', 'GardenBed', 2.64, -59.36)]
        world.refresh(self.g, self.save(), log, 'D185 8:00:00 AM')
        self.assertEqual(self.g.state_value('GardenBed#2.6,-59.4', 'stage'), 'growing')
        self.assertEqual(self.g.state_value('GardenBed#6.4,-59.4', 'stage'), 'empty')
        self.assertEqual(world.count(self.g, {'kind': 'GardenBed', 'region': 'GardenSouth', 'stage': 'empty'}), 11)

    def test_a_new_kind_appears_from_the_log(self):
        world.refresh(self.g, self.save(), [L('9:00:00 AM', 'interact', 'Mailbox', 40.0, 10.0)], None)
        self.assertEqual(self.g.nodes['Mailbox#40.0,10.0'].kind, 'Mailbox')
        self.assertIsNotNone(world.area_of(self.g, 'Mailbox#40.0,10.0'))

    def test_an_unnamed_save_object_is_named_by_a_log_event(self):
        fences = [obj('f1', kind='Fence', pos=(20.0, -40.0), save={}), obj('f2', kind='Fence', pos=(22.0, -40.0), save={})]
        world.refresh(self.g, self.save(fences), [], None)
        self.assertEqual(world.query(self.g, {'kind': 'Fence'}), [])   # unnamed prefab: not a node yet
        world.refresh(self.g, self.save(fences), [L('9:00:00 AM', 'interact', 'Fence', 20.0, -40.0)], None)
        world.refresh(self.g, self.save(fences), [], None)
        self.assertEqual(sorted(world.query(self.g, {'kind': 'Fence'})), ['Fence#20.0,-40.0', 'Fence#22.0,-40.0'])

    def test_inventory_minus_todays_planting_after_the_save(self):
        log = ['[D185 7:00:00 AM] > plant me=Player', '[STATS] totalPlanted.TulipSeed = 56',
               '[D185 9:00:00 AM] > plant me=Player', '[STATS] totalPlanted.TulipSeed = 57',
               '[D185 9:01:00 AM] > plant me=Player', '[STATS] totalPlanted.TulipSeed = 58']
        inv = world.inventory(self.save(inventory={'TulipSeed': 18, 'CarrotSeed': 7}), log, 'D185 8:00:00 AM')
        self.assertEqual((inv['TulipSeed'], inv['CarrotSeed']), (16, 7))

    def test_tara_position_from_the_last_event_else_the_save(self):
        world.refresh(self.g, self.save(), [], None)
        self.assertEqual(world.tara_pos(self.g), (1.5, -28.5))
        world.refresh(self.g, self.save(), [L('9:00:00 AM', 'water', 'GardenBed', 2.64, -59.36)], None)
        self.assertEqual(world.tara_pos(self.g), (2.64, -59.36))
        self.assertEqual(world.area_of(self.g, world.tara_pos(self.g)), 'GardenSouth')

    def test_save_fields_become_state_raw_and_mapped(self):
        world.refresh(self.g, self.save(), [], None)
        n = 'GardenBed#0.8,-25.3'
        self.assertEqual((self.g.state_value(n, 'stage'), self.g.state_value(n, 'watered'),
                          self.g.state_value(n, 'ready'), self.g.state_value(n, 'plantState')),
                         ('growing', True, False, '##growing'))
        self.assertEqual(self.g.state_value('BeeHive#1.5,-23.5', 'pollen'), '0')   # raw field, no mapping needed

    def test_nodes_and_catalogue_list_areas_kinds_and_states(self):
        world.refresh(self.g, self.save(), [], None)
        rows = {r['area']: r for r in world.nodes(self.g)}
        self.assertEqual(rows['GardenSouth']['kinds'], {'GardenBed': 12})
        self.assertEqual(rows['Garden']['kinds'], {'GardenBed': 12, 'BeeHive': 8})
        self.assertIn('GardenSouth', world.catalogue(self.g))


class Steps(Base):
    """A row's steps run with checked expectations; each step field observed for the table's learning."""

    def setUp(self):
        super().setUp()
        self.obs = os.path.join(self.tmp.name, 'observed-steps.jsonl')
        p = mock.patch.object(steps, 'OBSERVED', self.obs)
        p.start()
        self.addCleanup(p.stop)

    def row(self, id_, **params):
        return plan.resolve(next(r for r in plan.rows() if r['id'] == id_), params)

    def test_plant_row_runs_and_reports_the_event_position(self):
        f = self.use(FakeGame([obj('a', pos=(2.64, -59.36), stage='empty')], GAME, inventory={'TulipSeed': 3}))
        out = steps.run(self.row('plant', seed='Tulip'), {'seed': 'Tulip'}, f.scan()[0])
        self.assertTrue(out['ok'], out)
        self.assertIn('plant', out['events'])
        self.assertEqual((out['at'], out['kind']), ((2.64, -59.36), 'GardenBed'))
        self.assertEqual(f.objects['a']['state']['crop'], 'Tulip')

    def test_read_card_stores_the_crop(self):
        f = self.use(FakeGame([obj('a', stage='growing', wilted=True, crop='Tulip')], GAME))
        out = steps.run(self.row('remove_wilted'), {}, f.scan()[0])
        self.assertTrue(out['ok'], out)
        self.assertEqual(out['stored'], {'crop': 'Tulip'})
        self.assertIn('unplant_impl', out['events'])

    def test_a_failed_expect_stops_and_closes_the_card(self):
        f = self.use(FakeGame([obj('a', stage='empty')], GAME, inventory={'TulipSeed': 3}))
        r = self.row('plant', seed='Tulip')
        r['steps'][0]['expect'] = {'card': 'Fishing'}
        out = steps.run(r, {'seed': 'Tulip'}, f.scan()[0])
        self.assertFalse(out['ok'])
        self.assertEqual(out['failed_step'], 0)
        self.assertIsNone(f.card)
        self.assertEqual(out['surprises'][0][:3], (0, 'card', 'Fishing'))

    def test_a_missing_item_fails_the_pick_step(self):
        f = self.use(FakeGame([obj('a', stage='empty')], GAME, inventory={}))
        out = steps.run(self.row('plant', seed='Tulip'), {'seed': 'Tulip'}, f.scan()[0])
        self.assertEqual((out['ok'], out['failed_step'], out['missing']), (False, 1, 'Tulip'))
        self.assertIsNone(f.card)

    def test_observations_are_logged_per_step_field(self):
        import json
        f = self.use(FakeGame([obj('a', stage='growing', watered=False)], GAME))
        steps.run(self.row('water'), {}, f.scan()[0])
        recs = [json.loads(l) for l in open(self.obs)]
        self.assertEqual([(r['row'], r['step'], r['field'], r['verdict']) for r in recs], [('water', 0, 'events', 'ok')])


class Ask(Base):
    """One vision question at a time; its context (pending record) survives to the call that answers it."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(ask, 'STATE', os.path.join(self.tmp.name, 'ask.json'))
        p.start()
        self.addCleanup(p.stop)
        self.use(FakeGame([], GAME))

    def pending(self):
        return {'kind': 'button', 'goal': 'plant', 'params': {'seed': 'Tulip', 'region': 'GardenSouth'},
                'row': 'plant', 'step': 2}

    def test_pending_record_survives_to_the_next_call(self):
        with self.assertRaises(NeedVision):
            ask.ask('button', 'which button plants it?', self.pending(), {'goal': 'plant', 'vision': 0})
        self.assertEqual(ask.take_answer('plant'), self.pending())
        self.assertIsNone(ask.take_answer('plant'))   # taken once
        self.assertIsNone(ask.take_answer('water'))

    def test_answer_hint_names_the_goal_not_a_task_function(self):
        with self.assertRaises(NeedVision) as cm:
            ask.ask('button', 'which button?', self.pending(), {'goal': 'plant', 'vision': 0})
        msg = str(cm.exception)
        self.assertIn('./wf achieve plant seed=Tulip region=GardenSouth answer=', msg)
        self.assertNotIn('_all(', msg)

    def test_progress_on_another_goal_keeps_this_goals_question(self):
        """Live D188: progress of plant_garden erased harvest's pending crop question (one shared state)."""
        with self.assertRaises(NeedVision):
            ask.ask('name', 'which crop?', dict(self.pending(), goal='harvest'), {'goal': 'harvest', 'vision': 0})
        ask.progress('plant_garden')
        self.assertEqual(ask.take_answer('harvest')['goal'], 'harvest')

    def test_stuck_after_max_asks_without_progress(self):
        for _ in range(ask.MAX_ASKS):
            with self.assertRaises(NeedVision):
                ask.ask('click', 'where?', self.pending(), {'goal': 'plant', 'vision': 0})
        with self.assertRaises(observe.LawsStuck):
            ask.ask('click', 'where?', self.pending(), {'goal': 'plant', 'vision': 0})
        ask.progress('plant')
        with self.assertRaises(NeedVision):
            ask.ask('click', 'where?', self.pending(), {'goal': 'plant', 'vision': 0})

    def test_laws_still_uses_the_moved_helpers(self):
        from game import laws
        self.assertIs(laws.parse_point, ask.parse_point)
        self.assertIs(laws.draw_grid, ask.draw_grid)
        self.assertEqual(laws.parse_point('Q14'), (1320, 911))


def beds(prefix, xs, zs, zone, x0, y0, **state):
    """A garden of beds with distinct bubble points in `zone`."""
    out = []
    for i, z in enumerate(zs):
        for j, x in enumerate(xs):
            out.append(obj(f'{prefix}{i}{j}', pos=(x, z), zone=zone, bubble=(x0 + 110 * j, y0 + 90 * i), **state))
    return out


NX, NZ = (-1.66, 0.84, 3.34, 5.84), (-25.34, -29.09, -31.59)
SX, SZ = (2.64, 6.39, 10.14, 13.89), (-59.36, -63.11, -66.86)


class EngineBase(Base):
    def setUp(self):
        super().setUp()
        for mod, name, path in ((ask, 'STATE', 'ask.json'), (steps, 'OBSERVED', 'obs.jsonl'), (plan, 'DB', 'actions.json')):
            if name == 'DB':
                shutil.copy(plan.DB, os.path.join(self.tmp.name, path))
            p = mock.patch.object(mod, name, os.path.join(self.tmp.name, path))
            p.start()
            self.addCleanup(p.stop)

    def graph(self):
        g = OG.Graph()
        g.load(learn.GRAPH)
        return g



class Loop(EngineBase):
    """One loop for every goal: targets from the world graph, a path from the table, nav, steps, verify, learn."""

    def test_water_goal_waters_every_dry_bed_and_stops_on_empty_query(self):
        f = self.use(FakeGame(beds('n', NX[:3], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False)
                              + beds('w', NX[3:], NZ[:1], 'near', 900, 300, stage='growing', watered=True, wilted=False),
                              GAME))
        res = engine.achieve('water')
        self.assertEqual(res['stop'], 'done: query empty')
        self.assertEqual(len(res['done']), 3)
        self.assertTrue(all(o['state']['watered'] for o in f.objects.values()))
        self.assertEqual((res['vision'], f.asks), (0, []))

    def test_refill_subgoal_then_resume_without_double_count(self):
        f = self.use(FakeGame(beds('n', NX[:2], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False)
                              + [obj('well', kind='Well', pos=(1.0, -27.0), bubble=(1500, 300))], GAME))
        f.tara['can'] = 'empty'
        res = engine.achieve('water')
        self.assertEqual(len(res['done']), 2)
        self.assertEqual(res['subgoals'], 1)
        self.assertEqual(res['stop'], 'done: query empty')
        self.assertEqual(f.tara['can'], 'full')

    def test_plant_goal_finds_the_south_garden_and_plants_12(self):
        f = self.use(FakeGame(beds('n', NX, NZ, 'near', 500, 300, stage='growing', watered=True, wilted=False)
                              + beds('s', SX, SZ, 'south', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 18}))
        f.step_zone = 'south'
        res = engine.achieve('plant', seed='Tulip', region='GardenSouth')
        self.assertEqual(res['stop'], 'done: query empty', res)
        self.assertEqual(len(res['done']), 12)
        self.assertEqual(res['vision'], 0)
        self.assertTrue(all(o['state']['crop'] == 'Tulip' for o in f.objects.values() if o['zone'] == 'south'))
        g = self.graph()
        self.assertEqual(g.nodes['GardenSouth'].extra['area'], True)
        self.assertEqual(world.count(g, {'kind': 'GardenBed', 'region': 'GardenSouth', 'crop': 'Tulip'}), 12)
        self.assertEqual(f.inventory['TulipSeed'], 6)

    def test_a_bubble_in_another_garden_is_not_a_target(self):
        f = self.use(FakeGame(beds('n', NX, NZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False)
                              + beds('s', SX[:2], SZ[:1], 'south', 500, 600, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 18}))
        f.step_zone = 'south'
        with self.assertRaises(NeedVision) as cm:   # empty beds in both gardens look alike: which one is she in?
            engine.achieve('plant', seed='Tulip', region='GardenSouth')
        self.assertIn('area=', str(cm.exception))
        self.assertTrue(all(o['state']['stage'] == 'empty' for o in f.objects.values()))
        res = engine.achieve('plant', seed='Tulip', region='GardenSouth', answer='area=GardenSouth')
        self.assertEqual(len(res['done']), 2, res)
        self.assertTrue(all(o['state']['stage'] == 'empty' for o in f.objects.values() if o['zone'] == 'near'))

    def test_replant_keeps_the_crop_read_from_the_card(self):
        f = self.use(FakeGame([obj('a', pos=NX[0:1] + NZ[0:1], bubble=(700, 400), stage='growing', wilted=True,
                                   watered=False, crop='Carrot')], GAME, inventory={'CarrotSeed': 2}))
        res = engine.achieve('replant')
        self.assertEqual(f.objects['a']['state'], {'stage': 'growing', 'wilted': False, 'watered': True, 'crop': 'Carrot'})
        self.assertEqual(res['stop'], 'done: query empty')

    def test_missing_required_param_asks_with_the_values_seen(self):
        f = self.use(FakeGame(beds('n', NX, NZ, 'near', 500, 300, stage='growing', watered=True, wilted=False)
                              + beds('s', SX, SZ, 'south', 500, 300, stage='empty', watered=False, wilted=False), GAME))
        res = engine.achieve('plant', seed='Tulip')
        self.assertTrue(res['stop'].startswith('NEED_INPUT plant: region?'), res['stop'])
        self.assertIn('GardenSouth', res['stop'])
        self.assertEqual(f.clicks, [])

    def test_missing_seed_stops(self):
        f = self.use(FakeGame(beds('n', NX, NZ, 'near', 500, 300, stage='growing', watered=True, wilted=False)
                              + beds('s', SX[:1], SZ[:1], 'south', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'CarrotSeed': 3}))
        res = engine.achieve('plant', seed='Tulip', region='GardenSouth')
        self.assertEqual(res['stop'], 'missing TulipSeed')
        self.assertEqual(f.clicks, [])

    def test_late_stops_before_any_click(self):
        f = self.use(FakeGame(beds('n', NX, NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False), GAME))
        f.hour = 23.5
        res = engine.achieve('water')
        self.assertTrue(res['stop'].startswith('late'))
        self.assertEqual(f.clicks, [])

    def test_click_cap_stops(self):
        f = self.use(FakeGame(beds('n', NX, NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False), GAME))
        res = engine.achieve('water', max_clicks=2)
        self.assertEqual(res['clicks'], 2)
        self.assertTrue(res['stop'].startswith('click cap'))

    def test_a_raw_query_goal_works_like_a_library_goal(self):
        f = self.use(FakeGame(beds('n', NX[:2], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False),
                              GAME))
        res = engine.achieve({'kind': 'GardenBed', 'where': {'watered': False, 'stage': 'growing'},
                              'make': {'watered': True}})
        self.assertEqual(len(res['done']), 2)


HIVE = {'kind': 'BeeHive', 'when': {'ready': True}, 'bubble': {'kind': 'honey'}, 'event': 'beehive_collect',
        'effect': {'ready': False}}


class Learning(EngineBase):
    """A transition the table doesn't know is learned from play (frame change / event), then replayed."""

    def hives(self, ready):
        return [obj(f'h{i}', kind='BeeHive', pos=(x, -23.5), bubble=(400 + 150 * i, 300) if i in ready else None,
                    save={'pollen': '0'}, **({'ready': True} if i in ready else {}))
                for i, x in enumerate((-2.3, -1.0, 0.2, 1.5, 2.7, 4.0, 5.2, 6.5))]

    def test_a_new_kind_is_learned_with_at_most_one_answer_then_replayed(self):
        q = {'kind': 'BeeHive', 'where': {'ready': True}, 'make': {'ready': False}}
        f = self.use(FakeGame(beds('n', NX, NZ[:1], 'near', 500, 600, stage='growing', watered=True, wilted=False)
                              + self.hives({0, 3}), GAME + [HIVE]))
        res = engine.achieve(q)
        self.assertLessEqual(res['vision'], 1)
        self.assertEqual(len(res['done']), 2, res)
        self.assertFalse(f.objects['h0']['state']['ready'] or f.objects['h3']['state']['ready'])
        row = next(r for r in plan.rows('BeeHive'))
        self.assertEqual((row['when'], row['bubble'], row['effect']), ({'ready': True}, {'kind': 'honey', 'ready': True},
                                                                        {'ready': False}))
        self.assertEqual(row['steps'], [{'do': 'click_bubble', 'expect': {'events': ['beehive_collect']}}])
        self.assertGreaterEqual(row['seen'], 2)
        f.objects['h5'].update(bubble_pt=(900, 300))
        f.objects['h5']['state']['ready'] = True   # the next day: another hive is ready
        res2 = engine.achieve(q)
        self.assertEqual((res2['vision'], len(res2['done'])), (0, 1), res2)
        self.assertFalse(f.objects['h5']['state']['ready'])

    def test_no_change_seen_asks_name_and_the_answer_becomes_the_effect(self):
        r = learn.new_row('BeeHive', {}, Affordance('honey', None, (500, 300), False, 0.0, False, False),
                          {'events': ['beehive_progress'], 'after': [Affordance('honey', None, (500, 300), False, 0.0)]},
                          answer='pollen=collected')
        self.assertEqual((r['effect'], r['seen'], r['bubble']), ({'pollen': 'collected'}, 1, {'kind': 'honey'}))
        self.assertIsNone(learn.new_row('BeeHive', {}, Affordance('honey', None, (500, 300), False, 0.0),
                                        {'events': [], 'after': [Affordance('honey', None, (500, 300), False, 0.0)]}))

    def obs(self, *recs):
        import json
        with open(steps.OBSERVED, 'a') as fh:
            for row, step, field, exp, got, verdict in recs:
                fh.write(json.dumps({'row': row, 'step': step, 'field': field, 'expected': exp, 'got': got,
                                     'verdict': verdict}) + '\n')

    def test_gap_filled_after_two(self):
        rs = plan.rows()
        next(r for r in rs if r['id'] == 'plant')['steps'][0]['expect']['card'] = '?'
        plan.save_rows(rs)
        self.obs(('plant', 0, 'card', '?', 'Inventory / Seeds', 'gap'))
        learn.settle_rows()
        self.assertEqual(next(r for r in plan.rows() if r['id'] == 'plant')['steps'][0]['expect']['card'], '?')
        self.obs(('plant', 0, 'card', '?', 'Inventory / Seeds', 'gap'))
        learn.settle_rows()
        self.assertEqual(next(r for r in plan.rows() if r['id'] == 'plant')['steps'][0]['expect']['card'],
                         'Inventory / Seeds')

    def test_revise_after_three_contradictions(self):
        bad = ('water', 0, 'events', ['water|hazel_waterplant'], ['water_can_empty'], 'surprise')
        self.obs(bad, bad)
        learn.settle_rows()
        self.assertEqual(next(r for r in plan.rows() if r['id'] == 'water')['steps'][0]['expect']['events'],
                         ['water|hazel_waterplant'])
        self.obs(bad)
        learn.settle_rows()
        self.assertEqual(next(r for r in plan.rows() if r['id'] == 'water')['steps'][0]['expect']['events'],
                         ['water_can_empty'])

    def test_one_ok_after_surprises_keeps_the_expectation(self):
        bad = ('water', 0, 'events', ['water|hazel_waterplant'], ['x'], 'surprise')
        self.obs(bad, bad, ('water', 0, 'events', ['water|hazel_waterplant'], ['water'], 'ok'), bad)
        learn.settle_rows()
        self.assertEqual(next(r for r in plan.rows() if r['id'] == 'water')['steps'][0]['expect']['events'],
                         ['water|hazel_waterplant'])


class Report(EngineBase):
    """Per-run metrics (vision and clicks per target) and the catalogue the agent picks goals from."""

    def test_summary_has_per_target_metrics(self):
        f = self.use(FakeGame(beds('n', NX[:2], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False),
                              GAME))
        res = engine.achieve('water')
        self.assertEqual((res['clicks_per_target'], res['vision_per_target']), (1.0, 0.0))
        self.assertIn('water: done 2, left 0, clicks 2, vision 0', engine.summary(res))
        logged = [k for a, k in f.runlog if a and a[0] == 'engine']
        self.assertEqual(logged[-1]['done'], 2)

    def test_catalogue_lists_kinds_regions_rows(self):
        g = OG.Graph()
        g.load(SEED)
        fences = [obj('f1', kind='Fence', pos=(20.0, -40.0), save={})]
        world.refresh(g, FakeGame(NORTH + SOUTH + HIVES + fences, GAME).read_save()[1], [], None)
        cat = world.catalogue(g)
        self.assertIn('GardenSouth', cat)
        self.assertIn('GardenBed x12', cat)
        self.assertIn('GardenBed: water, remove_wilted, plant, pick', cat)   # trusted rows per kind
        self.assertIn('unnamed save objects: 1', cat)


class Wrappers(EngineBase):
    """Task functions are one-line goals; the CLI parses goal, params and the answer; routines count from the world."""

    def test_wrappers_call_achieve(self):
        from game import garden
        calls = []
        with mock.patch.object(engine, 'achieve', lambda goal, answer=None, **kw: calls.append((goal, answer, kw)) or {}):
            self.use(FakeGame([], GAME))
            garden.water_all(click='Q14')
            garden.plant_all(seed='Tulip', region='GardenSouth')
            garden.harvest_all()
            garden.replant_all()
        self.assertEqual(calls, [('water', 'Q14', {}), ('plant', None, {'seed': 'Tulip', 'region': 'GardenSouth'}),
                                 ('harvest', None, {}), ('replant', None, {})])

    def test_cli_parses_goal_params_and_answer(self):
        self.assertEqual(engine.parse_cli(['plant', 'seed=Tulip', 'region=GardenSouth', 'answer=Q14']),
                         ('plant', {'seed': 'Tulip', 'region': 'GardenSouth'}, 'Q14'))
        self.assertEqual(engine.parse_cli(['harvest', 'crops=Carrot,Tulip']), ('harvest', {'crops': ['Carrot', 'Tulip']}, None))
        goal, _, _ = engine.parse_cli(['{"kind": "BeeHive", "where": {"ready": true}, "make": {"ready": false}}'])
        self.assertEqual(goal['kind'], 'BeeHive')

    def test_routines_counts_from_world(self):
        import wf
        f = FakeGame(beds('n', NX[:3], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False)
                     + beds('w', NX[3:], NZ[:1], 'near', 900, 300, stage='growing', watered=False, wilted=True), GAME)
        log = [L('9:00:00 AM', 'water', 'GardenBed', NX[0], NZ[0])]
        with mock.patch.object(wf, 'read_save', f.read_save), mock.patch.object(wf, 'today_log', lambda: (log, '185', log)):
            self.assertEqual((wf.beds_left('dry'), wf.beds_left('wilted'), wf.beds_left('empty')), (2, 1, 0))


class Nav(EngineBase):
    """Navigation through the engine (ported from test_laws Seek/Vision/Language, L130-L135)."""
    FAR = [(40.0, -60.0), (42.5, -60.0)]   # a garden far from Tara's area: the map leads there

    def far(self, zone='far', body=None):
        return [obj(f'f{i}', pos=p, zone=zone, bubble=(700 + 200 * i, 300), body=body, stage='growing', watered=False,
                    wilted=False) for i, p in enumerate(self.FAR)]

    def test_far_garden_map_direction_steps_then_the_loop_runs(self):
        f = self.use(FakeGame(self.far(), GAME))
        f.step_zone = 'far'
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            res = engine.achieve('water')
        self.assertEqual((len(res['done']), f.asks), (2, []))
        self.assertEqual(f.clicks[0], (960 + nav.MAP_STEP_R, 540))   # map-led steps are long (user D188)

    def test_a_blocked_step_turns_a_little(self):
        f = self.use(FakeGame(self.far(), GAME))
        f.step_zone, f.step_ok = 'far', (lambda x, y: y != 540)   # straight ahead is a fence
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            res = engine.achieve('water')
        self.assertEqual(f.clicks[0][1], 540)
        self.assertNotEqual(f.clicks[1][1], 540)
        self.assertEqual(len(res['done']), 2)

    def test_an_unknown_bubble_without_a_drop_is_never_clicked(self):
        hive = obj('h', kind='BeeHive', pos=(1.5, -23.5), bubble=(800, 532), save={'pollen': '0'}, ready=True)
        f = self.use(FakeGame(self.far() + [hive], GAME + [HIVE]))
        f.step_zone = 'far'
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            res = engine.achieve('water')
        self.assertNotIn((800, 532), f.clicks)
        self.assertEqual(len(res['done']), 2)

    def test_inside_the_area_explores_free_ground_not_the_map(self):
        near = [obj('a', pos=(NX[0], NZ[0]), bubble=(900, 400), stage='growing', watered=False, wilted=False),
                obj('b', pos=(NX[1], NZ[0]), zone='far', bubble=(700, 300), stage='growing', watered=False, wilted=False)]
        f = self.use(FakeGame(near, GAME))
        f.step_zone = 'far'

        def no_map(node):
            raise AssertionError('map used inside the area')
        with mock.patch.object(nav, 'map_direction', no_map), mock.patch.object(nav, 'dry_spots', lambda tried=(): []):
            res = engine.achieve('water')
        self.assertEqual(len(res['done']), 2, res)

    def test_three_still_clicks_are_stuck_and_vision_gets_the_trace(self):
        f = self.use(FakeGame(self.far(), GAME))
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            with self.assertRaises(NeedVision) as cm:
                engine.achieve('water')
        self.assertIn('STUCK', str(cm.exception))
        self.assertLessEqual(len(f.clicks), nav.STUCK_CLICKS + 1)

    def test_no_bubble_asks_one_click_then_the_answer_walks_and_the_loop_runs(self):
        f = self.use(FakeGame(self.far(body=(1500, 300))[:1], GAME))
        with self.assertRaises(NeedVision) as cm:
            engine.achieve('water')
        self.assertIn('./wf achieve water answer=', str(cm.exception))
        res = engine.achieve('water', answer='S5')   # the cell on the far bed's body: she walks there
        self.assertEqual(len(res['done']), 1, res)

    def test_none_answer_ends_the_run(self):
        f = self.use(FakeGame(self.far(), GAME))
        res = engine.achieve('water', answer='none')
        self.assertEqual((res['stop'], f.clicks), ('vision: none left', []))

    def test_bad_answer_is_rejected_without_a_click(self):
        f = self.use(FakeGame(self.far(), GAME))
        with self.assertRaises(core.Failed):
            engine.achieve('water', answer='Z99')
        self.assertEqual(f.clicks, [])

    def test_russian_ui_stops_before_any_click(self):
        f = self.use(FakeGame(beds('n', NX, NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False), GAME))
        f.state = lambda: {'mode': 'gameplay', 'text': ['0) Понедельник 9:00']}
        with self.assertRaises(observe.WrongLanguage):
            engine.achieve('water')
        self.assertEqual(f.clicks, [])


class ReviewFixes(EngineBase):
    """Final review (2026-11-03): area gating after a walk, look-alike frame nodes, long walks, events without a
    position, log-only noise objects, unknown regions."""

    def test_a_look_alike_frame_node_is_not_where_she_is_when_her_area_is_unknown(self):
        f = self.use(FakeGame([obj('a', pos=(NX[0], NZ[0]), bubble=(980, 560), stage='growing', watered=True)], GAME))
        calls = []
        res = nav.new_res('t')
        res.update(area=None, lookalike={'GardenBed@Garden'})
        t = nav.Target('t', lambda a: False, 'x', None, 'GardenBed', 'GardenSouth', 'GardenSouth', None)
        with mock.patch.object(learn, 'toward', lambda a, b: calls.append((a, b))):
            nav.seek(t, res)
        self.assertNotIn(('GardenBed@Garden', 'GardenSouth'), calls)
        del f

    def test_a_long_walk_does_not_use_up_the_search(self):
        f = self.use(FakeGame(Nav.FAR and [obj(f'f{i}', pos=p, zone='far', bubble=(700 + 200 * i, 300), stage='growing',
                                               watered=False, wilted=False) for i, p in enumerate(Nav.FAR)], GAME))
        f.step_zone, f.steps_needed = 'far', 10
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            res = engine.achieve('water')
        self.assertEqual((len(res['done']), res['vision']), (2, 0), res)

    def test_a_logged_event_without_a_position_counts_on_the_target(self):
        f = self.use(FakeGame(beds('n', NX[:1], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False),
                              GAME))
        f.no_pos = True
        res = engine.achieve('water')
        self.assertEqual(len(res['done']), 1, res)
        self.assertTrue(any('no position' in str(s) for s in res['surprises']))

    def test_log_only_objects_of_unknown_kinds_are_not_saved(self):
        g = OG.Graph()
        g.load(SEED)
        world.refresh(g, FakeGame(NORTH, GAME).read_save()[1], [L('9:00:00 AM', 'pickup', 'Weed', 40.0, 10.0)], None)
        self.assertIn('Weed#40.0,10.0', g.nodes)   # this call sees it
        p = os.path.join(self.tmp.name, 'g.json')
        g.save(p)
        g2 = OG.Graph()
        g2.load(p)
        self.assertNotIn('Weed#40.0,10.0', g2.nodes)
        self.assertTrue(any(n.kind == 'GardenBed' and n.extra.get('pos') for n in g2.nodes.values()))

    def test_an_unknown_region_asks_with_the_areas_seen(self):
        f = self.use(FakeGame(beds('n', NX, NZ, 'near', 500, 300, stage='growing', watered=True, wilted=False)
                              + beds('s', SX, SZ, 'south', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 18}))
        res = engine.achieve('plant', seed='Tulip', region='GardenSouht')
        self.assertTrue(res['stop'].startswith('NEED_INPUT plant: region?'), res['stop'])
        self.assertIn('GardenSouth', res['stop'])
        self.assertEqual(f.clicks, [])


class Predictions(EngineBase):
    """User D185 live run: at 6:40 pm (dusk) the empty bed's bubble read as `unplant`; she walked on. Predictions
    (arrival at a seen object, the bubble the world says the area's objects show) are recorded with hit/miss; icon
    goals run in daylight only; a contradicting bubble outside daylight stops with a sleep suggestion."""

    def setUp(self):
        super().setUp()
        import evals.store as ES
        self.preds = os.path.join(self.tmp.name, 'predictions.jsonl')
        for p in (mock.patch.object(ES, 'PATH', self.preds), mock.patch.object(ES, 'ENABLED', True)):
            p.start()
            self.addCleanup(p.stop)

    def recs(self):
        import json
        try:
            return [json.loads(l) for l in open(self.preds)]
        except OSError:
            return []

    def misses(self, component, what):
        rs = self.recs()
        ids = {r['id'] for r in rs if r.get('component') == component and r.get('what') == what}
        return [r for r in rs if r.get('id') in ids and 'hit' in r and not r['hit']]

    def test_icon_goals_stop_outside_daylight_and_suggest_sleep(self):
        f = self.use(FakeGame(beds('s', SX[:2], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 5}))
        f.light = 'dusk'
        res = engine.achieve('plant', seed='Tulip', region='Garden')
        self.assertTrue(res['stop'].startswith('dark'), res['stop'])
        self.assertIn('sleep', res['stop'])
        self.assertEqual(f.clicks, [])

    def test_a_bubble_that_contradicts_the_world_is_a_recorded_miss(self):
        f = self.use(FakeGame(beds('s', SX[:2], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 5}))
        f.relabel = {'plant': 'unplant'}   # misread kind
        with self.assertRaises(NeedVision):
            engine.achieve('plant', seed='Tulip', region='Garden')
        m = self.misses('engine', 'bubble')
        self.assertTrue(m, self.recs())
        self.assertIn('unplant', str(m[0]['outcome']))

    def test_at_dusk_a_contradicting_bubble_stops_the_run(self):
        f = self.use(FakeGame(beds('n', NX[:2], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False),
                              GAME))
        f.light, f.hide_drop = 'dusk', True   # dry beds whose drop sub-icon isn't seen in the dusk light
        res = engine.achieve('water')
        self.assertTrue(res['stop'].startswith('dark'), res['stop'])
        self.assertIn('sleep', res['stop'])
        self.assertTrue(self.misses('engine', 'bubble'))

    def test_arrival_at_a_seen_object_is_a_recorded_prediction(self):
        f = self.use(FakeGame([obj('a', pos=(NX[0], NZ[0]), zone='far', bubble=(900, 400), body=(1500, 300),
                                   stage='empty', watered=False, wilted=False)], GAME, inventory={'TulipSeed': 2}))
        Det = __import__('collections').namedtuple('Det', 'point')
        with mock.patch.object(observe, 'see', lambda kind, tried=(): [Det((1500, 300))] if f.zone == 'near' else []):
            res = engine.achieve('plant', seed='Tulip', region='Garden')
        self.assertEqual(len(res['done']), 1)
        self.assertTrue(nav._predicted_arrival(nav.Target('t', None, 'x', None, 'GardenBed', 'GardenSouth', 'GardenSouth'),
                                               act.Click((1, 1), 'object', 0, node='GardenBed@Garden')))
        hits = [r for r in self.recs() if r.get('hit') is True]
        arrive = [r for r in self.recs() if r.get('component') == 'nav' and r.get('what') == 'arrive']
        self.assertTrue(arrive and any(h['id'] == arrive[0]['id'] for h in hits), self.recs())

    def test_the_daemon_is_stale_when_code_is_newer(self):
        import wfc
        self.assertTrue(wfc.stale(100.0, [50.0, 150.0]))
        self.assertFalse(wfc.stale(200.0, [50.0, 150.0]))


class FlashText(Base):
    """Short-lived cards (a few seconds) are read from the burst frames on EVERY click (OCR ~0.08 s/frame) and become
    state: the crop card's first line = crop (the save has none), "N days remaining", "has wilted"; junk dropped;
    a non-English card stops (user D185)."""

    def test_burst_text_junk_is_dropped(self):
        self.assertEqual(observe.clean_texts(['••40', '00000', 'АЛЛАnaР', 'Green Bean', '2 days remaining', 'Collect',
                                              'Bee Hive']),
                         ['Green Bean', '2 days remaining', 'Collect', 'Bee Hive'])

    def test_card_state_reads_crop_days_and_wilted(self):
        self.assertEqual(learn.card_state(['Green Bean', 'The unripe fruit of the', 'common bean plant. Grows',
                                           '2 days remaining']), {'crop': 'Green Bean', 'days_left': 2, 'ready': False})
        self.assertEqual(learn.card_state(['Carrot', 'A crisp orange vegetable', 'This plant has wilted. You']),
                         {'crop': 'Carrot', 'wilted': True})
        self.assertEqual(learn.card_state(['Bee Hive', 'Plant flowers nearby to', 'encourage the bees to']), {})
        self.assertEqual(learn.card_state(['Collect']), {})

    def test_a_growing_bed_click_teaches_its_crop(self):
        f = self.use(FakeGame([obj('a', pos=(NX[0], NZ[0]), bubble=(900, 400), stage='growing', watered=True,
                                   crop='Carrot')], GAME))
        g = OG.Graph()
        g.load(SEED)
        world.refresh(g, f.read_save()[1], [], None)
        learn.MEMORY['graph'] = g
        self.addCleanup(learn.MEMORY.__setitem__, 'graph', None)
        c = act.click((900, 400), 'bubble')
        self.assertIn('4 days remaining', c.burst_texts)
        nid = world.find(g, 'GardenBed', (NX[0], NZ[0]))
        self.assertEqual((g.state_value(nid, 'crop'), g.state_value(nid, 'days_left')), ('Carrot', 4))

    def test_a_non_english_flash_card_stops(self):
        f = self.use(FakeGame([obj('a', bubble=(900, 400), stage='growing', watered=True, crop='Carrot')], GAME))
        f.behaviour = [dict(GAME[4], flash=['Пчелиный улей', 'Посади рядом цветы,'])]
        with self.assertRaises(observe.WrongLanguage):
            act.click((900, 400), 'bubble')


class PlantProof(EngineBase):
    """Live D186: the picker showed the Tulip Bulbs card highlighted (tooltip only, no Select); the engine stopped
    'missing TulipSeed', closing the panel logged `> plant` (game: written whenever the panel closes) and the bed was
    marked growing. Only `totalPlanted` proves a planting; a missing confirm button is ONE vision question."""

    def test_a_closed_panel_without_total_planted_is_not_a_planting(self):
        g = OG.Graph()
        g.load(SEED)
        save = FakeGame(SOUTH, GAME).read_save()[1]
        world.refresh(g, save, [L('9:00:00 AM', 'plant', 'GardenBed', 10.14, -59.36)], 'D185 8:00:00 AM')
        self.assertEqual(g.state_value('GardenBed#10.1,-59.4', 'stage'), 'empty')
        world.refresh(g, save, ['[D185 9:05:00 AM] > interact me=Player', '[STATS] totalPlanted.TulipSeed = 58',
                                L('9:05:01 AM', 'plant', 'GardenBed', 10.14, -59.36)], 'D185 8:00:00 AM')
        self.assertEqual(g.state_value('GardenBed#10.1,-59.4', 'stage'), 'growing')
        g2 = OG.Graph()
        g2.load(SEED)   # the live order (D186): `> plant` when the panel opens, totalPlanted after Space
        world.refresh(g2, save, [L('10:44:35 AM', 'plant', 'GardenBed', 10.14, -59.36),
                                 '[D185 10:45:38 AM] [STATS] totalPlanted.TulipSeed = 105',
                                 L('10:45:59 AM', 'water', 'GardenBed', 10.14, -59.36)], 'D185 8:00:00 AM')
        self.assertEqual((g2.state_value('GardenBed#10.1,-59.4', 'stage'), g2.state_value('GardenBed#10.1,-59.4', 'watered')),
                         ('growing', True))

    def test_a_picker_without_select_asks_which_button_then_replays_it(self):
        confirm = [dict(GAME[1], space_confirms=False,   # a card whose button is "Plant" and Space doesn't confirm
                        card=[{'texts': ['Inventory', 'Seeds'], 'next': 'pick'},
                              {'texts': ['Inventory', 'Seeds', 'Tulip Bulbs', 'Plant'], 'next': 'press:Plant'}])]
        f = self.use(FakeGame(beds('s', SX[:2], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              confirm + GAME, inventory={'TulipSeed': 5}))
        with self.assertRaises(NeedVision) as cm:
            engine.achieve('plant', seed='Tulip', region='Garden')
        self.assertIn('button', str(cm.exception).lower())
        self.assertTrue(all(o['state']['stage'] == 'empty' for o in f.objects.values()))
        res = engine.achieve('plant', seed='Tulip', region='Garden', answer='Plant')
        self.assertEqual((len(res['done']), res['vision']), (2, 0), res)
        row = next(r for r in plan.rows() if r['id'] == 'plant')
        self.assertEqual(row['steps'][2], {'do': 'press', 'arg': 'Plant', 'expect': {'events': ['plant'], 'log': 'totalPlanted'}})

    def test_pick_card_reads_the_card_modal_text_not_the_fixed_title_band(self):
        """User D186: the picked card opened a modal with "Select"; the fixed title band read another text, so the right
        card was closed with Escape. The modal's own text names the card."""
        from game import items
        keys, real = [], ui.pick_card
        f = self.use(FakeGame([], GAME))
        f.run_action = lambda a: keys.append(a)
        with mock.patch.object(ui, 'shows', lambda w, wait=2.0: w == 'Select'), \
                mock.patch.object(ui, 'texts', lambda: ['Inventory', 'Seeds', 'Tulip Bulbs', 'Plant in Spring', 'Select']), \
                mock.patch.object(ui, 'detail_title', lambda: 'Inventory'), \
                mock.patch.object(items, 'learn', lambda crop, title: None), \
                mock.patch.object(items, 'crop', lambda img, s: None):
            self.assertEqual(real.__wrapped__('Tulip'), 'Tulip')
        self.assertNotIn('key:escape', keys)

    def test_pick_card_trusts_the_modal_text_over_a_misread_title_band(self):
        """Live D186: the card's modal opened (Select) after the click; the fixed title band read 'ılbs', so the right
        card was learned as 'ılbs' and closed with Escape although the screen said 'Tulip Bulbs'."""
        from game import items
        keys, learned, real, opened = [], [], ui.pick_card, []
        f = self.use(FakeGame([], GAME))
        f.run_action = lambda a: (keys.append(a), opened.append(1) if a.startswith('click') else None)
        f.grab = lambda: None
        screen = lambda: ['Inventory', 'Seeds', 'Tulip Bulbs', 'Select'] if opened else ['Inventory', 'Seeds']
        with mock.patch.object(ui, 'shows', lambda w, wait=2.0: w == 'Select' and bool(opened)), \
                mock.patch.object(ui, 'texts', screen), \
                mock.patch.object(ui, 'detail_title', lambda: 'ılbs'), \
                mock.patch.object(ui, 'card_spots', lambda box=None, img=None: [(125, 535)]), \
                mock.patch.object(items, 'match', lambda crop: (None, 0.0)), \
                mock.patch.object(items, 'crop', lambda img, s: 'crop'), \
                mock.patch.object(items, 'learn', lambda crop, title: learned.append(title)):
            self.assertEqual(real.__wrapped__('Tulip'), 'Tulip Bulbs')
        self.assertNotIn('key:escape', keys)
        self.assertEqual(learned, ['Tulip Bulbs'])

    def test_an_empty_bed_with_a_stale_crop_is_still_planted(self):
        f = self.use(FakeGame(beds('s', SX[:2], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 5}))
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], [], None)
        g.set_state(world.find(g, 'GardenBed', (SX[0], SZ[0])), 'crop', 'Tulip', None, 'event')   # a cancelled panel
        g.save(learn.GRAPH)
        res = engine.achieve('plant', seed='Tulip', region='Garden')
        self.assertEqual(len(res['done']), 2, res)

    def test_a_grid_cell_answer_becomes_a_click_step(self):
        self.assertEqual(engine.button_step('Q14', {'expect': {'log': 'x'}}), {'do': 'click_cell', 'arg': 'Q14',
                                                                              'expect': {'log': 'x'}})
        self.assertEqual(engine.button_step('Select', {}), {'do': 'press', 'arg': 'Select'})

    def test_pick_card_takes_a_highlighted_card_named_on_screen(self):
        from game import items
        keys, real = [], ui.pick_card
        f = self.use(FakeGame([], GAME))
        f.run_action = lambda a: keys.append(a)
        with mock.patch.object(ui, 'shows', lambda w, wait=2.0: False), \
                mock.patch.object(ui, 'texts', lambda: ['Inventory', 'Seeds', 'Tulip Bulbs', '18']), \
                mock.patch.object(ui, 'card_spots', lambda box=None, img=None: [(125, 535)]), \
                mock.patch.object(items, 'match', lambda crop: (None, 0.0)), \
                mock.patch.object(items, 'crop', lambda img, s: None), \
                mock.patch.object(items, 'learn', lambda crop, title: None):
            self.assertEqual(real.__wrapped__('Tulip'), 'Tulip Bulbs')
        self.assertNotIn('key:escape', keys)


class PauseMenu(Base):
    """Live D186: Escape on a screen that wasn't a card opened the pause menu, and world clicks landed on it until the
    game exited. close() never presses Escape into the pause menu; no world click while it is open."""

    def setUp(self):
        super().setUp()
        self.close = ui.close   # the real one (use() patches ui.close with the fake's)

    def test_close_on_the_pause_menu_resumes_instead_of_escape(self):
        f = self.use(FakeGame([], GAME))
        f.paused = True
        self.close.__wrapped__()
        self.assertFalse(f.paused)

    def test_a_textless_overlay_gets_no_escape(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay = True   # an overlay without text (HUD hidden, camera on a bed): nothing to close
        keys = []
        run = f.run_action
        f.run_action = lambda a: (keys.append(a), run(a))[1]
        self.close.__wrapped__()
        self.assertEqual((keys, f.paused), ([], False))

    def test_an_escape_that_opens_the_pause_menu_is_undone_and_reported(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Bee Hive', 'Plant flowers nearby', 'to encourage the bees']   # Escape doesn't close it
        with self.assertRaises(core.Failed) as cm:
            self.close.__wrapped__()
        self.assertFalse(f.paused)
        self.assertIn('pause menu', str(cm.exception))

    def test_act_click_never_clicks_the_world_while_paused(self):
        f = self.use(FakeGame([obj('a', bubble=(900, 400), stage='growing', watered=False, wilted=False)], GAME))
        f.paused = True
        act.click((960, 840), 'explore')
        self.assertEqual(f.menu_clicks, [])
        self.assertFalse(f.paused)


class SpaceFlow(EngineBase):
    """User D186: "select confirm can be run by a space click, and watering after planting is also a space click"."""

    def test_planting_confirms_with_space_and_waters_with_space(self):
        f = self.use(FakeGame(beds('s', SX[:2], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 5}))
        pressed = []
        press = f.press
        f.press = lambda label: (pressed.append(label), press(label))[1]
        with mock.patch.object(ui, 'press', f.press):
            res = engine.achieve('plant', seed='Tulip', region='Garden')
        self.assertEqual((len(res['done']), res['vision']), (2, 0), res)
        self.assertEqual(pressed, [])   # no Select click: Space confirms
        self.assertTrue(all(o['state']['watered'] for o in f.objects.values()), [o['state'] for o in f.objects.values()])
        row = next(r for r in plan.rows() if r['id'] == 'plant')
        self.assertEqual([s_['do'] for s_ in row['steps']], ['click_bubble', 'pick_card', 'press_space', 'press_space'])


class Screen(Base):
    """One reader of the screen state (gameplay / card / picker / pause) with hard rules: no world click outside
    gameplay, Escape only on a known card or picker, the pause menu is resumed (design review D186)."""

    def setUp(self):
        super().setUp()
        self.close = ui.close   # the real one

    def test_states_are_read_from_mode_and_texts(self):
        R = screen.classify
        self.assertEqual(R('gameplay', []), 'gameplay')
        self.assertEqual(R('overlay', []), 'gameplay')   # a textless overlay = HUD hidden (camera on a bed), L144
        self.assertEqual(R('overlay', ['Game Paused', 'Resume Game']), 'pause')
        self.assertEqual(R('overlay', ['Inventory', 'Seeds', 'Tulip Bulbs']), 'picker')
        self.assertEqual(R('overlay', ['Tulip Bulbs', 'Plant these tulip bulbs in a', 'Select']), 'card')
        self.assertEqual(R('overlay', ['Settings', 'Music Volume']), 'menu')
        self.assertEqual(R('dialogue', ['Hello']), 'dialogue')

    def test_world_clicks_only_in_gameplay(self):
        f = self.use(FakeGame([obj('a', stage='empty')], GAME, inventory={'TulipSeed': 2}))
        act.click((900, 400), 'bubble')   # opens the picker
        self.assertEqual(screen.read().kind, 'picker')
        n = len(f.clicks)
        act.click((1200, 800), 'explore')   # a world click: the picker is closed first, never clicked through
        self.assertIsNone(f.card)
        self.assertEqual(len(f.clicks), n + 1)

    def test_a_menu_that_stays_open_stops_world_clicks(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Settings', 'Music Volume']
        with self.assertRaises(observe.LawsStuck):
            act.click((960, 840), 'explore')
        self.assertEqual(f.clicks, [])

    def test_close_resumes_pause_and_escapes_only_cards(self):
        f = self.use(FakeGame([], GAME))
        f.paused = True
        self.close.__wrapped__()
        self.assertFalse(f.paused)
        f.blank_overlay = True
        keys = []
        run = f.run_action
        f.run_action = lambda a: (keys.append(a), run(a))[1]
        self.close.__wrapped__()   # textless overlay = gameplay: nothing to close
        self.assertEqual(keys, [])


class Smoke(Base):
    """One bed, one primitive at a time, each with its proof (design review D186): plant bubble in view -> click ->
    the picker's text -> pick the seed -> Space -> totalPlanted -> Space -> water."""

    def test_one_bed_plants_and_waters_with_a_proof_per_step(self):
        f = self.use(FakeGame([obj('a', pos=(SX[0], SZ[0]), stage='empty', watered=False, wilted=False)], GAME,
                              inventory={'TulipSeed': 2}))
        out = smoke.plant_one('Tulip')
        self.assertEqual([(s['step'], s['ok']) for s in out],
                         [('screen', True), ('bubble', True), ('click', True), ('pick', True), ('confirm', True),
                          ('water', True)])
        self.assertIn('totalPlanted', out[4]['proof'])
        self.assertEqual(f.objects['a']['state'], {'stage': 'growing', 'watered': True, 'wilted': False, 'crop': 'Tulip'})

    def test_the_first_failing_step_stops_and_closes_the_card(self):
        f = self.use(FakeGame([obj('a', stage='empty', watered=False, wilted=False)], GAME, inventory={}))
        out = smoke.plant_one('Tulip')
        self.assertEqual([(s['step'], s['ok']) for s in out][-1], ('pick', False))
        self.assertIsNone(f.card)

    def test_no_plant_bubble_in_view_stops_before_any_click(self):
        f = self.use(FakeGame([obj('a', stage='growing', watered=True)], GAME))
        out = smoke.plant_one('Tulip')
        self.assertEqual([(s['step'], s['ok']) for s in out][-1], ('bubble', False))
        self.assertEqual(f.clicks, [])


class BubbleLabels(Base):
    """Live D186 smoke: a seedling read as `unplant`, a tulip+drop as `beehive_progress` - polluted examples from
    "label a clicked bubble by the next event" when the event came from a neighbour (the hive by the beds)."""

    def test_a_drop_bubble_is_never_a_plant_bubble_and_events_are_not_bubble_kinds(self):
        f = self.use(FakeGame([], GAME))
        drop = [Affordance('water', None, (900, 400), False, 0.0, True)]
        for label in ('plant', 'out_of_water'):
            f.event_kind = lambda lines, l=label: l
            c = act.Click((900, 400), 'bubble', 0, lines=[f'[D186 9:00:00 AM] > {label} me=Player'], before=drop)
            self.assertIsNone(learn.learn_bubble(c, None))
        self.assertEqual(f.learned, [])

    def test_a_drop_bubble_is_never_relabelled_as_a_non_crop_kind(self):
        f = self.use(FakeGame([], GAME))
        c = act.Click((900, 400), 'bubble', 0, lines=['[D186 9:00:00 AM] > beehive_progress me=Player target=BeeHive(Clone)'],
                      before=[Affordance('water', None, (900, 400), False, 0.0, True)])
        f.event_kind = lambda lines: 'beehive_progress'
        self.assertIsNone(learn.learn_bubble(c, None))
        self.assertEqual(f.learned, [])


class SmokeLoop(Base):
    def test_plant_visible_plants_every_bed_in_view_then_stops(self):
        f = self.use(FakeGame(beds('s', SX[:3], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False)
                              + [obj('far', pos=(SX[3], SZ[0]), zone='far', stage='empty', watered=False, wilted=False)],
                              GAME, inventory={'TulipSeed': 5}))
        res = smoke.plant_visible('Tulip')
        self.assertEqual((res['planted'], res['watered']), (3, 3))
        self.assertIn('no plant bubble in view', res['stop'])
        self.assertEqual(f.objects['far']['state']['stage'], 'empty')

    def test_a_short_lived_tooltip_is_waited_out_not_escaped(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Rusty Watering Can']
        keys = []
        run = f.run_action
        f.run_action = lambda a: (keys.append(a), run(a))[1]
        f.wait_settle = lambda: setattr(f, 'blank_overlay', False)   # the tooltip fades
        self.assertEqual(screen.require_world().kind, 'gameplay')
        self.assertEqual(keys, [])


class SmokeCan(Base):
    def test_an_empty_can_stops_watering_not_planting(self):
        f = self.use(FakeGame(beds('s', SX[:3], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 5}))
        f.tara['can'] = 'empty'
        res = smoke.plant_visible('Tulip')
        self.assertEqual((res['planted'], res['watered'], res['can']), (3, 0, 'empty'))
        self.assertIn('no plant bubble in view', res['stop'])
        self.assertEqual(sum('out_of_water' in l for l in f.log), 1)   # Space-water tried once, then skipped


class SmokeDrop(Base):
    def test_a_plant_bubble_with_a_drop_is_not_an_empty_bed(self):
        f = self.use(FakeGame([obj('a', stage='growing', watered=False, wilted=False)], GAME))
        f.relabel = {'water': 'plant'}   # live D186: the just-planted bed's bubble read as plant +drop
        out = smoke.plant_one('Tulip')
        self.assertEqual([(s['step'], s['ok']) for s in out][-1], ('bubble', False))
        self.assertEqual(f.clicks, [])


class ScreenHint(Base):
    def test_close_waits_out_a_short_hint_instead_of_escaping(self):
        """Live D186: "Fill watering can at the / Well" isn't closed by Escape (the pause menu opened)."""
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Fill watering can at the', 'Well']
        keys = []
        run = f.run_action
        f.run_action = lambda a: (keys.append(a), run(a))[1]
        f.wait_settle = lambda: setattr(f, 'blank_overlay', False)   # the hint fades
        self.assertEqual(screen.close().kind, 'gameplay')
        self.assertEqual(keys, [])


class ScreenHint2(Base):
    def test_a_lasting_hint_without_buttons_is_passive_never_escaped(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Fill watering can at the', 'Well']   # stays
        keys = []
        run = f.run_action
        f.run_action = lambda a: (keys.append(a), run(a))[1]
        with mock.patch.object(screen, 'HINT_WAIT', 0.0):
            self.assertEqual(screen.require_world().kind, 'card')   # passive: world clicks may go on
            screen.close()
        self.assertEqual(keys, [])

    def test_the_can_state_comes_from_todays_log(self):
        f = self.use(FakeGame([], GAME))
        f.log = ['[D186 11:55:27 AM] > out_of_water me=Player target=GardenBed(Clone) at (13.89, 0.10, -66.86)']
        self.assertEqual(smoke.can_from_log(), 'empty')
        f.log.append('[D186 12:00:00 PM] > fill_watering_can me=Player target=Well')
        self.assertEqual(smoke.can_from_log(), 'full')
        f.log = []
        self.assertIsNone(smoke.can_from_log())


class SmokeMiss(Base):
    def test_a_wrong_bubble_is_skipped_and_the_loop_goes_on(self):
        grown = obj('g', pos=(SX[0], SZ[0]), bubble=(900, 400), stage='growing', watered=True, wilted=False, crop='Tulip')
        empty = obj('e', pos=(SX[1], SZ[0]), bubble=(1200, 400), stage='empty', watered=False, wilted=False)
        f = self.use(FakeGame([grown, empty], GAME + [dict(GAME[4], card=[{'texts': ['Tulip', 'A cup-shaped flower that',
                                                                                     'grows in Spring.'], 'next': 'space'}])],
                              inventory={'TulipSeed': 3}))
        f.behaviour = [dict(GAME[4], card=[{'texts': ['Tulip', 'A cup-shaped flower that', 'grows in Spring.'],
                                            'next': 'space'}])] + GAME
        f.relabel = {'plant_growing': 'plant'}   # the growing bed's bubble misread as plant
        res = smoke.plant_visible('Tulip', can='empty')
        self.assertEqual(res['planted'], 1, res['stop'])
        self.assertEqual(f.objects['e']['state']['stage'], 'growing')


class SmokeWalkDir(Base):
    def test_walk_until_steps_until_the_kind_shows(self):
        f = self.use(FakeGame([obj('a', zone='south', stage='empty', watered=False, wilted=False)], GAME))
        f.step_zone, f.steps_needed = 'south', 4
        res = smoke.walk_until((0, 1), 'plant', max_steps=8)
        self.assertEqual((res['found'], res['steps']), (True, 4))
        self.assertTrue(all(y > 540 for _, y in f.clicks))   # straight down

    def test_walk_until_stops_when_a_step_does_not_move(self):
        f = self.use(FakeGame([], GAME))
        res = smoke.walk_until((0, 1), 'plant', max_steps=8)
        self.assertEqual((res['found'], res['stop']), (False, 'no move'))


class Where(Base):
    """Her position: a positioned event since the last walk (exact), else the map pin through a calibration learned
    from (event position, pin) pairs (user D186: walking based on graph or map, each step closer to the goal)."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(where, 'CALIB', os.path.join(self.tmp.name, 'map_calib.json'))
        p.start()
        self.addCleanup(p.stop)

    def test_the_calibration_fits_scale_and_offset_from_two_pairs(self):
        where.add_pair((2.0, -26.0), (760, 520))
        self.assertIsNone(where.fit())   # one pair: unknown scale
        where.add_pair((8.0, -63.0), (772, 594))
        s, ox, oy = where.fit()
        self.assertAlmostEqual(s, 2.0, delta=0.05)
        self.assertEqual(tuple(round(v) for v in where.to_world((766, 556))), (5, -44))

    def test_near_decisions_never_use_the_map(self):
        f = self.use(FakeGame([], GAME))
        where.add_pair((2.0, -26.0), (760, 520))
        where.add_pair((8.0, -63.0), (772, 594))
        where.walked()
        f.map_snapshot, f.map_pin = (lambda: 'map'), (lambda img: (766, 556))
        self.assertEqual(where.position(far_ok=False), (None, None))

    def test_position_is_the_event_until_a_walk_then_the_map(self):
        f = self.use(FakeGame([], GAME))
        where.add_pair((2.0, -26.0), (760, 520))
        where.add_pair((8.0, -63.0), (772, 594))
        f.log.append('[D186 1:40:00 PM] > plant me=Player target=GardenBed(Clone) at (2.64, 0.10, -59.36)')
        self.assertEqual(where.position(), ('event', (2.64, -59.36)))
        where.walked()
        f.map_snapshot = lambda: 'map'
        f.map_pin = lambda img: (766, 556)
        src, pos = where.position()
        self.assertEqual((src, tuple(round(v) for v in pos)), ('map', (5, -44)))

    def test_pairs_that_disagree_give_no_calibration(self):
        """Live D187: beds 3.75 units apart gave the same pin; the map then put her 10 units off. A fit with a large
        error is no calibration: the position is unknown, not wrong."""
        for w, pin in (((6.39, -66.86), (634, 614)), ((2.64, -63.11), (598, 596)), ((2.64, -66.86), (598, 596))):
            where.add_pair(w, pin)
        self.assertIsNone(where.fit())

    def test_a_fresh_event_and_a_pin_become_a_pair(self):
        f = self.use(FakeGame([], GAME))
        f.log.append('[D186 1:40:00 PM] > plant me=Player target=GardenBed(Clone) at (2.64, 0.10, -59.36)')
        f.map_snapshot = lambda: 'map'
        f.map_pin = lambda img: (771, 587)
        self.assertTrue(where.calibrate_here())
        self.assertEqual(where.pairs()[-1], [[2.64, -59.36], [771, 587]])


class WalkCloser(Base):
    """Each step must bring her closer to the goal node; no progress -> turn; twice -> vision with the trace."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(ask, 'STATE', os.path.join(self.tmp.name, 'ask.json'))
        p.start()
        self.addCleanup(p.stop)

    def steps(self, positions):
        it = iter(positions)
        return mock.patch.object(where, 'position', lambda far_ok=True: ('map', next(it)))

    def test_steps_toward_a_far_goal_until_the_map_is_too_coarse(self):
        """User D187: the map only for very-far navigation (it's imprecise): steps while far, then 'near'."""
        f = self.use(FakeGame([], GAME))
        f.step_zone = 'near'
        with self.steps([(8.0, 10.0), (8.0, 0.0), (8.0, -10.0), (8.0, -20.0), (8.0, -30.0), (8.0, -40.0)]):
            res = smoke.walk_to_area((8.27, -63.11), arrive=4.0)
        self.assertEqual(res['stop'], 'near (map imprecise)')
        self.assertTrue(all(y > 540 for _, y in f.clicks))   # south = down
        self.assertEqual(res['steps'], 5)

    def test_an_event_position_walks_all_the_way(self):
        f = self.use(FakeGame([], GAME))
        f.step_zone = 'near'
        it = iter([(8.0, -40.0), (8.0, -46.0), (8.0, -52.0), (8.0, -58.0), (8.0, -62.0)])
        with mock.patch.object(where, 'position', lambda far_ok=True: ('event', next(it))):
            res = smoke.walk_to_area((8.27, -63.11), arrive=4.0)
        self.assertEqual(res['stop'], 'arrived')

    def test_no_progress_turns_then_asks_vision(self):
        f = self.use(FakeGame([], GAME))
        f.step_zone = 'near'
        with self.steps([(8.0, 10.0)] * 10):
            with self.assertRaises(NeedVision) as cm:
                smoke.walk_to_area((8.27, -63.11), arrive=4.0)
        self.assertIn('no closer', str(cm.exception))


class GardenLoop(Base):
    """Inside the area she moves by clicking visible beds (their events give her position); planted one by one."""

    def setUp(self):
        super().setUp()
        for mod, name in ((ask, 'STATE'), (where, 'CALIB')):
            p = mock.patch.object(mod, name, os.path.join(self.tmp.name, name + '.json'))
            p.start()
            self.addCleanup(p.stop)

    def test_a_visible_bed_is_clicked_when_no_bubble_shows_then_planted(self):
        near = obj('n', pos=(SX[0], SZ[0]), bubble=(900, 400), stage='empty', watered=False, wilted=False)
        far = obj('f', pos=(SX[1], SZ[0]), zone='far', bubble=(900, 400), body=(1400, 700), stage='empty',
                  watered=False, wilted=False)
        f = self.use(FakeGame([near, far], GAME, inventory={'TulipSeed': 5}))
        f.log.append(L('9:00:00 AM', 'plant_growing', 'GardenBed', SX[0], SZ[0]))   # she is in the garden
        f.world_graph = lambda: self._graph(f)
        f.map_snapshot, f.map_pin = (lambda: None), (lambda img: None)
        Det = __import__('collections').namedtuple('Det', 'point')
        with mock.patch.object(observe, 'see', lambda kind, tried=(): [Det((1400, 700))] if f.zone == 'near' else []):
            res = smoke.plant_garden('Tulip', region='Garden')
        self.assertEqual(res['planted'], 2, res)
        self.assertEqual(f.objects['f']['state']['stage'], 'growing')

    def _graph(self, f):
        g = OG.Graph()
        g.load(SEED)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        return g


class WhereWalks(Base):
    def setUp(self):
        super().setUp()
    def test_any_click_that_moved_her_without_an_event_is_a_walk_kept_on_disk(self):
        f = self.use(FakeGame([], GAME))
        f.log.append(L('9:00:00 AM', 'water', 'GardenBed', SX[0], SZ[0]))
        self.assertEqual(where.position()[0], 'event')
        f.step_zone = 'near'
        act.click((960, 860), 'step')   # walked, no event
        where._WALK.clear()             # a daemon restart: memory gone, the disk keeps it
        f.map_snapshot, f.map_pin = (lambda: None), (lambda img: None)
        self.assertEqual(where.position(), (None, None))


class GardenAnswer(Base):
    def setUp(self):
        super().setUp()
        for mod, name in ((ask, 'STATE'), (where, 'CALIB')):
            p = mock.patch.object(mod, name, os.path.join(self.tmp.name, name + '.json'))
            p.start()
            self.addCleanup(p.stop)

    def test_a_vision_cell_is_clicked_first_then_the_loop_runs(self):
        far = obj('f', pos=(SX[1], SZ[0]), zone='far', bubble=(900, 400), body=(840, 236), stage='empty',
                  watered=False, wilted=False)
        f = self.use(FakeGame([far], GAME, inventory={'TulipSeed': 5}))
        f.world_graph = lambda: GardenLoop._graph(self, f)
        f.map_snapshot, f.map_pin = (lambda: None), (lambda img: None)
        res = smoke.plant_garden('Tulip', region='Garden', answer='K4')
        self.assertEqual(f.clicks[0], (840, 236))
        self.assertEqual(res['planted'], 1, res)


class GardenProgress(Base):
    def test_a_planting_resets_the_vision_counter(self):
        f = self.use(FakeGame(beds('s', SX[:1], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 2}))
        with mock.patch.object(ask, 'STATE', os.path.join(self.tmp.name, 'ask.json')):
            ask.save_state({'goal': 'plant_garden', 'asks': 3, 'history': []})
            smoke.plant_visible('Tulip', can='empty')
            self.assertEqual(ask.load_state('plant_garden')['asks'], 0)

    def test_a_seeded_bed_in_the_save_is_growing(self):
        self.assertEqual(world._mapped('GardenBed', {'plantState': '##seed'})['stage'], 'growing')


class Morning(Base):
    """User D186: "run all at morning": plant the rest, refill the can at the well, water every dry bed - daylight only."""

    def setUp(self):
        super().setUp()
        for mod, name in ((ask, 'STATE'), (where, 'CALIB')):
            p = mock.patch.object(mod, name, os.path.join(self.tmp.name, name + '.json'))
            p.start()
            self.addCleanup(p.stop)

    def game(self, objs, **kw):
        f = self.use(FakeGame(objs, GAME, inventory={'TulipSeed': 5}, **kw))
        f.world_graph = lambda: GardenLoop._graph(self, f)
        f.map_snapshot, f.map_pin = (lambda: None), (lambda img: None)
        return f

    def test_outside_daylight_the_loops_stop_and_suggest_sleep(self):
        f = self.game([obj('a', stage='empty', watered=False, wilted=False)])
        f.light = 'dusk'
        res = smoke.morning('Tulip', region='Garden')
        self.assertTrue(res['stop'].startswith('dark'), res)
        self.assertIn('sleep', res['stop'])
        self.assertEqual(f.clicks, [])

    def test_water_visible_waters_every_drop_bubble(self):
        f = self.game(beds('n', NX[:2], NZ[:1], 'near', 500, 300, stage='growing', watered=False, wilted=False))
        res = smoke.water_visible()
        self.assertEqual((res['watered'], res['can']), (2, None))

    def test_fill_can_clicks_the_well_bubble(self):
        f = self.game([obj('well', kind='Well', pos=(1.0, -27.0), bubble=(1500, 300))])
        f.tara['can'] = 'empty'
        self.assertTrue(smoke.fill_can()['ok'])
        self.assertEqual(f.tara['can'], 'full')

    def test_morning_plants_refills_and_waters(self):
        f = self.game([obj('e', pos=(NX[0], NZ[0]), bubble=(500, 300), stage='empty', watered=False, wilted=False),
                       obj('d', pos=(NX[1], NZ[0]), bubble=(700, 300), stage='growing', watered=False, wilted=False),
                       obj('well', kind='Well', pos=(1.0, -27.0), bubble=(1500, 300))])
        f.tara['can'] = 'empty'
        res = smoke.morning('Tulip', region='Garden')
        self.assertEqual(f.objects['e']['state']['stage'], 'growing')
        self.assertTrue(f.objects['e']['state']['watered'] and f.objects['d']['state']['watered'], res)
        self.assertEqual(res['stop'], 'done')


class SmokeRain(Base):
    def test_a_water_space_that_does_nothing_stops_watering_not_planting(self):
        f = self.use(FakeGame(beds('s', SX[:2], SZ[:1], 'near', 500, 300, stage='empty', watered=False, wilted=False),
                              GAME, inventory={'TulipSeed': 5}))
        f.highlight_off = True   # rain: Space after planting does nothing
        orig = f.press_bubble
        f.press_bubble = lambda: orig() if f.card else None
        with mock.patch.object(ui, 'press_bubble', f.press_bubble):
            res = smoke.plant_visible('Tulip')
        self.assertEqual((res['planted'], res['watered']), (2, 0), res['stop'])


class StrictParams(EngineBase):
    def test_a_named_crop_must_be_known_before_picking(self):
        """User D187 "harvest carrots": the save has no crop type; a ripe bed of unknown crop is never picked as a
        carrot - it is reported."""
        f = self.use(FakeGame([obj('t', pos=(NX[0], NZ[0]), bubble=(700, 400), stage='produced', watered=True,
                                   wilted=False, crop='Tulip'),
                               obj('c', pos=(NX[1], NZ[0]), bubble=(900, 400), stage='produced', watered=True,
                                   wilted=False, crop='Carrot')], GAME))
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], [], None)
        g.set_state(world.find(g, 'GardenBed', (NX[1], NZ[0])), 'crop', 'Carrot', None, 'card')
        g.save(learn.GRAPH)
        res = engine.achieve({'kind': 'GardenBed', 'where': {'ready': True, 'crop': '$crops'}, 'make': {'ready': False}},
                             crops='Carrot')   # a goal that names the crop (harvest itself now takes every non-flower)
        self.assertEqual(f.objects['t']['state']['stage'], 'produced')   # the tulip stays (flowers serve the bees)
        self.assertEqual(f.objects['c']['state']['stage'], 'growing')    # the known carrot is picked
        self.assertTrue(any('unknown crop' in n for n in res['notes']), res)


class NewDay(Base):
    """D188: the save was from the rainy D187 (all watered); a new day resets watering, so every growing bed is dry."""

    def test_a_new_day_after_the_save_resets_watered(self):
        g = OG.Graph()
        g.load(SEED)
        save = FakeGame(NORTH, GAME).read_save()[1]   # day 185 in the save, beds watered
        world.refresh(g, save, ['[D186 7:00:00 AM] [TRIGGER] OnDayStarted'], None)
        self.assertEqual(world.count(g, {'kind': 'GardenBed', 'watered': False}), 12)
        g2 = OG.Graph()
        g2.load(SEED)
        world.refresh(g2, save, ['[D185 9:00:00 AM] > interact me=Player'], None)   # same day: as saved
        self.assertEqual(world.count(g2, {'kind': 'GardenBed', 'watered': False}), 0)


class RainGate(EngineBase):
    """User D187: avoid rain and dark for now - the chores stop on a rainy forecast before any click."""

    def test_rain_stops_the_chores_before_any_click(self):
        f = self.use(FakeGame(beds('n', NX[:2], NZ[:1], 'near', 500, 300, stage='growing', watered=False,
                                   wilted=False), GAME))
        f.log.append('[D185 7:00:00 AM] [TIME] Forecast is Raining today')
        res = engine.achieve('water')
        self.assertTrue(res['stop'].startswith('rain'), res['stop'])
        self.assertEqual(f.clicks, [])
        m = smoke.morning('Tulip', region='Garden')
        self.assertTrue(m['stop'].startswith('rain'), m['stop'])


class VisionAnswers(Base):
    """User D188: "each vision need should produce a graph and vectors improvement". A vision click answer whose
    result proves an object stores the clicked look as that kind, learns the direction toward the node it reached,
    and is recorded with hit/miss."""

    def setUp(self):
        super().setUp()
        self.stored = []
        p = mock.patch.object(learn, 'relabel', lambda img, box, kind: self.stored.append((tuple(box), kind)) or True)
        p.start()
        self.addCleanup(p.stop)
        import evals.store as ES
        self.preds = os.path.join(self.tmp.name, 'p.jsonl')
        for q in (mock.patch.object(ES, 'PATH', self.preds), mock.patch.object(ES, 'ENABLED', True)):
            q.start()
            self.addCleanup(q.stop)

    def recs(self):
        import json
        try:
            return [json.loads(l) for l in open(self.preds)]
        except OSError:
            return []

    def test_an_answer_proven_by_an_event_stores_the_look_as_that_kind(self):
        f = self.use(FakeGame([obj('a', pos=(NX[0], NZ[0]), zone='near', bubble=(1400, 700), body=(1400, 700),
                                   stage='growing', watered=True, wilted=False)], GAME))
        act.click((1400, 700), 'point')   # vision's cell on the bed: the click interacts (plant_growing)
        self.assertEqual(self.stored, [((1310, 630, 1490, 770), 'GardenBed')])
        hits = [r for r in self.recs() if r.get('hit') is True]
        self.assertTrue(any(r.get('component') == 'vision' for r in self.recs()) and hits, self.recs())

    def test_an_answer_whose_bubble_appears_under_it_names_the_kind(self):
        f = self.use(FakeGame([obj('a', pos=(NX[0], NZ[0]), zone='far', bubble=(1000, 600), body=(1000, 640),
                                   stage='empty', watered=False, wilted=False)], GAME))
        act.click((1000, 640), 'point')   # walks there; the bed's bubble shows next to the answered point
        self.assertEqual([k for _, k in self.stored], ['GardenBed'])

    def test_entering_the_house_stores_the_door(self):
        f = self.use(FakeGame([], GAME))
        run = f.run_action
        f.run_action = lambda a: (f.log.append('[D187 1:10:12 PM] [TRIGGER] OnEnterBuilding House')
                                  if a.startswith('click') else None, run(a))[1]
        act.click((1835, 380), 'point')
        self.assertEqual([k for _, k in self.stored], ['HouseDoor'])

    def test_free_ground_that_walks_stores_nothing_but_is_recorded(self):
        f = self.use(FakeGame([], GAME))
        f.step_zone = 'near'
        act.click((960, 860), 'point')
        self.assertEqual(self.stored, [])
        self.assertTrue(any(r.get('component') == 'vision' for r in self.recs()))

    def test_an_answer_that_reached_another_area_learns_the_direction(self):
        f = self.use(FakeGame(beds('n', NX[:1], NZ[:1], 'x', 500, 300, stage='growing', watered=True, wilted=False)
                              + [obj('s', pos=(SX[0], SZ[0]), bubble=(960, 900), body=(960, 900), stage='growing',
                                     watered=True, wilted=False)], GAME))
        g = OG.Graph()
        g.load(SEED)
        world.refresh(g, f.read_save()[1], [], None)
        learn.MEMORY['graph'] = g
        self.addCleanup(learn.MEMORY.__setitem__, 'graph', None)
        learned = []
        with mock.patch.object(OG, 'learn_toward', lambda gr, a, b, d, rate=0.5: learned.append((a, b, d))):
            act.click((960, 900), 'point', here='Garden')   # the south bed's event says she reached GardenSouth
        self.assertEqual([(a, b) for a, b, _ in learned], [('Garden', 'GardenSouth')])
        self.assertGreater(learned[0][2][1], 0.9)   # the answered point was straight down

class AnswerCrop(Base):
    def test_a_crop_that_is_mostly_letterbox_black_is_not_stored(self):
        """Live D188: the porch-steps answer at the frame's bottom edge stored a crop that was half black bar."""
        from PIL import Image
        stored = []
        f = self.use(FakeGame([], GAME))
        img = Image.new('RGB', (1920, 1080), (120, 90, 60))
        img.paste((0, 0, 0), (0, 1018, 1920, 1080))   # the letterbox bar
        c = act.Click((960, 1000), 'point', 0, lines=['[D188 7:16:00 AM] [TRIGGER] OnExitBuilding House'])
        with mock.patch.object(learn, 'relabel', lambda im, box, kind: stored.append(kind) or True):
            learn.learn_answer(c, img)
            self.assertEqual(stored, [])
            c2 = act.Click((960, 700), 'point', 0, lines=['[D188 7:16:00 AM] [TRIGGER] OnExitBuilding House'])
            learn.learn_answer(c2, img)
        self.assertEqual(stored, ['HouseExit'])


class HarvestPolicy(EngineBase):
    """User D188: "all crops except flowers for bees should be collected when they are ready"."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(icons, 'DIR', os.path.join(self.tmp.name, 'crop_icons'))
        p.start()
        self.addCleanup(p.stop)
        icons.reset()

    def ripe(self):
        return [obj('b', pos=(NX[0], NZ[0]), bubble=(700, 400), stage='produced', watered=True, wilted=False,
                    crop='Green Bean'),
                obj('t', pos=(NX[1], NZ[0]), bubble=(1100, 400), stage='produced', watered=True, wilted=False,
                    crop='Tulip')]

    def test_negation_in_filters(self):
        self.assertFalse(plan.holds({'crop': '!Tulip|Crocus'}, {'crop': 'Tulip'}))
        self.assertTrue(plan.holds({'crop': '!Tulip|Crocus'}, {'crop': 'Green Bean'}))

    def test_every_ready_crop_but_flowers_is_picked_without_asking_which(self):
        f = self.use(FakeGame(self.ripe(), GAME))
        names = {(700, 400): 'Green Bean', (1100, 400): 'Tulip'}
        with mock.patch.object(icons, 'name_of', lambda a: names.get(tuple(a.pt))):
            res = engine.achieve('harvest')
        self.assertEqual(f.objects['b']['state']['stage'], 'growing')    # the beans are picked
        self.assertEqual(f.objects['t']['state']['stage'], 'produced')   # the tulip stays for the bees
        self.assertEqual(res['vision'], 0)
        self.assertTrue(res['stop'].startswith('done'), res['stop'])

    def test_an_unknown_crop_icon_is_asked_once_then_known(self):
        f = self.use(FakeGame(self.ripe()[:1], GAME))
        with self.assertRaises(NeedVision) as cm:
            engine.achieve('harvest')
        self.assertIn('crop', str(cm.exception).lower())
        self.assertEqual(f.objects['b']['state']['stage'], 'produced')   # nothing picked on a guess
        res = engine.achieve('harvest', answer='Green Bean')
        self.assertEqual(f.objects['b']['state']['stage'], 'growing')
        self.assertEqual(res['vision'], 0)
        self.assertIn('Green_Bean', os.listdir(icons.DIR))


class PickBubble(Base):
    def test_a_ready_crop_bubble_fits_pick_whatever_its_kind(self):
        """Live D188: ripe beds show their crop icon + the "!" sub-icon, read as `plant_growing +ready` - not `pickup`."""
        pick = next(r for r in plan.rows('GardenBed') if r['id'] == 'pick')
        self.assertTrue(plan.fits(pick)(Affordance('plant_growing', None, (0, 0), False, 0.0, False, True)))
        self.assertFalse(plan.fits(pick)(Affordance('plant_growing', None, (0, 0), False, 0.0, False, False)))


class OwnerKind(EngineBase):
    def test_a_ready_hive_bubble_is_not_a_ready_bed(self):
        hive = obj('h', kind='BeeHive', pos=(1.5, -23.5), bubble=(960, 450), save={'pollen': '12'}, ready=True)
        bed = obj('b', pos=(NX[0], NZ[0]), zone='far', bubble=(700, 400), stage='produced', watered=True, wilted=False)
        f = self.use(FakeGame([hive, bed], GAME + [dict(HIVE, bubble={'kind': 'beehive_progress'})]))
        p = mock.patch.object(icons, 'name_of', lambda a: 'Honey')
        p.start()
        self.addCleanup(p.stop)
        try:
            engine.achieve('harvest')
        except ask.NeedVision:   # the bed is out of view: a question, never a false 'done' (live D188)
            pass
        self.assertNotIn((960, 450), f.clicks)   # the honey stays: harvest is for beds


class CollectPrompt(EngineBase):
    def test_a_ready_bed_is_collected_with_space_on_the_collect_prompt(self):
        """User D188: the harvest click was right but nothing confirmed the "Collect" button; Space confirms it."""
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), bubble=(700, 400), stage='produced', watered=True,
                                   wilted=False)], GAME))
        with mock.patch.object(icons, 'name_of', lambda a: 'Green Bean'):
            res = engine.achieve('harvest')
        self.assertEqual(f.objects['b']['state']['stage'], 'growing', res)
        row = next(r for r in plan.rows() if r['id'] == 'pick')
        self.assertEqual([s_['do'] for s_ in row['steps']], ['click_bubble', 'press_space'])


class NavNeverInteracts(EngineBase):
    """User D188: "clicking bubbles can't be a navigation, it's interaction". A walk toward a detected object clicks
    free ground beside it, never its bubble; a nav click that still interacts is a surprise, not noise."""

    def test_a_walk_to_a_detected_bed_never_clicks_a_bubble(self):
        ripe = obj('r', pos=(NX[0], NZ[0]), bubble=(1400, 600), stage='produced', watered=True, wilted=False)
        far = obj('f', pos=(NX[1], NZ[0]), zone='far', bubble=(700, 400), body=(1400, 760), stage='empty',
                  watered=False, wilted=False)
        f = self.use(FakeGame([ripe, far], GAME, inventory={'TulipSeed': 2}))
        Box = __import__('collections').namedtuple('Box', 'point box kind')
        with mock.patch.object(observe, 'see', lambda kind, tried=(): [Box((1400, 600), (1340, 560, 1460, 660), 'GardenBed')]
                               if f.zone == 'near' else []):
            res = nav.new_res('t')
            t = nav.Target('t', lambda a: a.kind == 'plant', 'x', None, 'GardenBed', 'Garden', 'Garden', None)
            nav.seek(t, res)
        self.assertTrue(f.clicks, 'nav clicked nothing')
        self.assertFalse([c for c in f.clicks if observe.d(c, (1400, 600)) < nav.FREE_GAP], f.clicks)
        self.assertEqual(f.objects['r']['state']['stage'], 'produced')   # nothing collected by a walk

    def test_a_nav_click_that_opens_a_card_is_a_surprise(self):
        f = self.use(FakeGame([obj('r', pos=(NX[0], NZ[0]), bubble=(1000, 900), body=(1000, 900), stage='produced',
                                   watered=True, wilted=False)], GAME))
        res = nav.new_res('t')
        res['surprises'] = []
        c = nav.step((0.0, 1.0), res, 'step', 'Garden')   # straight down lands on the bed: it opens the Collect prompt
        self.assertTrue(any('interact' in str(s_) for s_ in res['surprises']), res)


class AskBeforeMoving(EngineBase):
    """Live D188: ready bubbles with unknown crop icons were in view; the engine explored, a click opened the Collect
    prompt, the walk closed it, and only then it asked about a tulip. The question comes first, with zero clicks."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(icons, 'DIR', os.path.join(self.tmp.name, 'crop_icons'))
        p.start()
        self.addCleanup(p.stop)
        icons.reset()

    def test_an_unknown_ready_icon_in_view_is_asked_before_any_click(self):
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), bubble=(700, 400), stage='produced', watered=True,
                                   wilted=False)], GAME))
        with self.assertRaises(NeedVision) as cm:
            engine.achieve('harvest')
        self.assertEqual(f.clicks, [])
        self.assertIn('700,400', str(cm.exception))


class CardFromAWalk(EngineBase):
    def test_a_collect_prompt_opened_by_a_walk_is_finished_by_the_row(self):
        """Live D188: a walk click opened the Collect prompt and the walk closed it. A card the current row expects is
        finished by that row (Space) when the crop under the click is known and not a flower."""
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), bubble=(1260, 500), body=(1260, 540), stage='produced',
                                   watered=True, wilted=False)], GAME))
        f.interact(f.objects['b'])   # the walk's click opened the bed's Collect prompt
        pick = next(r for r in plan.rows() if r['id'] == 'pick')
        before = [Affordance('plant_growing', None, (1260, 500), False, 0.0, False, True)]
        c = act.Click((1260, 540), 'explore', 0, before=before, mode='overlay', texts=['Collect'])
        res = nav.new_res('harvest')
        res.update(row_now=pick, skip_names={'Tulip'}, icon_of={(1260, 500): 'Green Bean'})
        self.assertTrue(engine.finish_card(c, res))
        self.assertEqual(f.objects['b']['state']['stage'], 'growing')
        res['icon_of'] = {(1260, 500): 'Tulip'}
        f.objects['b']['state']['stage'] = 'produced'
        f.interact(f.objects['b'])
        self.assertFalse(engine.finish_card(c, res))   # a flower: the card is left to be closed


class CardRunCounts(EngineBase):
    def test_a_card_finished_during_a_walk_counts_as_done(self):
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), bubble=(1260, 500), body=(1260, 540), stage='produced',
                                   watered=True, wilted=False)], GAME))
        p = mock.patch.object(icons, 'name_of', lambda a: 'Green Bean')
        p.start()
        self.addCleanup(p.stop)
        real = nav.search

        def walk_opens_the_card(t, res, rounds=nav.SEEK_TURNS, halt=None):
            if f.objects['b']['state']['stage'] == 'produced' and not res.get('walked_once'):
                res['walked_once'] = True
                res['icon_of'] = {(1260, 500): 'Green Bean'}
                f.interact(f.objects['b'])
                c = act.Click((1260, 540), 'explore', 0, before=f.scan() or [Affordance('plant_growing', None,
                              (1260, 500), False, 0.0, False, True)], mode='overlay', texts=['Collect'])
                res['on_card'](c)
                return None
            return real(t, res, rounds, halt)
        with mock.patch.object(nav, 'search', walk_opens_the_card):
            res = engine.achieve('harvest')
        self.assertEqual(f.objects['b']['state']['stage'], 'growing')
        self.assertEqual(len(res['done']), 1, res)


class ReadyMisread(EngineBase):
    """Live D188: a growing carrot's bubble was read as ready; the click showed its info card ("2 days remaining")."""

    def test_a_crop_card_after_a_failed_pick_updates_the_bed_without_asking(self):
        grow = dict(GAME[4], when={'stage': 'produced'}, bubble={'kind': 'plant_growing'}, click_event='plant_growing',
                    card=[{'texts': ['Carrot', 'A crisp orange vegetable', '2 days remaining'], 'next': 'space'}],
                    flash=['Carrot', 'A crisp orange vegetable', '2 days remaining'],
                    effect={})   # the game: the bed is still growing - its card, not a Collect prompt
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), bubble=(700, 400), stage='produced', watered=True,
                                   wilted=False)], [grow] + GAME))
        with mock.patch.object(icons, 'name_of', lambda a: 'Carrot'):
            res = engine.achieve('harvest')
        self.assertEqual(res['vision'], 0, res)
        g = OG.Graph()
        g.load(learn.GRAPH)
        nid = world.find(g, 'GardenBed', (NX[0], NZ[0]))
        self.assertEqual((g.state_value(nid, 'crop'), g.state_value(nid, 'ready'), g.state_value(nid, 'days_left')),
                         ('Carrot', False, 2))

    def test_one_junk_cyrillic_burst_line_is_not_a_wrong_language(self):
        f = self.use(FakeGame([obj('b', bubble=(700, 400), stage='growing', watered=True, wilted=False, crop='Carrot')],
                              GAME))
        f.behaviour = [dict(GAME[4], flash=['Carrot', 'Ш ПРРадр»'])]   # OCR junk; the screen itself reads English
        act.click((700, 400), 'bubble')   # no WrongLanguage


class VisitBeds(EngineBase):
    """User D188, strategy A: go bed by bed from her exact position; a bed's bubble is the one at the bed's expected
    screen point, whatever its kind or "!" reading says; the click result decides and labels the bubble's truth."""

    def setUp(self):
        super().setUp()
        for mod, name in ((icons, 'DIR'), (learn, 'TRUTH')):
            p = mock.patch.object(mod, name, os.path.join(self.tmp.name, name.lower()))
            p.start()
            self.addCleanup(p.stop)
        icons.reset()
        p = mock.patch.object(icons, 'name_of', lambda a: 'Green Bean')
        p.start()
        self.addCleanup(p.stop)

    def game(self, b_state):
        a = obj('a', pos=(NX[0], NZ[0]), bubble=(960, 470), stage='growing', watered=True, wilted=False)
        b = obj('b', pos=(NX[1], NZ[0]), bubble=(1104, 540), **b_state)
        f = self.use(FakeGame([a, b], GAME, inventory={'TulipSeed': 2}))
        f.log.append(L('9:00:00 AM', 'plant_growing', 'GardenBed', NX[0], NZ[0]))   # she stands at bed a: exact
        return f

    def test_the_bubble_at_the_beds_point_is_used_whatever_its_reading(self):
        f = self.game(dict(stage='produced', watered=True, wilted=False))
        f.relabel = {'pickup': 'water'}   # misread kind; the fake's ready flag is shown, kind is not trusted
        res = engine.achieve('harvest')
        self.assertEqual(f.clicks[0], (1104, 540), f.clicks)
        self.assertEqual(f.objects['b']['state']['stage'], 'growing', res)
        labels = json.load(open(os.path.join(learn.TRUTH, 'labels.json')))['cases']
        self.assertEqual([c['ready'] for c in labels], [True])   # the Collect prompt proved it ready

    def test_a_seed_panel_is_evidence_the_bed_is_empty(self):
        f = self.game(dict(stage='empty', watered=False, wilted=False))
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        nid = world.find(g, 'GardenBed', (NX[1], NZ[0]))
        g.set_state(nid, 'stage', 'produced', None, 'save')   # the world believes it is ready
        g.set_state(nid, 'ready', True, None, 'save')
        g.save(learn.GRAPH)
        res = engine.achieve('harvest')
        self.assertEqual(res['vision'], 0, res)
        g.load(learn.GRAPH)
        self.assertEqual(g.state_value(nid, 'stage'), 'empty')

    def geo(self, beds_, at, **kw):
        f = self.use(GeoGame(beds_, GAME, at, inventory={'TulipSeed': 2}, **kw))
        f.log.append(L('9:00:00 AM', 'plant_growing', 'GardenBed', at[0], at[1]))   # she stands at a bed: exact
        return f

    def test_walks_bed_to_bed_and_picks_each_ready_bed(self):
        """A ready bed out of bubble range: one walk to the ground below it, then its bubble at its point (D188)."""
        grow = dict(stage='growing', watered=True, wilted=False)
        ready = dict(stage='produced', watered=True, wilted=False)
        f = self.geo([obj('a', pos=(NX[0], NZ[0]), **grow), obj('b', pos=(NX[1], NZ[0]), **ready),
                      obj('c', pos=(NX[3], NZ[0]), **ready)], (NX[0], NZ[0]))
        res = engine.achieve('harvest')
        self.assertEqual([f.objects[k]['state']['stage'] for k in 'bc'], ['growing', 'growing'], res)
        self.assertTrue(f.walks, f.clicks)
        self.assertLessEqual(len(f.walks), 2, f.clicks)
        self.assertEqual(res['vision'], 0, res)
        self.assertTrue(res['stop'].startswith('done'), res)

    def test_a_walk_that_does_not_arrive_gives_the_bed_back_to_the_search(self):
        """The bubble is not at the predicted point after the walk (she was blocked): no click on a guessed bubble."""
        ready = dict(stage='produced', watered=True, wilted=False)
        f = self.geo([obj('c', pos=(NX[3], NZ[0]), **ready)], (NX[0], NZ[0]))
        f.blocked = True
        engine.achieve('harvest', max_clicks=6)
        self.assertEqual(f.objects['c']['state']['stage'], 'produced')
        self.assertEqual([c for c in f.clicks if c not in f.walks], [], f.clicks)   # only walks, never a guess

    def test_a_bed_last_checked_on_an_earlier_day_is_checked_again(self):
        """Freshness (user D188): yesterday's save says not ready; a fresh-per-day goal visits it, today it is ready."""
        grow = dict(stage='growing', watered=True, wilted=False)
        f = self.geo([obj('a', pos=(NX[0], NZ[0]), **grow), obj('b', pos=(NX[1], NZ[0]), **grow)], (NX[0], NZ[0]),
                     save_day=184)
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        g.save(learn.GRAPH)
        f.frozen = f.read_save()
        f.objects['b']['state']['stage'] = 'produced'   # it ripened overnight; the save is from yesterday
        res = engine.achieve('harvest')
        self.assertEqual(f.objects['b']['state']['stage'], 'growing', res)

    def test_a_save_older_than_a_cards_reading_does_not_overwrite_it(self):
        g = OG.Graph()
        f = self.geo([obj('b', pos=(NX[1], NZ[0]), stage='produced', watered=True, wilted=False)], (NX[0], NZ[0]))
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        nid = world.find(g, 'GardenBed', (NX[1], NZ[0]))
        g.set_state(nid, 'ready', False, 'D185 11:20:00 AM', 'card')   # the click showed "2 days remaining"
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)    # the save is from 8:00 AM
        self.assertIs(g.state_value(nid, 'ready'), False)

    def test_status_shows_each_beds_reading_its_time_and_what_to_check(self):
        f = self.geo([obj('b', pos=(NX[1], NZ[0]), stage='growing', watered=True, wilted=False)], (NX[0], NZ[0]),
                     save_day=184)
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        nid = world.find(g, 'GardenBed', (NX[1], NZ[0]))
        lines = world.status(g, 'GardenBed', today=185)
        row = next(l for l in lines if nid in l)
        self.assertIn('ready=False (save D184', row)
        self.assertIn('CHECK', row)
        g.set_state(nid, 'ready', False, 'D185 11:20:00 AM', 'card')
        row = next(l for l in world.status(g, 'GardenBed', today=185) if nid in l)
        self.assertIn('ready=False (card D185 11:20', row)
        self.assertNotIn('CHECK', row)

    def test_without_an_exact_position_vision_gives_the_first_bed_and_its_collect_finishes(self):
        """Live D188 12:20: no event since her walk, the ready bed's bubble misread as `water`; nav wandered and the
        engine stopped 'done' with 7 ready beds left. Now: vision's start question, never a false done."""
        ready = dict(stage='produced', watered=True, wilted=False)
        f = self.use(GeoGame([obj('b', pos=(NX[1], NZ[0]), **ready), obj('c', pos=(NX[2], NZ[0]), **ready)],
                             GAME, (NX[1] - 1.0, NZ[0] - 1.5), inventory={'TulipSeed': 2}))
        f.relabel, f.hide_ready = {'pickup': 'water'}, True   # read as `water`, no "!" (live D188 12:20)
        with self.assertRaises(ask.NeedVision) as e:
            engine.achieve('harvest')
        self.assertIn('orange', str(e.exception))
        # the misread goes on: after vision's answer the beds go by position (strategy A)
        self.assertEqual(f.objects['b']['state']['stage'], 'produced')
        bx, by = f._pt(f.objects['b']['pos'])
        cell = f'{chr(65 + int(bx // ask.CELL_W))}{int(by // ask.CELL_H) + 1}'
        res = engine.achieve('harvest', answer=cell)
        self.assertEqual([f.objects[k]['state']['stage'] for k in 'bc'], ['growing', 'growing'], res)
        self.assertTrue(res['stop'].startswith('done'), res)

    def test_a_textless_overlay_after_a_walk_is_gameplay_not_an_interaction(self):
        """Live D188: every garden click read `overlay` with no text (the HUD hides on zoom); nav logged each walk
        as a surprise interaction and closed the screen."""
        c = act.Click((700, 600), 'step', 0, mode='overlay', texts=[], moved=True)
        res = {}
        self.assertTrue(nav.walked(c, None, res))
        self.assertEqual(res.get('surprises', []), [])
        self.assertFalse(act.on_card(c))
        self.assertTrue(act.on_card(act.Click((700, 600), 'step', 0, mode='overlay', texts=['Collect'])))


class Lost(EngineBase):
    """Live D188 12:31 (S40): far from the garden she followed phantom bed detections in the grass for 15+ clicks,
    the map was used once, nothing measured progress, and an old event position was trusted as exact."""
    Box = __import__('collections').namedtuple('Box', 'point box kind')

    def lost_game(self):
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), zone='far', bubble=(700, 400), stage='produced',
                                   watered=True, wilted=False)], GAME))
        f.step_zone, f.steps_needed = 'nowhere', 99   # every step walks, none arrives
        return f

    def test_a_walk_under_a_textless_overlay_makes_the_old_position_stale(self):
        f = self.lost_game()
        f.log.append(L('9:00:00 AM', 'plant_growing', 'GardenBed', NX[0], NZ[0]))
        f.blank_overlay = True   # the HUD hides on zoom: mode overlay, no text
        self.assertEqual(where.position(far_ok=False)[0], 'event')
        act.click((1300, 540), 'step')
        self.assertEqual(where.position(far_ok=False), (None, None))

    def test_two_arrival_misses_turn_detections_off_and_the_map_leads(self):
        f = self.lost_game()
        maps = []
        with mock.patch.object(observe, 'see', lambda kind, tried=(): [self.Box((1300, 700), (1250, 650, 1350, 690),
                                                                                'GardenBed')]), \
                mock.patch.object(nav, 'map_direction', lambda node: maps.append(node) or (1.0, 0.0)):
            try:
                engine.achieve('harvest', max_clicks=12)
            except ask.NeedVision:
                pass
        seen = [c for c in f.clicks if c == nav.beside(self.Box((1300, 700), (1250, 650, 1350, 690), 'GardenBed'), [])]
        self.assertLessEqual(len(seen), nav.MISS_MAX, f.clicks)
        self.assertTrue(maps, f.clicks)

    def test_map_steps_that_get_no_closer_on_the_map_are_lost(self):
        f = self.lost_game()

        def flat_map(node):
            nav.LAST_MAP.update(pin=(300, 300), goal=(690, 490))   # the pin never moves (far from any landmark)
            return (1.0, 0.0)
        with mock.patch.object(nav, 'map_direction', flat_map), mock.patch.object(nav, 'inside', lambda t, here: False):
            with self.assertRaises(ask.NeedVision) as e:
                engine.achieve('harvest', max_clicks=40)
        self.assertIn('LOST', str(e.exception))   # 6 blind walks or 3 flat map readings: whichever comes first
        self.assertLessEqual(len(f.clicks), nav.MAP_STEPS * nav.MAP_FLAT, f.clicks)

    def test_a_dead_reckoned_position_expires(self):
        """Live D188 13:02: a walk-end position left on disk by an earlier attempt sent the first clicks to her feet."""
        self.lost_game()
        where.walked(to=(1.0, 2.0))
        self.assertEqual(where.position(far_ok=False, walk_ok=True), ('walk', (1.0, 2.0)))
        with mock.patch.object(where.time, 'time', lambda: where._WALK['at'] + where.WALK_TTL + 1):
            self.assertEqual(where.position(far_ok=False, walk_ok=True), (None, None))

    def test_questions_left_by_killed_attempts_do_not_count(self):
        """Live D188 13:45: three killed attempts left harvest's vision counter at 3: one new question = LAWS_STUCK."""
        st = {'goal': 'harvest', 'asks': 3, 'history': ['old'], 't': 0.0}
        with open(ask.STATE, 'w') as fh:   # left by a killed attempt long ago
            json.dump({'harvest': st}, fh)
        self.assertEqual(ask.load_state('harvest')['asks'], 0)
        ask.save_state(st)                 # an active run saves now
        self.assertEqual(ask.load_state('harvest')['asks'], 3)

    def test_an_unusable_map_calibration_is_reported(self):
        self.lost_game()
        with mock.patch.object(where, 'pairs', lambda: [[[0, 0], [100, 100]], [[10, 0], [900, 100]], [[0, 10], [100, 0]]]):
            try:
                res = engine.achieve('harvest', max_clicks=2)
            except ask.NeedVision:
                res = None
        self.assertIn('map calibration', ' '.join(engine.LAST.get('notes', [])))

    def test_walks_without_progress_stop_with_one_question(self):
        f = self.lost_game()
        with mock.patch.object(nav, 'map_direction', lambda node: (1.0, 0.0)):
            with self.assertRaises(ask.NeedVision) as e:
                engine.achieve('harvest', max_clicks=40)
        self.assertIn('LOST', str(e.exception))
        self.assertLessEqual(len(f.clicks), nav.BLIND_MAX + 1, f.clicks)


class Landmarks(EngineBase):
    """User D188: "this is a mine, record it in map, vectors, graph" - a dead end at the farm's north-west corner."""

    def test_a_landmark_from_kinds_is_a_graph_node_with_its_map_point_and_dead_end(self):
        f = self.use(FakeGame([], GAME))
        g = self.graph()
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        n = g.nodes['Mine']
        self.assertEqual((n.type, n.kind, n.region), ('unique', 'Mine', 'Farm'))
        self.assertTrue(n.extra['dead_end'])
        self.assertEqual(n.extra['map']['kind'], 'MapMine')
        self.assertEqual(tuple(n.extra['map']['point']), (562, 450))
        self.assertEqual(world.landmark_at(g, (530, 425)), 'Mine')   # the pin by the mine
        self.assertIsNone(world.landmark_at(g, (900, 700)))


class MapWay(EngineBase):
    """User D188 (at the mine): 1. map used too late 2. steps very small 3. wrong direction - the mine is a dead end
    4. map and scene have roads: for two distant places the model guesses the way by map, graph and roads."""

    def lost(self):
        f = self.use(FakeGame([obj('b', pos=(NX[0], NZ[0]), zone='far', bubble=(700, 400), stage='produced',
                                   watered=True, wilted=False)], GAME))
        f.step_zone, f.steps_needed = 'nowhere', 99
        rs = f.read_save

        def far_save():   # live D188 15:30: the save had her by the mine, far from the garden
            name, s_ = rs()
            s_['currentPlayerPosition'] = {'x': -25.6, 'y': 1.1, 'z': 3.05}
            return name, s_
        f.read_save = far_save
        return f

    def reading(self, pin, goal=(690, 490), d=(1.0, 0.0), order=None):
        def md(node):
            if order is not None:
                order.append('map')
            nav.LAST_MAP.update(pin=tuple(pin), goal=tuple(goal), img=None)
            return d
        return md

    def test_without_a_known_place_the_map_comes_before_detections(self):
        self.lost()
        order = []
        Box = __import__('collections').namedtuple('Box', 'point box kind')
        see = lambda kind, tried=(): order.append('see') or [Box((1300, 700), (1250, 650, 1350, 690), 'GardenBed')]
        with mock.patch.object(observe, 'see', see), \
                mock.patch.object(nav, 'map_direction', self.reading((300, 300), order=order)):
            try:
                engine.achieve('harvest', max_clicks=4)
            except ask.NeedVision:
                pass
        self.assertEqual(order[0], 'map', order)

    def test_map_led_steps_are_long(self):
        f = self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((300, 300))):
            try:
                engine.achieve('harvest', max_clicks=3)
            except ask.NeedVision:
                pass
        x, y = f.clicks[0]
        self.assertGreaterEqual(math.hypot(x - 960, y - 540), nav.MAP_STEP_R - 2, f.clicks)

    def test_at_a_dead_end_vision_reads_the_map_for_a_road_direction(self):
        f = self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((530, 425))):   # the pin at the mine
            with self.assertRaises(ask.NeedVision) as e:
                engine.achieve('harvest', max_clicks=10)
        msg = str(e.exception)
        self.assertIn('dead end', msg)
        self.assertIn('Mine', msg)
        self.assertIn('NE', msg)
        self.assertEqual(f.clicks, [])   # no step into the dead end

    def test_progress_is_measured_along_the_road_route_not_the_straight_line(self):
        """Live D188 13:45: east of the mine the pin got closer as the crow flies but she was in a pocket by the river
        (rocks, water): the straight line learned a wrong way. The road route's length is the progress."""
        res = {'way': ('Mine', 'GardenBed@Garden', (1.0, 0.0)), 'map_best': 172.0}
        nav.LAST_MAP.clear()
        nav.LAST_MAP.update(pin=(600, 452), goal=(690, 490), route_len=260.0)   # closer in a line, longer by road
        with mock.patch('game.integrate.relation', lambda *a: self.fail('a wrong way learned')):
            nav._map_progress(res)
        self.assertEqual(res.get('map_flat'), 1)
        self.assertIn('way', res)

    def test_the_way_question_shows_the_frame_next_to_the_map(self):
        self.use(FakeGame([], GAME))
        from PIL import Image
        nav.LAST_MAP.clear()
        nav.LAST_MAP.update(pin=(530, 425), goal=(690, 490), img=Image.new('RGB', (1920, 1080), (40, 120, 200)))
        pic = nav.way_image()
        self.assertEqual(pic.size, (1920, 2160))   # full scale (user D188): the zoomed map on top, the view below
        self.assertNotEqual(pic.getpixel((960, 300)), pic.getpixel((960, 1600)))

    def test_the_way_map_is_zoomed_to_the_pin_and_the_goal(self):
        self.use(FakeGame([], GAME))
        from PIL import Image
        nav.LAST_MAP.clear()
        nav.LAST_MAP.update(pin=(530, 425), goal=(690, 490), img=Image.new('RGB', (1920, 1080), (40, 120, 200)))
        box = nav.way_box()
        self.assertTrue(box[0] < 530 and box[2] > 690 and box[1] < 425 and box[3] > 490, box)
        self.assertLess(box[2] - box[0], 1920 / 2)   # zoomed in at least 2x
        self.assertAlmostEqual((box[2] - box[0]) / (box[3] - box[1]), 16 / 9, 1)

    def test_the_answered_direction_walks_long_steps_and_progress_learns_the_way(self):
        f = self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((530, 425))):
            with self.assertRaises(ask.NeedVision):
                engine.achieve('harvest', max_clicks=10)
        pins = iter([(560, 470), (590, 490), (620, 495), (650, 495)])
        def closer(node):
            nav.LAST_MAP.update(pin=next(pins, (650, 495)), goal=(690, 490), img=None)
            return (1.0, 0.0)
        with mock.patch.object(nav, 'map_direction', closer):
            try:
                engine.achieve('harvest', answer='S', max_clicks=8)
            except ask.NeedVision:
                pass
        first = f.clicks[:nav.MAP_STEPS]
        self.assertTrue(all(y > 540 + nav.MAP_STEP_R * 0.8 for x, y in first), f.clicks)   # south, long
        g = self.graph()
        way = [e for e in g.edges('Mine', 'toward')]
        self.assertTrue(way and way[0]['dir'][1] > 0.9, g.edges('Mine'))


class NavLadder(MapWay):
    """User D188: each step - target visible by vectors? -> graph close + direction? -> map. Tara's place in the
    graph after each step; distance tiers map-far / screen-far / steps-far; failures -> vision + gap bundle."""
    Box = __import__('collections').namedtuple('Box', 'point box kind')

    def setUp(self):
        super().setUp()
        from game import integrate
        p = mock.patch.object(integrate, 'JOURNAL_DIR', os.path.join(self.tmp.name, 'journal'))
        p.start()
        self.addCleanup(p.stop)

    def dets(self, calls):
        return lambda kind, tried=(): calls.append(kind) or [self.Box((1300, 700), (1250, 650, 1350, 690), 'GardenBed')]

    def test_map_far_never_uses_detections(self):
        self.lost()
        calls = []
        with mock.patch.object(observe, 'see', self.dets(calls)), \
                mock.patch.object(nav, 'map_direction', self.reading((300, 300))):
            try:
                engine.achieve('harvest', max_clicks=6)
            except ask.NeedVision:
                pass
        self.assertNotIn('GardenBed', calls)   # target detections are phantoms far away; Path patches guide steps

    def test_near_on_the_map_the_vectors_lead(self):
        f = self.lost()
        calls = []
        with mock.patch.object(observe, 'see', self.dets(calls)), \
                mock.patch.object(nav, 'map_direction', self.reading((670, 480))):   # 22 px from the garden
            try:
                engine.achieve('harvest', max_clicks=3)
            except ask.NeedVision:
                pass
        self.assertTrue(calls)
        self.assertEqual(f.clicks[0], nav.beside(self.Box((1300, 700), (1250, 650, 1350, 690), 'GardenBed'), []))

    def test_close_without_a_visible_target_the_graph_direction_leads(self):
        f = self.lost()
        g = self.graph()
        g.add_edge('Well', 'Garden', 'toward', dir=[0.0, 1.0], source='learned')   # the target node is the area
        g.save(learn.GRAPH)
        with mock.patch.object(observe, 'closest_node', lambda affs=None: 'Well'), \
                mock.patch.object(nav, 'map_direction', self.reading((670, 480))):
            try:
                engine.achieve('harvest', max_clicks=2)
            except ask.NeedVision:
                pass
        x, y = f.clicks[0]
        self.assertEqual(x, 960)
        self.assertGreater(y, 540)   # south, the learned way

    def test_a_pin_that_jumps_is_rejected_with_a_question_and_a_gap(self):
        f = self.lost()
        pins = iter([(300, 300), (1320, 419)])

        def jumpy(node):
            nav.LAST_MAP.update(pin=next(pins, (1320, 419)), goal=(690, 490), img=None)
            return (1.0, 0.0)
        with mock.patch.object(nav, 'map_direction', jumpy):
            with self.assertRaises(ask.NeedVision) as e:
                engine.achieve('harvest', max_clicks=20)
        self.assertIn('pin', str(e.exception).lower())
        self.assertEqual(len(f.clicks), nav.MAP_STEPS)   # the first reading's steps only
        from game import integrate
        self.assertTrue(any(b['owner'] == 'nav' for b in integrate.gaps()))

    def test_lost_writes_a_nav_gap_bundle(self):
        self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((300, 300))):   # walks, never closer
            try:
                engine.achieve('harvest', max_clicks=40)
            except ask.NeedVision:
                pass
        from game import integrate
        self.assertTrue(any(b['owner'] == 'nav' and ('lost' in b['invariant'] or 'stuck' in b['invariant'])
                            for b in integrate.gaps()), integrate.gaps())

    def test_tara_keeps_her_tier_and_pin_in_the_graph_after_each_step(self):
        self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((300, 300))):
            try:
                engine.achieve('harvest', max_clicks=3)
            except ask.NeedVision:
                pass
        g = self.graph()
        self.assertEqual(tuple(g.nodes['Tara'].extra.get('pin')), (300, 300))
        e = next(e for e in g.edges('Tara', 'distance') if e['b'] == 'Garden')   # the tier lives on the edge
        self.assertEqual(e['tier'], 'map-far')


class DistanceEdges(NavLadder):
    """User D188: "so a new distance edge?" - "yes": Tara -> target `distance` edge each step (tier, map px, route
    px); ways between nodes carry their distance next to the compass point."""

    def edge(self, b='Garden'):
        return next((e for e in self.graph().edges('Tara', 'distance') if e['b'] == b), None)

    def test_each_step_rewrites_the_tara_to_target_distance_edge(self):
        self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((300, 300))):
            try:
                engine.achieve('harvest', max_clicks=3)
            except ask.NeedVision:
                pass
        e = self.edge()
        self.assertIsNotNone(e, self.graph().edges('Tara'))
        self.assertEqual(e['tier'], 'map-far')
        self.assertEqual(round(e['map_px']), round(math.dist((300, 300), (690, 490))))
        self.assertEqual(len([x for x in self.graph().edges('Tara', 'distance') if x['b'] == 'Garden']), 1)

    def test_progress_is_judged_against_the_edge_across_calls(self):
        self.lost()
        with mock.patch.object(nav, 'map_direction', self.reading((300, 300))):
            for _ in range(2):
                try:
                    engine.achieve('harvest', max_clicks=3)
                except ask.NeedVision:
                    pass
            res = {'params': {}}
            g = self.graph()
            learn.MEMORY['graph'] = g
            try:
                nav.LAST_MAP.clear()
                nav.LAST_MAP.update(pin=(300, 300), goal=(690, 490))
                nav._map_progress(res, 'Garden')
            finally:
                learn.MEMORY['graph'] = None
        self.assertGreaterEqual(res.get('map_flat', 0), 1)   # the same distance as the edge: no progress

    def test_a_learned_way_carries_its_distance(self):
        from game import integrate
        g = self.graph()
        learn.MEMORY['graph'] = g
        try:
            integrate.relation('Mine', 'Garden', (0.0, 1.0), 'test', route_px=172.0)
        finally:
            learn.MEMORY['graph'] = None
        e, = g.edges('Mine', 'toward')
        self.assertEqual((e['compass'], e['route_px']), ('S', 172.0))


class PathSteps(MapWay):
    """Way steps follow the path she stands on (live D188 16:16: S stepped into the rocks below her). The path is
    found by its embeddings (objects db `Path`); a blocked way asks vision for a cell on the path and stores its look."""
    Box = __import__('collections').namedtuple('Box', 'point box kind')

    def test_a_way_step_snaps_to_the_seen_path_near_its_direction(self):
        f = self.lost()
        f.step_zone, f.steps_needed = 'nowhere', 99
        path = [self.Box((700, 900), (650, 860, 750, 940), 'Path'), self.Box((1500, 300), (1450, 260, 1550, 340), 'Path')]
        with mock.patch.object(observe, 'see', lambda kind, tried=(): path if kind == 'Path' else []):
            res = nav.new_res('t')
            nav.walk_way('S', {'from': 'Mine', 'to': 'Garden'}, res)
        self.assertEqual(f.clicks[0], (700, 900))   # the path patch south-west, not the rocks straight below

    def test_a_blocked_way_asks_for_a_cell_on_the_path_and_learns_its_look(self):
        f = self.lost()
        f.step_zone, f.steps_needed, f.step_ok = 'nowhere', 99, (lambda x, y: False)   # every direction blocked
        with mock.patch.object(nav, 'map_direction', self.reading((530, 425))):
            with self.assertRaises(ask.NeedVision):
                engine.achieve('harvest', max_clicks=20)
            with self.assertRaises(ask.NeedVision) as e:
                engine.achieve('harvest', answer='S', max_clicks=20)
        self.assertIn('ON THE PATH', str(e.exception))
        f.step_ok = lambda x, y: True
        stored = []
        with mock.patch.object(learn, 'relabel', lambda img, box, kind: stored.append(kind) or True), \
                mock.patch.object(nav, 'map_direction', self.reading((560, 470))):
            try:
                engine.achieve('harvest', answer='H10', max_clicks=4)
            except ask.NeedVision:
                pass
        self.assertIn('Path', stored)


if __name__ == '__main__':
    unittest.main()
