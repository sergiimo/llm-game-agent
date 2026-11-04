"""Offline tests for the unified improvement loop (spec docs/superpowers/specs/2026-11-04-unified-improvement-loop-
refactor.md): one immutable experience per action, one integration boundary, idempotent replay, gap bundles.
Run: .venv/bin/python tools/test_experience.py"""
import dataclasses
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine import GAME, NX, NZ, EngineBase, FakeGame, L, obj  # noqa: E402
from game import act, engine, experience as X, integrate as I, learn, steps  # noqa: E402

GAME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'game')


def sample(**kw):
    e = X.Experience.new(
        goal=X.GoalRef('harvest', (('crops', 'Carrot'),), 'GardenBed#1', 'pick', 0),
        before=X.Observation('gameplay', ('pickup @1104,540',), ()),
        prediction=X.Prediction(events=('grab_item',), card='Collect'),
        action=X.Action('click', 'bubble', (1104, 540)),
        evidence=X.Evidence(lines=('[D188 9:01:00 AM] > grab_item me=Player target=GardenBed(Clone) at (0.84, 0.1, -25.34)',),
                            events=('grab_item',), at=(0.84, -25.34), node='GardenBed@Garden', mode='overlay',
                            texts=('Collect',), moved=False),
        verdict=X.Verdict('hit', (X.Check('events', ['grab_item'], ['grab_item'], True),)),
        artifacts=X.Artifacts(frames=('a.jpg',), log_mark=7, t=1.5), **kw)
    return e


class Records(unittest.TestCase):
    def test_an_experience_is_immutable(self):
        e = sample()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            e.verdict = X.Verdict('miss')

    def test_it_round_trips_through_json_with_the_same_id(self):
        e = sample()
        back = X.Experience.from_dict(json.loads(json.dumps(e.to_dict())))
        self.assertEqual(back, e)
        self.assertEqual(back.id, e.id)

    def test_the_id_is_stable_for_a_recorded_attempt_and_differs_between_attempts(self):
        self.assertEqual(sample().id, sample().id)
        other = dataclasses.replace(sample(), artifacts=X.Artifacts(frames=('b.jpg',), log_mark=9, t=2.0))
        self.assertNotEqual(X.Experience.new(**{f: getattr(other, f) for f in X.FIELDS}).id, sample().id)

    def test_a_correction_carries_its_experience_id(self):
        e = sample()
        c = X.Correction(e.id, world=(X.Update('world', 'card_state', {'nid': 'n'}),))
        self.assertEqual(c.updates()[0].key(e.id), f'{e.id}:world:card_state:' + json.dumps({'nid': 'n'}, sort_keys=True))


