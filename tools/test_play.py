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

    def write_inline_history_log(self, task, append=False, store=None):
        data = S.thaw(task)
        rows = list(data.get('params', {}).get('_outcomes', ()))
        rows.extend(row for child in data.get('stack', ()) for row in child.get('result', {}).get('outcomes', ()))
        rows.extend(row for child in data.get('params', {}).get('_subgoal_results', ())
                    for row in child.get('result', {}).get('outcomes', ()))
        rows.extend(row for cancelled in data.get('params', {}).get('_cancelled_subgoals', ())
                    for row in cancelled.get('subgoal', {}).get('result', {}).get('outcomes', ()))
        existing = set()
        path = os.path.join(os.path.dirname((store or self.store).path), 'log.jsonl')
        if append and os.path.exists(path):
            with open(path) as stream:
                for line in stream:
                    saved = json.loads(line)
                    if saved.get('phase') == 'outcome':
                        existing.add(saved.get('experience', {}).get('id'))
        with open(path, 'a' if append else 'w') as stream:
            for row in rows:
                if row['experience']['id'] in existing:
                    continue
                turn_id = row['experience']['artifacts']['turn_id']
                stream.write(json.dumps({'type': 'turn', 'task_id': data['task_id'], 'turn_id': turn_id,
                    'phase': 'intent', 'intent': {'turn_id': turn_id, 'action': row['action'],
                    'before': row['before'], 'expects': row.get('expects', {})}}) + '\n')
                stream.write(json.dumps({'type': 'turn', 'task_id': data['task_id'], 'turn_id': turn_id,
                    'phase': 'outcome', 'experience': row['experience']}) + '\n')

    def create_legacy_task(self, task):
        """Captured legacy fixtures need their canonical journal beside task.json before migration."""
        self.write_inline_history_log(task, store=self.store)
        return self.store.create(task)

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

    def test_house_vector_scope_includes_the_learned_exit_and_bed(self):
        from objects.graph import Graph, Node
        graph = Graph()
        graph.nodes['Farm'] = Node('Farm', 'region')
        graph.nodes['House'] = Node('House', 'region', region='Farm')
        graph.nodes['Bed'] = Node('Bed', 'unique', region='House')
        graph.nodes['HouseExit'] = Node('HouseExit', 'unique', region='House')
        graph.nodes['Garden'] = Node('Garden', 'region', region='Farm')
        scope = self.play()._vector_scope(graph, 'House', learned_kinds={'Bed', 'HouseExit'})
        self.assertEqual(scope['region'], 'House')
        self.assertEqual(scope['kinds'], ['Bed', 'HouseExit'])

    def test_new_task_reuses_its_vector_observation_in_the_first_next(self):
        observed = mock.Mock(wraps=self.port.observe)
        self.port.observe = observed
        context = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        self.assertEqual(context.turn_id, 1)
        observed.assert_called_once_with()

    def test_production_clues_project_only_current_region_not_the_full_nested_graph(self):
        from objects.graph import Graph, Node
        from types import SimpleNamespace
        from game import engine
        graph = Graph()
        graph.nodes['Farm'] = Node('Farm', 'region')
        graph.nodes['Garden'] = Node('Garden', 'region', region='Farm')
        graph.nodes['HouseDoor'] = Node('HouseDoor', 'unique', region='Farm')
        for n in range(500):
            graph.nodes[f'bed-{n}'] = Node(f'bed-{n}', 'member', 'GardenBed', region='Garden')
        save = {'saveCount': 1, 'currentScene': 'Farm', 'gameState': {'player': {'inventory': {'items': []}}}}
        raw = SimpleNamespace(read_save=lambda: ('source.save', save), today_log=lambda: ([], None))
        with mock.patch.object(core, 'WF', raw), mock.patch.object(engine, '_open_graph', return_value=graph):
            clues = self.play()._clues(self.store, {'hour': 10, 'light': 'day'})
        nodes = [row['node'] for row in clues['graph_clues'] if row.get('node')]
        self.assertTrue({'Farm', 'Garden', 'HouseDoor'} <= set(nodes))
        self.assertFalse(any(node.startswith('bed-') for node in nodes))
        self.assertLess(len(nodes), 10)
        self.assertLess(len(json.dumps(clues['graph_clues'])), 5000)


class CompactHistory(PlayCase):
    def outcome(self, experience_id, turn_id):
        experience = {
            'id': experience_id,
            'artifacts': {'turn_id': turn_id},
            'action': {'kind': 'read'},
            'before': {'mode': 'gameplay'},
            'prediction': {},
            'evidence': {'events': [], 'state': []},
            'verdict': {'value': 'unknown', 'checks': []},
        }
        return {'experience': experience,
                'before': {'screen': {'kind': 'gameplay'}, 'frame_path': f'{experience_id}-before.jpg'},
                'action': {'kind': 'read'}, 'expects': {}}

    def write_log(self, task_id, rows):
        with open(os.path.join(self.tmp.name, 'log.jsonl'), 'w') as stream:
            for row in rows:
                turn_id = row['experience']['artifacts']['turn_id']
                stream.write(json.dumps({'type': 'turn', 'task_id': task_id, 'turn_id': turn_id,
                    'phase': 'intent', 'intent': {'turn_id': turn_id, 'action': row['action'],
                    'before': row['before'], 'expects': row['expects']}}) + '\n')
                stream.write(json.dumps({'type': 'turn', 'task_id': task_id, 'turn_id': turn_id,
                    'phase': 'outcome', 'experience': row['experience']}) + '\n')

    def test_legacy_inline_history_migrates_to_exact_journal_refs_and_bounded_public_state(self):
        self.assertTrue(hasattr(self.store, 'compact'), 'TaskStore lacks the explicit atomic history migration')
        root, child, done = (self.outcome('root-e', 1), self.outcome('child-e', 2), self.outcome('done-e', 3))
        task = S.TaskState('compact-root', 'garden', history_schema=1, params={
            '_outcomes': [root],
            '_subgoal_results': [{'goal': 'sleep', 'params': {}, 'evidence_refs': ['done-e'],
                                  'result': {'outcomes': [done], 'slept': True}}]},
            stack=[S.Subgoal('shop', evidence_refs=['child-e'], result={'outcomes': [child]})])
        task.current_turn = {'turn_id': 4, 'task': task.to_dict(), 'screen': {'kind': 'gameplay'}}
        self.store.create(task)
        self.write_log(task.task_id, [root, child, done])

        self.assertTrue(self.store.compact())
        migrated = self.store.load()
        self.assertEqual(migrated.history_schema, 2)
        self.assertEqual(migrated.evidence_refs, ['root-e'])
        self.assertNotIn('_outcomes', migrated.params)
        self.assertNotIn('outcomes', migrated.stack[0].result)
        self.assertNotIn('outcomes', migrated.params['_subgoal_results'][0]['result'])

        from game import history
        records = history.records(os.path.join(self.tmp.name, 'log.jsonl'), ['done-e', 'root-e'])
        self.assertEqual([row['experience']['id'] for row in records], ['done-e', 'root-e'])
        self.assertEqual(records[0], done)
        public = history.public_task(migrated)
        self.assertNotIn('current_turn', public)
        self.assertNotIn('last_experience', public)
        self.assertLess(len(json.dumps(public)), 5000)

    def test_compaction_refuses_missing_canonical_evidence_without_changing_task(self):
        row = self.outcome('missing-e', 9)
        task = S.TaskState('fail-closed', 'sleep', history_schema=1, params={'_outcomes': [row]})
        self.store.create(task)
        with open(self.store.path, 'rb') as stream:
            before = stream.read()
        with open(os.path.join(self.tmp.name, 'log.jsonl'), 'w') as stream:
            stream.write('')
        with self.assertRaisesRegex(ValueError, 'lacks experiences: missing-e'):
            self.store.compact()
        with open(self.store.path, 'rb') as stream:
            self.assertEqual(stream.read(), before)

    def test_compact_subgoal_completes_after_restart_from_canonical_records(self):
        from game import experience as X
        play = self.play()
        c = play.turn('garden', {'region': 'Garden'}, store=self.store, adapter=self.port)
        c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'push',
                              'action': {'goal': 'sleep', 'params': {}}},
                      store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(events=('sleep_transition',), mode='gameplay'))
        c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {
            'kind': 'press', 'label': 'Sleep', 'expects': {'events': ['sleep_transition']}}},
            store=self.store, adapter=self.port)
        persisted = self.store.load()
        self.assertNotIn('outcomes', persisted.stack[-1].result,
                         'task state embedded the complete outcome instead of its canonical journal reference')
        self.assertEqual(len(persisted.stack[-1].evidence_refs), 1)

        c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'complete'},
                      store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertTrue(c.task['stack'][-1]['result']['slept'])


class CapturedAcceptance(PlayCase):
    """Live obligations fail explicitly until their source evidence is captured; no invented receipts."""
    def fixture(self, name):
        path = os.path.join(os.path.dirname(__file__), 'fixtures', 'play', name + '.json')
        self.assertTrue(os.path.exists(path), f'captured fixture missing: {name}')
        with open(path) as stream:
            return json.load(stream)

    def completed(self, name, section):
        fixture = self.fixture(name)
        capture = fixture[section]
        self.assertEqual(capture['status'], 'captured', capture['missing'])
        self.assertTrue(capture['turns'], 'a no-work replay cannot prove live acceptance')
        return fixture, capture

    def test_enter_house_wrong_bed_route_requires_vision_then_graph_or_vector_correction(self):
        # Removing outcome comparison would accept this captured no-move and allow another guessed click.
        fixture = self.fixture('enter-house-sleep')
        from game import learn
        from objects.graph import Graph
        graph = Graph()
        path = os.path.join(self.tmp.name, 'captured-graph.json')
        with open(path, 'w') as stream:
            json.dump(fixture['failure']['graph'], stream)
        graph.load(path)
        self.port.prepare = primitives.GameAdapter().prepare
        old = fixture['failure']['wrong_bed_experiences'][0]
        from game import experience as X, screen
        self.port.snapshot.update(screen={'kind': screen.classify(old['evidence']['mode'], old['evidence']['texts']),
                                         'texts': old['evidence']['texts']},
                                  frame_path=fixture['failure']['preserved_frame']['path'])
        def capture(intent, before, expects):
            return primitives.experience(intent, before, expects, X.Evidence(**old['evidence']),
                                         (fixture['failure']['preserved_frame']['path'],))
        self.port.capture = capture
        with mock.patch.dict(learn.MEMORY, graph=graph), \
                mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')):
            c = self.play().turn('sleep', store=self.store, adapter=self.port)
            c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action':
                 {'kind': 'waypoint', 'point': old['action']['pt'], 'walkable': True}},
                 store=self.store, adapter=self.port)
            self.assertIsNotNone(c.surprise)
            self.assertEqual(c.surprise.reason, 'no_progress')
            self.assertEqual(len(self.port.inputs), 1)
            with self.assertRaises(turn.DecisionRejected):
                self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'space'}},
                                 store=self.store, adapter=self.port)
            c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'look'},
                                 store=self.store, adapter=self.port)
            # This is a failure replay: record the missing clue as a gap, never fabricate a west-bed mapping.
            c = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'correct', 'correction':
                 {'kind': 'gap', 'data': {'invariant': 'Bed graph/vector clue absent; model vision required',
                                        'owner': 'navigation'}}}, store=self.store, adapter=self.port)
            self.assertIsNone(c.surprise)
            self.assertEqual(len(self.port.inputs), 1)
            self.assertEqual(len(I.gaps()), 1)
            with open(os.path.join(self.tmp.name, 'log.jsonl')) as stream:
                timeline = [json.loads(line) for line in stream]
            self.assertEqual(sum(row['phase'] == 'vision' for row in timeline), 1)

    def test_sleep_replay_reaches_west_bed_and_proves_sleep_transition(self):
        self.completed('enter-house-sleep', 'success')

    def test_sell_tulip_honey_and_buy_ten_each_available_seed_verifies_signed_inventory_and_money(self):
        self.completed('sell-grown-buy-seeds', 'success')

    def test_garden_shop_return_reopens_constrained_beds_without_false_completion(self):
        self.completed('garden-shop-return', 'success')



