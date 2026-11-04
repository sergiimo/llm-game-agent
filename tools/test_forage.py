"""Offline tests for game/forage.py: the foraging strategy (user D188, spec 2026-11-03 §13) - pure model vision, never
graph nodes. Run: .venv/bin/python tools/test_forage.py"""
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine import Base, FakeGame  # noqa: E402
from game import ask, forage, learn  # noqa: E402
from game.affordances import Affordance  # noqa: E402


class ForageGame(FakeGame):
    """Things on the ground at screen points (tree, rock, drop). A click on one walks her to it (it moves to the frame
    centre, its bubble shows just above her); a bubble click hits it; at 0 HP the log says `destroying` and its drops
    lie next to her; a drop's bubble click logs `grab_item`. A ground click walks (nothing in reach after)."""

    def __init__(self, things, energy=80):
        super().__init__([], [])
        self.things = [dict(t) for t in things]   # {'name', 'pt', 'hp', 'drops'?: n}
        self.near, self.energy, self.ground = None, energy, []

    def _thing_at(self, x, y):
        return next((t for t in self.things if abs(t['pt'][0] - x) < 50 and abs(t['pt'][1] - y) < 50), None)

    def scan(self):
        if self.near is None:
            return []
        return [Affordance('axe' if self.near['hp'] > 0 else 'pickup', None, (960, 470), True, 0.0, False, False)]

    def run_action(self, a):
        if a == 'key:space':
            return self._hit()
        m = re.match(r'click:(-?\d+):(-?\d+)', a)
        if not m:
            return super().run_action(a)
        x, y = int(m.group(1)), int(m.group(2))
        self.clicks.append((x, y))
        if self.near is not None and abs(x - 960) < 30 and abs(y - 470) < 30:
            return self._hit()
        t = self._thing_at(x, y)
        self.walk_frames = 1
        if t is None:
            self.ground.append((x, y))
            self.near = None
            return None
        self.near = t
        t['pt'] = (960, 540)

    def _hit(self):
        t = self.near
        if t is None:
            return
        self.energy -= 4
        if t['hp'] <= 0:   # a drop: picked up
            self.log.append(f'{self.stamp()} > grab_item me=Player target={t["name"]}(Clone) at (1.0, 0.10, 2.0)')
            self.things.remove(t)
            self.near = None
            return
        t['hp'] -= 1
        if t['hp'] == 0:
            self.log.append(f'{self.stamp()} [Actor] {t["name"]}(Clone) destroying')
            self.things.remove(t)
            self.near = None
            for i in range(t.get('drops', 0)):
                self.things.append({'name': 'Wood', 'pt': (900 + 60 * i, 640), 'hp': 0})

    def read_energy(self, img):
        return self.energy


class Forage(Base):
    def setUp(self):
        super().setUp()
        self.graph_file = learn.GRAPH
        self.stored = []   # looks the boundary would store (never the real objects db, D188 test pollution)
        p = mock.patch.object(learn, 'relabel', lambda img, box, kind: self.stored.append((kind, box)) or True)
        p.start()
        self.addCleanup(p.stop)

    def game(self, things, **kw):
        return self.use(ForageGame(things, **kw))

    def test_without_an_answer_it_asks_vision_for_the_nearest_target(self):
        f = self.game([{'name': 'TreePine', 'pt': (1300, 400), 'hp': 2}])
        with self.assertRaises(ask.NeedVision) as e:
            forage.run('chop')
        msg = str(e.exception)
        self.assertIn('tree', msg.lower())
        self.assertIn('./wf forage chop answer=', msg)
        self.assertEqual(f.clicks, [])

    def test_an_answer_walks_to_it_hits_its_bubble_until_the_log_proves_it_then_asks_again(self):
        f = self.game([{'name': 'TreePine', 'pt': (1300, 400), 'hp': 3}])
        with self.assertRaises(ask.NeedVision):
            forage.run('chop')
        cell = 'Q6'   # (1320, 371): on the tree
        with self.assertRaises(ask.NeedVision) as e:   # done with this tree: the next question
            forage.run('chop', answer=cell)
        self.assertEqual(f.things, [])
        self.assertEqual(f.clicks[1:], [(960, 470)] * 3)   # three hits on the bubble at her
        rec = [k for a, k in f.runlog if a and a[0] == 'forage']
        self.assertEqual(rec[-1]['result'], 'destroying', rec)
        self.assertIn('nearest', str(e.exception))

    def test_drops_are_picked_up_on_the_same_job(self):
        f = self.game([{'name': 'TreePine', 'pt': (1300, 400), 'hp': 1, 'drops': 1}])
        with self.assertRaises(ask.NeedVision) as e:
            forage.run('chop')
        self.assertIn('dropped', str(e.exception).lower())
        with self.assertRaises(ask.NeedVision):
            forage.run('chop', answer='Q6')
        with self.assertRaises(ask.NeedVision):
            forage.run('chop', answer='L10')   # (900, 641): the wood on the ground
        self.assertEqual(f.things, [])
        rec = [k for a, k in f.runlog if a and a[0] == 'forage']
        self.assertEqual([r['result'] for r in rec], ['destroying', 'grab_item'])

    def test_none_stops_it_without_a_click(self):
        f = self.game([])
        with self.assertRaises(ask.NeedVision):
            forage.run('rock')
        res = forage.run('rock', answer='none')
        self.assertTrue(res['stop'].startswith('done'), res)
        self.assertEqual(f.clicks, [])

    def test_a_walk_answer_clicks_ground_and_asks_again(self):
        f = self.game([])
        with self.assertRaises(ask.NeedVision):
            forage.run('forage')
        with self.assertRaises(ask.NeedVision):
            forage.run('forage', answer='walk:T8')
        self.assertEqual(f.ground, [(1560, 506)])

    def test_low_energy_stops_before_asking(self):
        f = self.game([{'name': 'StoneRock', 'pt': (1300, 400), 'hp': 2}], energy=10)
        res = forage.run('rock')
        self.assertIn('energy', res['stop'])
        self.assertEqual(f.clicks, [])

    def test_an_answer_with_nothing_to_act_on_is_recorded_and_it_asks_again(self):
        f = self.game([])
        with self.assertRaises(ask.NeedVision):
            forage.run('rock')
        with self.assertRaises(ask.NeedVision):
            forage.run('rock', answer='Q6')   # nothing there: she walked, no bubble at her
        rec = [k for a, k in f.runlog if a and a[0] == 'forage']
        self.assertEqual(rec[-1]['result'], 'no bubble', rec)

    def test_it_never_writes_the_world_graph(self):
        self.game([{'name': 'TreePine', 'pt': (1300, 400), 'hp': 1}])
        before = os.path.getmtime(self.graph_file)
        with self.assertRaises(ask.NeedVision):
            forage.run('chop')
        with self.assertRaises(ask.NeedVision):
            forage.run('chop', answer='Q6')
        self.assertEqual(os.path.getmtime(self.graph_file), before)

    def test_a_proven_answer_stores_its_look_under_the_games_name(self):
        """Every vision answer improves the vectors (user D188): the destroyed object's name labels the answered crop."""
        self.game([{'name': 'StoneRock', 'pt': (1300, 400), 'hp': 1}])
        with self.assertRaises(ask.NeedVision):
            forage.run('rock')
        with self.assertRaises(ask.NeedVision):
            forage.run('rock', answer='Q6')
        self.assertEqual(self.stored, [('StoneRock', (1230, 301, 1410, 441))])


if __name__ == '__main__':
    unittest.main()
