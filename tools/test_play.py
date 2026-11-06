"""Universal public boundary: real task persistence and dispatcher, fake physical I/O only."""
import contextlib
import importlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import wf
from game import core, engine, forage, garden, integrate as I, nav, primitives, sleep, task_state as S, turn
from test_turn import Port
from evals import store as eval_store


# Literal public inputs exercise the registered argparse surface, including old escape hatches.
ALIASES = [
    ['play', 'sleep'], ['garden'], ['sleep'], ['forage', 'rock'], ['achieve', 'water'],
    ['goto', 'farmhouse'], ['go-world', '1', '2'], ['improve'], ['calib'], ['road', '--go'],
    ['advance'], ['teach', 'step', 'F7'], ['edge', 'replay', 'House', 'Garden'],
    ['do', 'go:1:2', 'key:space'], ['key', 'space', 'space'], ['click', '100', '200', '--double'],
    ['py', 'sleep_until_morning(); morning()'], ['call', 'smoke.morning'], ['resume'],
    ['where'], ['pos'], ['plan', 'House'], ['ask-step', 'House'], ['click-text', 'Collect'], ['hold', '1', 'space'],
    ['walk', 'up', '1'], ['path', 'up:1'], ['scroll', '1'], ['type', 'hello'], ['route', 'test'],
]


class PlayCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = S.TaskStore(os.path.join(self.tmp.name, 'task.json'))
        self.port = Port()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(I, 'JOURNAL_DIR', self.tmp.name).start()
        from types import SimpleNamespace
        mock.patch.object(core, 'WF', SimpleNamespace(run_log=lambda *args, **kw: None)).start()

    def play(self):
        self.assertIsNotNone(importlib.util.find_spec('game.play'), 'universal model-owned boundary is missing')
        return importlib.import_module('game.play')

    def cli(self, argv, directory=None):
        play = self.play()
        # A dispatcher regression must fail at the physical boundary before touching the live game.
        with mock.patch.object(eval_store, 'ENABLED', False), \
                mock.patch.object(eval_store, 'PATH', os.path.join(self.tmp.name, 'evals.jsonl')), \
                mock.patch.object(core, 'WF', core.WF), \
                mock.patch.object(wf, 'run_dir', return_value=directory or self.tmp.name), \
                mock.patch.object(play, 'GameAdapter', return_value=self.port), \
                mock.patch.object(play, '_clues', return_value={}), \
                mock.patch.object(wf, 'ensure_front', side_effect=AssertionError('legacy focus/input path')), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            wf.main(argv)
        return out.getvalue()



class Play(PlayCase):
    def test_every_public_gameplay_alias_returns_before_input(self):
        # A public alias choosing a hidden follow-up would emit input or enter the legacy focus path.
        for argv in ALIASES:
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as directory:
                output = self.cli(argv, directory)
                self.assertIn('NEXT ', output)
                self.assertEqual(self.port.inputs, [])

    def test_every_registered_command_is_classified(self):
        import argparse
        registered = set()
        original = argparse._SubParsersAction.add_parser
        def register(parser, name, **kw):
            registered.add(name)
            return original(parser, name, **kw)
        with mock.patch.object(argparse._SubParsersAction, 'add_parser', register):
            self.cli(['sleep'])
        self.assertTrue(hasattr(wf, 'OBSERVATION_COMMANDS'), 'command classification must cover the actual registry')
        self.assertEqual(registered, set(wf.PLAY_COMMANDS) | set(wf.OBSERVATION_COMMANDS) |
                         {'pause', 'focus', 'focus-mode', 'move-mouse', 'edge', 'road'})
        self.assertEqual({args[0] for args in ALIASES}, set(wf.PLAY_COMMANDS) | {'edge', 'road'})

    def test_aliases_never_call_legacy_workflow_drivers(self):
        self.play()
        with contextlib.ExitStack() as stack:
            for module, name in [(sleep, 'do'), (engine, 'achieve'), (nav, 'reach'), (nav, 'search'),
                                 (garden, '_tend'), (forage, 'run')]:
                stack.enter_context(mock.patch.object(module, name, side_effect=AssertionError('legacy driver')))
            for argv in ALIASES:
                with self.subTest(argv=argv), tempfile.TemporaryDirectory() as directory:
                    self.assertIn('NEXT ', self.cli(argv, directory))

    def test_one_decision_performs_at_most_one_input(self):
        play = self.play()
        c = play.turn('navigate', {'destination': 'House'}, store=self.store, adapter=self.port)
        self.assertEqual(self.port.inputs, [])
        c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'press', 'label': 'Open'}},
                      store=self.store, adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1)
        with self.assertRaises(turn.StaleTurn):
            play.turn(answer={'turn_id': c.turn_id - 1, 'kind': 'act', 'action': {'kind': 'space'}},
                      store=self.store, adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1)

    def test_domain_alias_and_play_resume_the_same_task_id(self):
        self.play()
        garden_context = json.loads(self.cli(['garden']).split('NEXT ', 1)[1])
        universal = json.loads(self.cli(['play']).split('NEXT ', 1)[1])
        self.assertEqual(garden_context['task']['task_id'], universal['task']['task_id'])
        self.assertEqual(garden_context['turn_id'], universal['turn_id'])