class ApiGapRepairs(PlayCase):
    """Public-turn regressions for catalogue discovery, named inspection and nested arrival."""
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        self.graph = Graph()
        mock.patch.dict(learn.MEMORY, graph=self.graph).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()

    def choose(self, c, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def catalogue(self, item='SeedA'):
        return {'item': item, 'category': 'seed', 'available': True,
                'frame_path': 'full.jpg', 'evidence_refs': ['full.jpg']}

    def start(self, money=5):
        self.port.snapshot.update(money=money, inventory={'GrownA': 1}, inventory_complete=True)
        return self.play().turn('garden', {'authorization': {
            'sales': [{'item': 'GrownA', 'quantity': 1}],
            'purchases': [{'category': 'seed', 'quantity_per_type': 2, 'max_spend': 'available_money'}]}},
            store=self.store, adapter=self.port)

    def test_cli_catalogue_registration_is_versioned_durable_and_does_not_push_a_child(self):
        root = json.loads(self.cli(['play', 'shop']).split('NEXT ', 1)[1])
        decision = json.dumps({'kind': 'catalogue', 'action': {
            'catalogue': [self.catalogue()], 'catalogue_complete': True}})
        try:
            result = self.cli(['play', f'turn_id={root["turn_id"]}', 'answer=' + decision])
        except (SystemExit, ValueError) as error:
            self.fail(f'catalogue page registration must be an input-free public turn: {error}')
        c = json.loads(result.split('NEXT ', 1)[1])
        persisted = json.loads(self.cli(['play']).split('NEXT ', 1)[1])
        self.assertEqual(c['task']['stack'], [])
        self.assertEqual(persisted['task']['params']['_shop_catalogue'], [self.catalogue()])
        self.assertTrue(persisted['task']['params']['_shop_catalogue_complete'])
        self.assertGreater(c['turn_id'], root['turn_id'])
        self.assertEqual(self.port.inputs, [])
        with self.assertRaises(SystemExit):
            self.cli(['play', f'turn_id={root["turn_id"]}', 'answer=' + decision])

    def test_catalogue_rejects_uncaptured_frame_without_changing_task_or_stack(self):
        c = self.start()
        entry = dict(self.catalogue(), frame_path='invented.jpg', evidence_refs=['invented.jpg'])
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'catalogue', action={'catalogue': [entry]})
        self.assertNotIn('_shop_catalogue', self.store.load().params)
        self.assertEqual(self.store.load().stack, [])
        self.assertEqual(self.port.inputs, [])

    def test_item_children_bind_registered_entry_and_remaining_verified_numeric_budget(self):
        c = self.start()
        try:
            c = self.choose(c, 'catalogue', action={'catalogue': [self.catalogue(), self.catalogue('SeedB')],
                                                   'catalogue_complete': True})
        except turn.DecisionRejected as error:
            self.fail(f'catalogue registration must not require a shop child: {error}')
        c = self.choose(c, 'push', action={'goal': 'shop', 'params':
            {'trade': 'sell', 'item': 'GrownA', 'quantity': 1}})
        TradeReview.trade_outcome(self, 'GrownA', 1, 7, selling=True)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Sell',
                                         'sale': {'item': 'GrownA', 'quantity': 1, 'price': 7}})
        c = self.choose(self.choose(c, 'complete'), 'resume')
        self.port.snapshot['money'] = 999  # stale/high readings cannot grant authority
        c = self.choose(c, 'push', action={'goal': 'shop', 'params': {'item': 'SeedA', 'quantity': 2}})
        child = self.store.load().stack[-1]
        self.assertEqual(child.params['catalogue'], [self.catalogue()])
        self.assertEqual(child.params['max_spend'], 12)
        self.port.snapshot['money'] = 12
        TradeReview.trade_outcome(self, 'SeedA', 2, 4)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Buy',
                                         'purchase': {'item': 'SeedA', 'quantity': 2, 'price': 4}})
        self.assertIsNone(c.surprise)
        c = self.choose(self.choose(c, 'complete'), 'resume')
        c = self.choose(c, 'push', action={'goal': 'shop', 'params': {'item': 'SeedB', 'quantity': 2}})
        self.assertEqual(self.store.load().stack[-1].params['max_spend'], 8)
        self.assertEqual(len(self.port.inputs), 2)

    def test_named_shop_item_inspection_resolves_its_label_not_an_untrusted_point(self):
        from game import experience as X
        from types import SimpleNamespace
        snapshot = dict(self.port.snapshot, screen={'kind': 'shop', 'texts': ['Buy', 'Sell', 'Seed A']})
        adapter, inputs = ReviewRoundOne.real_adapter(self, snapshot, X.Evidence(mode='card', texts=('Seed A details',)))
        mock.patch.object(core, 'WF', SimpleNamespace(find_text=lambda label, exact:
                          [{'cx': 220, 'cy': 420}] if label == 'Seed A' and exact else [])).start()
        c = self.play().turn('shop', store=self.store, adapter=adapter)
        c = ReviewRoundOne.choose(self, c, adapter, 'act', action={
            'kind': 'select_card', 'label': 'Seed A', 'point': [1000, 600]})
        self.assertEqual(inputs, ['click:220:420'])
        self.assertIsNone(c.surprise)
        self.assertNotIn('_purchase_intents', self.store.load().params)
        c = ReviewRoundOne.choose(self, c, adapter, 'act', action={'kind': 'select_card', 'label': 'Buy'})
        self.assertEqual(inputs, ['click:220:420'])
        self.assertIsNotNone(c.surprise, 'named inspection must not bypass the financial-control guard')

    def nested_graph(self):
        from objects.graph import Node
        self.graph.nodes['World'] = Node('World', 'region')
        self.graph.nodes['Outer'] = Node('Outer', 'region', region='World')
        self.graph.nodes['ArbitraryInner'] = Node('ArbitraryInner', 'region', region='Outer')
        self.graph.nodes['FixtureObject#1,2'] = Node('FixtureObject#1,2', 'member', 'FixtureObject',
                                                    region='ArbitraryInner', pos=[1., 2.], scene='World')

    def test_nested_region_arrival_uses_fresh_positioned_object_graph_ancestry(self):
        from game import experience as X
        self.nested_graph()
        self.port.snapshot['region'] = 'World'
        c = self.start()
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'ArbitraryInner'}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(lines=('> inspect me=Player target=FixtureObject at (1.0, 0.0, 2.0)',),
                       events=('inspect',), at=(1., 2.), mode='gameplay', state=(('region', 'World'),)))
        c = self.choose(c, 'act', action={'kind': 'target', 'point': [1100, 600], 'visible_road': True,
                                         'expects': {'region': 'ArbitraryInner'}})
        self.assertIsNone(c.surprise)
        captured = dict(c.last_outcome['evidence']['state'])
        self.assertEqual(list(captured['regions']), ['World', 'Outer', 'ArbitraryInner'])
        self.assertEqual(captured['region_provenance']['node'], 'FixtureObject#1,2')
        c = self.choose(c, 'complete')
        self.assertEqual(c.task['stack'][-1]['result']['region'], 'ArbitraryInner')
        c = self.choose(c, 'resume')
        self.assertEqual(c.task['stack'], ())
        self.assertEqual(len(self.port.inputs), 1)

    def test_stored_graph_location_without_fresh_event_does_not_prove_nested_arrival(self):
        from game import experience as X
        from objects.graph import Node
        self.nested_graph()
        self.graph.nodes['Tara'] = Node('Tara', 'unique', region='ArbitraryInner', pos=[1., 2.])
        self.port.snapshot['region'] = 'World'
        c = self.start()
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'ArbitraryInner'}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(mode='gameplay', moved=False, state=(('region', 'World'),)))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1100, 600], 'walkable': True,
                                         'expects': {'region': 'ArbitraryInner'}})
        self.assertIsNotNone(c.surprise)
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'complete')
        self.assertNotIn('regions', dict(c.last_outcome['evidence']['state']))

    def test_latest_positioned_event_disagreement_cannot_reuse_an_earlier_region_proof(self):
        from game import experience as X
        self.nested_graph()
        self.port.snapshot['region'] = 'World'
        c = self.start()
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'ArbitraryInner'}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(lines=('> inspect me=Player target=FixtureObject at (1.0, 0.0, 2.0)',
                              '> inspect me=Player target=UnmappedObject at (9.0, 0.0, 9.0)'),
                       events=('inspect', 'inspect'), at=(9., 9.), mode='gameplay', state=(('region', 'World'),)))
        c = self.choose(c, 'act', action={'kind': 'target', 'point': [1100, 600], 'visible_road': True,
                                         'expects': {'region': 'ArbitraryInner'}})
        self.assertIsNotNone(c.surprise)
        self.assertNotIn('regions', dict(c.last_outcome['evidence']['state']))

    def union_catalogue(self, identified=False, duplicate_available=False):
        self.port.snapshot.update(money=20, inventory={}, inventory_complete=True)
        c = self.play().turn('shop', {'authorization': {'purchases': [
            {'category': 'seed', 'quantity_per_type': 2, 'max_spend': 'available_money'}]}},
            store=self.store, adapter=self.port)
        first = self.catalogue()
        if identified:
            first.update(source='source-a', page='seeds')
        c = self.choose(c, 'catalogue', action={'catalogue': [first]})
        self.port.snapshot['frame_path'] = 'source-b.jpg'
        c = self.choose(c, 'act', action={'kind': 'read'})
        duplicate = dict(self.catalogue(), available=duplicate_available, frame_path='source-b.jpg',
                         evidence_refs=['source-b.jpg'])
        second = dict(self.catalogue('SeedB'), frame_path='source-b.jpg', evidence_refs=['source-b.jpg'])
        if identified:
            duplicate.update(source='source-b', page='seeds')
            second.update(source='source-b', page='seeds')
        c = self.choose(c, 'catalogue', action={'catalogue': [duplicate, second], 'catalogue_complete': True})
        return c

    def buy_item(self, c, item):
        c = self.choose(c, 'push', action={'goal': 'shop', 'params': {'item': item, 'quantity': 2}})
        TradeReview.trade_outcome(self, item, 2, 4)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Buy',
                                         'purchase': {'item': item, 'quantity': 2, 'price': 4}})
        self.assertIsNone(c.surprise)
        return self.choose(self.choose(c, 'complete'), 'resume')

    def test_unavailable_duplicate_preserves_union_and_root_still_requires_the_available_item(self):
        c = self.union_catalogue()
        union = {row['item']: row for row in self.store.load().params['_shop_catalogue']}
        self.assertTrue(union['SeedA']['available'], 'another page cannot erase source-a availability')
        observations = self.store.load().params['_shop_catalogue_observations']
        self.assertEqual([(row['frame_path'], row['available']) for row in observations if row['item'] == 'SeedA'],
                         [('full.jpg', True), ('source-b.jpg', False)])
        c = self.buy_item(c, 'SeedB')
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'complete')
        c = self.buy_item(c, 'SeedA')
        c = self.choose(c, 'complete')
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(self.port.snapshot['inventory'], {'SeedA': 2, 'SeedB': 2})
        self.assertEqual(len(self.port.inputs), 2)

    def test_per_source_page_observations_survive_restart_and_cannot_buy_a_duplicate_type_twice(self):
        try:
            c = self.union_catalogue(identified=True, duplicate_available=True)
        except turn.DecisionRejected as error:
            self.fail(f'generic source/page provenance must be accepted: {error}')
        restored = S.TaskStore(self.store.path).load()
        self.assertEqual([(row['source'], row['page']) for row in restored.params['_shop_catalogue_observations']],
                         [('source-a', 'seeds'), ('source-b', 'seeds'), ('source-b', 'seeds')])
        c = self.buy_item(c, 'SeedA')
        c = self.choose(c, 'push', action={'goal': 'shop', 'params': {'item': 'SeedA', 'quantity': 2}})
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Buy',
                                         'purchase': {'item': 'SeedA', 'quantity': 2, 'price': 4}})
        self.assertIsNotNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(len(self.store.load().params['_purchase_intents']), 1)

    def test_source_page_refresh_preserves_history_and_other_source_availability(self):
        c = self.union_catalogue(identified=True, duplicate_available=True)
        self.port.snapshot['frame_path'] = 'source-a-refresh.jpg'
        c = self.choose(c, 'act', action={'kind': 'read'})
        entry = dict(self.catalogue(), source='source-a', page='seeds', available=False,
                     frame_path='source-a-refresh.jpg', evidence_refs=['source-a-refresh.jpg'])
        c = self.choose(c, 'catalogue', action={'catalogue': [entry]})
        state = S.TaskStore(self.store.path).load()
        observed = state.params['_shop_catalogue_observations']
        self.assertEqual([row['available'] for row in observed if row['item'] == 'SeedA' and
                          row['source'] == 'source-a'], [True, False])
        union = next(row for row in state.params['_shop_catalogue'] if row['item'] == 'SeedA')
        self.assertTrue(union['available'])
        self.assertEqual(union['source'], 'source-b')
        self.assertFalse(state.params['_shop_catalogue_complete'])
        self.assertEqual(self.port.inputs, [])

    def test_other_scene_same_kind_same_coordinates_cannot_mask_the_current_scene_region(self):
        from game import experience as X
        from objects.graph import Node
        self.graph.nodes['OtherWorld'] = Node('OtherWorld', 'region', region='World')
        self.graph.nodes['OtherInner'] = Node('OtherInner', 'region', region='OtherWorld')
        self.graph.nodes['other'] = Node('other', 'member', 'FixtureObject', region='OtherInner',
                                         pos=[1., 2.], scene='OtherWorld')
        self.nested_graph()  # current-scene candidate deliberately inserted after the cross-scene duplicate
        self.port.snapshot['region'] = 'World'
        c = self.start()
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'ArbitraryInner'}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(lines=('> inspect me=Player target=FixtureObject at (1.0, 0.0, 2.0)',),
                       events=('inspect',), at=(1., 2.), mode='gameplay', state=(('region', 'World'),)))
        c = self.choose(c, 'act', action={'kind': 'target', 'point': [1100, 600], 'visible_road': True,
                                         'expects': {'region': 'ArbitraryInner'}})
        self.assertIsNone(c.surprise)
        proof = dict(c.last_outcome['evidence']['state'])['region_provenance']
        self.assertEqual(proof['node'], 'FixtureObject#1,2')
        self.assertEqual(c.transaction['actual_node'], 'FixtureObject#1,2',
                         'captured scene proof and canonical interaction ownership must agree')
        self.assertIn(c.last_outcome['id'], self.graph.nodes['FixtureObject#1,2'].extra['exps'])
        self.assertNotIn('exps', self.graph.nodes['other'].extra)
        c = self.choose(c, 'complete')
        self.assertEqual(c.task['stack'][-1]['result']['region'], 'ArbitraryInner')

    def test_ambiguous_current_scene_positioned_objects_cannot_prove_nested_region(self):
        from game import experience as X
        from objects.graph import Node
        self.nested_graph()
        self.graph.nodes['AnotherInner'] = Node('AnotherInner', 'region', region='World')
        self.graph.nodes['ambiguous'] = Node('ambiguous', 'member', 'FixtureObject', region='AnotherInner',
                                             pos=[1., 2.], scene='World')
        self.port.snapshot['region'] = 'World'
        c = self.start()
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'ArbitraryInner'}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(lines=('> inspect me=Player target=FixtureObject at (1.0, 0.0, 2.0)',),
                       events=('inspect',), at=(1., 2.), mode='gameplay', state=(('region', 'World'),)))
        c = self.choose(c, 'act', action={'kind': 'target', 'point': [1100, 600], 'visible_road': True,
                                         'expects': {'region': 'ArbitraryInner'}})
        self.assertIsNotNone(c.surprise)
        self.assertNotIn('regions', dict(c.last_outcome['evidence']['state']))
        self.assertIsNone(c.transaction['actual_node'])
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'complete')

    def scene_refresh_graph(self, duplicate=False):
        from objects.graph import Node
        for scene in ('SceneA', 'SceneB'):
            self.graph.nodes[scene] = Node(scene, 'region')
            self.graph.nodes[scene + '-bed'] = Node(scene + '-bed', 'member', 'GardenBed', region=scene,
                pos=[1., 2.], scene=scene, state={
                    'watered': {'value': False, 'game_time': 'D210 8:00:00 AM', 'source': 'save'},
                    'stage': {'value': 'growing', 'game_time': 'D210 8:00:00 AM', 'source': 'save'}})
        if duplicate:
            self.graph.nodes['ambiguous-b'] = Node('ambiguous-b', 'member', 'GardenBed', region='SceneB',
                pos=[1., 2.], scene='SceneB')

    def production_clues(self, lines, scenes=None):
        from game import observe
        from types import SimpleNamespace
        save = {'saveCount': 1, 'currentScene': 'SceneA',
                'gameState': {'time': {'day': 210, 'timeOfDay': {'totalSeconds': 28800}},
                              'player': {'inventory': {'items': []}}}}
        if scenes is not None:
            save['scenes'] = scenes
        raw = SimpleNamespace(read_save=lambda: ('save.json', save), today_log=lambda: (lines, None),
                              current_scene=lambda: 'SceneB')
        with mock.patch.object(core, 'WF', raw), mock.patch.object(engine, '_open_graph', return_value=self.graph), \
                mock.patch.object(observe, 'clock', return_value=(10., 'day')):
            return self.play()._clues(self.store)

    def test_real_clues_refresh_updates_only_current_source_scene_object(self):
        self.scene_refresh_graph()
        lines = ['[D210 9:00:00 AM] ChangeScene SceneB/Spawn',
                 '[D210 9:01:00 AM] > water me=Player target=GardenBed at (1.0, 0.0, 2.0)']
        data = self.production_clues(lines)
        self.assertFalse(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertTrue(self.graph.state_value('SceneB-bed', 'watered'))
        self.assertEqual(self.graph.nodes['SceneA-bed'].extra['scene'], 'SceneA')
        self.assertEqual(self.graph.nodes['SceneB-bed'].extra['scene'], 'SceneB')
        self.assertEqual(data['scene'], 'SceneB')
        self.assertEqual(data['save_scene'], 'SceneA')
        self.assertEqual(data['state_provenance']['save_scene'], data['state_provenance']['position'])
        self.assertIsNone(turn._saved_position(data), 'a later scene log cannot relabel a stale saved position')

    def test_real_clues_newer_save_scene_anchors_events_after_older_scene_log(self):
        self.scene_refresh_graph()
        lines = ['[D210 7:30:00 AM] ChangeScene SceneB/Spawn',
                 '[D210 9:01:00 AM] > water me=Player target=GardenBed at (1.0, 0.0, 2.0)']
        data = self.production_clues(lines)  # snapshot at 08:00 explicitly names SceneA
        self.assertTrue(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertFalse(self.graph.state_value('SceneB-bed', 'watered'))
        self.assertEqual(data['scene'], 'SceneA')

    def test_real_clues_historical_event_sources_survive_refresh_then_integration_replay(self):
        from game import experience as X
        self.scene_refresh_graph()
        lines = ['[D210 8:59:00 AM] ChangeScene SceneA/Spawn',
                 '[D210 9:00:00 AM] > water me=Player target=GardenBed at (1.0, 0.0, 2.0)',
                 '[D210 9:01:00 AM] ChangeScene SceneB/Spawn',
                 '[D210 9:02:00 AM] > unplant_impl me=Player target=GardenBed at (1.0, 0.0, 2.0)']
        data = self.production_clues(lines)
        self.assertTrue(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertEqual(self.graph.state_value('SceneA-bed', 'stage'), 'growing')
        self.assertEqual(self.graph.state_value('SceneB-bed', 'stage'), 'empty')
        before = dict(self.port.snapshot, region='SceneA', scene='SceneA')
        e = primitives.experience(S.Intent(1, {'kind': 'target', 'point': [1100, 600]}, 0, 1.), before, {},
            X.Evidence(lines=tuple(lines), events=('water', 'unplant_impl'), at=(1., 2.),
                       mode='gameplay', state=(('region', data['region']), ('scene', data['scene']))))
        self.assertIn('event_sources', dict(e.evidence.state), 'immutable outcomes must retain each event source scene')
        sources = dict(e.evidence.state)['event_sources']
        self.assertEqual([row['scene'] for row in sources], ['SceneA', 'SceneB'])
        result = I.apply(e)
        self.assertFalse(result.get('errors'))
        self.assertEqual(I.event_node(e), 'SceneB-bed')
        self.assertTrue(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertEqual(self.graph.state_value('SceneA-bed', 'stage'), 'growing')
        self.assertEqual(self.graph.state_value('SceneB-bed', 'stage'), 'empty')
        self.assertEqual(I.apply(e)['applied'], 0)

    def test_real_clues_ambiguous_source_scene_records_conflict_without_mutating_candidates(self):
        self.scene_refresh_graph(duplicate=True)
        lines = ['[D210 9:00:00 AM] ChangeScene SceneB/Spawn',
                 '[D210 9:01:00 AM] > water me=Player target=GardenBed at (1.0, 0.0, 2.0)']
        data = self.production_clues(lines)
        self.assertFalse(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertFalse(self.graph.state_value('SceneB-bed', 'watered'))
        self.assertIsNone(self.graph.state_value('ambiguous-b', 'watered'))
        self.assertTrue(any(row.get('world_conflict') for row in data['graph_clues']))

    def test_real_clues_save_objects_with_equal_coordinates_keep_separate_scene_identity(self):
        self.scene_refresh_graph()
        self.graph.extra['prefabs'] = {'fixture-bed': 'GardenBed'}
        scenes = [{'sceneName': scene, 'addedObjects': [{
            'prefabId': {'s': 'fixture-bed'}, 'position': {'x': 1., 'y': 0., 'z': 2.},
            'actorState': {'userState': {'entries': [{'name': 'marker', 'value': scene}]}}}]}
                  for scene in ('SceneA', 'SceneB')]
        self.production_clues([], scenes=scenes)
        self.assertEqual(self.graph.state_value('SceneA-bed', 'marker'), 'SceneA')
        self.assertEqual(self.graph.state_value('SceneB-bed', 'marker'), 'SceneB')
        self.assertEqual(self.graph.nodes['SceneA-bed'].extra['scene'], 'SceneA')
        self.assertEqual(self.graph.nodes['SceneB-bed'].extra['scene'], 'SceneB')

    def test_explicit_unknown_production_scene_never_uses_legacy_global_identity_fallback(self):
        from game import experience as X
        self.scene_refresh_graph()
        self.port.snapshot.update(scene=None, region=None)
        c = self.start()
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'SceneB'}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(lines=('> water me=Player target=GardenBed at (1.0, 0.0, 2.0)',),
                       events=('water',), at=(1., 2.), mode='gameplay',
                       state=(('scene', None), ('region', None))))
        c = self.choose(c, 'act', action={'kind': 'target', 'point': [1100, 600], 'visible_road': True})
        self.assertIsNotNone(c.surprise)
        self.assertIsNone(c.transaction['actual_node'])
        self.assertFalse(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertFalse(self.graph.state_value('SceneB-bed', 'watered'))

    def test_legacy_adapter_without_scene_keeps_resolved_object_scene_during_integration(self):
        from game import experience as X
        self.scene_refresh_graph()
        del self.graph.nodes['SceneA-bed']
        c = self.play().turn('inspect', store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(lines=('> water me=Player target=GardenBed at (1.0, 0.0, 2.0)',),
                       events=('water',), at=(1., 2.), mode='gameplay'))
        c = self.choose(c, 'act', action={'kind': 'target', 'point': [1100, 600], 'visible_road': True,
                                         'expects': {'events': ['water']}})
        self.assertIsNone(c.surprise)
        self.assertEqual(c.transaction['actual_node'], 'SceneB-bed')
        self.assertTrue(self.graph.state_value('SceneB-bed', 'watered'))
        self.assertEqual(self.graph.nodes['SceneB-bed'].extra['event_provenance']['scene'], 'SceneB')
        self.assertEqual(len([n for n in self.graph.nodes.values() if n.kind == 'GardenBed']), 1)

    def test_explicit_unknown_before_event_is_not_assigned_to_a_later_scene(self):
        from game import experience as X
        self.scene_refresh_graph()
        before = dict(self.port.snapshot, scene=None, region=None)
        lines = ('[D210 9:00:00 AM] > water me=Player target=GardenBed at (1.0, 0.0, 2.0)',
                 '[D210 9:01:00 AM] ChangeScene SceneB/Spawn')
        e = primitives.experience(S.Intent(1, {'kind': 'target', 'point': [1100, 600]}, 0, 1.), before, {},
            X.Evidence(lines=lines, events=('water',), at=(1., 2.), mode='gameplay',
                       state=(('scene', 'SceneB'), ('region', 'SceneB'))))
        sources = dict(e.evidence.state)['event_sources']
        self.assertIsNone(sources[0]['scene'], 'the later scene cannot retroactively establish event source')
        self.assertIsNone(sources[0]['scope'])
        self.assertNotIn('regions', dict(e.evidence.state))
        result = I.apply(e)
        self.assertTrue(result.get('errors'))
        self.assertIsNone(I.event_node(e))
        self.assertFalse(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertFalse(self.graph.state_value('SceneB-bed', 'watered'))

    def test_transition_before_event_establishes_source_from_explicit_unknown_context(self):
        from game import experience as X
        self.scene_refresh_graph()
        before = dict(self.port.snapshot, scene=None, region=None)
        lines = ('[D210 9:00:00 AM] ChangeScene SceneB/Spawn',
                 '[D210 9:01:00 AM] > water me=Player target=GardenBed at (1.0, 0.0, 2.0)')
        e = primitives.experience(S.Intent(1, {'kind': 'target', 'point': [1100, 600]}, 0, 1.), before, {},
            X.Evidence(lines=lines, events=('water',), at=(1., 2.), mode='gameplay',
                       state=(('scene', 'SceneB'), ('region', 'SceneB'))))
        sources = dict(e.evidence.state)['event_sources']
        self.assertEqual(sources[0]['scene'], 'SceneB')
        self.assertEqual(sources[0]['scope'], 'SceneB')
        result = I.apply(e)
        self.assertFalse(result.get('errors'))
        self.assertEqual(I.event_node(e), 'SceneB-bed')
        self.assertFalse(self.graph.state_value('SceneA-bed', 'watered'))
        self.assertTrue(self.graph.state_value('SceneB-bed', 'watered'))


class CapturedMoney(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        path = os.path.join(os.path.dirname(__file__), 'fixtures', 'play', 'root-money-character-state.json')
        with open(path) as stream:
            self.captured = json.load(stream)

    def test_public_creation_reads_money_from_captured_player_character_state(self):
        from game import observe
        from objects.graph import Graph
        from types import SimpleNamespace
        source = self.captured['source_save_provenance']
        save = self.captured['save_fragment']
        raw = SimpleNamespace(read_save=lambda: (source['path'], save), today_log=lambda: ([], None),
                              current_scene=lambda: save['currentScene'])
        self.port.observe = lambda: dict(self.port.snapshot, **self.play()._clues(self.store))
        with mock.patch.object(core, 'WF', raw), mock.patch.object(engine, '_open_graph', return_value=Graph()), \
                mock.patch.object(observe, 'clock', return_value=(8.333, 'day')):
            c = self.play().turn('garden', {'authorization': {'purchases': [
                {'category': 'Seed', 'quantity_per_type': 10, 'max_spend': 'available_money'}]}},
                store=self.store, adapter=self.port)
        self.assertEqual(c.task['params']['_trade_start_money'], 100)
        self.assertEqual(c.task['params']['_trade_start_money_provenance']['save_count'], 7920)
        self.assertEqual(self.port.inputs, [])

    def test_bare_resume_repairs_captured_root_from_its_original_snapshot_without_new_turn(self):
        from types import SimpleNamespace
        original = self.captured['broken_root']
        self.create_legacy_task(S.TaskState.from_dict(original))
        source = self.captured['source_save_provenance']
        def read(path=None):
            self.assertEqual(path, source['path'], 'repair must not use a later/stale current balance')
            return path, self.captured['save_fragment']
        with mock.patch.object(core, 'WF', SimpleNamespace(read_save=read)):
            c = self.play().turn(store=self.store, adapter=self.port)
            persisted = self.store.load()
            self.assertEqual(persisted.params['_trade_start_money'], 100)
            self.assertEqual(c.task['params']['_trade_start_money'], 100)
            self.assertEqual(c.turn_id, original['current_turn']['turn_id'])
            self.assertEqual(persisted.task_id, original['task_id'])
            self.assertEqual(persisted.active, S.TaskState.from_dict(original).active)
            again = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertEqual(again.turn_id, c.turn_id)
        self.assertEqual(self.store.load().to_dict(), persisted.to_dict())
        self.assertEqual(self.port.inputs, [])
        with open(os.path.join(self.tmp.name, 'log.jsonl')) as stream:
            rows = [json.loads(line) for line in stream]
        self.assertEqual(sum(row.get('phase') == 'migration' for row in rows), 1)

    def test_original_snapshot_identity_mismatch_cannot_inflate_missing_start_money(self):
        from types import SimpleNamespace
        self.store.create(S.TaskState.from_dict(self.captured['broken_root']))
        later = dict(self.captured['save_fragment'], saveCount=7921)
        later['gameState'] = dict(later['gameState'], characters=[{'name': 'Player', 'state': {
            'userState': {'entries': [{'name': 'money', 'value': '999'}]}}}])
        with mock.patch.object(core, 'WF', SimpleNamespace(read_save=lambda path=None: (path, later))):
            c = self.play().turn(store=self.store, adapter=self.port)
        self.assertIsNone(c.task['params']['_trade_start_money'])
        self.assertIsNone(self.store.load().params['_trade_start_money'])
        self.assertEqual(self.port.inputs, [])

    def test_repair_rejects_wrong_snapshot_time_or_path_and_never_rebases_known_funds(self):
        from types import SimpleNamespace
        original = self.captured['broken_root']
        source = self.captured['source_save_provenance']
        for change in ('time', 'path', 'known'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                task = S.TaskState.from_dict(json.loads(json.dumps(original)))
                if change == 'known':
                    task.params['_trade_start_money'] = 75
                    task.current_turn['task']['params']['_trade_start_money'] = 75
                self.store.create(task)
                save = json.loads(json.dumps(self.captured['save_fragment']))
                if change == 'time':
                    save['gameState']['time']['timeOfDay']['totalSeconds'] += 60
                save['gameState']['characters'][0]['state']['userState']['entries'][0]['value'] = '999'
                returned_path = source['path'] + '.different' if change == 'path' else source['path']
                def read(path=None):
                    self.assertNotEqual(change, 'known', 'known starting funds must never be reread/rebased')
                    return returned_path, save
                with mock.patch.object(core, 'WF', SimpleNamespace(read_save=read)):
                    c = self.play().turn(store=self.store, adapter=self.port)
                self.assertEqual(c.task['params']['_trade_start_money'], 75 if change == 'known' else None)
        self.assertEqual(self.port.inputs, [])

    def test_authoritative_character_money_wins_over_stale_direct_player_state(self):
        from game import observe
        from objects.graph import Graph
        from types import SimpleNamespace
        source = self.captured['source_save_provenance']
        save = json.loads(json.dumps(self.captured['save_fragment']))
        save['gameState']['player']['state'] = {'userState': {'entries': [{'name': 'money', 'value': '999'}]}}
        raw = SimpleNamespace(read_save=lambda: (source['path'], save), today_log=lambda: ([], None),
                              current_scene=lambda: save['currentScene'])
        self.port.observe = lambda: dict(self.port.snapshot, **self.play()._clues(self.store))
        with mock.patch.object(core, 'WF', raw), mock.patch.object(engine, '_open_graph', return_value=Graph()), \
                mock.patch.object(observe, 'clock', return_value=(8.333, 'day')):
            c = self.play().turn('garden', store=self.store, adapter=self.port)
        self.assertEqual(c.task['params']['_trade_start_money'], 100)
        self.assertIn('characters[name=Player]', c.task['params']['_trade_start_money_provenance']['field'])
        self.assertEqual(self.port.inputs, [])


class CapturedCancellation(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        path = os.path.join(os.path.dirname(__file__), 'fixtures', 'play', 'duplicate-shop-admin-resume.json')
        with open(path) as stream:
            self.captured = json.load(stream)

    def choose(self, c, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def duplicate(self):
        task = S.TaskState.from_dict(self.captured['task'])
        self.store.create(task)
        self.write_inline_history_log(task)
        c = self.play().turn(store=self.store, adapter=self.port)
        return self.choose(c, 'act', action={'kind': 'read'})  # refresh a pre-upgrade cached capability list, zero input

    def test_captured_admin_duplicate_cancels_without_losing_evidence_or_parent_across_restart(self):
        c = self.duplicate()
        self.assertIn('cancel', c.allowed_decisions, 'the public turn needs safe administrative child cancellation')
        before = self.store.load()
        with open(os.path.join(self.tmp.name, 'experiences.jsonl'), 'rb') as stream:
            journal = stream.read()
        c = self.choose(c, 'cancel', rationale='remove accidental duplicate child; no trade occurred')
        after = self.store.load()
        self.assertEqual(after.task_id, self.captured['task']['task_id'])
        self.assertEqual(len(after.stack), 1)
        self.assertEqual(after.stack[0].params, before.stack[0].params)
        self.assertEqual(after.stack[0].status, 'active')
        self.assertEqual(after.active, before.stack[-1].parent_interaction)
        cancelled = after.params['_cancelled_subgoals'][-1]
        self.assertEqual(cancelled['subgoal']['result'], before.stack[-1].result)
        self.assertIn('duplicate', cancelled['rationale'])
        self.assertNotIn('_subgoal_results', after.params)
        with open(os.path.join(self.tmp.name, 'experiences.jsonl'), 'rb') as stream:
            self.assertEqual(stream.read(), journal)
        restarted = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertEqual(restarted.turn_id, c.turn_id)
        self.assertEqual(len(restarted.task['stack']), 1)
        with self.assertRaises(turn.StaleTurn):
            self.choose(type('Old', (), {'turn_id': c.turn_id - 1})(), 'cancel', rationale='stale repeat')
        self.assertEqual(self.port.inputs, [])
        with open(os.path.join(self.tmp.name, 'log.jsonl')) as stream:
            rows = [json.loads(line) for line in stream]
        self.assertEqual(sum(row.get('phase') == 'cancellation' for row in rows), 1)

    def test_suspended_administrative_duplicate_can_cancel_and_reactivate_previous_child(self):
        c = self.choose(self.duplicate(), 'suspend')
        self.assertIn('cancel', c.allowed_decisions)
        c = self.choose(c, 'cancel', rationale='discard suspended administrative duplicate')
        self.assertEqual(len(c.task['stack']), 1)
        self.assertEqual(c.task['stack'][-1]['status'], 'active')
        self.assertEqual(self.port.inputs, [])

    def test_financial_reservation_and_receipt_prevent_cancellation(self):
        self.port.snapshot.update(inventory={'GrownA': 2}, inventory_complete=True, money=100)
        c = self.play().turn('shop', {'authorization': {'sales': [{'item': 'GrownA', 'quantity': 2}]}},
                             store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'shop', 'params':
                                         {'trade': 'sell', 'item': 'GrownA', 'quantity': 2}})
        TradeReview.trade_outcome(self, 'GrownA', 2, 10, selling=True)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Sell',
                                         'sale': {'item': 'GrownA', 'quantity': 2, 'price': 10}})
        self.assertIn('cancel', c.allowed_decisions)
        with self.assertRaisesRegex(turn.DecisionRejected, 'reservation|financial'):
            self.choose(c, 'cancel', rationale='cannot undo a sale')
        self.assertEqual(len(self.store.load().stack), 1)
        self.assertEqual(len(self.store.load().params['_sale_intents']), 1)
        self.assertEqual(len(self.port.inputs), 1)

    def test_other_irreversible_domain_event_prevents_cancellation(self):
        from game import experience as X
        c = self.play().turn('work', store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'refill', 'params': {}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(events=('fill_watering_can',), mode='gameplay'))
        c = self.choose(c, 'act', action={'kind': 'space', 'expects': {'events': ['fill_watering_can']}})
        self.assertIn('cancel', c.allowed_decisions)
        with self.assertRaisesRegex(turn.DecisionRejected, 'domain|irreversible'):
            self.choose(c, 'cancel', rationale='cannot discard a completed resource action')
        self.assertEqual(len(self.port.inputs), 1)

    def test_pending_financial_reservation_survives_recovery_and_cannot_cancel(self):
        self.port.snapshot.update(inventory={'GrownA': 2}, inventory_complete=True, money=100)
        c = self.play().turn('shop', {'authorization': {'sales': [{'item': 'GrownA', 'quantity': 2}]}},
                             store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'shop', 'params':
                                         {'trade': 'sell', 'item': 'GrownA', 'quantity': 2}})
        self.port.fail = True
        with self.assertRaises(RuntimeError):
            self.choose(c, 'act', action={'kind': 'press', 'label': 'Sell',
                                          'sale': {'item': 'GrownA', 'quantity': 2, 'price': 10}})
        self.port.fail = False
        c = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        c = self.choose(c, 'correct', correction={'kind': 'revise_decision'})
        with self.assertRaisesRegex(turn.DecisionRejected, 'reservation'):
            self.choose(c, 'cancel', rationale='uncertain sale must retain its reservation')
        self.assertEqual(len(self.store.load().params['_sale_intents']), 1)
        self.assertEqual(len(self.port.inputs), 1)

    def test_an_earlier_sibling_trade_does_not_prevent_cancelling_an_untouched_new_child(self):
        self.port.snapshot.update(inventory={'GrownA': 2, 'GrownB': 2}, inventory_complete=True, money=100)
        c = self.play().turn('shop', {'authorization': {'sales': [
            {'item': 'GrownA', 'quantity': 2}, {'item': 'GrownB', 'quantity': 2}]}},
            store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'shop', 'params':
                                         {'trade': 'sell', 'item': 'GrownA', 'quantity': 2}})
        TradeReview.trade_outcome(self, 'GrownA', 2, 10, selling=True)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Sell',
                                         'sale': {'item': 'GrownA', 'quantity': 2, 'price': 10}})
        c = self.choose(self.choose(c, 'complete'), 'resume')
        c = self.choose(c, 'push', action={'goal': 'shop', 'params':
                                         {'trade': 'sell', 'item': 'GrownB', 'quantity': 2}})
        self.assertIsInstance(self.store.load().stack[-1].started_turn, int)
        c = self.choose(c, 'cancel', rationale='new child is untouched despite an earlier sibling sale')
        self.assertEqual(len(c.task['stack']), 0)
        self.assertEqual(len(self.store.load().params['_sale_intents']), 1)
        self.assertEqual(len(self.store.load().params['_subgoal_results']), 1)
        self.assertEqual(len(self.port.inputs), 1)
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'complete')

    def test_menu_only_child_can_cancel_without_treating_ui_verification_as_domain_work(self):
        from game import experience as X
        c = self.play().turn('work', store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'inspect', 'params': {}})
        self.port.capture = lambda intent, before, expected: primitives.experience(intent, before, expected,
            X.Evidence(mode='inventory'))
        c = self.choose(c, 'act', action={'kind': 'key', 'label': 'i', 'expects': {'mode': 'inventory'}})
        c = self.choose(c, 'cancel', rationale='menu inspection only; no irreversible action')
        self.assertEqual(len(c.task['stack']), 0)
        self.assertIsNone(c.transaction)
        self.assertEqual(len(self.port.inputs), 1)

    def test_proven_no_effect_world_misses_can_cancel_an_obsolete_child(self):
        from game import experience as X
        c = self.play().turn('work', store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'sleep', 'params': {}})
        self.port.capture = lambda intent, before, expected: primitives.experience(
            intent, before, expected, X.Evidence(mode='gameplay', moved=False))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [820, 700],
                                         'walkable': True, 'expects': {'moved': True}})
        self.assertIsNotNone(c.surprise)
        c = self.choose(c, 'correct', correction={'kind': 'revise_decision', 'data': {
            'reason': 'captured no movement, event, card, resource change or mode change'}})
        c = self.choose(c, 'cancel', rationale='obsolete child contains only proven no-effect world misses')
        self.assertEqual(c.task['stack'], ())
        self.assertEqual(len(self.port.inputs), 1)

    def test_unnamed_positioned_evidence_cannot_be_discarded_by_cancellation(self):
        from game import experience as X
        self.port.snapshot['position'] = [1., 2.]
        cases = [X.Evidence(mode='gameplay', at=(1., 2.), lines=('unknown log',)),
                 X.Evidence(mode='gameplay', lines=('unclassified interaction at (1.0, 0.0, 2.0)',)),
                 X.Evidence(mode='gameplay', state=(('region_provenance',
                     {'source': 'positioned_event', 'node': 'unclassified'}),)),
                 X.Evidence(mode='gameplay', node='unclassified'),
                 X.Evidence(mode='gameplay', state=(('position', (1., 2.)),))]
        for evidence in cases:
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                c = self.play().turn('work', store=self.store, adapter=self.port)
                c = self.choose(c, 'push', action={'goal': 'inspect', 'params': {}})
                self.port.capture = lambda intent, before, expected: primitives.experience(
                    intent, before, expected, evidence)
                c = self.choose(c, 'act', action={'kind': 'read'})
                self.assertIsNone(c.surprise)
                with self.assertRaisesRegex(turn.DecisionRejected, 'positioned'):
                    self.choose(c, 'cancel', rationale='unknown positional evidence needs inspection')
                self.assertEqual(len(self.store.load().stack), 1)
                self.assertNotIn('_cancelled_subgoals', self.store.load().params)
        self.assertEqual(self.port.inputs, [])


