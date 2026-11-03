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
        self.log.append(f'{self.stamp()} > {event} me=Player target={o["kind"]}(Clone) at ({x}, 0.10, {z})')

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
        self.card, self.picked = None, None

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
        return 'day'

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
        return []

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
        ts = self.texts()
        return {'mode': 'gameplay' if not ts else 'overlay', 'text': [f'{i}) {t}' for i, t in enumerate(ts)]}

    def run_action(self, a):
        if a == 'key:space':
            return self.press_bubble()
        if a == 'key:escape':
            return self.close()
        x, y = (int(v) for v in re.match(r'click:(-?\d+):(-?\d+)', a).groups())
        self.clicks.append((x, y))
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
            self._walk(self.step_zone)

    def interact(self, o):
        b = self.beh_of(o)
        if b is None:
            return
        if b.get('click_event'):
            self.emit(b['click_event'], o)
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
            out.append(Affordance(b['bubble']['kind'], None, tuple(o['bubble_pt']), False, 0.0, drop, bool(ready)))
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
        if self.screen() and self.screen()['next'] == 'space':
            self._advance('space')

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
     'event': 'plant', 'stats': 'totalPlanted.$seedSeed', 'uses_seed': True,
     'effect': {'stage': 'growing', 'crop': '$seed', 'watered': False}},
    {'kind': 'GardenBed', 'when': {'stage': 'growing|producing', 'watered': False}, 'bubble': {'kind': 'water'},
     'needs': {'Tara.can': 'full'}, 'fail_event': 'out_of_water', 'event': 'water', 'effect': {'watered': True}},
    {'kind': 'GardenBed', 'when': {'stage': 'produced'}, 'bubble': {'kind': 'pickup'}, 'event': 'grab_item',
     'effect': {'stage': 'growing', 'watered': False}},
    {'kind': 'GardenBed', 'when': {'stage': 'growing|producing', 'watered': True}, 'bubble': {'kind': 'plant_growing'},
     'event': 'plant_growing', 'effect': {}},
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
        self.assertEqual(plan.effects_of_event('plant'), {'stage': 'growing', 'watered': False})
        self.assertEqual(plan.effects_of_event('plant', {'seed': 'Tulip'})['crop'], 'Tulip')
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
               L('9:01:00 AM', 'plant', 'GardenBed', 2.64, -59.36)]
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
        res = engine.achieve('plant', seed='Tulip', region='GardenSouth')
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


if __name__ == '__main__':
    unittest.main()