class UniversalOutcomes(PlayCase):
    # These tests catch outcome paths that accept a second input without relevant proof/correction.
    def movement(self, moved, before=(0., 0.), after=(0., 0.)):
        play = self.play()
        self.port.snapshot['position'] = list(before)
        def capture(intent, old, expected):
            evidence = __import__('game.experience', fromlist=['Evidence']).Evidence(moved=moved, mode='gameplay')
            # The adapter's captured state is part of the immutable outcome, not a later mutable observation.
            from game import experience as X
            evidence_data = evidence.to_dict() if hasattr(evidence, 'to_dict') else __import__('dataclasses').asdict(evidence)
            evidence_data['state'] = (('position', list(after)),)
            self.assertIn('state', X.Evidence.__dataclass_fields__, 'outcomes must preserve after-state evidence')
            return primitives.experience(intent, old, expected, X.Evidence(**evidence_data), ('after.jpg',))
        self.port.capture = capture
        c = play.turn('navigate', {'destination_position': [10., 0.]}, store=self.store, adapter=self.port)
        c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action':
                             {'kind': 'waypoint', 'point': [100, 500], 'walkable': True}},
                      store=self.store, adapter=self.port)
        self.assertIsNotNone(c.surprise)
        with self.assertRaises(turn.DecisionRejected):
            play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'space'}},
                      store=self.store, adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1, 'the second input is blocked')
        c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'correct', 'correction':
                             {'kind': 'revise_decision', 'data': {'reason': 'inspect a fresh road'}}},
                      store=self.store, adapter=self.port)
        self.assertIsNone(c.surprise)

    def test_no_move_blocks_next_input_until_model_correction(self):
        self.movement(False)

    def test_movement_away_from_goal_is_not_progress(self):
        self.movement(True, after=(-3., 0.))

    def test_irrelevant_movement_is_not_progress(self):
        self.movement(True, after=(0., 3.))

    def correction_fixture(self):
        from game import experience as X, learn
        from objects.graph import Graph, Node
        graph = Graph()
        for name in ('House', 'Bed', 'Garden'):
            graph.nodes[name] = Node(name, 'unique', name)
        graph.add_edge('House', 'Bed', 'toward', dir=[1., 0.], source='old')
        graph.add_edge('House', 'Garden', 'toward', dir=[0., 1.], source='old')
        mock.patch.dict(learn.MEMORY, graph=graph).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), self.port.snapshot, {}, X.Evidence())
        data = {'edge': {'a': 'House', 'b': 'Bed', 'rel': 'toward'}, 'values': {'dir': [-1., 0.]},
                'frame_path': 'full.jpg', 'rationale': 'visible bed is west', 'evidence_refs': ['full.jpg']}
        return graph, e, data

    def test_vision_graph_correction_updates_only_named_edge_with_provenance(self):
        graph, e, data = self.correction_fixture()
        try:
            result = I.correct(e, 'graph', data)
        except ValueError as error:
            self.fail(f'graph must be a public correction class: {error}')
        self.assertEqual(result['applied'], 1)
        self.assertEqual(graph.edges('House')[0]['dir'], [-1., 0.])
        self.assertEqual(graph.edges('House')[0]['provenance']['experience'], e.id)
        self.assertEqual(graph.edges('House')[0]['provenance']['frame_path'], 'full.jpg')
        self.assertEqual(graph.edges('House')[1], {'a': 'House', 'b': 'Garden', 'rel': 'toward',
                                                'dir': [0., 1.], 'source': 'old', 'compass': 'S'})
        self.assertEqual(self.port.inputs, [])

    def test_vision_appearance_correction_reembeds_only_named_kind(self):
        import numpy as np
        from PIL import Image
        from objects import store as vectors, dino
        from game import experience as X
        db = vectors.Store(os.path.join(self.tmp.name, 'db'))
        db.add('Bed', Image.new('RGB', (20, 20)), [1., 0.])
        db.add('GardenBed', Image.new('RGB', (20, 20)), [0., 1.])
        before = db.examples('GardenBed')[0].vec.copy()
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), self.port.snapshot, {}, X.Evidence())
        with mock.patch.object(vectors, 'Store', return_value=db), \
                mock.patch.object(dino, 'mean_vector', return_value=np.array([.6, .8])):
            try:
                result = I.correct(e, 'appearance', {'op': 'reembed', 'kind': 'Bed', 'frame_path': 'full.jpg',
                                                    'rationale': 'refresh bed clue', 'evidence_refs': ['full.jpg']})
            except ValueError as error:
                self.fail(f'named-kind reembedding must be supported: {error}')
        self.assertEqual(result['applied'], 1)
        np.testing.assert_allclose(db.examples('Bed')[0].vec, [.6, .8])
        np.testing.assert_array_equal(db.examples('GardenBed')[0].vec, before)
        self.assertEqual(self.port.inputs, [])

    def test_correction_replay_is_idempotent(self):
        graph, e, data = self.correction_fixture()
        try:
            first = I.correct(e, 'graph', data)
            second = I.correct(e, 'graph', data)
        except ValueError as error:
            self.fail(f'graph correction replay must be supported: {error}')
        self.assertEqual((first['applied'], second['applied']), (1, 0))
        self.assertEqual(len(I.journal()), 1)