class CapturedMovement(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        path = os.path.join(os.path.dirname(__file__), 'fixtures', 'play', 'explicit-movement-expectation.json')
        with open(path) as stream:
            self.captured = json.load(stream)

    def choose(self, c, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def navigation(self):
        self.port.snapshot = self.captured['intent']['before']
        c = self.play().turn('garden', store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'shop', 'params':
                                         {'trade': 'sell', 'item': 'Tulip', 'quantity': 64}})
        return self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'Town'}})

    def test_captured_explicit_movement_hit_is_relevant_without_proving_navigation_arrival(self):
        from game import experience as X
        c = self.navigation()
        root = c.task['task_id']
        source = self.captured['experience']
        self.port.capture = lambda intent, before, expected: primitives.experience(
            intent, before, expected, X.Evidence(**source['evidence']), source['artifacts']['frames'])
        decision = dict(self.captured['decision'])
        c = self.choose(c, decision.pop('kind'), **decision)
        self.assertEqual(c.last_outcome['verdict']['value'], 'hit')
        self.assertIsNone(c.surprise, 'explicit movement proof must not become irrelevant_movement')
        self.assertEqual(len(self.port.inputs), 1)
        with self.assertRaisesRegex(turn.DecisionRejected, 'region'):
            self.choose(c, 'complete')
        self.assertEqual(c.task['task_id'], root)
        self.assertEqual(len(self.store.load().stack), 2)
        self.assertEqual(self.store.load().stack[0].status, 'suspended')
        self.assertEqual(self.store.load().stack[-1].params, {'region': 'Town'})

    def test_absent_or_mismatched_movement_expectations_remain_surprises(self):
        from game import experience as X
        for expected, actual in [(None, True), (None, False), (True, False), (False, True)]:
            with self.subTest(expected=expected, actual=actual), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.navigation()
                self.port.capture = lambda intent, before, expects: primitives.experience(
                    intent, before, expects, X.Evidence(moved=actual, mode='gameplay', state=(('region', 'Farm'),)))
                action = {'kind': 'waypoint', 'point': [1700, 650], 'walkable': True}
                if expected is not None:
                    action['expects'] = {'moved': expected}
                c = self.choose(c, 'act', action=action)
                self.assertIsNotNone(c.surprise)
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, 'act', action=action)
                self.assertEqual(len(self.port.inputs), 1)

    def test_expected_stationary_waypoint_still_requires_progress_and_blocks_second_attempt(self):
        from game import experience as X
        c = self.navigation()
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(moved=False, mode='gameplay', state=(('region', 'Farm'),)))
        action = {'kind': 'waypoint', 'point': [1700, 650], 'walkable': True, 'expects': {'moved': False}}
        c = self.choose(c, 'act', action=action)
        self.assertEqual(c.last_outcome['verdict']['value'], 'hit')
        self.assertIsNotNone(c.surprise, 'matched stationary evidence does not establish waypoint progress')
        self.assertEqual(c.surprise.reason, 'no_progress')
        with self.assertRaises(turn.DecisionRejected):
            self.choose(c, 'act', action=action)
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(len(self.store.load().stack), 2)

    def test_corrected_live_task_resumes_same_turn_and_stack_then_read_refreshes_without_input(self):
        original = self.captured['task']
        self.create_legacy_task(S.TaskState.from_dict(original))
        c = self.play().turn(store=self.store, adapter=self.port)
        self.assertEqual(c.turn_id, 15)
        self.assertIsNone(c.surprise)
        self.assertEqual(c.task['task_id'], original['task_id'])
        before = self.store.load()
        c = self.choose(c, 'act', action={'kind': 'read'})
        after = self.store.load()
        self.assertEqual(after.task_id, before.task_id)
        self.assertEqual([(s.goal, s.params, s.status) for s in after.stack],
                         [(s.goal, s.params, s.status) for s in before.stack])
        self.assertEqual(c.turn_id, 16)
        self.assertEqual(self.port.inputs, [])