class Boundary(EngineBase):
    """The integrator: persist, then world -> evals -> memory -> transitions -> gap, each once per experience."""

    def setUp(self):
        super().setUp()
        for name in ('JOURNAL_DIR',):
            p = mock.patch.object(I, name, os.path.join(self.tmp.name, 'journal'))
            p.start()
            self.addCleanup(p.stop)

    def game(self):
        return self.use(FakeGame([obj('b', pos=(NX[1], NZ[0]), bubble=(1104, 540), stage='produced', watered=True,
                                      wilted=False)], GAME))

    def test_one_click_is_one_experience_referenced_by_learning_eval_and_transition_records(self):
        f = self.game()
        with mock.patch('game.icons.name_of', lambda a: 'Green Bean'):
            engine.achieve('harvest')
        exps = I.journal()
        click_ids = [e.id for e in exps if e.action.kind == 'click']
        self.assertTrue(click_ids)
        obs = [json.loads(l) for l in open(steps.OBSERVED)]
        self.assertTrue(obs and all(o.get('exp') in {e.id for e in exps} for o in obs), obs)
        clicks = [k for a, k in f.runlog if a and a[0] == 'click']
        self.assertTrue(clicks and all(k.get('exp') in click_ids for k in clicks))
        g = self.graph()
        nid = next(n for n in g.nodes if n.startswith('GardenBed#0.8,-25.3'))
        self.assertTrue(set(g.nodes[nid].extra.get('exps', [])) & set(click_ids + [e.id for e in exps]))

    def test_replay_proposes_the_same_and_applies_nothing_twice(self):
        self.game()
        with mock.patch('game.icons.name_of', lambda a: 'Green Bean'):
            engine.achieve('harvest')
        before = open(steps.OBSERVED).read()
        props = [I.propose(e) for e in I.journal()]
        self.assertEqual(props, [I.propose(e) for e in I.journal()])
        applied = I.replay()
        self.assertEqual(applied, 0)
        self.assertEqual(open(steps.OBSERVED).read(), before)

    def test_a_press_step_is_its_own_experience(self):
        f = self.game()
        with mock.patch('game.icons.name_of', lambda a: 'Green Bean'):
            engine.achieve('harvest')
        kinds = [e.action.kind for e in I.journal()]
        self.assertIn('click', kinds)
        self.assertIn('space', kinds)   # the Collect prompt's Space

    def test_a_repeated_unresolved_miss_becomes_one_gap_bundle_with_a_fixture(self):
        self.game()
        e1 = dataclasses.replace(sample(), verdict=X.Verdict('miss', (X.Check('card', 'Collect', 'Seeds', False),)))
        e1 = X.Experience.new(**{f: getattr(e1, f) for f in X.FIELDS})
        e2 = X.Experience.new(**dict({f: getattr(e1, f) for f in X.FIELDS},
                                     artifacts=X.Artifacts(frames=('c.jpg',), log_mark=11, t=3.0)))
        I.apply(e1)
        self.assertEqual(I.settle(), [])
        I.apply(e2)
        I.settle()
        I.settle()   # once per invariant
        bundles = I.gaps()
        self.assertEqual(len(bundles), 1)
        b = bundles[0]
        self.assertEqual(set(b['experiences']), {e1.id, e2.id})
        self.assertIn('pick', b['invariant'])
        self.assertEqual(b['owner'], 'steps')
        self.assertIn('actions.json', b['tables'])
        path = I.fixture(b['id'], os.path.join(self.tmp.name, 'fixtures'))
        fx = json.load(open(path))
        self.assertEqual(len(fx['experiences']), 2)
        self.assertFalse(I.verify_fixture(fx))   # the gap still reproduces offline: the invariant fails

    def test_a_vision_answer_is_an_experience_and_its_look_is_a_memory_update(self):
        self.game()
        img = __import__('PIL.Image', fromlist=['Image']).new('RGB', (1920, 1080), (90, 140, 60))
        with mock.patch.object(learn, 'relabel', lambda img, box, kind: True) as _:
            c = act.Click((1104, 540), 'point', 3, lines=['[D188 9:01:00 AM] > water me=Player target=GardenBed(Clone) '
                                                          'at (0.84, 0.10, -25.34)'], events=['water'], moved=False)
            c.img0 = img
            e, learned = I.on_click(c, img, None)
        self.assertEqual(e.action.what, 'point')
        self.assertEqual(learned, 'GardenBed')


class Safety(unittest.TestCase):
    def test_low_level_actuators_have_no_semantic_learning_imports(self):
        for name in ('act.py', 'ui.py'):
            src = open(os.path.join(GAME_DIR, name)).read()
            self.assertIsNone(re.search(r'^\s*from \. import [^\n]*\blearn\b|import (evals|game\.learn)|from \.learn',
                                        src, re.M), name)

    def test_navigation_does_not_write_learned_memory(self):
        src = open(os.path.join(GAME_DIR, 'nav.py')).read()
        self.assertNotIn('L.relabel(', src)
        self.assertNotIn('L.learn_toward(', src)

    def test_runtime_code_cannot_apply_code_patches(self):
        for f in os.listdir(GAME_DIR):
            if f.endswith('.py'):
                src = open(os.path.join(GAME_DIR, f)).read()
                self.assertNotRegex(src, r'git\s+apply|git\s+commit|patch\s+-p|apply_patch', f)


if __name__ == '__main__':
    unittest.main()