class Subgoals(PlayCase):
    def start(self, authorization=None):
        self.play()
        params = {'chores': ['replant'], 'region': 'Garden', 'authorization': authorization or {}}
        self.store.create(S.TaskState('garden-root', 'garden', params=params, targets=['bed', 'other'],
            active=S.Interaction('bed-tx', phase='plant', actual_node='bed', crop='Tulip',
                                 provisional={'facts': {'emptied': True}}),
            unresolved=[{'node': 'other', 'reason': 'seed_shortage', 'item': 'TulipSeed', 'crop': 'Tulip'}]))
        return self.play().turn(store=self.store, adapter=self.port)

    def choose(self, c, kind, **data):
        # New store and entry-point instance on every boundary exercise persisted state, not live objects.
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def outcome(self, events=(), before=None, after=None):
        from game import experience as X
        self.port.snapshot = dict(self.port.snapshot, **(before or {}))
        def capture(intent, old, expects):
            evidence = X.Evidence(events=events, mode='gameplay', state=tuple((after or {}).items()))
            self.port.snapshot = dict(self.port.snapshot, **(after or {}))
            return primitives.experience(intent, old, expects, evidence, ('after.jpg',))
        self.port.capture = capture

    def push(self, c, goal, params=None):
        self.assertIn('push', c.allowed_decisions, 'the universal loop must expose explicit durable subgoals')
        return self.choose(c, 'push', action={'goal': goal, 'params': params or {}})

    def test_garden_sleep_shop_return_survives_restart_at_every_boundary(self):
        c = self.start({'purchases': [{'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20}]})
        frozen = self.store.load().active
        c = self.push(c, 'sleep')
        self.assertEqual(S.TaskStore(self.store.path).load().stack[-1].parent_interaction, frozen)
        self.outcome(('sleep_transition',))
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Sleep', 'expects': {'events': ['sleep_transition']}})
        c = self.choose(c, 'complete')
        self.assertIsNone(c.transaction, 'completion cannot silently restore the parent')
        c = self.choose(c, 'resume')
        self.assertEqual(c.transaction['transaction_id'], 'bed-tx')
        c = self.push(c, 'shop', {'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20})
        self.outcome(before={'inventory': {'TulipSeed': 0}, 'money': 95},
                     after={'inventory': {'TulipSeed': 2}, 'money': 75})
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Buy', 'purchase':
                         {'item': 'TulipSeed', 'quantity': 2, 'price': 20}})
        c = self.choose(c, 'complete')
        self.assertEqual(c.task['stack'][-1]['result']['acquired'], 2)
        c = self.choose(c, 'resume')
        self.assertEqual(c.transaction['transaction_id'], 'bed-tx')
        c = self.push(c, 'navigate', {'region': 'Garden'})
        self.outcome(after={'region': 'Garden'})
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Exit', 'expects': {'region': 'Garden'}})
        c = self.choose(c, 'complete')
        self.assertIsNone(c.transaction)
        c = self.choose(c, 'resume')
        self.assertEqual(c.transaction['transaction_id'], 'bed-tx')
        self.assertEqual(c.transaction['crop'], 'Tulip')
        self.assertEqual(len(self.port.inputs), 3)
        self.assertEqual(c.task['task_id'], 'garden-root')
        self.assertEqual(list(c.task['stack']), [])

    def test_nested_suspend_resume_retains_both_parent_interactions(self):
        c = self.push(self.start(), 'sleep')
        saved = self.store.load()
        saved.active = S.Interaction('sleep-tx', phase='inspect')
        saved.current_turn = None
        self.store.save(saved)
        c = self.play().turn(store=self.store, adapter=self.port)
        c = self.push(c, 'navigate', {'region': 'House'})
        self.assertEqual(c.task['stack'][0]['status'], 'suspended')
        self.assertEqual(c.task['stack'][0]['parent_interaction']['transaction_id'], 'bed-tx')
        self.outcome(after={'region': 'House'})
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Enter', 'expects': {'region': 'House'}})
        c = self.choose(c, 'complete')
        c = self.choose(c, 'resume')
        self.assertEqual(c.transaction['transaction_id'], 'sleep-tx')
        self.assertEqual(c.task['stack'][0]['status'], 'active')
        c = self.choose(c, 'suspend')
        self.assertNotIn('act', c.allowed_decisions)
        c = self.choose(c, 'resume')
        self.assertEqual(c.transaction['transaction_id'], 'sleep-tx')

    def test_seed_shortage_correction_preserves_exact_item_constraint(self):
        c = self.start()
        self.outcome(after={'picker_empty': True})
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Seeds'})
        c = self.choose(c, 'correct', correction={'kind': 'blocked_target', 'data':
                        {'node': 'bed', 'reason': 'seed_shortage', 'item': 'TulipSeed'}})
        constraint = c.coverage['unresolved'][-1]
        self.assertIn('item', constraint, 'typed shortage must retain its named seed item')
        self.assertEqual(constraint['item'], 'TulipSeed')
        self.assertEqual(constraint['reason'], 'seed_shortage')
        self.assertEqual(list(c.coverage['covered']), [])

    def test_pending_subgoal_intent_reconciles_without_repeat(self):
        c = self.push(self.start(), 'sleep')
        self.outcome(('sleep_transition',))
        self.port.fail = True
        with self.assertRaises(RuntimeError):
            self.choose(c, 'act', action={'kind': 'press', 'label': 'Sleep', 'expects': {'events': ['sleep_transition']}})
        restarted = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertEqual(len(self.port.inputs), 1)
        self.assertIsNotNone(restarted.surprise)
        self.assertEqual(restarted.task['stack'][-1]['parent_interaction']['transaction_id'], 'bed-tx')
        restarted = self.choose(restarted, 'correct', correction={'kind': 'revise_decision'})
        restarted = self.choose(restarted, 'complete')
        self.assertEqual(restarted.task['stack'][-1]['status'], 'complete')
        self.assertEqual(len(self.port.inputs), 1)

    def test_shop_quantity_and_spend_require_task_authorization(self):
        for auth, purchase in [({}, {'item': 'TulipSeed', 'quantity': 2, 'price': 20}),
                              ({'purchases': [{'item': 'TulipSeed', 'quantity': 1, 'max_spend': 20}]},
                               {'item': 'TulipSeed', 'quantity': 2, 'price': 20}),
                              ({'purchases': [{'item': 'TulipSeed', 'quantity': 2, 'max_spend': 10}]},
                               {'item': 'TulipSeed', 'quantity': 2, 'price': 20})]:
            with self.subTest(auth=auth), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                c = self.push(self.start(auth), 'shop', {'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20})
                c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Buy', 'purchase': purchase})
                self.assertIsNotNone(c.surprise)
                self.assertEqual(self.port.inputs, [])

    def test_blocked_bed_reopens_only_after_verified_seed_acquisition(self):
        c = self.push(self.start({'purchases': [{'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20}]}),
                      'shop', {'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20})
        self.outcome(before={'inventory': {'TulipSeed': 0}, 'money': 95},
                     after={'inventory': {'TulipSeed': 0}, 'money': 75})
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Buy', 'purchase':
                         {'item': 'TulipSeed', 'quantity': 2, 'price': 20}})
        # Money alone cannot finish a purchase or release seed constraints.
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'complete')
        self.assertEqual(len(self.store.load().unresolved), 1)
        c = self.choose(c, 'correct', correction={'kind': 'revise_decision'})
        self.outcome(after={'inventory': {'TulipSeed': 2}, 'money': 75})
        c = self.choose(c, 'act', action={'kind': 'read'})
        c = self.choose(c, 'complete')
        self.assertEqual(list(c.coverage['unresolved']), [])
        self.assertEqual(list(c.coverage['covered']), [])
        self.assertEqual(list(c.coverage['targets']), ['bed', 'other'])
        self.assertFalse(self.store.load().stack[-1].parent_interaction.provisional['facts'].get('planted'))


class BoundaryValidation(PlayCase):
    def test_unknown_or_irrelevant_evidence_blocks_next_input(self):
        from game import experience as X
        for evidence in (X.Evidence(mode='gameplay', state=(('money', 95),)),
                         X.Evidence(mode='gameplay', events=('talk',))):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected, evidence)
                c = self.play().turn('sleep', store=store, adapter=self.port)
                c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act',
                    'action': {'kind': 'space', 'expects': {'events': ['sleep_transition']}}},
                    store=store, adapter=self.port)
                self.assertIsNotNone(c.surprise)
                self.assertNotIn('act', c.allowed_decisions)

    def test_generic_wrong_modal_and_wrong_object_are_surprises(self):
        from game import experience as X
        for evidence, expected in [(X.Evidence(mode='dialogue'), {'mode': 'card'}),
                                    (X.Evidence(mode='gameplay', node='Other'), {'node': 'Bed'})]:
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.capture = lambda intent, old, wanted: primitives.experience(intent, old, wanted, evidence)
                c = self.play().turn('sleep', store=store, adapter=self.port)
                c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act',
                    'action': {'kind': 'space', 'expects': expected}}, store=store, adapter=self.port)
                self.assertIsNotNone(c.surprise)

    def test_universal_primitives_support_guarded_dialogue_and_menu_inputs(self):
        adapter = primitives.GameAdapter()
        for action, mode, command in [({'kind': 'space'}, 'dialogue', 'key:space'),
                                      ({'kind': 'space'}, 'cutscene', 'key:space'),
                                      ({'kind': 'key', 'label': 'j'}, 'gameplay', 'key:j'),
                                      ({'kind': 'close'}, 'map', 'key:escape')]:
            with self.subTest(action=action, mode=mode):
                try:
                    prepared = adapter.prepare(action, {'screen': {'kind': mode}})
                except ValueError as error:
                    self.fail(f'whole-game primitive must support this explicit guarded input: {error}')
                self.assertEqual(prepared['command'], command)
        for mode in ('pause', 'unknown', 'menu'):
            with self.assertRaises(ValueError):
                adapter.prepare({'kind': 'key', 'label': 'j'}, {'screen': {'kind': mode}})

    def test_measured_movement_toward_goal_is_progress(self):
        from game import experience as X
        self.port.snapshot['position'] = [0., 0.]
        self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected,
            X.Evidence(mode='gameplay', moved=True, state=(('position', [3., 0.]),)))
        c = self.play().turn('navigate', {'destination_position': [10., 0.]}, store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act',
            'action': {'kind': 'waypoint', 'point': [1200, 600], 'walkable': True}},
            store=self.store, adapter=self.port)
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)

    def test_expected_node_uses_canonical_positioned_event_identity(self):
        from game import experience as X, learn
        from objects.graph import Graph, Node
        graph = Graph()
        graph.nodes['Bed'] = Node('Bed', 'member', 'GardenBed', pos=[1., 2.], scene='Farm')
        mock.patch.dict(learn.MEMORY, graph=graph).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected,
            X.Evidence(lines=('> water me=Player target=GardenBed at (1.0, 0.0, 2.0)',),
                       events=('water',), at=(1., 2.), mode='gameplay'))
        c = self.play().turn('garden', store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action':
            {'kind': 'space', 'expects': {'node': 'Bed', 'events': ['water']}}},
            store=self.store, adapter=self.port)
        self.assertEqual(c.transaction['actual_node'], 'Bed')
        self.assertIsNone(c.surprise)

    def test_appearance_sample_uses_the_named_captured_frame(self):
        from game import experience as X
        from objects import store as vectors, dino
        from PIL import Image
        import numpy as np
        before = os.path.join(self.tmp.name, 'before.png')
        after = os.path.join(self.tmp.name, 'after.png')
        Image.new('RGB', (10, 10), 'red').save(before)
        Image.new('RGB', (10, 10), 'blue').save(after)
        observation = dict(self.port.snapshot, frame_path=before)
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), observation, {}, X.Evidence(), (after,))
        db = vectors.Store(os.path.join(self.tmp.name, 'db'))
        with mock.patch.object(vectors, 'Store', return_value=db), \
                mock.patch.object(dino, 'mean_vector', return_value=np.array([1., 0.])):
            result = I.correct(e, 'appearance', {'op': 'sample', 'kind': 'Bed', 'box': [0, 0, 10, 10],
                'frame_path': after, 'rationale': 'bed on outcome frame', 'evidence_refs': [after]})
        self.assertEqual(result['applied'], 1)
        sample = db.examples('Bed')[0]
        with Image.open(db.example_path('Bed', sample.id)) as crop:
            self.assertEqual(crop.getpixel((5, 5)), (0, 0, 255))

    def test_production_input_focuses_only_for_explicit_input_and_releases_after_capture(self):
        from types import SimpleNamespace
        events = []
        raw = SimpleNamespace(ensure_front=lambda: events.append('focus'),
                              release_focus=lambda: events.append('release'),
                              run_action=lambda command: events.append('input'),
                              wait_settle=lambda: events.append('settle'),
                              log_since=lambda mark: '', _unhash=lambda text: text)
        snapshot = dict(self.port.snapshot, frame_path=None)
        adapter = primitives.GameAdapter()
        with mock.patch.object(core, 'WF', raw), mock.patch.object(adapter, 'observe', return_value=snapshot):
            adapter.perform({'kind': 'key', 'command': 'key:j'})
            adapter.capture(S.Intent(1, {'kind': 'key'}, 0, 1.), snapshot, {})
        self.assertEqual(events, ['focus', 'input', 'settle', 'release'])

    def test_graph_correction_rejects_missing_provenance_without_mutation(self):
        fixture = UniversalOutcomes()
        fixture.tmp, fixture.port = self.tmp, self.port
        graph, e, data = fixture.correction_fixture()
        before = [dict(edge) for edge in graph.edges()]
        for key in ('frame_path', 'rationale', 'evidence_refs'):
            invalid = dict(data)
            invalid.pop(key)
            with self.assertRaises(ValueError):
                I.correct(e, 'graph', invalid)
        self.assertEqual(graph.edges(), before)

    def test_production_clues_capture_save_inventory_money_region_and_provenance(self):
        from game import learn, observe
        from objects.graph import Graph
        from types import SimpleNamespace
        save = {'saveCount': 7, 'currentScene': 'Farm', 'currentPlayerPosition': {'x': 1., 'z': 2.},
                'gameState': {'time': {'day': 210, 'timeOfDay': {'totalSeconds': 32400}},
                              'player': {'state': {'userState': {'entries': [{'name': 'money', 'value': 95}]}},
                                         'inventory': {'items': [{'nameHash': 'TulipSeed', 'count': 2}]}}}}
        wf_port = SimpleNamespace(read_save=lambda: ('save.json', save), today_log=lambda: ([], None),
                                  current_scene=lambda: 'House')
        with mock.patch.object(core, 'WF', wf_port), mock.patch.object(engine, '_open_graph', return_value=Graph()), \
                mock.patch.object(observe, 'clock', return_value=(9., 'day')):
            data = self.play()._clues(self.store)
        self.assertIn('inventory', data, 'production clues must retain purchase evidence')
        self.assertEqual(data['inventory'], {'TulipSeed': 2})
        self.assertTrue(data['inventory_complete'])
        self.assertEqual(data['money'], 95)
        self.assertEqual(data['region'], 'House')
        self.assertEqual(data['state_provenance']['inventory']['save_count'], 7)
        self.assertEqual(data['state_provenance']['inventory']['source'], 'save')

    def test_late_new_generic_task_refuses_optional_input_until_sleep_subgoal(self):
        self.port.snapshot['hour'] = 20.
        c = self.play().turn('forage', {'job': 'rock'}, store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'space'}},
                             store=self.store, adapter=self.port)
        self.assertEqual(self.port.inputs, [])
        self.assertIsNotNone(c.surprise)

    def test_alias_failure_has_nonzero_exit_without_input(self):
        with self.assertRaises(SystemExit) as raised:
            self.cli(['play', 'sleep', 'answer=accept', 'turn_id=1'])
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(self.port.inputs, [])

    def test_root_shop_completion_and_repeated_purchase_bounds(self):
        from game import experience as X
        self.port.snapshot.update(inventory={'TulipSeed': 0}, money=95)
        c = self.play().turn('shop', {'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20,
            'authorization': {'purchases': [{'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20}]}},
            store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
            X.Evidence(mode='card', state=(('inventory', {'TulipSeed': 2}), ('money', 75))))
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'press', 'label': 'Buy',
            'purchase': {'item': 'TulipSeed', 'quantity': 2, 'price': 20}}}, store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'press', 'label': 'Buy',
            'purchase': {'item': 'TulipSeed', 'quantity': 2, 'price': 20}}}, store=self.store, adapter=self.port)
        self.assertIsNotNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1, 'reserved authorization prevents a repeated purchase')
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'correct', 'correction': {'kind': 'revise_decision'}},
                             store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'complete'}, store=self.store, adapter=self.port)
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(len(self.port.inputs), 1)

    def test_unqualified_unrelated_event_and_unchanged_close_are_surprises(self):
        from game import experience as X
        for action, evidence in [({'kind': 'space'}, X.Evidence(mode='gameplay', events=('talk',))),
                                  ({'kind': 'close'}, X.Evidence(mode='card', texts=('same card',)))]:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.snapshot['screen'] = {'kind': 'card', 'texts': ['same card']}
                self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected, evidence)
                c = self.play().turn('sleep', store=store, adapter=self.port)
                c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': action},
                                     store=store, adapter=self.port)
                self.assertIsNotNone(c.surprise)

    def test_buy_quantity_label_cannot_bypass_authorization(self):
        c = self.play().turn('shop', store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act',
            'action': {'kind': 'press', 'label': 'Buy (1)'}}, store=self.store, adapter=self.port)
        self.assertEqual(self.port.inputs, [])
        self.assertIsNotNone(c.surprise)

    def test_shell_safe_waypoint_answer_uses_the_same_versioned_boundary(self):
        c = self.play().turn('navigate', store=self.store, adapter=self.port)
        try:
            self.play().turn(params={'turn_id': c.turn_id}, answer='walk:F7', store=self.store, adapter=self.port)
        except ValueError as error:
            self.fail(f'shell-safe explicit waypoint decision must parse: {error}')
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(self.port.inputs[0]['kind'], 'waypoint')

    def test_production_clues_expose_named_graph_edges_and_global_interrupts(self):
        from game import observe
        from objects.graph import Graph, Node
        from types import SimpleNamespace
        graph = Graph()
        graph.nodes['House'] = Node('House', 'region', 'House')
        graph.nodes['Bed'] = Node('Bed', 'unique', 'Bed', region='House')
        graph.add_edge('House', 'Bed', 'toward', dir=[-1, 0], source='vision')
        raw = SimpleNamespace(read_save=lambda: ('save.json', {}), today_log=lambda: ([], None),
                              current_scene=lambda: 'House')
        with mock.patch.object(core, 'WF', raw), mock.patch.object(engine, '_open_graph', return_value=graph), \
                mock.patch.object(observe, 'clock', return_value=(20., 'day')):
            data = self.play()._clues(self.store)
        self.assertTrue(any(row.get('edge', {}).get('b') == 'Bed' for row in data['graph_clues']))
        self.assertTrue(any('SLEEP_REQUIRED' in reason for reason in data.get('interrupts', ())))

    def test_shop_does_not_allow_coordinate_purchase_without_authorization(self):
        task = S.TaskState('shop', 'shop', params={})
        self.store.create(task)
        self.port.snapshot['screen'] = {'kind': 'shop', 'texts': ['Buy', 'Tulip Seeds']}
        c = self.play().turn(store=self.store, adapter=self.port)
        c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act',
            'action': {'kind': 'select_card', 'point': [1000, 600]}}, store=self.store, adapter=self.port)
        self.assertEqual(self.port.inputs, [])
        self.assertIsNotNone(c.surprise)