class ObservationRecovery(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        path = os.path.join(os.path.dirname(__file__), 'fixtures', 'play', 'split-observation-refusal.json')
        with open(path) as stream:
            self.captured = json.load(stream)

    def choose(self, c, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def snapshot(self, count=7923, stamp='D210 8:40:00 AM', position=(53.77716064453125, -42.365909576416016),
                 mode='gameplay', scene='Farm'):
        proof = {'source': 'save', 'path': '/captured/saves/%s.local' % count,
                 'save_count': count, 'game_time': stamp}
        return {'screen': {'kind': mode, 'texts': ['pre'] if mode == 'unknown' else []},
                'frame_path': 'source-full.jpg', 'visible_affordances': [], 'graph_clues': [], 'interrupts': [],
                'game_time': 'D210 8:55:09 AM', 'position': list(position), 'scene': scene, 'region': scene,
                'save_scene': scene, 'state_provenance': {'position': proof, 'save_scene': proof}}

    def uncertain_waypoint(self, expects=None):
        from game import experience as X
        self.port.snapshot = self.snapshot()
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='unknown', texts=('pre',)), ('black-full.jpg',))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640],
                                         'walkable': True, 'expects': expects or {'moved': True}})
        self.assertIsNotNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)
        return c

    def read_snapshot(self, c, snapshot, **captured):
        from game import experience as X
        self.port.snapshot = snapshot
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode=snapshot['screen']['kind'],
                                               texts=tuple(snapshot['screen']['texts']),
                                               state=X._t(tuple(snapshot.items())), **captured), (snapshot['frame_path'],))
        return self.choose(c, 'read')

    def test_recovery_requires_every_original_expectation_including_region_node_event_mode_card_and_log(self):
        cases = [{'region': 'Town'}, {'node': 'TownGate'}, {'events': ['arrival']}, {'mode': 'shop'},
                 {'card': 'Catalogue'}, {'log': 'route_confirm'},
                 {'events': ['arrival'], 'allowed_events': ['arrival_aux']}]
        for extra in cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.uncertain_waypoint(dict(moved=True, **extra))
                captured = {'events': ('arrival', 'unrequested')} if extra.get('allowed_events') else {}
                c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679)), **captured)
                self.assertIsNotNone(c.surprise, 'movement alone cannot satisfy the remaining original expectations')
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640], 'walkable': True})
                self.assertEqual(len(self.port.inputs), 1)

    def test_recovery_accepts_fresh_evidence_when_all_original_expectations_match(self):
        expects = {'moved': True, 'region': 'Town', 'node': 'TownGate', 'events': ['arrival'],
                   'allowed_events': ['arrival_aux'], 'mode': 'gameplay', 'card': 'Catalogue', 'log': 'route_confirm'}
        c = self.uncertain_waypoint(expects)
        from game import history
        task = self.store.load()
        rows = history.records(os.path.join(self.tmp.name, 'log.jsonl'), task.evidence_refs)
        self.assertEqual(rows[0]['expects'], expects)
        snapshot = self.snapshot(7925, 'D210 9:00:00 AM', (1, 2), scene='Town')
        snapshot['screen']['texts'] = ['Catalogue']
        c = self.read_snapshot(c, snapshot, node='TownGate', events=('arrival', 'arrival_aux'), lines=('route_confirm',))
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)

    def test_guard_refresh_does_not_discard_other_original_expectations_or_credit_movement(self):
        self.port.snapshot = self.snapshot(mode='unknown')
        self.port.prepare = primitives.GameAdapter().prepare
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640], 'walkable': True,
                                         'expects': {'moved': True, 'region': 'Town'}})
        self.assertEqual(c.last_outcome['verdict']['value'], 'unsafe')
        c = self.read_snapshot(c, self.snapshot())
        self.assertIsNotNone(c.surprise)
        proof = dict(c.last_outcome['evidence']['state'])['observation_reconciliation']
        self.assertEqual(proof['surprise'], 'wrong_region')
        self.assertIsNone(c.last_outcome['evidence']['moved'])
        self.assertEqual(self.port.inputs, [])

    def test_recovery_checks_fresh_event_source_scene_without_relabeling_it_with_original_before_scene(self):
        from game import learn
        from objects.graph import Graph, Node
        graph = Graph()
        graph.nodes['FarmBed'] = Node('FarmBed', 'member', 'GardenBed', scene='Farm', pos=[1., 2.])
        graph.nodes['TownBed'] = Node('TownBed', 'member', 'GardenBed', scene='Town', pos=[1., 2.])
        with mock.patch.dict(learn.MEMORY, graph=graph):
            c = self.uncertain_waypoint({'moved': True, 'node': 'FarmBed', 'events': ['water']})
            c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (1, 2), scene='Town'),
                lines=('> water me=Player target=GardenBed at (1.0, 0.0, 2.0)',), events=('water',), at=(1., 2.))
            self.assertIsNotNone(c.surprise, 'fresh Town event cannot satisfy expected Farm object')
            self.assertEqual(dict(c.last_outcome['evidence']['state'])['event_sources'][0]['scene'], 'Town')
            self.assertFalse(graph.state_value('FarmBed', 'watered'))
            self.assertTrue(graph.state_value('TownBed', 'watered'))
            self.assertEqual(len(self.port.inputs), 1)

    def archived_waypoint(self):
        from game import experience as X
        self.port.snapshot = self.snapshot()
        self.port.snapshot['game_time'] = 'D210 8:45:00 AM'
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        c = self.choose(c, 'push', action={'goal': 'navigate', 'params': {'region': 'Farm'}})
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='gameplay', moved=True,
                state=(('region', 'Farm'), ('game_time', 'D210 8:46:00 AM'))))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1200, 640],
                                         'walkable': True, 'expects': {'moved': True}})
        c = self.choose(c, 'complete')
        c = self.choose(c, 'resume')
        self.assertEqual(len(self.store.load().params['_subgoal_results']), 1)
        return c

    def test_archived_completed_child_movement_sharing_stale_baseline_prevents_recovery(self):
        from game import experience as X
        c = self.archived_waypoint()
        self.port.snapshot = self.snapshot()
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='unknown'), ('black-full.jpg',))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640],
                                         'walkable': True, 'expects': {'moved': True}})
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679)))
        self.assertIsNotNone(c.surprise, 'archiving a child cannot erase attribution ambiguity')
        self.assertIsNone(c.last_outcome['evidence']['moved'])
        self.assertEqual(len(self.port.inputs), 2)

    def test_archived_child_before_a_newer_baseline_does_not_prevent_proven_recovery(self):
        from game import experience as X
        c = self.archived_waypoint()
        self.port.snapshot = self.snapshot(7924, 'D210 8:50:00 AM')
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='unknown'), ('black-full.jpg',))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640],
                                         'walkable': True, 'expects': {'moved': True}})
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679)))
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 2)

    def test_missing_archived_evidence_keeps_attribution_ambiguous_after_restart(self):
        from game import experience as X
        c = self.archived_waypoint()
        task = self.store.load()
        task.params['_subgoal_results'][0]['evidence_refs'].append('missing-legacy-proof')
        self.store.save(task)  # captured legacy/incomplete archive: public read must fail closed
        self.port.snapshot = self.snapshot(7924, 'D210 8:50:00 AM')
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='unknown'), ('black-full.jpg',))
        c = self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640],
                                         'walkable': True, 'expects': {'moved': True}})
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679)))
        self.assertIsNotNone(c.surprise)
        self.assertIsNone(c.last_outcome['evidence']['moved'])
        self.assertEqual(len(self.port.inputs), 2)

    def test_unknown_waypoint_can_reconcile_from_newer_authoritative_snapshot_without_replaying_input(self):
        c = self.uncertain_waypoint()
        old = c
        original = c.last_outcome.to_dict() if hasattr(c.last_outcome, 'to_dict') else S.thaw(c.last_outcome)
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.927650451660156, -41.678768157958984)))
        self.assertIsNone(c.surprise)
        self.assertTrue(c.last_outcome['evidence']['moved'])
        proof = dict(c.last_outcome['evidence']['state'])['observation_reconciliation']
        self.assertEqual(proof['source_experience'], original['id'])
        self.assertEqual(proof['result'], 'verified_movement')
        self.assertEqual(len(self.port.inputs), 1)
        from game import history
        task = self.store.load()
        outcomes = history.records(os.path.join(self.tmp.name, 'log.jsonl'), task.evidence_refs)
        self.assertEqual(outcomes[0]['experience'], original, 'original incomplete experience is immutable')
        with self.assertRaisesRegex(turn.DecisionRejected, 'region'):
            self.choose(c, 'complete')
        with self.assertRaises(turn.StaleTurn):
            self.choose(old, 'read')
        self.assertEqual(len(self.port.inputs), 1)

    def test_stale_preinput_or_unproved_snapshots_keep_surprise_and_refuse_second_input(self):
        cases = [self.snapshot(), self.snapshot(7924, 'D210 8:50:00 AM', (58.928, -41.679)),
                 self.snapshot(7925, 'D210 9:00:00 AM'),
                 self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679), mode='unknown')]
        for snapshot in cases:
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.uncertain_waypoint()
                c = self.read_snapshot(c, snapshot)
                self.assertIsNotNone(c.surprise)
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640], 'walkable': True})
                self.assertEqual(len(self.port.inputs), 1)

    def test_read_rejects_model_supplied_state_or_action(self):
        c = self.uncertain_waypoint()
        for data in ({'action': {'money': 100, 'position': [1, 2]}}, {'correction': {'kind': 'human'}}):
            with self.subTest(data=data), self.assertRaises(turn.DecisionRejected):
                self.choose(c, 'read', **data)
        self.assertEqual(len(self.port.inputs), 1)

    def test_verified_save_movement_with_unknown_image_keeps_surprise_until_a_known_frame(self):
        c = self.uncertain_waypoint()
        original_id = c.last_outcome['id']
        snapshot = self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679), mode='unknown')
        c = self.read_snapshot(c, snapshot)
        self.assertTrue(c.last_outcome['evidence']['moved'])
        self.assertEqual(c.surprise.experience_id, original_id)
        snapshot['screen'] = {'kind': 'pause', 'texts': ['Resume Game']}
        c = self.read_snapshot(c, snapshot)
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)

    def test_incoherent_provenance_or_changed_lineage_cannot_reconcile(self):
        import copy
        valid = self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679))
        cases = []
        for changes in ('no_save_scene_proof', 'scene_disagrees', 'other_lineage', 'count_not_new', 'unattributed'):
            snapshot = copy.deepcopy(valid)
            if changes == 'no_save_scene_proof':
                del snapshot['state_provenance']['save_scene']
            elif changes == 'scene_disagrees':
                snapshot['scene'] = 'OtherScene'
            else:
                for proof in snapshot['state_provenance'].values():
                    if changes == 'other_lineage':
                        proof['path'] = '/other/saves/7925.local'
                    elif changes == 'count_not_new':
                        proof['save_count'] = 7923
                    else:
                        proof['source'] = 'model'
            cases.append(snapshot)
        for snapshot in cases:
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.uncertain_waypoint()
                c = self.read_snapshot(c, snapshot)
                self.assertIsNotNone(c.surprise)
                self.assertIsNone(c.last_outcome['evidence']['moved'])
                self.assertEqual(len(self.port.inputs), 1)

    def test_pending_capture_restart_is_reconciled_without_a_second_input(self):
        self.port.snapshot = self.snapshot()
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        self.port.fail = True
        with self.assertRaises(RuntimeError):
            self.choose(c, 'act', action={'kind': 'waypoint', 'point': [1250, 640],
                                         'walkable': True, 'expects': {'moved': True}})
        self.port.fail = False
        from game import experience as X
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='unknown'), ('black-full.jpg',))
        c = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertEqual(c.surprise.reason, 'pending_intent_reconciled')
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679)))
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)

    def test_authoritative_scene_transition_can_prove_physical_region_arrival(self):
        c = self.uncertain_waypoint()
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (1, 2), scene='Town'))
        self.assertIsNone(c.surprise)
        c = self.choose(c, 'complete')
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(len(self.port.inputs), 1)

    def test_save_delta_cannot_credit_uncertain_waypoint_when_another_input_shared_stale_baseline(self):
        from game import experience as X
        self.port.snapshot = self.snapshot()
        self.port.snapshot['game_time'] = 'D210 8:45:00 AM'
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='gameplay', moved=True,
                                               state=(('game_time', 'D210 8:46:00 AM'),)))
        action = {'kind': 'waypoint', 'point': [1250, 640], 'walkable': True, 'expects': {'moved': True}}
        c = self.choose(c, 'act', action=action)
        self.port.snapshot = self.snapshot()  # authoritative baseline still 8:40, after the earlier input
        self.port.capture = lambda intent, before, expects: primitives.experience(
            intent, before, expects, X.Evidence(mode='unknown'), ('black-full.jpg',))
        c = self.choose(c, 'act', action=action)
        c = self.read_snapshot(c, self.snapshot(7925, 'D210 9:00:00 AM', (58.928, -41.679)))
        self.assertIsNotNone(c.surprise, 'save delta may belong to the preceding waypoint')
        self.assertIsNone(c.last_outcome['evidence']['moved'])
        self.assertEqual(len(self.port.inputs), 2)

    def test_captured_source_frame_is_rendered_and_refused_turns_have_no_after_capture(self):
        import hashlib
        from PIL import Image
        frame = self.captured['preserved_frame']
        path = os.path.join(os.path.dirname(__file__), 'fixtures', 'play', os.path.basename(frame['path']))
        with open(path, 'rb') as stream:
            self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), frame['sha256'])
        with Image.open(path) as image:
            self.assertEqual(image.size, (1920, 1080))
            self.assertGreater(image.convert('L').getextrema()[1], 20)
        outcomes = {row['turn_id']: row['experience'] for row in self.captured['source_rows']
                    if row['phase'] == 'outcome'}
        self.assertEqual(outcomes[19]['verdict']['value'], 'hit')
        for tid in (20, 22):
            self.assertEqual(outcomes[tid]['verdict']['value'], 'unsafe')
            self.assertEqual(outcomes[tid]['artifacts']['frames'], [])
            self.assertEqual(outcomes[tid]['evidence']['state'], [])


