"""Offline tests for the unified improvement loop (spec docs/superpowers/specs/2026-11-04-unified-improvement-loop-
refactor.md): one immutable experience per action, one integration boundary, idempotent replay, gap bundles.
Run: .venv/bin/python tools/test_experience.py"""
import dataclasses
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_engine import GAME, NX, NZ, EngineBase, FakeGame, L, obj  # noqa: E402
from game import act, engine, experience as X, integrate as I, learn, play, primitives, steps, world
from game.task_state import TaskStore  # noqa: E402

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


class SQLiteExperienceStore(unittest.TestCase):
    def setUp(self):
        from runtime.db import Database
        from runtime.run_store import RunStore
        from runtime.experience_store import ExperienceStore
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(os.path.join(self.tmp.name, 'wf.sqlite3'))
        run_id = RunStore(self.db).start('experiences', 'test', os.path.join(self.tmp.name, 'run'))
        self.store = ExperienceStore(self.db, run_id)

    def test_immutable_payload_and_gap_foreign_keys(self):
        e = sample().to_dict()
        self.assertTrue(self.store.record(e))
        self.assertFalse(self.store.record(e))
        with self.assertRaisesRegex(ValueError, 'conflicting immutable'):
            self.store.record(dict(e, action={'kind': 'different'}))
        bundle = {'id': 'gap-1', 'kind': 'capability', 'owner': 'turn', 'invariant': 'missing', 'experiences': [e['id']]}
        self.store.put_gap(bundle, [e['id']])
        self.assertEqual(self.store.gaps()[0]['id'], 'gap-1')
        with self.assertRaises(Exception):
            self.store.put_gap(dict(bundle, id='bad-gap'), ['missing-experience'])

    def test_concurrent_update_claim_has_one_winner(self):
        e = sample().to_dict()
        self.store.record(e)
        barrier = threading.Barrier(8)
        claims = []
        def claim():
            barrier.wait()
            claims.append(self.store.claim_update(e['id'], 'memory', 'learn', {'kind': 'Bed'}))
        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(claim is not None for claim in claims), 1)

    def test_stale_claim_is_recoverable_and_old_owner_cannot_finish_it(self):
        e = sample().to_dict()
        self.store.record(e)
        first = self.store.claim_update(e['id'], 'memory', 'learn', {'kind': 'Bed'})
        with self.db.transaction(immediate=True) as connection:
            connection.execute('UPDATE applied_updates SET claimed_at=0 WHERE id=?', (first.id,))
        recovered = self.store.claim_update(e['id'], 'memory', 'learn', {'kind': 'Bed'})
        self.assertIsNotNone(recovered)
        self.assertNotEqual(first.token, recovered.token)
        with self.assertRaisesRegex(RuntimeError, 'no longer owned'):
            self.store.finish_update(first, 'applied', 'late')
        self.store.finish_update(recovered, 'applied', 'done')
        self.assertIsNone(self.store.claim_update(e['id'], 'memory', 'learn', {'kind': 'Bed'}))


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

    def harvest_turns(self):
        """Exercise the real turn/adapter/integration boundary; only the physical game's controls are faked."""
        f = self.game()
        graph = engine._open_graph()
        world.refresh(graph, f.read_save()[1], f.today_log()[0])
        store = TaskStore(os.path.join(self.tmp.name, 'task.json'))
        self.task_store = store
        adapter = primitives.GameAdapter()
        raw = f.run_action
        def input_command(command):
            if command == 'click:960:500' and f.card:
                f.clicks.append((960, 500))
                return f.press_bubble()  # fake game's response to its Collect button, one physical input
            return raw(command)
        with mock.patch.object(f, 'find_text', return_value=[{'cx': 960, 'cy': 500}], create=True), \
                mock.patch.object(f, 'run_action', input_command):
            c = play.turn('garden', {'chores': ['harvest'], 'crops': 'Green Bean'}, store=store, adapter=adapter)
            c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {
                'kind': 'bubble', 'point': [1104, 540], 'visible_road': True, 'crop': 'Green Bean',
                'row': 'pick', 'step': 0, 'expects': {'card': 'Collect'}}}, store=store, adapter=adapter)
            self.assertIsNone(c.surprise)
            c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {
                'kind': 'press', 'label': 'Collect', 'row': 'pick', 'step': 1,
                'expects': {'events': ['grab_item']}}}, store=store, adapter=adapter)
            self.assertIsNone(c.surprise)
        self.assertEqual(len(f.clicks), 2)
        return f

    def test_one_click_is_one_experience_referenced_by_learning_eval_and_transition_records(self):
        f = self.harvest_turns()
        exps = I.journal()
        click_ids = [e.id for e in exps if e.action.kind == 'click']
        self.assertTrue(click_ids)
        with open(steps.OBSERVED) as records:
            obs = [json.loads(line) for line in records]
        self.assertTrue(obs and all(o.get('exp') in {e.id for e in exps} for o in obs), obs)
        from runtime.run_store import RunStore
        timeline = RunStore(self.task_store.db).events(self.task_store.run_id)
        outcomes = [row['experience']['id'] for row in timeline if row['phase'] == 'outcome']
        integrated = [row['experience'] for row in timeline if row['phase'] == 'integration']
        self.assertEqual(set(outcomes), {e.id for e in exps})
        self.assertEqual(outcomes, integrated)
        g = self.graph()
        nid = next(n for n in g.nodes if n.startswith('GardenBed#0.8,-25.3'))
        self.assertTrue(set(g.nodes[nid].extra.get('exps', [])) & set(click_ids + [e.id for e in exps]))

    def test_replay_proposes_the_same_and_applies_nothing_twice(self):
        self.harvest_turns()
        with open(steps.OBSERVED) as records:
            before = records.read()
        props = [I.propose(e) for e in I.journal()]
        self.assertEqual(props, [I.propose(e) for e in I.journal()])
        applied = I.replay()
        self.assertEqual(applied, 0)
        with open(steps.OBSERVED) as records:
            self.assertEqual(records.read(), before)

    def test_journal_write_failure_propagates_and_never_marks_experience_applied(self):
        e = sample()
        with mock.patch('runtime.experience_store.ExperienceStore.record', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                I.apply(e, X.Correction(e.id))
        self.assertEqual(I.journal(), [])

    def test_unknown_claim_completion_never_duplicates_the_experience_or_consumer(self):
        e = sample()
        correction = X.Correction(e.id, gap=(X.Update('gap', 'bundle', {'invariant': 'test claim'}),))
        with mock.patch('runtime.experience_store.ExperienceStore.finish_update',
                        side_effect=OSError('claim completion unavailable')):
            with self.assertRaisesRegex(OSError, 'claim completion unavailable'):
                I.apply(e, correction)
        self.assertEqual([row.id for row in I.journal()], [e.id])
        self.assertEqual(I.apply(e, correction)['applied'], 0)
        self.assertEqual([row.id for row in I.journal()], [e.id])

    def test_stale_claim_replay_does_not_duplicate_completed_external_effect(self):
        e = sample()
        correction = X.Correction(e.id, transitions=(X.Update('transitions', 'observation', {'i': 0}),))
        with mock.patch('runtime.experience_store.ExperienceStore.finish_update',
                        side_effect=OSError('crash after effect')):
            with self.assertRaisesRegex(OSError, 'crash after effect'):
                I.apply(e, correction)
        with open(steps.OBSERVED) as stream:
            self.assertEqual(sum(json.loads(line).get('exp') == e.id for line in stream if line.strip()), 1)
        backend = I._experience_store()
        with backend.database.transaction(immediate=True) as connection:
            connection.execute('UPDATE applied_updates SET claimed_at=0 WHERE experience_id=?', (e.id,))
        self.assertEqual(I.apply(e, correction)['applied'], 1)
        with open(steps.OBSERVED) as stream:
            self.assertEqual(sum(json.loads(line).get('exp') == e.id for line in stream if line.strip()), 1)

    def test_a_press_step_is_its_own_experience(self):
        f = self.harvest_turns()
        kinds = [e.action.kind for e in I.journal()]
        self.assertIn('click', kinds)
        self.assertIn('press', kinds)   # the model's explicit named Collect control

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
        with open(path) as source:
            fx = json.load(source)
        self.assertEqual(len(fx['experiences']), 2)
        self.assertFalse(I.verify_fixture(fx))   # the gap still reproduces offline: the invariant fails

    def test_a_vision_answer_is_an_experience_and_its_look_is_a_memory_update(self):
        self.game()
        img = __import__('PIL.Image', fromlist=['Image']).new('RGB', (1920, 1080), (90, 140, 60))
        with mock.patch.object(learn, 'relabel', lambda img, box, kind, idempotency_key=None: True) as _:
            c = act.Click((1104, 540), 'point', 3, lines=['[D188 9:01:00 AM] > water me=Player target=GardenBed(Clone) '
                                                          'at (0.84, 0.10, -25.34)'], events=['water'], moved=False)
            c.img0 = img
            e, learned = I.on_click(c, img, None)
        self.assertEqual(e.action.what, 'point')
        self.assertEqual(learned, 'GardenBed')


class Safety(unittest.TestCase):
    def test_low_level_actuators_have_no_semantic_learning_imports(self):
        for name in ('act.py', 'ui.py'):
            with open(os.path.join(GAME_DIR, name)) as source:
                src = source.read()
            self.assertIsNone(re.search(r'^\s*from \. import [^\n]*\blearn\b|import (evals|game\.learn)|from \.learn',
                                        src, re.M), name)

    def test_navigation_does_not_write_learned_memory(self):
        with open(os.path.join(GAME_DIR, 'nav.py')) as source:
            src = source.read()
        self.assertNotIn('L.relabel(', src)
        self.assertNotIn('L.learn_toward(', src)

    def test_runtime_code_cannot_apply_code_patches(self):
        for f in os.listdir(GAME_DIR):
            if f.endswith('.py'):
                with open(os.path.join(GAME_DIR, f)) as source:
                    src = source.read()
                self.assertNotRegex(src, r'git\s+apply|git\s+commit|patch\s+-p|apply_patch', f)


class LateCard(unittest.TestCase):
    """Live D189 7:11: the Collect prompt showed after the check had read an empty screen -> a false miss and a
    button question that would have rewritten the pick row's click step."""

    def test_an_expected_card_that_shows_late_is_a_hit(self):
        from game import ui
        seq = iter([[], ['Collect']])
        with mock.patch.object(ui, 'texts', lambda: next(seq, ['Collect'])), \
                mock.patch.object(ui, 'shows', lambda word, wait=2.0: True):
            checks, bad = I.verify({'card': 'Collect'}, [], [])
        self.assertEqual(bad, [])
        self.assertTrue(checks[0].ok)

    def test_a_card_that_never_shows_is_still_a_miss(self):
        from game import ui
        with mock.patch.object(ui, 'texts', lambda: ['Seeds']), \
                mock.patch.object(ui, 'shows', lambda word, wait=2.0: False):
            _, bad = I.verify({'card': 'Collect'}, [], [])
        self.assertEqual(bad[0][0], 'card')


if __name__ == '__main__':
    unittest.main()