class ReviewRoundOne(PlayCase):
    def real_adapter(self, snapshot, evidence):
        """Keep real prepare and universal guard; fake only observation and physical I/O/capture."""
        adapter = primitives.GameAdapter()
        inputs = []
        mock.patch.object(adapter, 'observe', return_value=snapshot).start()
        mock.patch.object(adapter, 'mark', return_value=0).start()
        mock.patch.object(adapter, 'perform', side_effect=lambda action: inputs.append(action['command'])).start()
        mock.patch.object(adapter, 'capture', side_effect=lambda intent, old, expected:
            primitives.experience(intent, old, expected, evidence, ('after.jpg',))).start()
        return adapter, inputs

    def choose(self, c, adapter, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=self.store, adapter=adapter)

    def test_observed_purchase_surface_protects_coordinates_under_any_declared_goal(self):
        from game import experience as X
        snapshot = dict(self.port.snapshot, screen={'kind': 'card', 'texts': ['Tulip Seeds', 'Buy (1)']})
        adapter, inputs = self.real_adapter(snapshot, X.Evidence(mode='card', texts=('Buy (1)',)))
        action = {'kind': 'select_card', 'point': [1000, 600]}
        self.assertEqual(adapter.prepare(dict(action), snapshot)['command'], 'click:1000:600')
        c = self.play().turn('navigate', store=self.store, adapter=adapter)
        c = self.choose(c, adapter, 'act', action=action)
        self.assertEqual(inputs, [], 'observed Buy surface must gate the coordinate regardless of goal')
        self.assertIsNotNone(c.surprise)

    def test_refill_subgoal_can_navigate_fill_and_resume_its_empty_can_parent(self):
        from game import experience as X
        snapshot = dict(self.port.snapshot, hour=9., can='empty', position=[0., 0.],
                        visible_affordances=[{'kind': 'fill_can', 'point': [1100, 600], 'highlighted': True}])
        adapter, inputs = self.real_adapter(snapshot, X.Evidence(mode='gameplay', moved=True,
                                                                 state=(('position', [3., 0.]),)))
        self.store.create(S.TaskState('garden-root', 'garden', params={'chores': ['water']},
                                      active=S.Interaction('parent-bed', phase='water')))
        c = self.play().turn(store=self.store, adapter=adapter)
        c = self.choose(c, adapter, 'push', action={'goal': 'refill', 'params': {'destination_position': [10., 0.]}})
        c = self.choose(c, adapter, 'act', action={'kind': 'waypoint', 'point': [1100, 600], 'walkable': True})
        self.assertEqual(len(inputs), 1, 'empty can must not block its own resolving navigation')
        self.assertIsNone(c.surprise)
        adapter.capture.side_effect = lambda intent, old, expected: primitives.experience(intent, old, expected,
            X.Evidence(mode='gameplay', events=('fill_watering_can',), state=(('can', 'full'),)))
        c = self.choose(c, adapter, 'act', action={'kind': 'space', 'expects': {'events': ['fill_watering_can']}})
        self.assertEqual(len(inputs), 2)
        c = self.choose(c, adapter, 'complete')
        snapshot['can'] = 'full'
        c = self.choose(c, adapter, 'resume')
        self.assertEqual(c.transaction['transaction_id'], 'parent-bed')
        self.assertEqual(c.transaction['phase'], 'water')

    def test_complete_sparse_inventory_proves_zero_to_positive_purchase(self):
        from game import experience as X
        self.port.snapshot.update(inventory={}, inventory_complete=True, money=95)
        self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected,
            X.Evidence(mode='card', state=(('inventory', {'TulipSeed': 2}), ('inventory_complete', True), ('money', 75))))
        c = self.play().turn('shop', {'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20,
            'authorization': {'purchases': [{'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20}]}},
            store=self.store, adapter=self.port)
        c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
                         'purchase': {'item': 'TulipSeed', 'quantity': 2, 'price': 20}})
        self.assertIsNone(c.surprise, 'complete sparse inventory has known zero count for the absent item')
        c = self.choose(c, self.port, 'complete')
        self.assertEqual(c.task['status'], 'complete')

    def test_incomplete_sparse_inventory_still_cannot_prove_purchase(self):
        from game import experience as X
        self.port.snapshot.update(inventory={}, inventory_complete=False, money=95)
        self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected,
            X.Evidence(mode='card', state=(('inventory', {'TulipSeed': 2}), ('inventory_complete', True), ('money', 75))))
        c = self.play().turn('shop', {'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20,
            'authorization': {'purchases': [{'item': 'TulipSeed', 'quantity': 2, 'max_spend': 20}]}},
            store=self.store, adapter=self.port)
        c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
                         'purchase': {'item': 'TulipSeed', 'quantity': 2, 'price': 20}})
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, self.port, 'complete')
        self.assertEqual(c.task['status'], 'active')

    def test_explicitly_incomplete_inventory_rejects_even_a_named_stock_count(self):
        from game import experience as X
        for before_complete, after_complete in [(False, True), (True, False)]:
            with self.subTest(before=before_complete, after=after_complete), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.snapshot.update(inventory={'SeedA': 0}, inventory_complete=before_complete, money=95)
                self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected,
                    X.Evidence(mode='card', state=(('inventory', {'SeedA': 2}),
                                                 ('inventory_complete', after_complete), ('money', 75))))
                c = self.play().turn('shop', {'item': 'SeedA', 'quantity': 2, 'max_spend': 20,
                    'authorization': {'purchases': [{'item': 'SeedA', 'quantity': 2, 'max_spend': 20}]}},
                    store=self.store, adapter=self.port)
                c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
                    'purchase': {'item': 'SeedA', 'quantity': 2, 'price': 20}})
                self.assertIsNotNone(c.surprise)
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, self.port, 'complete')

    def test_unchanged_matching_region_does_not_make_a_waypoint_progress(self):
        from game import experience as X
        for moved, position in [(False, [0., 0.]), (True, [0., 3.])]:
            with self.subTest(moved=moved), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.snapshot.update(region='House', position=[0., 0.])
                self.port.capture = lambda intent, old, expected: primitives.experience(intent, old, expected,
                    X.Evidence(mode='gameplay', moved=moved, state=(('region', 'House'), ('position', position))))
                c = self.play().turn('navigate', {'destination_position': [10., 0.]},
                                     store=self.store, adapter=self.port)
                c = self.choose(c, self.port, 'act', action={'kind': 'waypoint', 'point': [1100, 600],
                    'walkable': True, 'expects': {'region': 'House'}})
                self.assertIsNotNone(c.surprise)
                count = len(self.port.inputs)
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, self.port, 'act', action={'kind': 'space'})
                self.assertEqual(len(self.port.inputs), count)

    def test_public_legacy_appearance_forms_are_rejected_even_with_provenance(self):
        import numpy as np
        from PIL import Image
        from objects import store as vectors, dino
        from game import badges, experience as X
        frame = os.path.join(self.tmp.name, 'appearance.png')
        Image.new('RGB', (1920, 1080), 'blue').save(frame)
        before = dict(self.port.snapshot, frame_path=frame)
        e = primitives.experience(S.Intent(1, {'kind': 'target', 'point': [1100, 600]}, 0, 1.), before, {}, X.Evidence())
        db = vectors.Store(os.path.join(self.tmp.name, 'db'))
        with mock.patch.object(vectors, 'Store', return_value=db), \
                mock.patch.object(dino, 'mean_vector', return_value=np.array([1., 0.])), \
                mock.patch.object(badges, 'DIR', os.path.join(self.tmp.name, 'badges')):
            for op, values in [('proven_look', {'kind': 'Bed', 'box': [0, 0, 10, 10]}),
                               ('relabel', {'node': 'Bed', 'box': [0, 0, 10, 10]}),
                               ('badge', {'label': 'ready'})]:
                for provenance in ({}, {'frame_path': frame, 'rationale': 'model source', 'evidence_refs': [frame]}):
                    with self.subTest(op=op, provenance=bool(provenance)), self.assertRaises(ValueError):
                        I.correct(e, 'appearance', {'op': op, **values, **provenance})
        self.assertEqual(db.kinds(), [])

    def test_accepted_appearance_sample_preserves_all_provenance_and_replays_once(self):
        import numpy as np
        from PIL import Image
        from objects import store as vectors, dino
        from game import experience as X
        frame = os.path.join(self.tmp.name, 'appearance.png')
        Image.new('RGB', (20, 20), 'blue').save(frame)
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.),
                                 dict(self.port.snapshot, frame_path=frame), {}, X.Evidence())
        db = vectors.Store(os.path.join(self.tmp.name, 'db'))
        data = {'op': 'sample', 'kind': 'Bed', 'box': [0, 0, 10, 10], 'frame_path': frame,
                'rationale': 'named bed source', 'evidence_refs': [frame, e.id]}
        with mock.patch.object(vectors, 'Store', return_value=db), \
                mock.patch.object(dino, 'mean_vector', return_value=np.array([1., 0.])):
            self.assertEqual(I.correct(e, 'appearance', data)['applied'], 1)
            self.assertEqual(I.correct(e, 'appearance', data)['applied'], 0)
        self.assertEqual(len(db.examples('Bed')), 1)
        self.assertEqual(db.examples('Bed')[0].source, {'source': 'vision', 'frame_path': frame,
            'experience': e.id, 'rationale': 'named bed source', 'evidence_refs': [frame, e.id]})