class CapturedModeTransition(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn, where
        from objects.graph import Graph
        self.fixtures = os.path.join(os.path.dirname(__file__), 'fixtures', 'play')
        with open(os.path.join(self.fixtures, 'resume-mode-transition.json')) as stream:
            self.captured = json.load(stream)
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(where, 'walked', side_effect=AssertionError('UI transition is not world movement')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        from types import SimpleNamespace
        mock.patch.object(core, 'WF', SimpleNamespace(wait_settle=mock.Mock(), log_since=lambda mark: '',
            log_mark=lambda: 0,
            _unhash=lambda value: value, find_text=lambda *args, **kw: [{'cx': 960, 'cy': 460}],
            run_log=lambda *args, **kw: None)).start()

    def frame(self, name):
        return os.path.join(self.fixtures, self.captured['frames'][name]['file'])

    def test_source_frames_preserve_exact_full_scale_pause_unknown_and_gameplay_evidence(self):
        import hashlib
        from PIL import Image
        for name, frame in self.captured['frames'].items():
            with self.subTest(name=name), open(self.frame(name), 'rb') as stream:
                self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), frame['sha256'])
            with Image.open(self.frame(name)) as image:
                self.assertEqual(image.size, (1920, 1080))
        self.assertEqual(self.captured['task']['last_experience']['id'], 'd5d286a079fa9921')
        self.assertEqual(self.captured['task']['last_experience']['evidence']['texts'], ['lere'])
        self.assertEqual(self.captured['next_clues']['screen']['kind'], 'gameplay')

    def observation(self, name):
        import copy
        source = self.captured['task']['last_experience']
        state = copy.deepcopy(self.captured['intent']['before'] if name == 'pause' else dict(source['evidence']['state']))
        state['screen'] = (self.captured['intent']['before']['screen'] if name == 'pause' else
                           {'kind': source['evidence']['mode'], 'texts': source['evidence']['texts']}
                           if name == 'unknown' else self.captured['next_clues']['screen'])
        state.update(frame_path=self.frame(name), visible_affordances=[], graph_clues=[])
        return state

    def choose(self, c, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def test_captured_unknown_resume_capture_settles_once_more_without_repeating_input(self):
        self.port.snapshot = self.observation('pause')
        self.port.prepare = primitives.GameAdapter().prepare
        capture = primitives.GameAdapter()
        capture.observe = mock.Mock(side_effect=[self.observation('unknown'), self.observation('gameplay')])
        self.port.capture = capture.capture
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Resume Game', 'expects': {'mode': 'gameplay'}})
        self.assertEqual(c.last_outcome['verdict']['value'], 'hit')
        self.assertIsNone(c.surprise)
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(capture.observe.call_count, 2)
        self.assertEqual(list(c.last_outcome['artifacts']['frames']), [self.frame('unknown'), self.frame('gameplay')])
        samples = dict(c.last_outcome['evidence']['state'])['observation_samples']
        self.assertEqual([sample['screen']['kind'] for sample in samples], ['unknown', 'gameplay'])
        self.assertEqual(list(samples[0]['screen']['texts']), ['lere'])
        self.assertIsNone(c.last_outcome['evidence']['moved'], 'pause overlay disappearance is not Tara movement')

    def test_unknown_or_wrong_followup_observation_retains_mismatch_and_blocks_repeat(self):
        for final in ('unknown', 'pause'):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                self.port.snapshot = self.observation('pause')
                self.port.prepare = primitives.GameAdapter().prepare
                capture = primitives.GameAdapter()
                capture.observe = mock.Mock(side_effect=[self.observation('unknown'), self.observation(final)])
                self.port.capture = capture.capture
                c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
                action = {'kind': 'press', 'label': 'Resume Game', 'expects': {'mode': 'gameplay'}}
                c = self.choose(c, 'act', action=action)
                self.assertIsNotNone(c.surprise)
                self.assertEqual(capture.observe.call_count, 2, 'bounded observation only, never a capture loop')
                with self.assertRaises(turn.DecisionRejected):
                    self.choose(c, 'act', action=action)
                self.assertEqual(len(self.port.inputs), 1)

    def test_captured_existing_task_mode_mismatch_reconciles_from_fresh_expected_mode_without_input(self):
        from game import experience as X
        self.create_legacy_task(S.TaskState.from_dict(self.captured['task']))
        self.port.snapshot = self.observation('gameplay')
        self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
            X.Evidence(mode='gameplay', state=X._t(tuple(self.port.snapshot.items()))), (self.frame('gameplay'),))
        c = self.play().turn(store=self.store, adapter=self.port)
        original = S.thaw(c.last_outcome)
        stack = [(s.goal, s.params, s.status) for s in self.store.load().stack]
        self.assertEqual(c.turn_id, 25)
        c = self.choose(c, 'read')
        self.assertIsNone(c.surprise)
        proof = dict(c.last_outcome['evidence']['state'])['observation_reconciliation']
        self.assertEqual(proof['source_experience'], 'd5d286a079fa9921')
        self.assertEqual(proof['result'], 'verified_observation')
        self.assertIsNone(c.last_outcome['evidence']['moved'])
        self.assertEqual([(s.goal, s.params, s.status) for s in self.store.load().stack], stack)
        from game import history
        refs = self.store.load().stack[-1].evidence_refs
        rows = history.records(os.path.join(self.tmp.name, 'log.jsonl'), refs)
        self.assertEqual(next(row['experience'] for row in rows if row['experience']['id'] == original['id']), original)
        self.assertEqual(self.port.inputs, [])

    def test_fresh_wrong_mode_retains_original_failure_and_model_can_revise_from_captured_frames(self):
        from game import experience as X
        self.create_legacy_task(S.TaskState.from_dict(self.captured['task']))
        self.port.snapshot = self.observation('pause')
        self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
            X.Evidence(mode='pause', state=X._t(tuple(self.port.snapshot.items()))), (self.frame('pause'),))
        c = self.play().turn(store=self.store, adapter=self.port)
        c = self.choose(c, 'read')
        self.assertIsNotNone(c.surprise, 'current pause cannot prove the original expected gameplay mode')
        self.assertEqual(c.surprise.experience_id, 'd5d286a079fa9921')
        c = self.choose(c, 'correct', correction={'kind': 'revise_decision', 'data': {'reason':
            'The preserved outcome and next-turn frames show gameplay after Resume; a later safety pause is separate.'}},
            evidence_refs=[self.frame('unknown'), self.frame('gameplay')])
        self.assertIsNone(c.surprise)
        self.assertEqual(c.screen['kind'], 'pause')
        self.assertEqual(len(self.store.load().stack), 2)
        self.assertEqual(self.port.inputs, [])

    def test_mode_reconciliation_requires_all_other_original_expectations(self):
        from game import experience as X
        for extra in ({'region': 'Town'}, {'node': 'TownGate'}, {'events': ['arrival']}, {'moved': True}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                self.port.snapshot = self.observation('pause')
                self.port.prepare = primitives.GameAdapter().prepare
                self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
                    X.Evidence(mode='unknown', texts=('lere',)), (self.frame('unknown'),))
                c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
                c = self.choose(c, 'act', action={'kind': 'press', 'label': 'Resume Game',
                                                 'expects': dict(mode='gameplay', **extra)})
                self.port.snapshot = self.observation('gameplay')
                self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
                    X.Evidence(mode='gameplay', state=X._t(tuple(self.port.snapshot.items()))), (self.frame('gameplay'),))
                c = self.choose(c, 'read')
                self.assertIsNotNone(c.surprise)
                self.assertEqual(len(self.port.inputs), 1)


