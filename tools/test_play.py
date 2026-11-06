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


if __name__ == '__main__':
    unittest.main()