class TradeReview(PlayCase):
    real_adapter = ReviewRoundOne.real_adapter
    choose = ReviewRoundOne.choose

    def test_observed_sale_surface_blocks_coordinates_without_sale_authority_under_other_goal(self):
        from game import experience as X
        snapshot = dict(self.port.snapshot, screen={'kind': 'card', 'texts': ['Grown crop', 'Sell 2']})
        adapter, inputs = self.real_adapter(snapshot, X.Evidence(mode='card', texts=('Sell 2',)))
        action = {'kind': 'select_card', 'point': [1000, 600]}
        self.assertEqual(adapter.prepare(dict(action), snapshot)['command'], 'click:1000:600')
        c = self.play().turn('navigate', store=self.store, adapter=adapter)
        c = self.choose(c, adapter, 'act', action=action)
        self.assertEqual(inputs, [])
        self.assertIsNotNone(c.surprise)

    def trade_outcome(self, item, quantity, price, selling=False):
        from game import experience as X
        old_money = self.port.snapshot['money']
        old_quantity = self.port.snapshot['inventory'].get(item, 0)
        new_quantity = old_quantity + (-quantity if selling else quantity)
        inventory = dict(self.port.snapshot['inventory'])
        if new_quantity:
            inventory[item] = new_quantity
        else:
            inventory.pop(item, None)
        after = {'inventory': inventory, 'inventory_complete': True,
                 'money': old_money + (price if selling else -price)}
        def capture(intent, before, expected):
            self.port.snapshot = dict(self.port.snapshot, **after)
            return primitives.experience(intent, before, expected,
                X.Evidence(mode='card', state=tuple(after.items())))
        self.port.capture = capture

    def test_sale_is_bounded_reserved_and_verified_with_opposite_signed_sparse_deltas(self):
        self.port.snapshot.update(inventory={'GrownA': 3}, inventory_complete=True, money=5)
        c = self.play().turn('shop', {'trade': 'sell', 'item': 'GrownA', 'quantity': 3,
            'authorization': {'sales': [{'item': 'GrownA', 'quantity': 3}]}}, store=self.store, adapter=self.port)
        self.trade_outcome('GrownA', 3, 12, selling=True)
        action = {'kind': 'press', 'label': 'Sell 3', 'sale': {'item': 'GrownA', 'quantity': 3, 'price': 12}}
        c = self.choose(c, self.port, 'act', action=action)
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)
        self.port.snapshot = dict(self.port.snapshot, inventory={'GrownA': 3}, money=5)  # stale save
        c = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        c = self.choose(c, self.port, 'act', action=action)
        self.assertEqual(len(self.port.inputs), 1, 'sale quantity reservation must survive the next turn')
        self.assertIsNotNone(c.surprise)
        c = self.choose(c, self.port, 'correct', correction={'kind': 'revise_decision'})
        c = self.choose(c, self.port, 'complete')
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(len(self.store.load().params['_sale_intents']), 1)

    def test_sale_missing_wrong_item_and_excess_quantity_authorization_issue_no_input(self):
        for auth, sale in [({}, {'item': 'GrownA', 'quantity': 2, 'price': 12}),
                           ({'sales': [{'item': 'Other', 'quantity': 2}]},
                            {'item': 'GrownA', 'quantity': 2, 'price': 12}),
                           ({'sales': [{'item': 'GrownA', 'quantity': 1}]},
                            {'item': 'GrownA', 'quantity': 2, 'price': 12})]:
            with self.subTest(auth=auth), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.play().turn('shop', {'trade': 'sell', 'item': 'GrownA', 'quantity': 2,
                    'authorization': auth}, store=self.store, adapter=self.port)
                c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Sell 2', 'sale': sale})
                self.assertEqual(self.port.inputs, [])
                self.assertIsNotNone(c.surprise)

    def test_wrong_signed_sale_deltas_cannot_complete(self):
        from game import experience as X
        self.port.snapshot.update(inventory={'GrownA': 2}, inventory_complete=True, money=20)
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(mode='gameplay', state=(('inventory', {}), ('inventory_complete', True), ('money', 8))))
        c = self.play().turn('shop', {'trade': 'sell', 'item': 'GrownA', 'quantity': 2,
            'authorization': {'sales': [{'item': 'GrownA', 'quantity': 2}]}}, store=self.store, adapter=self.port)
        c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Sell 2',
            'sale': {'item': 'GrownA', 'quantity': 2, 'price': 12}})
        self.assertIsNotNone(c.surprise)
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, self.port, 'complete')

    def catalogue(self, *items):
        return [{'item': item, 'category': 'seed', 'available': True, 'frame_path': 'full.jpg',
                 'evidence_refs': ['full.jpg']} for item in items]

    def test_sale_then_exact_quantity_per_discovered_available_type_completes_only_after_all_trades(self):
        self.port.snapshot.update(inventory={'GrownA': 2, 'HiveProduct': 3}, inventory_complete=True, money=20)
        authorization = {'sales': [{'item': 'GrownA', 'quantity': 2}, {'item': 'HiveProduct', 'quantity': 3}],
                         'purchases': [{'category': 'seed', 'quantity_per_type': 10, 'max_spend': 100}]}
        c = self.play().turn('shop', {'authorization': authorization}, store=self.store, adapter=self.port)
        for item, quantity, price in [('GrownA', 2, 12), ('HiveProduct', 3, 15)]:
            c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
                {'trade': 'sell', 'item': item, 'quantity': quantity}})
            self.trade_outcome(item, quantity, price, selling=True)
            c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Sell',
                'sale': {'item': item, 'quantity': quantity, 'price': price}})
            self.assertIsNone(c.surprise)
            c = self.choose(c, self.port, 'complete')
            c = self.choose(c, self.port, 'resume')
        for item in ('SeedA', 'SeedB'):
            c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
                {'item': item, 'quantity': 10, 'max_spend': 20, 'catalogue': self.catalogue('SeedA', 'SeedB'),
                 'catalogue_complete': True}})
            self.trade_outcome(item, 10, 20)
            c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
                'purchase': {'item': item, 'quantity': 10, 'price': 20}})
            self.assertIsNone(c.surprise)
            c = self.choose(c, self.port, 'complete')
            self.assertEqual(c.task['stack'][-1]['result']['acquired'], 10)
            c = self.choose(c, self.port, 'resume')
            if item == 'SeedA':
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, self.port, 'complete')
        c = self.choose(c, self.port, 'complete')
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(self.port.snapshot['inventory'], {'SeedA': 10, 'SeedB': 10})
        self.assertEqual(self.port.snapshot['money'], 7)
        self.assertEqual(len(self.port.inputs), 4)

    def test_catalogue_purchase_rejects_unavailable_wrong_category_and_excess_per_type(self):
        for change, quantity in [({'available': False}, 10), ({'category': 'food'}, 10), ({}, 11)]:
            with self.subTest(change=change, quantity=quantity), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                catalogue = self.catalogue('SeedA')
                catalogue[0].update(change)
                c = self.play().turn('shop', {'authorization': {'purchases':
                    [{'category': 'seed', 'quantity_per_type': 10, 'max_spend': 100}]}},
                    store=self.store, adapter=self.port)
                c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
                    {'item': 'SeedA', 'quantity': quantity, 'max_spend': 20, 'catalogue': catalogue}})
                c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
                    'purchase': {'item': 'SeedA', 'quantity': quantity, 'price': 20}})
                self.assertEqual(self.port.inputs, [])
                self.assertIsNotNone(c.surprise)

    def test_catalogue_discovery_requires_its_captured_source_frame(self):
        c = self.play().turn('shop', {'authorization': {'purchases':
            [{'category': 'seed', 'quantity_per_type': 10, 'max_spend': 100}]}},
            store=self.store, adapter=self.port)
        catalogue = self.catalogue('SeedA')
        catalogue[0]['frame_path'] = 'invented.jpg'
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
                {'item': 'SeedA', 'quantity': 10, 'max_spend': 20, 'catalogue': catalogue}})
        self.assertEqual(list(self.store.load().stack), [])


    def test_ambiguous_observed_trade_coordinates_require_named_financial_control(self):
        from game import experience as X
        snapshot = dict(self.port.snapshot, screen={'kind': 'card', 'texts': ['Buy', 'Sell']},
                        inventory={'SeedA': 1}, inventory_complete=True, money=20)
        adapter, inputs = self.real_adapter(snapshot, X.Evidence(mode='card'))
        c = self.play().turn('shop', {'item': 'SeedA', 'quantity': 1, 'max_spend': 10,
            'authorization': {'purchases': [{'item': 'SeedA', 'quantity': 1, 'max_spend': 10}]}},
            store=self.store, adapter=adapter)
        c = self.choose(c, adapter, 'act', action={'kind': 'select_card', 'point': [1000, 600],
            'purchase': {'item': 'SeedA', 'quantity': 1, 'price': 10}})
        self.assertEqual(inputs, [], 'coordinate metadata cannot resolve a Buy/Sell control ambiguity')
        self.assertIsNotNone(c.surprise)


    def test_available_money_budget_uses_captured_funds_and_verified_sales_not_a_later_stale_balance(self):
        self.port.snapshot.update(inventory={'GrownA': 3}, inventory_complete=True, money=5)
        authorization = {'sales': [{'item': 'GrownA', 'quantity': 3}],
                         'purchases': [{'item': 'SeedA', 'quantity': 2, 'max_spend': 'available_money'}]}
        c = self.play().turn('shop', {'authorization': authorization}, store=self.store, adapter=self.port)
        c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
            {'trade': 'sell', 'item': 'GrownA', 'quantity': 3}})
        self.trade_outcome('GrownA', 3, 12, selling=True)
        c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Sell',
            'sale': {'item': 'GrownA', 'quantity': 3, 'price': 12}})
        c = self.choose(c, self.port, 'complete')
        c = self.choose(c, self.port, 'resume')
        c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
            {'item': 'SeedA', 'quantity': 2, 'max_spend': 20}})
        self.port.snapshot = dict(self.port.snapshot, money=999)  # cannot inflate the authorized budget
        try:
            c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
                'purchase': {'item': 'SeedA', 'quantity': 2, 'price': 18}})
        except TypeError as error:
            self.fail(f'available_money must be an explicit bounded authorization mode: {error}')
        self.assertEqual(len(self.port.inputs), 1)
        self.assertIsNotNone(c.surprise)
        c = self.choose(c, self.port, 'correct', correction={'kind': 'revise_decision'})
        self.port.snapshot = dict(self.port.snapshot, money=17)
        self.trade_outcome('SeedA', 2, 17)
        c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
            'purchase': {'item': 'SeedA', 'quantity': 2, 'price': 17}})
        self.assertIsNone(c.surprise)
        c = self.choose(c, self.port, 'complete')
        c = self.choose(c, self.port, 'resume')
        c = self.choose(c, self.port, 'complete')
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(self.port.snapshot['money'], 0)
        self.assertEqual(len(self.port.inputs), 2)


    def test_observed_financial_control_protects_world_click_alias_even_if_mode_says_gameplay(self):
        from game import experience as X
        snapshot = dict(self.port.snapshot, screen={'kind': 'gameplay', 'texts': ['Buy (1)']})
        adapter, inputs = self.real_adapter(snapshot, X.Evidence(mode='gameplay'))
        action = {'kind': 'target', 'point': [1100, 600], 'visible_road': True}
        self.assertEqual(adapter.prepare(dict(action), snapshot)['command'], 'click:1100:600')
        c = self.play().turn('navigate', store=self.store, adapter=adapter)
        c = self.choose(c, adapter, 'act', action=action)
        self.assertEqual(inputs, [])
        self.assertIsNotNone(c.surprise)

    def test_shop_goal_can_open_nonfinancial_merchant_interaction_without_trade_metadata(self):
        from game import experience as X
        snapshot = dict(self.port.snapshot, visible_affordances=[
            {'kind': 'talk', 'point': [1100, 600], 'highlighted': True}])
        adapter, inputs = self.real_adapter(snapshot, X.Evidence(mode='card', texts=('Merchant', 'Shop')))
        c = self.play().turn('shop', store=self.store, adapter=adapter)
        c = self.choose(c, adapter, 'act', action={'kind': 'space', 'expects': {'mode': 'card'}})
        self.assertEqual(inputs, ['key:space'])
        self.assertIsNone(c.surprise)