class CapturedMapRefusal(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        self.fixtures = os.path.join(os.path.dirname(__file__), 'fixtures', 'play')
        with open(os.path.join(self.fixtures, 'map-input-refusals.json')) as stream:
            self.captured = json.load(stream)
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        self.port.prepare = primitives.GameAdapter().prepare
        self.port.snapshot = next(row['intent']['before'] for row in self.captured['rows']
                                  if row['phase'] == 'intent' and row['turn_id'] == 34)

    def choose(self, c, kind, **data):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': kind, **data},
                                store=S.TaskStore(self.store.path), adapter=self.port)

    def test_documented_key_m_shorthand_issues_one_guarded_menu_input_through_public_cli(self):
        from game import experience as X
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
            X.Evidence(mode='map', state=(('region', 'Town'),)))
        result = self.cli(['play', 'turn_id=%s' % c.turn_id, 'answer=key:m'])
        self.assertIn('NEXT', result)
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(self.port.inputs[0]['command'], 'key:m')
        self.assertIsNotNone(self.store.load().last_surprise, 'shorthand cannot invent an expected map transition')

    def test_captured_json_key_field_is_refused_with_explicit_schema_diagnostic_and_no_input(self):
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        c = self.choose(c, 'act', action={'kind': 'key', 'key': 'm', 'expects': {'mode': 'map'}})
        self.assertEqual(c.last_outcome['verdict']['value'], 'unsafe')
        self.assertIn('label', c.last_outcome['verdict']['checks'][0]['got'])
        self.assertEqual(list(c.last_outcome['artifacts']['frames']), [])
        self.assertEqual(self.port.inputs, [])

    def test_captured_press_m_in_gameplay_remains_refused_without_ocr_or_actuation(self):
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        c = self.choose(c, 'act', action={'kind': 'press', 'label': 'M', 'expects': {'mode': 'map'}})
        self.assertEqual(c.last_outcome['verdict']['value'], 'unsafe')
        self.assertIn('named control blocked by gameplay', c.last_outcome['verdict']['checks'][0]['got'])
        self.assertEqual(self.port.inputs, [])

    def test_canonical_key_label_is_one_input_and_shorthand_does_not_enable_movement(self):
        from game import experience as X
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
            X.Evidence(mode='map', state=(('region', 'Town'),)))
        c = self.choose(c, 'act', action={'kind': 'key', 'label': 'm', 'expects': {'mode': 'map'}})
        self.assertIsNone(c.surprise)
        self.assertEqual([row['command'] for row in self.port.inputs], ['key:m'])
        for key in ('w', 'shift+m', ''):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
                self.cli(['play', 'turn_id=%s' % c.turn_id, 'answer=key:' + key], directory=directory)
                self.assertEqual(self.store.load().last_experience['verdict']['value'], 'unsafe')
                self.assertEqual(self.port.inputs, [])

    def test_exact_turn37_recovers_by_model_revision_without_map_retry_or_financial_change(self):
        self.create_legacy_task(S.TaskState.from_dict(self.captured['task']))
        self.port.snapshot = dict(self.port.snapshot, screen={'kind': 'pause', 'texts': ['Resume Game']})
        c = self.play().turn(store=self.store, adapter=self.port)
        before = self.store.load()
        self.assertEqual(c.turn_id, 37)
        c = self.choose(c, 'correct', correction={'kind': 'revise_decision', 'data': {'reason':
            'Both map requests were guard refusals before input; continue with model vision and visible roads.'}})
        after = self.store.load()
        self.assertIsNone(c.surprise)
        self.assertEqual(c.turn_id, 38)
        self.assertEqual(after.task_id, before.task_id)
        self.assertEqual([(s.goal, s.params, s.status) for s in after.stack],
                         [(s.goal, s.params, s.status) for s in before.stack])
        self.assertEqual(after.params, before.params)
        self.assertEqual(after.last_experience, before.last_experience)
        self.assertEqual(self.port.inputs, [])

    def test_captured_frames_are_identical_rendered_town_and_both_map_attempts_were_refused(self):
        import hashlib
        from PIL import Image, ImageStat
        self.assertEqual(len({frame['sha256'] for frame in self.captured['frames']}), 1)
        path = os.path.join(self.fixtures, self.captured['preserved_frame'])
        with open(path, 'rb') as stream:
            self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), self.captured['frames'][0]['sha256'])
        with Image.open(path) as image:
            self.assertEqual(image.size, (1920, 1080))
            self.assertGreater(ImageStat.Stat(image.convert('L')).mean[0], 20)
        for row in self.captured['rows']:
            if row['phase'] == 'outcome':
                self.assertEqual(row['experience']['verdict']['value'], 'unsafe')
                self.assertEqual(row['experience']['artifacts']['frames'], [])


class MapModalProof(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn, where
        from objects.graph import Graph
        self.fixtures = os.path.join(os.path.dirname(__file__), 'fixtures', 'play')
        with open(os.path.join(self.fixtures, 'map-modal-proof.json')) as stream:
            self.captured = json.load(stream)
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(where, 'walked', side_effect=AssertionError('UI observation cannot move Tara')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()

    def image(self, key):
        from PIL import Image
        return Image.open(os.path.join(self.fixtures, self.captured['frames'][key]['file'])).convert('RGB')

    def observe_image(self, key, pin, texts=()):
        from types import SimpleNamespace
        from game import act
        image = self.image(key)
        raw = SimpleNamespace(grab=lambda: image, classify=lambda frame: {'mode': 'overlay', 'text': list(texts)},
                              find_bubbles=lambda frame: [], map_pin=mock.Mock(return_value=pin))
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name):
            return primitives.GameAdapter().observe()

    def test_exact_town_frame_with_false_pin_clue_is_gameplay_and_canonical_map_key_is_allowed(self):
        # The old classifier promoted any pin-colored candidate, even when the frame is the captured Town road.
        observation = self.observe_image('town', (643, 615))
        self.assertEqual(observation['screen']['kind'], 'gameplay')
        action = primitives.GameAdapter().prepare({'kind': 'key', 'label': 'm'}, observation)
        self.assertEqual(action['command'], 'key:m')

    def test_generic_model_guidance_requires_learning_map_first_without_selecting_a_route(self):
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        guidance = ' '.join(c.recommendation.reasons)
        self.assertIn('map first', guidance)
        self.assertIn('farthest safe visible point', guidance)
        self.assertIsNone(c.recommendation.action, 'map-first guidance must not schedule a hidden navigation input')
        self.assertEqual(self.port.inputs, [])

    def test_indoor_navigation_guidance_exits_before_opening_the_map(self):
        self.port.snapshot = dict(self.port.snapshot, region='House')
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        guidance = ' '.join(c.recommendation.reasons)
        self.assertIn('exit the building', guidance)
        self.assertNotIn('map first', guidance)
        self.assertIsNone(c.recommendation.action)

        with self.assertRaisesRegex(ValueError, 'map unavailable indoors'):
            primitives.GameAdapter().prepare({'kind': 'key', 'label': 'm'}, self.port.snapshot)

    def test_surprise_guidance_surfaces_authoritative_mode_events_and_text(self):
        task = {'goal': 'sleep', 'params': {}, 'stack': [], 'last_surprise': {'actual': {
            'mode': 'dialogue', 'events': ['sleep11'], 'texts': ['Tara: Is it time for bed?']}}}
        recommendation = self.play().recommend(task, {'screen': {'kind': 'dialogue'}, 'region': 'House'})
        guidance = ' '.join(recommendation.reasons)
        self.assertIn('mode=dialogue', guidance)
        self.assertIn('events=sleep11', guidance)
        self.assertIn('Tara: Is it time for bed?', guidance)
        self.assertIn('do not infer no input', guidance)

    def test_confirmed_interaction_missing_vector_requests_model_appearance_sample(self):
        task = {'goal': 'sleep', 'params': {}, 'stack': []}
        observation = {'screen': {'kind': 'gameplay'}, 'region': 'House', 'graph_clues': [
            {'node': 'Bed', 'kind': 'Bed', 'appearance_needed': True,
             'interaction_hint': {'experience': 'exp-sleep', 'frame_path': 'bed.jpg'}}]}
        guidance = ' '.join(self.play().recommend(task, observation).reasons)
        self.assertIn('missing appearance sample for Bed', guidance)
        self.assertIn('model vision', guidance)
        self.assertIn('appearance correction', guidance)

    def test_guidance_surfaces_latest_authoritative_verdict_and_checks(self):
        task = {'goal': 'navigate', 'params': {'region': 'Town'}, 'stack': [], 'last_experience': {
            'id': 'move-proof', 'verdict': {'value': 'hit', 'checks': [
                {'field': 'moved', 'expected': True, 'got': True, 'ok': True}]},
            'evidence': {'mode': 'gameplay', 'events': [], 'moved': True}}}
        guidance = ' '.join(self.play().recommend(task, {'screen': {'kind': 'gameplay'}, 'region': 'Town'}).reasons)
        self.assertIn('latest outcome move-proof: verdict=hit', guidance)
        self.assertIn('moved expected=True got=True ok=True', guidance)

    def test_recognized_map_guidance_names_the_close_primitive_not_a_menu_key(self):
        self.port.snapshot = dict(self.port.snapshot, screen={'kind': 'map', 'texts': []})
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        guidance = ' '.join(c.recommendation.reasons)
        self.assertIn('close primitive', guidance)
        self.assertIn('not key:m or key:esc', guidance)
        self.assertIsNone(c.recommendation.action, 'the model still decides after inspecting the map')
        self.assertEqual(self.port.inputs, [])

    def test_true_captured_map_panel_remains_map_and_blocks_world_input(self):
        observation = self.observe_image('map', wf.map_pin(self.image('map')))
        self.assertEqual(observation['screen']['kind'], 'map')
        with self.assertRaisesRegex(ValueError, 'world input blocked by map'):
            primitives.GameAdapter().prepare({'kind': 'waypoint', 'point': [600, 650], 'walkable': True}, observation)

    def test_valid_hud_clock_proves_world_under_stray_ocr_without_affordances(self):
        from types import SimpleNamespace
        from game import act, observe
        image = self.image('town')
        raw = SimpleNamespace(grab=lambda: image,
                              classify=lambda frame: {'mode': 'overlay', 'text': ['pre']},
                              game_hour=wf.game_hour,
                              map_pin=lambda frame: None,
                              game_stamp=lambda: 'D212 9:10:00 AM')
        with mock.patch.object(core, 'WF', raw), mock.patch.object(observe, 'scan', return_value=[]), \
                mock.patch.object(act, 'frames_dir', return_value=self.tmp.name):
            observation = primitives.GameAdapter().observe()
        self.assertEqual(observation['screen']['kind'], 'gameplay')

    def test_true_map_with_unrecognized_ocr_still_uses_panel_proof_and_blocks_world_input(self):
        observation = self.observe_image('map', wf.map_pin(self.image('map')), texts=['island'])
        self.assertEqual(observation['screen']['kind'], 'map')
        with self.assertRaisesRegex(ValueError, 'world input blocked by map'):
            primitives.GameAdapter().prepare({'kind': 'target', 'point': [900, 500], 'visible_road': True}, observation)

    def test_exact_turn49_refresh_then_resume_then_first_canonical_map_action_preserves_sale_and_finances(self):
        from types import SimpleNamespace
        from game import experience as X
        self.create_legacy_task(S.TaskState.from_dict(self.captured['task']))
        self.port.prepare = primitives.GameAdapter().prepare
        base = {'frame_path': 'current-full.jpg', 'visible_affordances': [], 'graph_clues': [], 'interrupts': [],
                'region': 'Town', 'scene': 'Town'}
        self.port.snapshot = dict(base, screen={'kind': 'pause', 'texts': ['Resume Game']})
        def capture(intent, before, expects):
            if intent.action.get('label') == 'Resume Game':
                self.port.snapshot = dict(base, screen={'kind': 'gameplay', 'texts': []})
            if intent.action.get('kind') == 'key':
                self.port.snapshot = dict(base, screen={'kind': 'map', 'texts': []})
            return primitives.experience(intent, before, expects,
                X.Evidence(mode=self.port.snapshot['screen']['kind'], state=X._t(tuple(self.port.snapshot.items()))))
        self.port.capture = capture
        raw = SimpleNamespace(find_text=lambda *args, **kw: [{'cx': 960, 'cy': 460}],
                              run_log=lambda *args, **kw: None)
        with mock.patch.object(core, 'WF', raw):
            play = self.play()
            c = play.turn(store=self.store, adapter=self.port)
            self.assertEqual(c.turn_id, 49)
            before = self.store.load()
            c = play.turn(answer={'turn_id': 49, 'kind': 'read'}, store=self.store, adapter=self.port)
            self.assertEqual(c.screen['kind'], 'pause')
            self.assertEqual(self.port.inputs, [])
            c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {
                'kind': 'press', 'label': 'Resume Game', 'expects': {'mode': 'gameplay'}}}, store=self.store, adapter=self.port)
            c = play.turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {
                'kind': 'key', 'label': 'm', 'expects': {'mode': 'map'}}}, store=self.store, adapter=self.port)
            self.assertEqual(c.screen['kind'], 'map')
            self.assertIsNone(c.surprise)
            after = self.store.load()
            self.assertEqual(after.task_id, before.task_id)
            self.assertEqual([(s.goal, s.params, s.status) for s in after.stack],
                             [(s.goal, s.params, s.status) for s in before.stack])
            self.assertEqual(after.params, before.params)
            self.assertEqual([row['command'] for row in self.port.inputs], ['text:Resume Game', 'key:m'])

    def test_frame_fixture_hashes_are_full_scale_and_historical_map_is_not_current_live_proof(self):
        import hashlib
        for key, frame in self.captured['frames'].items():
            path = os.path.join(self.fixtures, frame['file'])
            with open(path, 'rb') as stream:
                self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), frame['sha256'])
            self.assertEqual(self.image(key).size, (1920, 1080))
        self.assertIn('historical', self.captured['provenance_note'])


