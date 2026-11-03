"""Offline tests for tools/game/laws.py (interaction laws, L124). Run: .venv/bin/python tools/test_laws.py"""
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import affordances, chains, core, garden, laws, ui, well  # noqa: E402
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
        return None

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

    def run_action(self, a):
        x, y = (int(v) for v in re.match(r'click:(-?\d+):(-?\d+)', a).groups())
        self.clicks.append((x, y))
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
                self.zone = b['zone']   # walked there
                return
        if getattr(self, 'step_zone', None) and getattr(self, 'step_ok', lambda x, y: True)(x, y):
            self.zone = self.step_zone   # a few steps on the road bring the garden into reach

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
        kind = {'wilted': 'unplant', 'dry': 'water', 'wet': 'water', 'ripe': 'pickup', 'empty': 'plant'}
        learned = dict(getattr(self, 'learned', []))
        honey = [Affordance('beehive_progress' if 'beehive_progress' in learned else 'unknown', None, p, False, 0.0, False)
                 for p in getattr(self, 'honey', ()) if self.zone == 'near']
        return honey + [Affordance(kind[b['state']], None, b['bubble'], False, 0.0, b['state'] in ('wilted', 'dry'))
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
        ps = [mock.patch.object(laws, 'STATE', os.path.join(self.tmp.name, 'laws.json')),
              mock.patch.object(chains, 'OBSERVED', os.path.join(self.tmp.name, 'observed.jsonl')),
              mock.patch.object(laws, 'GRAPH', self._graph_copy()),
              mock.patch.object(laws, 'BURST', (0.0,)), mock.patch.object(laws, 'EVENT_WAIT', 0.0),
              # default: no vector match on screen and no map (the vision path); Seek tests override these
              mock.patch.object(laws, '_see', lambda kind, tried=(): []),
              mock.patch.object(laws, '_map_direction', lambda node: None)]
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


class Seek(Base):
    """User D185: no fitting bubble -> the node's vector on screen -> click; not seen -> map direction -> a few steps."""
    Det = __import__('collections').namedtuple('Det', 'point')

    def test_a_bed_seen_by_its_vector_is_clicked_without_vision(self):
        f = self.use(Fake({'a': bed('dry', zone='far', bubble=(900, 400), body=(1500, 300))}))
        with mock.patch.object(laws, '_see', lambda kind, tried=(): [self.Det((1500, 300))] if f.zone == 'near' else []):
            with self.assertRaises(NeedVision):   # all watered: only then vision is asked (is anything left?)
                laws.run('water')
        self.assertEqual(len(f.asks), 1)
        self.assertEqual(f.beds['a']['state'], 'wet')
        self.assertEqual(f.clicks[0], (1500, 300))

    def test_not_seen_map_direction_steps_then_the_loop_runs(self):
        f = self.use(Fake({'a': bed('dry', zone='far', bubble=(900, 400), body=(5000, 5000))}))
        f.step_zone = 'far'
        with mock.patch.object(laws, '_map_direction', lambda node: (1.0, 0.0)):
            with self.assertRaises(NeedVision):   # all watered: only then vision is asked (is anything left?)
                laws.run('water')
        self.assertEqual(len(f.asks), 1)
        self.assertEqual(f.clicks[0], (960 + laws.STEP_R[0], 540))   # straight toward the garden on the map
        self.assertEqual(f.beds['a']['state'], 'wet')

    def test_a_blocked_step_turns_a_little(self):
        f = self.use(Fake({'a': bed('dry', zone='far', bubble=(900, 400), body=(5000, 5000))}))
        f.step_zone, f.step_ok = 'far', (lambda x, y: y != 540)   # straight ahead is a fence
        with mock.patch.object(laws, '_map_direction', lambda node: (1.0, 0.0)):
            with self.assertRaises(NeedVision):   # all watered: only then vision is asked (is anything left?)
                laws.run('water')
        self.assertEqual(f.clicks[0][1], 540)
        self.assertNotEqual(f.clicks[1][1], 540)
        self.assertEqual(f.beds['a']['state'], 'wet')

    def test_an_unknown_bubble_is_clicked_once_and_learned_from_its_event(self):
        f = self.use(Fake({'a': bed('dry', zone='far', bubble=(900, 400), body=(5000, 5000))}))
        f.honey = f.hives = [(800, 532)]
        f.step_zone = 'far'
        with mock.patch.object(laws, '_map_direction', lambda node: (1.0, 0.0)):
            with self.assertRaises(NeedVision):
                laws.run('water')
        self.assertEqual(f.learned, [('beehive_progress', 'unknown')])
        self.assertEqual(f.clicks.count((800, 532)), 1)
        self.assertEqual(f.beds['a']['state'], 'wet')

    def test_a_hive_seen_as_a_bed_is_not_clicked_again_and_the_graph_leads_down(self):
        f = self.use(Fake({'a': bed('dry', zone='far', bubble=(900, 400), body=(5000, 5000))}))
        f.hives = [(1300, 890)]
        f.step_zone, f.step_ok = 'far', (lambda x, y: (x, y) != (1300, 890))
        with mock.patch.object(laws, '_see', lambda kind, tried=(): [self.Det(p) for p in [(1300, 890)]
                                                                     if not any(laws._d(p, t) < 80 for t in tried)]):
            with self.assertRaises(NeedVision):
                laws.run('water')
        self.assertEqual(f.clicks.count((1300, 890)), 1)
        self.assertEqual(f.clicks[1], (960, 540 + laws.STEP_R[0]))   # BeeHive -> beds: straight down
        self.assertEqual(f.beds['a']['state'], 'wet')

    def test_after_the_refill_she_is_at_the_well_and_the_graph_leads_to_the_beds(self):
        f = self.use(Fake({'a': bed('dry', zone='near', bubble=(900, 400)),
                           'b': bed('dry', zone='far', bubble=(700, 300), body=(5000, 5000))}, can=False))
        def fill(graph=None):
            f.can, f.zone = True, 'well'   # the well: no bed in reach
        f.fill_can = fill
        mock.patch.object(well, 'fill_can', fill).start()
        self.addCleanup(mock.patch.stopall)
        f.step_zone = 'far'
        with self.assertRaises(NeedVision):
            laws.run('water')
        from objects import graph as OG
        dx, dy = OG.TOWARD[('Well', 'GardenBed@Garden')]
        self.assertIn((int(960 + dx * laws.STEP_R[0]), int(540 + dy * laws.STEP_R[0])), f.clicks)
        self.assertEqual(f.beds['b']['state'], 'wet')

    def test_inside_the_garden_explores_free_ground_not_the_map(self):
        """D185: after watering, inside the Garden the map kept pointing at the garden; explore free ground instead."""
        f = self.use(Fake({'a': bed('dry', zone='near', bubble=(900, 400)),
                           'b': bed('dry', zone='far', bubble=(700, 300), body=(5000, 5000))}))
        f.step_zone = 'far'
        def no_map(node):
            raise AssertionError('map used inside the region')
        with mock.patch.object(laws, '_map_direction', no_map):
            with self.assertRaises(NeedVision):
                laws.run('water')
        self.assertEqual((f.beds['a']['state'], f.beds['b']['state']), ('wet', 'wet'))
        self.assertIn((960 + laws.EXPLORE_R, 540), f.clicks)

    def test_a_step_onto_a_hive_is_blocked_and_vision_gets_the_trace(self):
        f = self.use(Fake({'b': bed('dry', zone='far', bubble=(700, 300), body=(5000, 5000))}, can=True))
        f.hives = [(960, 540 + laws.STEP_R[0])]          # straight down from the well is a hive
        f.step_zone, f.step_ok = None, None              # nothing walks
        with mock.patch.object(laws, '_map_direction', lambda node: None):
            st = laws._load_state('water')
            res = {'here': 'BeeHive', 'clicks': 0, 'trace': []}
            self.assertIsNone(laws._step((0.0, 1.0), res, 'graph'))
        self.assertTrue(any('blocked by BeeHive' in t for t in res['trace']))
        with self.assertRaises(NeedVision):
            laws.run('water')
        self.assertIn('already tried this call', f.asks[-1][1])

    def test_limited_turns_then_vision(self):
        f = self.use(Fake({'a': bed('dry', zone='far', bubble=(900, 400), body=(5000, 5000))}))
        f.step_zone, f.step_ok = None, None   # steps never bring it in reach (and never move her)
        with mock.patch.object(laws, '_map_direction', lambda node: (0.0, -1.0)):
            with self.assertRaises(NeedVision):
                laws.run('water')
        self.assertEqual(len(f.asks), 1)
        self.assertLessEqual(len(f.clicks), len(laws.STEP_R) * len(laws.STEP_TURN))


class Language(Base):
    def test_russian_ui_stops_before_any_click(self):
        f = self.use(Fake({'a': bed('dry', bubble=(900, 400))}))
        f.state = lambda: {'mode': 'gameplay', 'text': ['0) Среда 09:40', '1) 100']}
        with self.assertRaises(laws.WrongLanguage) as e:
            laws.run('water')
        self.assertIn('WRONG_LANGUAGE', str(e.exception))
        self.assertEqual(f.clicks, [])

    def test_english_ui_runs(self):
        f = self.use(Fake({'a': bed('dry', bubble=(900, 400))}))
        f.state = lambda: {'mode': 'gameplay', 'text': ['0) Wednesday 9:40 am']}
        with self.assertRaises(NeedVision):
            laws.run('water')
        self.assertEqual(f.beds['a']['state'], 'wet')


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


class BubbleLoop(Base):
    def test_replants_every_wilted_bed_in_reach_with_the_same_crop_and_waters_it(self):
        f = self.use(Fake({'a': bed('wilted', 'Tulip', bubble=(1100, 600)), 'b': bed('wilted', 'Green Bean', bubble=(800, 600)),
                           'c': bed('wet', bubble=(960, 400))}))
        f.save_left = 2
        res = garden.replant_all()
        self.assertEqual(len(res['done']), 2)
        self.assertEqual((f.beds['a']['crop'], f.beds['a']['state']), ('Tulip', 'wet'))
        self.assertEqual((f.beds['b']['crop'], f.beds['b']['state']), ('Green Bean', 'wet'))
        self.assertEqual(res['vision'], 0)
        self.assertEqual(f.asks, [])
        self.assertEqual(f.beds['c']['state'], 'wet')   # a bubble without a drop is never clicked
        self.assertNotIn((960, 400), f.clicks)

    def test_seed_overrides_the_crop(self):
        f = self.use(Fake({'a': bed('wilted', 'Green Bean', bubble=(1100, 600))}))
        f.save_left = 1
        garden.replant_all(seed='Carrot')
        self.assertEqual(f.beds['a']['crop'], 'Carrot')

    def test_a_dry_bed_misread_as_wilted_is_watered_and_noted(self):
        f = self.use(Fake({'a': bed('dry', bubble=(1100, 600)), 'b': bed('wilted', bubble=(800, 600))}))
        f.save_left = 1
        res = garden.replant_all()
        self.assertEqual(len(res['done']), 1)
        self.assertEqual(f.beds['a']['state'], 'wet')
        self.assertTrue(any('was dry' in o for o in res['other']))

    def test_no_seeds_stops_and_leaves_the_bed_empty(self):
        f = self.use(Fake({'a': bed('wilted', 'Tulip', bubble=(1100, 600))}, seeds={'Tulip': 0}))
        f.save_left = 1
        res = garden.replant_all()
        self.assertIn('no seeds for Tulip', res['stop'])
        self.assertEqual(f.screen, 'gameplay')

    def test_save_says_none_left_does_nothing(self):
        f = self.use(Fake({'a': bed('wet', bubble=(1100, 600))}))
        f.save_left = 0
        res = garden.replant_all()
        self.assertEqual((res['clicks'], f.asks), (0, []))

    def test_water_refills_an_empty_can_and_continues(self):
        f = self.use(Fake({'a': bed('dry', bubble=(1100, 600)), 'b': bed('dry', bubble=(800, 600))}, can=False))
        with self.assertRaises(NeedVision):   # all watered, no drop bubble left: ask for the next node
            garden.water_all()
        self.assertEqual((f.beds['a']['state'], f.beds['b']['state']), ('wet', 'wet'))
        self.assertTrue(f.can)

    def test_harvest_picks_only_ripe(self):
        f = self.use(Fake({'a': bed('ripe', bubble=(1100, 600)), 'b': bed('dry', bubble=(800, 600))}))
        res = garden.harvest_all(click=None) if False else None
        with self.assertRaises(NeedVision):
            garden.harvest_all()
        self.assertEqual((f.beds['a']['state'], f.beds['b']['state']), ('wet', 'dry'))
        del res


class Vision(Base):
    def test_no_bubble_asks_one_click_point_then_the_answer_walks_and_the_loop_runs(self):
        f = self.use(Fake({'far': bed('wilted', 'Tulip', zone='far', bubble=(1000, 500), body=(1320, 911))}))
        f.save_left = 1
        with self.assertRaises(NeedVision) as cm:
            garden.replant_all()
        self.assertEqual(len(f.asks), 1)
        self.assertEqual(f.asks[0][0], 'click')
        self.assertIn('magenta circle', f.asks[0][1])
        self.assertIn("replant_all(click=", str(f.asks))
        res = garden.replant_all(click='Q14')
        self.assertEqual(len(res['done']), 1)
        self.assertEqual(f.beds['far']['state'], 'wet')

    def test_a_vision_click_on_a_bed_in_reach_interacts_and_is_used(self):
        f = self.use(Fake({'a': bed('wilted', 'Carrot', bubble=(1200, 700), body=(1320, 911))}))
        f.save_left = 1
        f.beds['a']['zone'] = 'near'
        res = garden.replant_all(click='Q14')
        self.assertEqual(len(res['done']), 1)
        self.assertEqual(f.beds['a']['crop'], 'Carrot')

    def test_misread_growing_bed_is_told_back_to_vision(self):
        f = self.use(Fake({'g': bed('wet', bubble=(1200, 700), body=(1320, 911))}))
        f.save_left = 1
        with self.assertRaises(NeedVision):
            garden.replant_all(click='Q14')
        self.assertIn('plant_growing', f.asks[-1][1])

    def test_none_answer_ends_the_run(self):
        f = self.use(Fake({}))
        res = garden.replant_all(click='none')
        self.assertEqual(res['stop'], 'vision: none left')
        self.assertEqual(f.clicks, [])

    def test_bad_answer_is_rejected_without_a_click(self):
        f = self.use(Fake({}))
        with self.assertRaises(core.Failed) as cm:
            garden.replant_all(click='B2')
        self.assertIn('HUD', str(cm.exception))
        self.assertEqual(f.clicks, [])

    def test_stuck_after_max_asks_without_progress(self):
        f = self.use(Fake({}))
        for _ in range(laws.MAX_ASKS):
            with self.assertRaises(NeedVision):
                garden.replant_all(click='M12')
        with self.assertRaises(laws.LawsStuck) as cm:
            garden.replant_all(click='M12')
        self.assertIn('LAWS_STUCK', str(cm.exception))

    def test_progress_resets_the_counter(self):
        f = self.use(Fake({'far': bed('wilted', 'Tulip', zone='far', bubble=(1000, 500), body=(1320, 911))}))
        f.save_left = 2
        for _ in range(laws.MAX_ASKS - 1):
            with self.assertRaises(NeedVision):
                garden.replant_all(click='M12')
        with self.assertRaises(NeedVision):   # the far bed done, the save still says 1 more: ask again, not stuck
            garden.replant_all(click='Q14')
        self.assertEqual(laws._load_state('replant')['asks'], 1)


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
        self.assertFalse(c.nothing())   # view change unknown (no pixels): not claimed as nothing
        c.moved = False
        self.assertTrue(c.nothing())
        del f

    def test_burst_frames_catch_a_view_change(self):
        from PIL import Image
        a, b = Image.new('RGB', (1920, 1080), (10, 10, 10)), Image.new('RGB', (1920, 1080), (200, 200, 200))
        self.assertTrue(laws._view_changed(a, b))
        self.assertFalse(laws._view_changed(a, a.copy()))


class ChainsDB(Base):
    def db(self):
        import json
        p = os.path.join(self.tmp.name, 'chains.json')
        with open(chains.DB) as fh, open(p, 'w') as out:
            out.write(fh.read())
        self.addCleanup(lambda: None)
        mock.patch.object(chains, 'DB', p).start()
        self.addCleanup(mock.patch.stopall)
        return p, json

    def test_every_step_has_all_fields_and_a_source(self):
        db = chains.load()
        for name, steps in db.items():
            if name.startswith('_'):
                continue
            for s in steps:
                self.assertEqual(set(s['expect']), set(chains.FIELDS), s['step'])
                self.assertTrue(s.get('source'), s['step'])

    def test_replant_run_checks_every_step_and_matches_the_db(self):
        self.db()
        f = self.use(Fake({'a': bed('wilted', 'Tulip', bubble=(1100, 600))}))
        f.save_left = 1
        res = garden.replant_all()
        self.assertEqual(len(res['done']), 1)
        import json
        rows = [json.loads(line) for line in open(chains.OBSERVED)]
        self.assertEqual(sorted({(r['chain'], r['step']) for r in rows}), [('replant', i) for i in range(5)])
        self.assertEqual([r for r in rows if r['verdict'] == 'surprise'], [])

    def test_a_different_result_is_a_surprise(self):
        self.db()
        f = self.use(Fake({'a': bed('wilted', 'Tulip', bubble=(1100, 600))}))
        c = laws.record_click((1100, 600), 'bubble', chain='water', idx=0)
        self.assertIn(('events', ['water'], ['unplant']), c.surprises)
        del f

    def test_gaps_fill_only_after_two_agreeing_observations(self):
        p, json = self.db()
        f = self.use(Fake({'a': bed('ripe', bubble=(1100, 600))}))
        laws.record_click((1100, 600), 'bubble')   # grab_item -> harvest[0], bubble after: no-drop (regrowing, watered)
        self.assertFalse(any(x[4] for x in chains.gaps(apply=True)))
        self.assertEqual(chains.load()['harvest'][0]['expect']['bubble'], '?')
        f.beds['a']['state'] = 'ripe'
        laws.record_click((1100, 600), 'bubble')
        filled = [x for x in chains.gaps(apply=True) if x[4]]
        self.assertIn(('harvest', 0, 'bubble'), [x[:3] for x in filled])
        self.assertEqual(chains.load()['harvest'][0]['expect']['bubble'], 'no-drop')
        self.assertIn('observed x2', chains.load()['harvest'][0]['source'])

    def test_disagreeing_observations_stay_a_gap(self):
        self.db()
        ripe = Affordance('pickup', None, (1100, 600), False, 0.0, False)
        regrow = Affordance('water', None, (1100, 600), False, 0.0, False)
        for after in ([regrow], [], [regrow]):   # no-drop, gone, no-drop
            chains.observe('harvest', 0, laws.Click((1100, 600), 'bubble', 0, events=['grab_item'], before=[ripe], after=after))
        chains.gaps(apply=True)
        self.assertEqual(chains.load()['harvest'][0]['expect']['bubble'], '?')

class Memory(Base):
    def graph(self):
        from objects import graph as G
        g = G.Graph()
        g.load(laws.GRAPH)
        return g

    def test_a_replant_run_is_remembered_per_group(self):
        f = self.use(Fake({'a': bed('wilted', 'Tulip', bubble=(1100, 600)), 'b': bed('dry', bubble=(800, 600))}))
        f.save_left = 1
        f.game_stamp = lambda: 'D184 7:30:00 AM'
        garden.replant_all()
        g = self.graph()
        t = g.state_value(laws.GROUP, 'today')
        self.assertEqual(t['day'], 184)
        self.assertEqual((t['removed'], t['planted']), (1, 1))
        self.assertEqual(t['watered'], 1)   # the new seedling; the save's 1 wilted is done, so the run stops there
        self.assertEqual(g.state_value(laws.GROUP, 'crops'), ['Tulip'])

    def test_memory_goes_into_the_vision_question(self):
        f = self.use(Fake({}))
        f.game_stamp = lambda: 'D184 7:30:00 AM'
        g = self.graph()
        g.set_state(laws.GROUP, 'crops', ['Tulip', 'Carrot'], 'D184 7:00:00 AM', 'event')
        g.save(laws.GRAPH)
        with self.assertRaises(NeedVision):
            garden.replant_all()
        self.assertIn('crops grown here: Tulip, Carrot', f.asks[-1][1])
        self.assertIn('Well', f.asks[-1][1])

    def test_a_new_day_resets_the_tally(self):
        from objects import graph as G
        g = self.graph()
        G.note_click(g, laws.GROUP, ['water'], 'D183 9:00:00 PM')
        G.note_click(g, laws.GROUP, ['water'], 'D184 7:00:00 AM')
        self.assertEqual(g.state_value(laws.GROUP, 'today'), {'day': 184, 'watered': 1})

    def test_can_state_from_events(self):
        from objects import graph as G
        g = self.graph()
        G.note_click(g, laws.GROUP, ['out_of_water'], 'D184 7:00:00 AM')
        self.assertEqual(g.state_value('Tara', 'can'), 'empty')
        G.note_click(g, laws.GROUP, ['full_watering_can'], 'D184 7:01:00 AM')
        self.assertEqual(g.state_value('Tara', 'can'), 'full')

    def test_no_positions_or_layouts_in_the_runner(self):
        src = open(laws.__file__).read()
        for word in ('ref_offset', 'pitch', 'camera_shift', 'Tara.at', 'log_pos'):
            self.assertNotIn(word, src)

    def test_draw_grid_marks_tara(self):
        from PIL import Image
        pic = laws.draw_grid(Image.new('RGB', (1920, 1080), (0, 0, 0)))
        self.assertEqual(pic.getpixel((960, 540 - 26)), (255, 0, 255))


if __name__ == '__main__':
    unittest.main()
