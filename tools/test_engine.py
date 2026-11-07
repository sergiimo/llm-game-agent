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
from game import act, affordances, ask, badges, brief, core, engine, garden as garden_actions, icons, learn, nav, observe, plan, screen, smoke, steps, ui, where, world  # noqa: E402
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
        return 'fake.sav', {'currentScene': 'Farm',
                            'scenes': [{'sceneName': 'Farm', 'addedObjects': objs, 'updatedObjects': []}],
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
        if a == 'text:Resume Game':
            self.paused = False
            return None
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

    def scan(self, image=None):
        if self.card:   # a card hides the bubbles (game D184)
            return []
        out = []
        for o in self.objects.values():
            b = self.beh_of(o) if o['zone'] == self.zone else None
            if b is None or not o.get('bubble_pt'):
                continue
            s = o['state']
            drop = bool(s.get('wilted')) or (s.get('watered') is False and s.get('stage') in ('growing', 'producing'))
            ready = o.get('scan_ready', s['ready'] if 'ready' in s else s.get('stage') == 'produced')
            out.append(Affordance(self.relabel.get(b['bubble']['kind'], b['bubble']['kind']), None, tuple(o['bubble_pt']),
                                  False, 0.0, drop and not self.hide_drop, bool(ready) and not self.hide_ready,
                                  o.get('badge'), o.get('icon')))
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
            near = _m.dist(o['pos'], self.pos) <= self.SHOW and not o.get('no_bubble')
            o['bubble_pt'] = self._pt(o['pos']) if near else None

    def scan(self, image=None):
        self._place()
        return super().scan(image)

    def run_action(self, a):
        self._place()
        m = re.match(r'click:(-?\d+):(-?\d+)', a)
        if m and not self.card and not self.paused and self._bed_at(int(m.group(1)), int(m.group(2))):
            o = self._bed_at(int(m.group(1)), int(m.group(2)))
            self.clicks.append((int(m.group(1)), int(m.group(2))))
            self.pos = (o['pos'][0], o['pos'][1] - 1.0)
            self.walk_frames = 1
            self._place()
            return self.interact(o)
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

    def _bed_at(self, x, y):
        import math as _m
        for o in self.objects.values():
            bx, by = self._pt(o['pos'])
            if abs(bx - x) < 40 and abs(by + 40 - y) < 40 and _m.dist(o['pos'], self.pos) > self.SHOW:
                return o
        return None

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
              mock.patch.object(badges, 'DIR', os.path.join(self.tmp.name, 'badges')),   # never the real stores
              mock.patch.object(icons, 'DIR', os.path.join(self.tmp.name, 'crop_icons')),
              mock.patch.object(act, 'BURST', (0.0, 0.0)), mock.patch.object(act, 'EVENT_WAIT', 0.0),
              mock.patch.object(observe, 'see', lambda kind, tried=(): []),
              mock.patch.object(observe, 'see_all', lambda region=None: []),
              mock.patch.object(nav, 'map_direction', lambda node: None)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        badges.reset()
        icons.reset()
        self.addCleanup(badges.reset)
        self.addCleanup(icons.reset)

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

    def test_an_explicit_region_parameter_scopes_a_library_goal(self):
        self.assertEqual(engine._where({'where': {'ready': True}}, {'region': 'GardenSouth'}),
                         {'ready': True, 'region': 'GardenSouth'})

    def test_an_explicit_crop_overrides_the_default_flower_skip_policy(self):
        spec = {'where': {'crop': '!$flowers'}, 'skip_bubbles': {'crop': '$flowers'}}
        self.assertEqual(engine._where(spec, {'crops': 'Tulip'}), {'crop': 'Tulip'})
        self.assertNotIn('Tulip', engine._skip_names(spec, {'crops': 'Tulip'}))

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

    def test_ready_hive_has_a_seeded_collect_path(self):
        self.assertEqual(plan.path('BeeHive', {'ready': True}, {'ready': False}, {})[0]['id'], 'hive_collect')

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
        before = next(r for r in plan.rows() if r['id'] == 'water')
        plan.count('water', True)
        plan.count('water', False)
        r = next(r for r in plan.rows() if r['id'] == 'water')
        self.assertEqual((r['seen'], r['ok'], r['surprises']),
                         (before['seen'] + 2, before['ok'] + 1, before['surprises'] + 1))


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

    def test_water_event_after_an_empty_save_proves_the_bed_is_no_longer_empty(self):
        world.refresh(self.g, self.save(), [L('9:00:00 AM', 'water', 'GardenBed', 6.39, -63.11)],
                      'D185 8:00:00 AM')
        nid = 'GardenBed#6.4,-63.1'
        self.assertEqual(world.state_of(self.g, nid)['stage'], 'growing')
        self.assertTrue(world.state_of(self.g, nid)['watered'])

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

    def test_plant_confirmation_accepts_complete_after_the_opening_click_logged_plant(self):
        planting = dict(GAME[1], click_event='plant', event='complete')
        f = self.use(FakeGame([obj('a', stage='empty')], [planting] + GAME[2:],
                              inventory={'TulipSeed': 3}))

        out = steps.run(self.row('plant', seed='Tulip'), {'seed': 'Tulip'}, f.scan()[0])

        self.assertTrue(out['ok'], out)
        self.assertIn('totalPlanted.TulipSeed', '\n'.join(out['lines']))
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
        ask.save_state({'goal': 'garden', 'asks': 1, 'history': [],
                        'pending': {'kind': 'click', 'goal': 'garden'}})
        out = steps.run(r, {'seed': 'Tulip'}, f.scan()[0])
        self.assertFalse(out['ok'])
        self.assertEqual(out['failed_step'], 0)
        self.assertIn('NEED_VISION game:', out.get('why', ''))
        self.assertIn('DIAGNOSTIC ONLY', out['why'])
        self.assertEqual(len(f.asks), 1)
        self.assertNotIn('pending', ask.load_state('garden'))
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

    def test_duplicate_streaming_observation_keeps_pending_and_budget(self):
        pending = dict(self.pending(), goal='garden', params={'region': 'Garden'}, streaming=True)
        with self.assertRaises(NeedVision):
            ask.ask('click', 'first frame', pending, {'goal': 'garden', 'vision': 0})
        with self.assertRaises(NeedVision):
            ask.ask('click', 'refreshed same frame', pending, {'goal': 'garden', 'vision': 0})
        state = ask.load_state('garden')
        self.assertEqual(state['asks'], 1)
        self.assertEqual(state['pending']['params'], {'region': 'Garden'})

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











HIVE = {'kind': 'BeeHive', 'when': {'ready': True}, 'bubble': {'kind': 'honey'}, 'event': 'beehive_collect',
        'effect': {'ready': False}}


class Learning(EngineBase):
    """A transition the table doesn't know is learned from play (frame change / event), then replayed."""

    def hives(self, ready):
        return [obj(f'h{i}', kind='BeeHive', pos=(x, -23.5), bubble=(400 + 150 * i, 300) if i in ready else None,
                    save={'pollen': '0'}, **({'ready': True} if i in ready else {}))
                for i, x in enumerate((-2.3, -1.0, 0.2, 1.5, 2.7, 4.0, 5.2, 6.5))]

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


    def test_garden_cli_defaults_to_the_main_garden(self):
        import wf
        calls = []
        with mock.patch.object(wf, 'game_cmd', lambda kind, args: calls.append((kind, args)) or 0), \
             mock.patch.object(wf, 'ensure_front'), mock.patch.object(wf, 'release_focus', return_value=False), \
             mock.patch.object(wf, 'wait_settle'), mock.patch.object(wf, 'state', return_value={'mode': 'gameplay', 'text': []}), \
             mock.patch.object(wf, 'print_log'):
            wf.main(['garden'])
            wf.main(['garden', 'region=GardenSouth', 'max_clicks=9'])
        self.assertEqual(calls, [('garden', []), ('garden', ['region=GardenSouth', 'max_clicks=9'])])

    def test_garden_cli_normalizes_shell_safe_structured_vision_answers(self):
        import wf
        self.assertEqual(
            wf.garden_cli_args(['region=Garden', 'answer=walk:F7', 'relative=NW', 'distance=near']),
            ({'region': 'Garden'}, 'walk F7 relative=NW distance=near'))
        self.assertEqual(
            wf.garden_cli_args(['answer=target:J6', 'crop=Green Bean', 'relative=SE', 'distance=inside',
                                'max_clicks=9', 'crops=Tulip']),
            ({'max_clicks': 9, 'crops': 'Tulip'}, 'target J6 crop=Green Bean relative=SE distance=inside'))

    def test_garden_cli_rejects_orphan_localization_metadata(self):
        import wf
        with self.assertRaisesRegex(ValueError, 'both relative and distance'):
            wf.garden_cli_args(['answer=walk:F7', 'relative=NW'])

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

    @staticmethod
    def far_map(node):
        nav.LAST_MAP.update(pin=(100, 100), goal=(700, 500), img=None)
        return (1.0, 0.0)

    def far(self, zone='far', body=None):
        return [obj(f'f{i}', pos=p, zone=zone, bubble=(700 + 200 * i, 300), body=body, stage='growing', watered=False,
                    wilted=False) for i, p in enumerate(self.FAR)]










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
        actions = []
        run = f.run_action
        f.run_action = lambda a: (actions.append(a), run(a))[1]
        self.close.__wrapped__()
        self.assertFalse(f.paused)
        self.assertEqual(actions[0], 'text:Resume Game')

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
        f.blank_overlay, f.overlay_texts = True, ['Bee Hive', 'Plant flowers nearby', 'Collect']   # Escape doesn't close it
        # (a card WITH a button: buttonless cards are waited out, never escaped - live D189 quest toast)
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
        self.assertEqual(R('overlay', ['']), 'gameplay')   # live OCR may retain one empty numbered row after resume
        self.assertEqual(R('overlay', ['Game Paused', 'Resume Game']), 'pause')
        self.assertEqual(R('cutscene', ['Game Paused', 'Resume Game']), 'pause')
        self.assertEqual(R('overlay', ['Inventory', 'Seeds', 'Tulip Bulbs']), 'picker')
        self.assertEqual(R('overlay', ['Tulip Bulbs', 'Plant these tulip bulbs in a', 'Select']), 'card')
        self.assertEqual(R('overlay', ['Settings', 'Music Volume']), 'menu')
        self.assertEqual(R('dialogue', ['Hello']), 'dialogue')

    def test_captured_scenery_ocr_fragment_is_not_a_card_but_short_controls_are(self):
        # D209 turn 25, turn-6b0fd8403fa949d199d04097372df5a9.jpg: HUD + two bubbles, no card.
        # Real comparison turn-239041414174482dbce58391c373c3a7.jpg: a visible Collect card.
        self.assertNotEqual(screen.classify('overlay', ['ain']), 'card')
        for texts in (['Collect'], ['Buy'], ['Yes'], ['No'], ['OK'], ['Tulip', '3 days remaining']):
            with self.subTest(texts=texts):
                self.assertEqual(screen.classify('overlay', texts), 'card')

    def test_captured_nate_needs_semantic_screen_evidence_not_text_length(self):
        # Resume exp 2983f90507bbc166: NATE was read over two recognized world affordances.
        self.assertEqual(screen.classify('overlay', ['NATE']), 'unknown')
        for text in ('ain', 'NATE', 'Unrecognized overlay title'):
            with self.subTest(text=text):
                self.assertEqual(screen.classify('overlay', [text]), 'unknown')
                self.assertEqual(screen.classify('overlay', [text], world_visible=True), 'gameplay')
        for texts, expected in [(['Collect'], 'card'), (['Inventory', 'Seeds'], 'picker'),
                                (['Tulip', '3 days remaining'], 'card'), (['Game Paused'], 'pause')]:
            with self.subTest(texts=texts):
                self.assertEqual(screen.classify('overlay', texts, world_visible=True), expected)

    def test_unknown_overlay_is_not_closed_or_clicked_through(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Unrecognized overlay title']
        commands = []
        f.run_action = lambda command: commands.append(command)
        self.assertEqual(screen.read().kind, 'unknown')
        self.assertEqual(screen.close().kind, 'unknown')
        with self.assertRaises(observe.LawsStuck):
            screen.require_world()
        self.assertEqual(commands, [])

    def test_persistent_progress_details_are_closed_before_world_is_allowed(self):
        for texts in (['Carrot', 'A crisp orange vegetable', '3 days remaining', 'Makes 4'],
                      ['Pumpkin', '1 day remaining'], ['Honey', 'Makes 1']):
            with self.subTest(texts=texts):
                info = {'kind': 'GardenBed', 'card': [{'texts': texts, 'next': 'space'}]}
                f = self.use(FakeGame([obj('a')], [info]))
                f.interact(f.objects['a'])
                with mock.patch.object(screen, 'HINT_WAIT', 0.0):
                    result = screen.require_world()
                self.assertEqual(result.kind, 'gameplay')
                self.assertIsNone(f.card)
                self.assertFalse(f.paused)

    def test_a_progress_detail_that_fades_during_settle_is_never_escaped(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Carrot', '1 day remaining', 'Makes 4']
        f.wait_settle = lambda: setattr(f, 'blank_overlay', False)
        commands = []
        run = f.run_action
        f.run_action = lambda command: (commands.append(command), run(command))[1]
        self.assertEqual(screen.require_world().kind, 'gameplay')
        self.assertEqual(commands, [])

    def test_progress_detail_escape_opening_pause_is_resumed_and_blocks_world_click(self):
        f = self.use(FakeGame([], GAME))
        f.blank_overlay, f.overlay_texts = True, ['Carrot', '3 days remaining', 'Makes 4']
        with mock.patch.object(screen, 'HINT_WAIT', 0.0):
            with self.assertRaisesRegex(core.Failed, 'Escape opened the pause menu'):
                act.click((1200, 800), 'explore')
        self.assertFalse(f.paused)
        self.assertEqual(f.clicks, [])

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


class WorldMapGuard(EngineBase):
    def map_game(self, objects=(), escape_closes=True, toggle_closes=True):
        from PIL import Image
        f = self.use(FakeGame(objects, GAME))
        f.blank_overlay = True  # both the map and garden zoom can have no OCR text
        f.map_open = True
        f.map_frame = Image.new('RGB', (1920, 1080), 'red')
        f.world_frame = Image.new('RGB', (1920, 1080), 'green')
        f.grab = lambda: f.map_frame if f.map_open else f.world_frame
        f.map_pin = lambda img: (900, 500) if img is f.map_frame else None
        f.keys = []
        run_action = f.run_action

        def run(command):
            if f.map_open and command in ('key:escape', 'key:m'):
                f.keys.append(command)
                if (command == 'key:escape' and escape_closes) or (command == 'key:m' and toggle_closes):
                    f.map_open = False
                return None
            return run_action(command)

        f.run_action = run
        return f

    def test_act_gameplay_closes_a_textless_map_before_world_perception(self):
        f = self.map_game()
        act.gameplay()
        self.assertFalse(f.map_open)
        self.assertEqual(f.keys, ['key:escape'])
        self.assertIs(f.grab(), f.world_frame)

    def test_textless_nonmap_garden_zoom_remains_gameplay_without_input(self):
        f = self.map_game()
        f.map_open = False
        act.gameplay()
        self.assertEqual(screen.require_world().kind, 'gameplay')
        self.assertEqual(f.keys, [])
        self.assertFalse(f.paused)

    def test_resuming_pause_rechecks_the_map_it_reveals_before_returning_world(self):
        f = self.map_game()
        f.paused = True
        f.map_pin = lambda img: (900, 500) if not f.paused and img is f.map_frame else None
        self.assertEqual(screen.require_world().kind, 'gameplay')
        self.assertFalse(f.paused)
        self.assertFalse(f.map_open)
        self.assertEqual(f.keys, ['key:escape'])
        self.assertIs(f.grab(), f.world_frame)

    def test_map_toggle_is_only_used_after_verified_escape_failure(self):
        f = self.map_game(escape_closes=False)
        self.assertEqual(screen.require_world().kind, 'gameplay')
        self.assertFalse(f.map_open)
        self.assertEqual(f.keys, ['key:escape', 'key:m'])

    def test_unclosable_textless_map_blocks_gameplay_and_world_click(self):
        f = self.map_game(escape_closes=False, toggle_closes=False)
        for operation in (act.gameplay, lambda: act.click((900, 700), 'point')):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(observe.LawsStuck, 'MAP'):
                    operation()
        self.assertEqual(f.clicks, [])



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

    def test_an_event_older_than_the_save_does_not_override_the_saved_position(self):
        f = self.use(FakeGame([], GAME))
        f.log.append(L('7:35:00 AM', 'beehive_progress', 'BeeHive', 6.47, -23.46))
        self.assertEqual(where.position(far_ok=False), (None, None))

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


class VisionAnswers(Base):
    """User D188: "each vision need should produce a graph and vectors improvement". A vision click answer whose
    result proves an object stores the clicked look as that kind, learns the direction toward the node it reached,
    and is recorded with hit/miss."""

    def setUp(self):
        super().setUp()
        self.stored = []
        p = mock.patch.object(learn, 'relabel',
                              lambda img, box, kind, idempotency_key=None:
                              self.stored.append((tuple(box), kind)) or True)
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



class PickBubble(Base):
    def test_a_ready_crop_bubble_fits_pick_whatever_its_kind(self):
        """Live D188: ripe beds show their crop icon + the "!" sub-icon, read as `plant_growing +ready` - not `pickup`."""
        pick = next(r for r in plan.rows('GardenBed') if r['id'] == 'pick')
        self.assertTrue(plan.fits(pick)(Affordance('plant_growing', None, (0, 0), False, 0.0, False, True)))
        self.assertFalse(plan.fits(pick)(Affordance('plant_growing', None, (0, 0), False, 0.0, False, False)))


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
        f = self.use(FakeGame([obj('r', pos=(NX[0], NZ[0]), bubble=None, body=(960, 860), stage='produced',
                                   watered=True, wilted=False)], GAME))   # an object with no bubble in view
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


class ReadyMisread(EngineBase):
    """Live D188: a growing carrot's bubble was read as ready; the click showed its info card ("2 days remaining")."""


    def test_one_junk_cyrillic_burst_line_is_not_a_wrong_language(self):
        f = self.use(FakeGame([obj('b', bubble=(700, 400), stage='growing', watered=True, wilted=False, crop='Carrot')],
                              GAME))
        f.behaviour = [dict(GAME[4], flash=['Carrot', 'Ш ПРРадр»'])]   # OCR junk; the screen itself reads English
        act.click((700, 400), 'bubble')   # no WrongLanguage


class CollectOnTheWay(EngineBase):
    def setUp(self):
        super().setUp()
        for mod, name in ((icons, 'DIR'), (learn, 'TRUTH')):
            p = mock.patch.object(mod, name, os.path.join(self.tmp.name, name.lower())); p.start(); self.addCleanup(p.stop)
        icons.reset()
        p = mock.patch.object(icons, 'name_of', lambda a: 'Green Bean'); p.start(); self.addCleanup(p.stop)

    def game(self, b_state):
        a = obj('a', pos=(NX[0], NZ[0]), bubble=(960, 470), stage='growing', watered=True, wilted=False)
        b = obj('b', pos=(NX[1], NZ[0]), bubble=(1104, 540), **b_state)
        f = self.use(FakeGame([a, b], GAME, inventory={'TulipSeed': 2}))
        f.log.append(L('9:00:00 AM', 'plant_growing', 'GardenBed', NX[0], NZ[0]))
        return f

    def test_a_collect_on_the_way_uses_the_targets_crop_from_the_graph(self):
        f = self.game(dict(stage='produced', watered=True, wilted=False))
        g = OG.Graph(); g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        nid = world.find(g, 'GardenBed', f.objects['b']['pos'])
        self.assertIsNotNone(nid)
        g.set_state(nid, 'crop', 'Green Bean', 'D185 9:00:00 AM', 'vision')
        engine.L.MEMORY['graph'] = g
        before = []  # the card click has no bubble near it; graph crop is the only crop evidence
        f.interact(f.objects['b'])
        row = next(r for r in plan.rows() if r['id'] == 'pick')
        res = {'row_now': dict(row, params={}), 'skip_names': {'Tulip'}, 'tid_now': nid,
               'params': {}, 'goal': 'harvest', 'graph_crop_ok': True}
        c = act.Click((1170, 750), 'explore', 0, before=before, mode='overlay', texts=['Collect'])
        self.assertTrue(engine.finish_card(c, res))
        self.assertEqual(f.objects['b']['state']['stage'], 'growing')

    def test_a_collect_on_the_way_with_no_crop_known_asks_with_the_card_open(self):
        f = self.game(dict(stage='produced', watered=True, wilted=False))
        g = OG.Graph(); g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        nid = world.find(g, 'GardenBed', f.objects['b']['pos'])
        engine.L.MEMORY['graph'] = g
        before = []
        f.interact(f.objects['b'])
        row = next(r for r in plan.rows() if r['id'] == 'pick')
        res = {'row_now': dict(row, params={}), 'skip_names': {'Tulip'}, 'tid_now': nid,
               'params': {}, 'goal': 'harvest', 'graph_crop_ok': True}
        c = act.Click((1170, 750), 'explore', 0, before=before, mode='overlay', texts=['Collect'])
        with self.assertRaises(ask.NeedVision):
            engine.finish_card(c, res)
        self.assertEqual(ask.load_state('harvest')['pending']['collect_open'], True)


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



    def geo(self, beds_, at, **kw):
        f = self.use(GeoGame(beds_, GAME, at, inventory={'TulipSeed': 2}, **kw))
        f.log.append(L('9:00:00 AM', 'plant_growing', 'GardenBed', at[0], at[1]))   # she stands at a bed: exact
        return f




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







class DistanceEdges(NavLadder):
    """User D188: "so a new distance edge?" - "yes": Tara -> target `distance` edge each step (tier, map px, route
    px); ways between nodes carry their distance next to the compass point."""

    def edge(self, b='Garden'):
        return next((e for e in self.graph().edges('Tara', 'distance') if e['b'] == b), None)



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


class ButtonAnswers(EngineBase):
    """Live D189: a late Collect prompt nearly turned a vision `button` answer into a rewrite of the pick row's
    click_bubble step. A click step is never overwritten: the answered button goes in after it."""

    def test_a_button_answer_after_a_click_step_is_inserted_not_a_rewrite(self):
        self.use(FakeGame([], GAME))
        ask.save_state({'goal': 'harvest', 'asks': 1, 'history': [], 'pending': {'kind': 'button', 'goal': 'harvest',
                                                                                   'row': 'pick', 'step': 0}})
        res = {'learned': [], 'clicks': 0}
        engine._answer(self.graph(), 'harvest', {}, 'space', res)
        steps_ = next(r for r in plan.rows() if r['id'] == 'pick')['steps']
        self.assertEqual(steps_[0]['do'], 'click_bubble')
        self.assertEqual(steps_[1]['do'], 'press_space')


class CollectProof(EngineBase):
    """Live D189 7:28 (user: "again and again this collect issue"): the bean bubbles read `water` without "!", the
    ready tulips were skipped (flowers), explore clicks on bean beds opened Collect - and the engine closed it (crop
    unknown) every time. A Collect prompt is the game's proof the bed is ready: name the crop by its icon and pick."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(icons, 'DIR', os.path.join(self.tmp.name, 'icons'))
        p.start()
        self.addCleanup(p.stop)

    def game(self):
        bean = obj('b', pos=(NX[1], NZ[0]), bubble=(1260, 670), body=(1170, 750), stage='produced', watered=True,
                   wilted=False)
        tulip = obj('t', pos=(NX[1], NZ[1]), bubble=(970, 516), stage='produced', watered=True, wilted=False)
        f = self.use(FakeGame([bean, tulip], GAME))
        names = {(1260, 670): 'Green Bean', (970, 516): 'Tulip'}
        p = mock.patch.object(icons, 'name_of', lambda a: names.get(tuple(a.pt)))
        p.start()
        self.addCleanup(p.stop)
        return f, names


    def test_a_walk_click_that_opens_collect_on_a_bean_bed_finishes_the_pick(self):
        f, _ = self.game()
        before = f.scan()
        f.run_action('click:1170:750')   # an explore click on the bean bed: the game offers Collect
        self.assertEqual(f.texts(), ['Collect'])
        row = next(r for r in plan.rows() if r['id'] == 'pick')
        res = {'row_now': dict(row, params={}), 'skip_names': {'Tulip'}}
        c = act.Click((1170, 750), 'explore', 0, before=before, mode='overlay', texts=['Collect'])
        self.assertTrue(engine.finish_card(c, res))
        self.assertEqual(f.objects['b']['state']['stage'], 'growing')



class FirstHarvest(EngineBase):
    """Live D189 8:36 (the first real pick): Space on Collect logged `> harvest` (not grab_item), then a quest toast
    "Where Have You Bean?" - Escape on it opened the pause menu."""

    def test_the_pick_is_proven_by_its_harvest_event(self):
        row = next(r for r in plan.rows() if r['id'] == 'pick')
        self.assertIn('harvest', plan._events_of(row))
        self.assertEqual(plan.effects_of_event('harvest').get('ready'), False)

    def test_a_card_without_a_button_is_waited_out_never_escaped(self):
        toast = screen.Screen('card', ['Where Have You Bean?', 'New quest', 'Pick some beans for Gramma'])
        self.assertTrue(screen.passive(toast))
        self.assertFalse(screen.passive(screen.Screen('card', ['Green Bean', 'Collect'])))


class ClickTheBed(VisitBeds):
    def far_bed(self, crop=None):
        x, z = NX[1], NZ[0]
        far = obj('far', pos=(x - 2.5, z - 4.5), stage='produced', watered=True, wilted=False)
        if crop: far['state']['crop'] = crop
        f = self.use(GeoGame([far], GAME, (x, z), inventory={'TulipSeed': 2}))
        f.log.append(L('8:30:00 AM', 'plant_growing', 'GardenBed', x, z))
        g = OG.Graph(); g.load(learn.GRAPH); world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        keep = world.find(g, 'GardenBed', far['pos'])
        for n in world.query(g, {'kind': 'GardenBed'}):
            if n != keep: g.set_state(n, 'ready', False, 'D185 8:20:00 AM', 'card')
        if crop: g.set_state(keep, 'crop', crop, 'D185 8:20:00 AM', 'icon')
        g.save(learn.GRAPH)
        return f, keep



class OneByOne(VisitBeds):
    """Live D189 11:13-11:37 (user: "the problem is in 'go one by one' logic - it stucks"): beds the world believed
    ready had their predicted points on a neighbouring, already-picked bed's sprout; each click opened the Seeds
    panel, the evidence went to the clicked bed, the targets stayed ready, the same bubble was clicked again."""

    def setup_beds(self):
        x, z = NX[1], NZ[0]
        e = obj('e', pos=(x, z), stage='empty', watered=False, wilted=False)
        t1 = obj('t1', pos=(x - 1.2, z), no_bubble=True, stage='growing', watered=True, wilted=False)
        f = self.use(GeoGame([e, t1], GAME, (x, z - 1.0), inventory={'TulipSeed': 2}))
        f.log.append(L('8:30:00 AM', 'plant_growing', 'GardenBed', x, z - 1.0))   # an exact position by the beds
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        return f, g, world.find(g, 'GardenBed', t1['pos']), world.find(g, 'GardenBed', e['pos'])

    def test_a_tried_bubble_is_never_the_visit_again(self):
        f, g, tid, eid = self.setup_beds()
        res = {'clicks': 0, 'btried': []}
        a = engine._visit(g, tid, 'GardenBed', res)
        self.assertIsNotNone(a)                        # the neighbour's bubble at the target's point
        engine._settle_visit(tid, eid, res)            # its click proved the neighbour (e)
        b = engine._visit(g, tid, 'GardenBed', res)
        self.assertTrue(b is None or math.dist(b.pt, f._pt(f.objects['e']['pos'])) > 60, (b, f.clicks))

    def test_a_planting_icon_is_never_a_pick(self):
        """The bubble at the target's point is the just-harvested bed's planting icon: move on, never click it."""
        f, g, tid, _ = self.setup_beds()
        f.objects['e']['state']['stage'] = 'empty'
        pick = next(r for r in plan.rows() if r['id'] == 'pick')
        res = {'clicks': 0, 'btried': []}
        a = engine._visit(g, tid, 'GardenBed', res, pick)
        self.assertTrue(a is None or a.kind != 'plant', a)


    def test_evidence_on_another_bed_turns_the_targets_visit_off_and_counts(self):
        f, g, tid, eid = self.setup_beds()
        res = {'visit_off': set(), 'fails': {}, 'surprises': [], 'btried': []}
        engine._settle_visit(tid, eid, res)
        self.assertIn(tid, res['visit_off'])
        self.assertEqual(res['fails'][tid], 1)
        res2 = {'visit_off': set(), 'fails': {}, 'surprises': [], 'btried': []}
        engine._settle_visit(tid, tid, res2)   # the click proved the target itself: no back-off
        self.assertNotIn(tid, res2['visit_off'])


class SeenIsFresh(VisitBeds):
    """User D189: "so issue is in thinking that 'I'm at ready beds' or 'I don't know where are the ready beds'": the
    morning save said 4 beds ready; she stood at them, their bubbles showed no "!" - the world kept them ready."""


class FarRow(VisitBeds):
    """Live D189 1:28 PM: two beds of the far row were ready (save), on screen but beyond bubble range; the engine
    stopped 'done: no fitting bubble left in view (4 with unknown state)' without going there."""

    def test_only_maybes_is_done_only_within_bubble_range(self):
        x, z = NX[1], NZ[0]
        f = self.use(GeoGame([obj('near', pos=(x, z - 1.0), stage='produced', watered=True, wilted=False),
                              obj('far', pos=(x, z - 4.5), stage='produced', watered=True, wilted=False)],
                             GAME, (x, z)))
        f.log.append(L('8:30:00 AM', 'plant_growing', 'GardenBed', x, z))
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        near, far = world.find(g, 'GardenBed', (x, z - 1.0)), world.find(g, 'GardenBed', (x, z - 4.5))
        for n in (near, far):   # readiness unknown: the maybes the range rule is about
            g.nodes[n].state.pop('ready', None)
        where_ = {'ready': True, 'crop': '!Tulip'}
        res = {}
        self.assertFalse(engine._only_maybes(g, [near, far], where_, res))   # far is out of bubble range
        self.assertTrue(engine._only_maybes(g, [near], where_, {}))


class VisionBeforeDone(VisitBeds):
    """User D189: "fallback to model vision should solve ALL cases ... notice it in retro and make sure learnings
    were saved": a 'done' while the world still lists beds is a conclusion code can't prove - vision confirms."""

    def quiet(self, f, keep):
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        ids = [world.find(g, 'GardenBed', p) for p in keep]
        for n in world.query(g, {'kind': 'GardenBed'}):
            if n not in ids:
                g.set_state(n, 'ready', False, 'D185 8:20:00 AM', 'card')
        g.save(learn.GRAPH)
        return ids


class TowardTheTarget(EngineBase):
    """Live D189 2:35 PM (user: "she barely moved 3 last clicks vs going to the far west bed which is unchecked"):
    inside the garden nav walked to whichever bed the vectors saw, left, right, left; the target bed was elsewhere."""
    Box = __import__('collections').namedtuple('Box', 'point box kind')

    def setUp(self):
        super().setUp()
        p = mock.patch.object(observe, 'see', lambda kind, tried=(): [self.Box((870, 690), (820, 640, 920, 680), kind),
                                                                       self.Box((1150, 690), (1100, 640, 1200, 680),
                                                                                kind)])
        p.start()
        self.addCleanup(p.stop)

    def test_near_with_known_positions_the_step_goes_toward_the_target_bed(self):
        f = self.use(FakeGame([], GAME))
        f.step_zone, f.steps_needed = 'nowhere', 99
        res = nav.new_res('t')
        res['inside'] = True
        t = nav.Target('t', lambda a: False, 'a bed', None, 'GardenBed', 'Garden', 'Garden', None,
                       pos=(-6.0, 0.0), here=(0.0, 0.0))   # the target 6 units west of her
        nav.seek(t, res)
        x, y = f.clicks[0]
        self.assertLess(x, 960 - 150, f.clicks)            # west
        self.assertLess(abs(y - 540), 80, f.clicks)

    def test_three_walks_that_barely_move_the_view_are_stuck(self):
        """Measured by the view's shift (the camera follows her), not by where the click asked her to go."""
        res = {'walks': []}
        for shift in ((-20, 30), (25, 20), (-15, 25)):   # the fence held her: the view hardly moved
            nav.walk_moved(res, (900, 800), shift)
        self.assertTrue(nav.barely_moved(res))
        res2 = {'walks': []}
        for shift in ((-200, 0), (-210, 10), (-190, 0)):  # walking west
            nav.walk_moved(res2, (700, 540), shift)
        self.assertFalse(nav.barely_moved(res2))

    def test_the_view_shift_is_measured_between_two_frames(self):
        import numpy as np
        from PIL import Image
        rng = np.random.default_rng(1)
        a = rng.integers(0, 255, (540, 960), dtype=np.uint8)
        b = np.roll(a, (12, -30), axis=(0, 1))   # the scene moved 30 px left, 12 down (at 960x540)
        dx, dy = observe.view_shift(Image.fromarray(a), Image.fromarray(b))
        self.assertLess(abs(dx - 60) + abs(dy + 24), 8, (dx, dy))   # her move in 1920-frame px: right 60, up 24


class PauseWhileAsking(EngineBase):
    """Live D189 18:52: the agent read a vision image for 46 s while the game ran (the idle alert): a question
    freezes the clock - after its frame is taken, and only on plain gameplay (Escape would close an open card)."""

    def test_a_question_pauses_the_game_on_gameplay_only(self):
        f = self.use(FakeGame([], GAME))
        calls = []
        f.set_paused = lambda want: calls.append(want) or 'paused'
        with self.assertRaises(ask.NeedVision):
            ask.ask('click', 'where?', {'goal': 'harvest'}, {})
        self.assertEqual(calls, [True])
        f.overlay_texts, f.blank_overlay = ['Collect'], True   # a card is open: never Escape it away
        calls.clear()
        with self.assertRaises(ask.NeedVision):
            ask.ask('button', 'which?', {'goal': 'harvest'}, {})
        self.assertEqual(calls, [])

    def test_a_streaming_question_also_freezes_game_time(self):
        f = self.use(FakeGame([], GAME))
        calls = []
        f.set_paused = lambda want: calls.append(want) or 'paused'

        with self.assertRaises(ask.NeedVision):
            ask.ask('click', 'where next?', {'goal': 'garden', 'streaming': True}, {})

        self.assertEqual(calls, [True])

    def test_a_core_failure_vision_question_also_freezes_game_time(self):
        f = self.use(FakeGame([], GAME))
        calls = []
        f.set_paused = lambda want: calls.append(want) or 'paused'

        self.assertIn('NEED_VISION', core.ask_vision('what blocked this action?'))

        self.assertEqual(calls, [True])


class ModelDecides(VisitBeds):
    """When direct interaction is absent, one marked graph/heatmap brief replaces coded near-navigation rungs."""

    def far_game(self):
        x, z = NX[1], NZ[0]
        near = obj('near', pos=(x, z - 1.0), stage='growing', watered=True, wilted=False,
                   badge='none', icon='Carrot')
        far = obj('far', pos=(x, z - 4.5), stage='produced', watered=True, wilted=False)
        f = self.geo([near, far], (x, z))
        g = OG.Graph()
        g.load(learn.GRAPH)
        world.refresh(g, f.read_save()[1], f.today_log()[0], None)
        nid = world.find(g, 'GardenBed', far['pos'])
        for other in world.query(g, {'kind': 'GardenBed'}):
            if other != nid:
                g.set_state(other, 'ready', False, 'D185 9:00:00 AM', 'card')
        g.save(learn.GRAPH)
        return f, g, nid


    def test_parse_decision_grammar(self):
        pending = {'brief_ids': ['bed-a', 'bed-b'], 'in_view': ['bed-a']}
        self.assertEqual(engine.parse_decision('click bed-a', pending), ('click', 'bed-a'))
        self.assertEqual(engine.parse_decision('walk Q14', pending), ('walk', (1320, 911)))
        self.assertEqual(engine.parse_decision('settle bed-a: ready=false, crop=Tulip', pending),
                         ('settle', ['bed-a'], {'ready': False, 'crop': 'Tulip'}))
        self.assertEqual(engine.parse_decision('done', pending), ('done',))
        with self.assertRaisesRegex(core.Failed, 'not in the brief'):
            engine.parse_decision('click missing', pending)
        with self.assertRaisesRegex(core.Failed, 'own spot'):
            engine.parse_decision('walk M8', pending)
        with self.assertRaisesRegex(core.Failed, 'not shown in view'):
            engine.parse_decision('settle bed-b: ready=false', pending)


    def decision_game(self, crop=None, zone='near'):
        bed = obj('b', pos=(NX[1], NZ[0]), zone=zone, bubble=(1260, 670), body=(1170, 750),
                  stage='produced', watered=True, wilted=False)
        bed['icon'] = crop
        f = self.use(FakeGame([bed], GAME))
        g = OG.Graph()
        g.load(SEED)
        world.refresh(g, f.read_save()[1], [], None)
        nid = world.find(g, 'GardenBed', bed['pos'])
        g.nodes[nid].state.pop('crop', None)
        if crop:
            g.set_state(nid, 'crop', crop, f.game_stamp(), 'vision')
        g.save(learn.GRAPH)
        self.pending_decision([nid], [nid], {nid: [1170, 750]})
        return f, nid

    def pending_decision(self, ids, visible, screens, bubbles=()):
        state = ask.load_state('harvest')
        state['pending'] = dict(kind='name', goal='harvest', params={}, decide=True, brief_ids=ids,
                                in_view=visible, screens=screens, bubbles=list(bubbles))
        ask.save_state(state)



    def test_no_event_walk_invalidates_saved_object_projection_but_keeps_frame_evidence(self):
        f, g, nid = self.far_game()
        where.walked()
        bubble = Affordance('water', None, (850, 420), False, 0.0)
        detection = type('Detection', (), {'kind': 'GardenBed', 'point': (1200, 700)})()
        with mock.patch.object(observe, 'scan', return_value=[bubble]), \
                mock.patch.object(observe, 'see_all', return_value=[detection]):
            state = brief.build(g, 'GardenBed', [nid], {})
            with self.assertRaises(ask.NeedVision):
                engine.decide_q(g, {'kind': 'GardenBed'}, [nid], {'goal': 'harvest', 'params': {}})
        pending = ask.load_state('harvest')['pending']
        self.assertEqual(pending['position_source'], 'unknown')
        self.assertEqual(pending['position'], [])
        self.assertEqual(pending['screens'][nid], None)
        self.assertEqual(pending['in_view'], [])
        self.assertEqual(pending['bubbles'][0]['pt'], [850, 420])
        self.assertEqual(state['heatmap'][0]['pt'], (1200, 700))






    def wrong_decision_game(self, stage='growing', icon='Tulip'):
        a = obj('a', pos=(NX[0], NZ[0]), zone='far', bubble=(700, 400), body=(600, 750),
                stage='produced', watered=True, wilted=False)
        b = obj('b', pos=(NX[2], NZ[0]), bubble=(1260, 670), body=(1170, 750),
                stage=stage, watered=True, wilted=False)
        b['icon'] = icon
        f = self.use(FakeGame([a, b], GAME))
        g = self.graph()
        world.refresh(g, f.read_save()[1], [], None)
        aid = world.find(g, 'GardenBed', a['pos'])
        bid = world.find(g, 'GardenBed', b['pos'])
        g.set_state(aid, 'crop', 'Green Bean', f.game_stamp(), 'vision')
        g.save(learn.GRAPH)
        self.pending_decision([aid, bid], [aid, bid], {aid: [1260, 670], bid: [1600, 750]})
        return f, aid, bid







    def test_settle_requires_an_object(self):
        with self.assertRaisesRegex(core.Failed, 'at least one object'):
            engine.parse_decision('settle : ready=false', {'brief_ids': [], 'in_view': []})


class EventWait(EngineBase):
    """User D189: "so remove it, keep manual for hard cases": a click waits for a log line only when asked - a step
    expecting events (water) or a hard case by hand (a vision answer); never a card click (Collect) or a walk."""

    def waits(self, **kw):
        self.use(FakeGame([], GAME))
        calls = []
        with mock.patch.object(core, 'seen', lambda pat, mark, wait: calls.append(wait) or False):
            act.click((700, 600), **kw)
        return calls

    def test_a_card_click_and_a_walk_never_wait(self):
        self.assertEqual(self.waits(what='bubble', predict={'card': 'Collect'}), [])
        self.assertEqual(self.waits(what='step'), [])

    def test_an_events_click_and_a_hard_case_wait(self):
        self.assertTrue(self.waits(what='bubble', predict={'events': ['water']}))
        self.assertTrue(self.waits(what='point', wait_event=True))


class SafeWalks(EngineBase):
    """User D189: "she moved few steps - tried to water carrot, moved few steps - tried to water another carrot":
    a walk click at the frame centre (her own spot) and walk clicks on bubbles interacted instead of walking."""

    def test_a_walk_point_on_her_spot_or_a_bubble_is_not_ground(self):
        from game.affordances import Affordance
        affs = [Affordance('water', None, (956, 504), False, 0.0, True, False)]
        self.assertFalse(nav.walkable((960, 540), affs))          # her own spot
        self.assertFalse(nav.walkable((990, 560), affs))          # next to her, under the bubble she faces
        self.assertFalse(nav.walkable((1300, 700), affs + [Affordance('plant', None, (1310, 690), False, 0.0)]))
        self.assertTrue(nav.walkable((1300, 760), affs))

    def test_a_step_never_clicks_a_bubble(self):
        f = self.use(FakeGame([obj('c', bubble=(1280, 540), stage='growing', watered=False, wilted=False)], GAME))
        f.step_zone, f.steps_needed = 'nowhere', 99
        nav.step((1.0, 0.0), nav.new_res('t'))   # straight right: the first point is the carrot's bubble
        self.assertNotIn((1280, 540), f.clicks)
        self.assertEqual(f.objects['c']['state']['watered'], False)

    def test_an_event_of_another_goal_is_a_red_flag_that_stops_the_call(self):
        """Watering during a harvest: no harvest row logs it - stop at once, a gap for the code factory."""
        f = self.use(FakeGame([obj('c', bubble=(700, 400), stage='growing', watered=False, wilted=False)], GAME))
        res = {'allowed_events': {'harvest', 'grab_item', 'plant_growing'}, 'stop': None, 'notes': []}
        c = act.Click((700, 400), 'step', 0, events=['out_of_water', 'complete'])
        self.assertTrue(engine.red_flag(c, res))
        self.assertIn('RED FLAG', res['stop'])
        self.assertFalse(engine.red_flag(act.Click((1, 1), 'step', 0, events=['complete']), {'allowed_events': set()}))


class UnknownBubbles(EngineBase):
    """User D189: "we should ask vision to fill the gaps the moment we run the scan and see unknown bubbles": an icon
    wave 2 can't name and a badge wave 1 can't read are asked about at once, and the answer fills both stores."""


class UniversalAliases(unittest.TestCase):
    """The old function names observe/resume the real durable loop without navigating or scheduling."""

if __name__ == '__main__':
    unittest.main()