class ExpectationValidation(PlayCase):
    def setUp(self):
        super().setUp()
        from game import learn
        from objects.graph import Graph
        self.fixtures = os.path.join(os.path.dirname(__file__), 'fixtures', 'play')
        with open(os.path.join(self.fixtures, 'bubble-boolean-expectation.json')) as stream:
            self.captured = json.load(stream)
        mock.patch.dict(learn.MEMORY, graph=Graph()).start()
        mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')).start()
        mock.patch.object(eval_store, 'ENABLED', False).start()
        self.port.snapshot = self.captured['task']['active']['pending_intent']['before']
        self.port.prepare = primitives.GameAdapter().prepare

    def choose(self, c, **action):
        return self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': action},
                                store=self.store, adapter=self.port)

    def test_boolean_card_is_rejected_before_input_even_when_the_bubble_preparation_would_succeed(self):
        from game import experience as X
        self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
            X.Evidence(mode='card', texts=('Sleep',)))
        for road in (False, True):
            with self.subTest(visible_road=road), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.play().turn('sleep', store=self.store, adapter=self.port)
                with self.assertRaisesRegex(turn.DecisionRejected, 'card'):
                    self.choose(c, kind='bubble', point=[728, 488], visible_road=road, expects={'card': True})
                self.assertEqual(self.port.inputs, [])
                task = self.store.load()
                self.assertIsNone(task.pending_intent)
                self.assertFalse(task.active and task.active.pending_intent)
                self.assertEqual(task.current_turn['turn_id'], c.turn_id)

    def test_malformed_expectations_cannot_reach_observation_or_physical_input(self):
        cases = [True, [], {'card': False}, {'card': 1}, {'card': []}, {'mode': True}, {'moved': 'true'},
                 {'events': 'water'}, {'events': [True]}, {'allowed_events': 'water'}, {'log': '['},
                 {'node': 1}, {'destination_position': [True, 1]}, {'unknown': True}]
        for expects in cases:
            with self.subTest(expects=expects), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                c = self.play().turn('sleep', store=self.store, adapter=self.port)
                with mock.patch.object(self.port, 'observe', side_effect=AssertionError('invalid expectation observed game')):
                    with self.assertRaises(turn.DecisionRejected):
                        self.choose(c, kind='bubble', point=[728, 488], visible_road=True, expects=expects)
                self.assertEqual(self.port.inputs, [])

    def test_text_card_or_question_gap_are_supported_without_boolean_normalization(self):
        from game import experience as X
        for expected in ('Sleep', '?'):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.port.inputs.clear()
                self.port.capture = lambda intent, before, expects: primitives.experience(intent, before, expects,
                    X.Evidence(mode='card', texts=('Sleep',)))
                c = self.play().turn('sleep', store=self.store, adapter=self.port)
                c = self.choose(c, kind='bubble', point=[728, 488], visible_road=True,
                                expects={'card': expected, 'log': '?'})
                self.assertEqual(len(self.port.inputs), 1)
                self.assertEqual(c.last_outcome['prediction']['card'], expected)
                self.assertNotEqual(c.last_outcome['verdict']['value'], 'unsafe')

    def test_exact_legacy_pending_recovers_as_unknown_without_replay_and_keeps_stack(self):
        from game import experience as X
        from types import SimpleNamespace
        self.create_legacy_task(S.TaskState.from_dict(self.captured['task']))
        adapter = primitives.GameAdapter()
        adapter.observe = mock.Mock(return_value=dict(self.port.snapshot, screen={'kind': 'pause', 'texts': ['Resume Game']}))
        adapter.capture = mock.Mock(side_effect=lambda intent, before, expects:
            primitives.experience(intent, before, expects, X.Evidence(mode='pause', texts=('Resume Game',))))
        raw = SimpleNamespace(run_action=mock.Mock(side_effect=AssertionError('must never replay input')),
                              run_log=lambda *args, **kw: None)
        with mock.patch.object(core, 'WF', raw):
            self.store.compact()
            before = self.store.load()
            c = self.play().turn(store=self.store, adapter=adapter)
            after = self.store.load()
        self.assertEqual(c.turn_id, 161)
        self.assertEqual(after.task_id, before.task_id)
        self.assertEqual([(s.goal, s.params, s.status) for s in after.stack],
                         [(s.goal, s.params, s.status) for s in before.stack])
        self.assertIsNone(after.active.pending_intent)
        self.assertEqual(c.last_outcome['verdict']['value'], 'unsafe')
        proof = dict(c.last_outcome['evidence']['state'])['invalid_expectations']
        self.assertEqual(proof['original'], {'card': True})
        self.assertEqual(proof['input_status'], 'unknown', 'current adapter cannot establish the legacy origin')
        self.assertIsNotNone(c.surprise)
        self.assertEqual(adapter.capture.call_count, 1)
        self.assertEqual(adapter.capture.call_args.args[2], {})
        raw.run_action.assert_not_called()
        self.assertEqual(after.params, before.params)
        again = self.play().turn(store=self.store, adapter=adapter)
        self.assertEqual(again.turn_id, c.turn_id)
        self.assertEqual(self.store.load().stack[-1].evidence_refs, after.stack[-1].evidence_refs)
        with self.assertRaises(turn.DecisionRejected):
            self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'act', 'action': {'kind': 'bubble',
                'point': [728, 488], 'visible_road': True}}, store=self.store, adapter=adapter)

    def test_legacy_custom_input_restarted_with_game_adapter_cannot_be_reclassified_not_issued(self):
        from game import experience as X, params
        from types import SimpleNamespace
        self.port.prepare = lambda action, before: action  # legacy custom port permits command-less inputs
        c = self.play().turn('sleep', store=self.store, adapter=self.port)
        with mock.patch.object(params, 'expectations', side_effect=lambda value: value):
            with self.assertRaises(AttributeError):
                self.choose(c, kind='bubble', point=[728, 488], expects={'card': True})
        self.assertEqual(len(self.port.inputs), 1, 'the originating adapter actually performed this legacy action')
        legacy = self.store.load().to_dict()
        legacy['active']['pending_intent'].pop('provenance', None)  # old writer had no origin schema
        self.store.save(S.TaskState.from_dict(legacy))
        adapter = primitives.GameAdapter()
        adapter.observe = mock.Mock(return_value=self.port.snapshot)
        adapter.capture = mock.Mock(side_effect=lambda intent, before, expects:
            primitives.experience(intent, before, expects, X.Evidence(mode='card', texts=('Sleep',))))
        raw = SimpleNamespace(run_action=mock.Mock(side_effect=AssertionError('input replayed')),
                              run_log=lambda *args, **kw: None)
        with mock.patch.object(core, 'WF', raw):
            c = self.play().turn(store=self.store, adapter=adapter)
        proof = dict(c.last_outcome['evidence']['state'])['invalid_expectations']
        self.assertEqual(proof['input_status'], 'unknown')
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(adapter.capture.call_count, 1)
        raw.run_action.assert_not_called()
        self.assertIsNotNone(c.surprise)

    def test_durable_origin_refusal_survives_adapter_change_without_claiming_adapter_identity_proof(self):
        from game import params
        from types import SimpleNamespace
        c = self.play().turn('sleep', store=self.store, adapter=self.port)
        with mock.patch.object(params, 'expectations', side_effect=lambda value: value):
            with self.assertRaises(AttributeError):
                self.choose(c, kind='bubble', point=[728, 488], expects={'card': True})
        self.assertEqual(self.port.inputs, [], 'this producer refused before perform')
        source = self.store.load().active.pending_intent
        self.assertEqual(source.provenance['preparation'], 'refused')
        self.assertTrue(source.provenance['refusal'])
        adapter = primitives.GameAdapter()
        adapter.observe = mock.Mock(return_value=self.port.snapshot)
        adapter.capture = mock.Mock(side_effect=AssertionError('durable refusal needs no action capture'))
        raw = SimpleNamespace(run_action=mock.Mock(side_effect=AssertionError('refused input replayed')),
                              run_log=lambda *args, **kw: None)
        with mock.patch.object(core, 'WF', raw):
            c = self.play().turn(store=self.store, adapter=adapter)
        proof = dict(c.last_outcome['evidence']['state'])['invalid_expectations']
        self.assertEqual(proof['input_status'], 'not_issued')
        self.assertEqual(S.thaw(proof['intent_provenance']), source.provenance)
        adapter.capture.assert_not_called()
        raw.run_action.assert_not_called()

    def test_incomplete_or_prepared_origin_never_proves_not_issued_after_restart(self):
        from game import experience as X
        from types import SimpleNamespace
        complete = {'boundary': 'primitives.execute/v1', 'adapter': 'legacy.Custom',
                    'preparation': 'refused', 'refusal': 'blocked road'}
        cases = [dict(complete, preparation='prepared', refusal=None), {'preparation': 'refused'},
                 dict(complete, boundary='unversioned'), dict(complete, adapter=''), dict(complete, refusal='')]
        for origin in cases:
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as directory:
                task = S.TaskState.from_dict(self.captured['task'])
                task.active.pending_intent.provenance = origin
                self.store = S.TaskStore(os.path.join(directory, 'task.json'))
                self.create_legacy_task(task)
                adapter = primitives.GameAdapter()
                adapter.observe = mock.Mock(return_value=self.port.snapshot)
                adapter.capture = mock.Mock(side_effect=lambda intent, before, expects:
                    primitives.experience(intent, before, expects, X.Evidence(mode='pause', texts=('Resume Game',))))
                raw = SimpleNamespace(run_action=mock.Mock(side_effect=AssertionError('input replayed')),
                                      run_log=lambda *args, **kw: None)
                with mock.patch.object(core, 'WF', raw):
                    c = self.play().turn(store=self.store, adapter=adapter)
                self.assertEqual(dict(c.last_outcome['evidence']['state'])['invalid_expectations']['input_status'], 'unknown')
                self.assertEqual(adapter.capture.call_count, 1)
                raw.run_action.assert_not_called()

    def test_malformed_pending_with_prepared_command_is_observed_as_uncertain_never_retried(self):
        from game import experience as X
        from types import SimpleNamespace
        task = S.TaskState.from_dict(self.captured['task'])
        task.active.pending_intent.action.update(command='click:728:488', visible_road=True)
        self.create_legacy_task(task)  # distinct legacy fixture: a physical input could have happened
        adapter = primitives.GameAdapter()
        adapter.observe = mock.Mock(return_value=self.port.snapshot)
        adapter.capture = mock.Mock(side_effect=lambda intent, before, expects:
            primitives.experience(intent, before, expects, X.Evidence(mode='card', texts=('Sleep',))))
        raw = SimpleNamespace(run_action=mock.Mock(side_effect=AssertionError('uncertain input replayed')),
                              run_log=lambda *args, **kw: None)
        with mock.patch.object(core, 'WF', raw):
            c = self.play().turn(store=self.store, adapter=adapter)
        self.assertIsNotNone(c.surprise)
        self.assertEqual(dict(c.last_outcome['evidence']['state'])['invalid_expectations']['input_status'], 'unknown')
        self.assertEqual(adapter.capture.call_count, 1)
        self.assertEqual(adapter.capture.call_args.args[2], {})
        raw.run_action.assert_not_called()

    def test_custom_adapter_missing_command_does_not_claim_production_preinput_proof(self):
        from game import experience as X
        self.create_legacy_task(S.TaskState.from_dict(self.captured['task']))
        self.port.capture = mock.Mock(side_effect=lambda intent, before, expects:
            primitives.experience(intent, before, expects, X.Evidence(mode='card', texts=('Sleep',))))
        c = self.play().turn(store=self.store, adapter=self.port)
        self.assertEqual(dict(c.last_outcome['evidence']['state'])['invalid_expectations']['input_status'], 'unknown')
        self.assertEqual(self.port.capture.call_count, 1)
        self.assertEqual(self.port.inputs, [])

    def test_malformed_card_cli_refuses_without_a_pending_intent_or_input(self):
        c = self.play().turn('sleep', store=self.store, adapter=self.port)
        with self.assertRaises(SystemExit) as failure:
            self.cli(['play', 'turn_id=%s' % c.turn_id,
                'answer={"kind":"act","action":{"kind":"bubble","point":[728,488],"visible_road":true,"expects":{"card":true}}}'])
        self.assertEqual(failure.exception.code, 1)
        self.assertEqual(self.port.inputs, [])
        task = self.store.load()
        self.assertIsNone(task.pending_intent)
        self.assertFalse(task.active and task.active.pending_intent)