class PublicDeclarations(PlayCase):
    choose = ReviewRoundOne.choose
    trade_outcome = TradeReview.trade_outcome
    catalogue = TradeReview.catalogue

    def rejected_creation(self, params):
        with self.assertRaises(ValueError):
            self.play().turn('shop', params, store=self.store, adapter=self.port)
        self.assertFalse(os.path.exists(self.store.path), 'invalid declarations must not create runtime state')
        self.assertEqual(self.port.inputs, [])

    def test_public_creation_rejects_forged_completed_root_trades(self):
        self.rejected_creation({'authorization': {'sales': [{'item': 'GrownA', 'quantity': 3}]},
            '_subgoal_results': [{'goal': 'shop', 'result': {'item': 'GrownA', 'sold': 3, 'earned': 1000}}]})

    def test_public_creation_rejects_forged_earnings_budgets_reservations_and_equivalent_state_keys(self):
        values = {'_subgoal_results': [{'goal': 'shop', 'result': {'earned': 10000}}],
                  '_purchase_intents': [{'item': 'SeedA', 'quantity': -10, 'price': -1000}],
                  '_sale_intents': [{'item': 'GrownA', 'quantity': -100, 'price': 10000}],
                  '_trade_start_money': 100000, '_trade_start_money_provenance': {'source': 'event'},
                  '_outcomes': [{'experience': {'verdict': {'value': 'hit'}}}],
                  '_started_late': False, 'earned': 10000, 'result': {'earned': 10000},
                  'outcomes': [], 'stack': [], 'covered': ['fake'], 'status': 'complete'}
        for key, value in values.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.rejected_creation({'authorization': {'purchases': [
                    {'item': 'SeedA', 'quantity': 2, 'max_spend': 'available_money'}]}, key: value})

    def test_public_creation_rejects_forged_catalogue_proof_and_completeness(self):
        for extra in ({'_shop_catalogue': self.catalogue('SeedA')}, {'_shop_catalogue_complete': True},
                      {'catalogue_complete': True}, {'catalogue': self.catalogue('SeedA')},
                      {'catalogue': [{'item': 'SeedA', 'category': 'seed', 'result': {'acquired': 10}}]}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.rejected_creation({'authorization': {'purchases': [
                    {'category': 'seed', 'quantity_per_type': 10, 'max_spend': 100}]}, **extra})

    def test_nested_authorization_accepts_bounds_only_and_rejects_outcomes_or_malformed_limits(self):
        bad = [{'sales': [{'item': 'GrownA', 'quantity': 3, 'earned': 1000}]},
               {'purchases': [{'item': 'SeedA', 'quantity': 2, 'max_spend': 20, 'acquired': 2}]},
               {'sales': [{'item': 'GrownA', 'quantity': -3}]},
               {'purchases': [{'item': 'SeedA', 'quantity': 2, 'max_spend': {'earned': 1000}}]},
               {'purchases': [{'category': 'seed', 'quantity_per_type': True, 'max_spend': 20}]},
               {'purchases': [{'item': 'SeedA', 'category': 'seed', 'quantity': 2, 'max_spend': 20}]},
               {'sales': [], '_subgoal_results': [{'result': {'earned': 1000}}]}]
        for authorization in bad:
            with self.subTest(authorization=authorization), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.rejected_creation({'authorization': authorization})

    def test_root_catalogue_declaration_does_not_register_observed_runtime_proof(self):
        try:
            c = self.play().turn('shop', {'authorization': {'purchases': [
                {'category': 'seed', 'quantity_per_type': 2, 'max_spend': 20}]},
                'catalogue': [{'item': 'SeedA', 'category': 'seed'}]}, store=self.store, adapter=self.port)
        except ValueError as error:
            self.fail(f'a requested catalogue type is a declaration, not a captured observation: {error}')
        self.assertNotIn('_shop_catalogue', c.task['params'])
        self.assertNotIn('_shop_catalogue_complete', c.task['params'])
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, self.port, 'complete')

    def test_subgoal_declarations_reject_runtime_results_authority_and_catalogue_outcomes(self):
        c = self.play().turn('shop', store=self.store, adapter=self.port)
        for extra in ({'_subgoal_results': [{'result': {'earned': 1000}}]},
                      {'authorization': {'sales': [{'item': 'Other', 'quantity': 100}]}},
                      {'catalogue': [{**self.catalogue('SeedA')[0], 'earned': 1000}]}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.choose(c, self.port, 'push', action={'goal': 'shop', 'params': extra})
        self.assertEqual(self.store.load().stack, [])

    def test_public_cli_rejects_forged_accounting_before_creating_a_task(self):
        with self.assertRaises(SystemExit) as raised:
            self.cli(['play', 'shop', 'authorization={"sales":[{"item":"GrownA","quantity":3}]}',
                      '_subgoal_results=[{"goal":"shop","result":{"item":"GrownA","sold":3,"earned":1000}}]'])
        self.assertEqual(raised.exception.code, 1)
        self.assertFalse(os.path.exists(self.store.path))
        self.assertEqual(self.port.inputs, [])

    def test_persisted_restart_retains_real_trade_results_budget_catalogue_and_reservations(self):
        self.port.snapshot.update(inventory={'GrownA': 3}, inventory_complete=True, money=5)
        c = self.play().turn('shop', {'authorization': {
            'sales': [{'item': 'GrownA', 'quantity': 3}],
            'purchases': [{'category': 'seed', 'quantity_per_type': 2, 'max_spend': 'available_money'}]}},
            store=self.store, adapter=self.port)
        c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
            {'trade': 'sell', 'item': 'GrownA', 'quantity': 3}})
        self.trade_outcome('GrownA', 3, 12, selling=True)
        c = self.choose(c, self.port, 'act', action={'kind': 'press', 'label': 'Sell',
            'sale': {'item': 'GrownA', 'quantity': 3, 'price': 12}})
        c = self.choose(c, self.port, 'complete')
        c = self.choose(c, self.port, 'resume')
        c = self.choose(c, self.port, 'push', action={'goal': 'shop', 'params':
            {'item': 'SeedA', 'quantity': 2, 'max_spend': 17, 'catalogue': self.catalogue('SeedA'),
             'catalogue_complete': True}})
        before = self.store.load().to_dict()
        restarted = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        for key in ('_subgoal_results', '_sale_intents', '_trade_start_money', '_shop_catalogue',
                    '_shop_catalogue_complete'):
            self.assertEqual(restarted.task['params'][key], S.freeze(before['params'][key]))
        self.assertEqual(restarted.turn_id, c.turn_id)
        self.trade_outcome('SeedA', 2, 17)
        c = self.choose(restarted, self.port, 'act', action={'kind': 'press', 'label': 'Buy',
            'purchase': {'item': 'SeedA', 'quantity': 2, 'price': 17}})
        c = self.choose(c, self.port, 'complete')
        c = self.choose(c, self.port, 'resume')
        restarted = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertEqual(restarted.task['params']['_purchase_intents'][0]['price'], 17)
        c = self.choose(restarted, self.port, 'complete')
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(len(self.port.inputs), 2)


if __name__ == '__main__':
    unittest.main()
