"""Offline tests for the generic gameplay engine (spec 2026-11-03): FakeGame + world, table, steps, ask, loop, learning.
Run: .venv/bin/python -m unittest tools/test_engine.py"""
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import act, affordances, ask, core, engine, learn, nav, observe, plan, steps, ui, world  # noqa: E402
from objects.loop import NeedVision  # noqa: E402
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
    def grab(self):
        from PIL import Image
        if self.walk_frames:
            self.walk_frames -= 1
            return Image.new('L', (8, 8), 0)
        return Image.new('L', (8, 8), 200)

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
                                  False, 0.0, drop and not self.hide_drop, bool(ready)))
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
        ps = [mock.patch.object(learn, 'GRAPH', g),
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
        self.assertEqual(f.clicks[0], (960 + nav.STEP_R[0], 540))

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
        p = mock.patch.object(ES, 'PATH', self.preds)
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
                                           '2 days remaining']), {'crop': 'Green Bean', 'days_left': 2})
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
        f.blank_overlay, f.overlay_texts = True, ['Bee Hive', 'Plant flowers nearby']   # Escape doesn't close it
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


if __name__ == '__main__':
    unittest.main()