class ReadLatency(PlayCase):
    def native_adapter(self):
        from types import SimpleNamespace
        from PIL import Image
        from game import act, observe, screen
        grabs = mock.Mock(side_effect=lambda: Image.new('RGB', (1920, 1080), '#808080'))
        waits, inputs = mock.Mock(), mock.Mock(return_value=None)
        raw = SimpleNamespace(grab=grabs, wait_settle=waits, log_mark=lambda: 0,
                              log_since=lambda mark: '', _unhash=lambda text: text,
                              run_action=inputs, game_stamp=lambda: 'D211 12:25:04 PM')
        mock.patch.object(core, 'WF', raw).start()
        mock.patch.object(act, 'frames_dir', return_value=self.tmp.name).start()
        mock.patch.object(observe, 'scan', return_value=[]).start()
        mock.patch.object(screen, 'read', return_value=screen.Screen('gameplay', [])).start()
        return primitives.GameAdapter(lambda: {'graph_clues': [{'node': 'current-source'}]}), grabs, waits, inputs

    def test_public_native_read_uses_one_coherent_snapshot_for_outcome_and_next(self):
        adapter, grabs, waits, inputs = self.native_adapter()
        c = self.play().turn('sleep', store=self.store, adapter=adapter)
        grabs.reset_mock(); waits.reset_mock()
        fresh = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'read'},
                                 store=self.store, adapter=adapter)
        self.assertEqual(grabs.call_count, 1, 'read repeated native capture/perception/clues')
        waits.assert_not_called()  # no physical action to settle
        inputs.assert_not_called()
        e = self.store.load().last_experience
        self.assertEqual(e['action']['kind'], 'read')
        self.assertIsNone(e['evidence']['moved'])  # one snapshot has no before/after movement comparison
        self.assertEqual(e['artifacts']['frames'], [fresh.frame_path])
        self.assertEqual(dict(e['evidence']['state'])['frame_path'], fresh.frame_path)
        self.assertEqual(fresh.graph_clues[0]['node'], 'current-source')
        self.assertNotEqual(c.frame_path, fresh.frame_path)
        # A new physical action still takes a new pre-input snapshot; the lease cannot cross decisions.
        grabs.reset_mock()
        after_action = self.play().turn(answer={'turn_id': fresh.turn_id, 'kind': 'act', 'action':
                                      {'kind': 'waypoint', 'point': [900, 650], 'walkable': True}},
                                      store=self.store, adapter=adapter)
        self.assertEqual(grabs.call_count, 2, 'physical action repeated the post-action observation for NEXT')
        self.assertEqual(inputs.call_count, 1)
        outcome = self.store.load().last_experience
        self.assertEqual(after_action.frame_path, outcome['artifacts']['frames'][-1])
        self.assertEqual(dict(outcome['evidence']['state'])['frame_path'], after_action.frame_path)

    def test_native_read_preserves_black_guard_and_one_bounded_reobservation(self):
        from PIL import Image
        adapter, grabs, waits, inputs = self.native_adapter()
        c = self.play().turn('sleep', store=self.store, adapter=adapter)
        grabs.reset_mock(); waits.reset_mock()
        grabs.side_effect = lambda: Image.new('RGB', (1920, 1080), 'black')
        fresh = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'read'},
                                 store=self.store, adapter=adapter)
        self.assertEqual(grabs.call_count, 2)
        self.assertEqual(waits.call_count, 1)
        inputs.assert_not_called()
        self.assertEqual(fresh.screen['kind'], 'unknown')
        e = self.store.load().last_experience
        self.assertIsNone(e['evidence']['moved'])
        self.assertEqual(dict(e['evidence']['state'])['capture_validity'], 'black')
        self.assertEqual(len(e['artifacts']['frames']), 2)
        self.assertEqual(e['artifacts']['frames'][-1], fresh.frame_path)
        self.assertEqual(e['verdict']['value'], 'unknown')

    def test_restart_pending_read_recaptures_instead_of_reusing_historical_before(self):
        adapter, grabs, waits, inputs = self.native_adapter()
        c = self.play().turn('sleep', store=self.store, adapter=adapter)
        task = self.store.load()
        task.pending_intent = S.Intent(c.turn_id, {'kind': 'read'}, 0, 0.,
                                      {'screen': {'kind': 'map'}, 'frame_path': c.frame_path})
        self.store.save(task)
        # New adapter has no in-process capture receipt for this old before snapshot.
        adapter = primitives.GameAdapter(lambda: {'graph_clues': [{'node': 'restart-source'}]})
        grabs.reset_mock()
        fresh = self.play().turn(store=self.store, adapter=adapter)
        e = self.store.load().last_experience
        self.assertEqual(e['evidence']['mode'], 'gameplay')
        self.assertNotEqual(e['artifacts']['frames'][0], c.frame_path)
        self.assertIsNotNone(fresh.surprise)
        self.assertGreaterEqual(grabs.call_count, 1)
        inputs.assert_not_called()

    def test_freezing_runtime_state_preserves_complete_immutable_evidence_without_intermediate_serialization(self):
        from collections.abc import Mapping
        task = S.TaskState('snapshot', 'sleep', params={'evidence': [{'source': ['frame', 3]}]},
                           active=S.Interaction('i', pending_intent=S.Intent(1, {'kind': 'read'}, 0, 0.)))
        expected = S.freeze(task.to_dict())
        with mock.patch.object(S.TaskState, 'to_dict', side_effect=AssertionError('snapshot serialized intermediate history')):
            snapshot = S.freeze(task)
        self.assertIsInstance(snapshot, Mapping)
        self.assertEqual(snapshot, expected)
        task.params['evidence'][0]['source'][1] = 9
        self.assertEqual(snapshot['params']['evidence'][0]['source'][1], 3)
        with self.assertRaises(TypeError):
            snapshot['active']['pending_intent']['action']['kind'] = 'press'

    def test_versioned_read_does_not_materialize_a_second_full_cached_context(self):
        c = self.play().turn('navigate', {'region': 'Town'}, store=self.store, adapter=self.port)
        with mock.patch.object(turn.TurnContext, 'from_dict', side_effect=AssertionError('read copied cached context')):
            fresh = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'read'},
                                     store=self.store, adapter=self.port)
        self.assertEqual(fresh.turn_id, c.turn_id + 1)
        self.assertEqual(self.port.inputs, [])

    def test_state_snapshot_subclasses_keep_the_same_immutable_contract(self):
        from dataclasses import dataclass, field
        from collections.abc import Mapping
        @dataclass
        class ExtendedState(S.TaskState):
            extra: dict = field(default_factory=lambda: {'proof': [1, 2]})
        task = ExtendedState('extended', 'sleep')
        snapshot = S.freeze(task)
        self.assertIsInstance(snapshot, Mapping)
        task.extra['proof'].append(3)
        self.assertEqual(snapshot['extra']['proof'], (1, 2))

    def test_public_next_is_bounded_and_labels_fresh_vs_cached_observation(self):
        refs = [f'experience-{n}' for n in range(100)]
        self.store.create(S.TaskState('bounded', 'sleep', evidence_refs=refs))
        fresh = self.play().turn(store=self.store, adapter=self.port)
        self.assertTrue(hasattr(fresh, 'observation_freshness'),
                        'TurnContext does not distinguish a fresh observation from cached context')
        self.assertEqual(fresh.observation_freshness, 'fresh')
        cached = self.play().turn(store=S.TaskStore(self.store.path), adapter=self.port)
        self.assertEqual(cached.observation_freshness, 'cached')
        self.assertEqual(cached.turn_id, fresh.turn_id)
        self.assertLess(len(self.play().summary(cached)), 100_000)
        self.assertLess(os.path.getsize(self.store.path), 100_000)

        newer = self.play().turn(answer={'turn_id': cached.turn_id, 'kind': 'read'},
                                 store=self.store, adapter=self.port)
        self.assertEqual(newer.observation_freshness, 'fresh')
        self.assertLess(os.path.getsize(self.store.path), 100_000)
        self.assertEqual(self.port.inputs, [])

        self.play().turn(answer={'turn_id': newer.turn_id, 'kind': 'act', 'action': {'kind': 'space'}},
                         store=self.store, adapter=self.port)
        self.assertLess(os.path.getsize(self.store.path), 100_000,
                        'one physical action re-embedded journal history into durable state')
        self.assertEqual(len(self.port.inputs), 1)

    def test_public_zero_input_read_does_not_copy_financial_guard_state(self):
        c = self.play().turn('sleep', store=self.store, adapter=self.port)
        with mock.patch.object(self.play(), 'guard', side_effect=AssertionError('pure read entered input guard')):
            fresh = self.play().turn(answer={'turn_id': c.turn_id, 'kind': 'read'},
                                     store=self.store, adapter=self.port)
        self.assertEqual(fresh.turn_id, c.turn_id + 1)
        self.assertEqual(self.port.inputs, [])
        # An act labelled read with financial metadata must still enter the ordinary guard and refuse.
        with self.assertRaisesRegex(AssertionError, 'financial metadata remains guarded'), \
             mock.patch.object(self.play(), 'guard', side_effect=AssertionError('financial metadata remains guarded')):
            self.play().turn(answer={'turn_id': fresh.turn_id, 'kind': 'act', 'action':
                {'kind': 'read', 'sale': {'item': 'Any', 'quantity': 1, 'price': 1}}},
                store=self.store, adapter=self.port)
        self.assertEqual(self.port.inputs, [])

    def test_atomic_persistence_does_not_write_once_per_evidence_scalar(self):
        original = S.os.fdopen
        writes = []
        class CountWrites:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def write(self, value):
                writes.append(len(value))
                return self.stream.write(value)
        task = S.TaskState('large', 'navigate', params={'_outcomes': [
            {'text': 'complete captured evidence', 'position': [n, n + 1]} for n in range(1000)]})
        with mock.patch.object(S.os, 'fdopen', side_effect=lambda *args, **kw: CountWrites(original(*args, **kw))):
            self.store.create(task)
        self.assertLessEqual(len(writes), 2, 'task persistence amplified writes by evidence scalar count')
        self.assertEqual(self.store.load().to_dict(), task.to_dict())

    def test_cached_context_does_not_serialize_full_history_for_parameter_routing(self):
        task = S.TaskState('latency', 'navigate', params={'region': 'Town', '_trade_start_money': 100,
            '_outcomes': [{'historical_evidence': list(range(1000))}]})
        self.store.create(task)
        c = self.play().turn(store=self.store, adapter=self.port)
        with mock.patch.object(S.TaskState, 'to_dict', side_effect=AssertionError('metadata routing copied full history')), \
             mock.patch.object(self.port, 'observe', side_effect=AssertionError('cached read captured game')):
            again = self.play().turn(store=self.store, adapter=self.port)
        self.assertEqual({k: v for k, v in again.to_dict().items() if k != 'observation_freshness'},
                         {k: v for k, v in c.to_dict().items() if k != 'observation_freshness'})
        self.assertEqual(again.observation_freshness, 'cached')
        self.assertEqual(self.port.inputs, [])

    def test_interrupt_clues_use_current_declarations_without_copying_evidence_history(self):
        from types import SimpleNamespace
        from objects.graph import Graph
        from game import observe, ask
        self.store.create(S.TaskState('latency', 'navigate', params={'region': 'Town', '_started_late': True,
            '_outcomes': [{'historical_evidence': list(range(1000))}]}))
        save = {'saveCount': 1, 'currentScene': 'Town', 'gameState': {'player': {'inventory': {'items': []}}}}
        today_log = mock.Mock(return_value=(['[D9 7:00:00 AM] Forecast is Raining'], 9, []))
        raw = SimpleNamespace(read_save=lambda: ('source.save', save), today_log=today_log,
                              current_scene=mock.Mock(side_effect=AssertionError('clues reread scene log')),
                              grab=mock.Mock(side_effect=AssertionError('clues captured a second frame')))
        with mock.patch.object(core, 'WF', raw), mock.patch.object(engine, '_open_graph', return_value=Graph()), \
             mock.patch.object(observe, 'clock', side_effect=AssertionError('clues captured clock separately')), \
             mock.patch.object(ask, 'rain', side_effect=AssertionError('clues reread forecast log')), \
             mock.patch.object(S.TaskState, 'to_dict', side_effect=AssertionError('interrupt check copied full history')):
            clues = self.play()._clues(self.store, {'hour': 20, 'light': 'night'})
        self.assertIn('SLEEP_REQUIRED', clues['interrupts'][0])
        self.assertEqual(clues['rain'], 'Raining')
        today_log.assert_called_once_with()


class Play(PlayCase):
    def test_every_public_gameplay_alias_returns_before_input(self):
        # A public alias choosing a hidden follow-up would emit input or enter the legacy focus path.
        for argv in ALIASES:
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as directory:
                output = self.cli(argv, directory)
                self.assertIn('NEXT ', output)
                context = json.loads(output.split('NEXT ', 1)[1])
                self.assertIn('view', context)
                self.assertIn('result', context)
                self.assertIn('memory', context)
                self.assertIn('vector_detections', context)
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
