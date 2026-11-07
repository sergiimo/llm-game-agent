"""The garden public boundary: one model decision, durable evidence, no hidden scheduler."""
import json
import os
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from game import core, engine, experience as X, integrate, learn, primitives
from game.task_state import TaskStore, TaskState, Interaction
from objects.graph import Graph, Node
from game.turn import Decision, DecisionRejected


class GardenTurns(unittest.TestCase):
    def test_captured_seed_shortage_blocks_only_actual_target_and_continues_after_restart(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'garden', 'empty-seeds-blocked-target.json')
        with open(fixture) as f:
            captured = json.load(f)
        next_record = event('water')
        next_record['evidence']['lines'] = ['[D209 5:00:00 PM] > water me=Player target=GardenBed(Clone) at (6.39, 0.10, -66.86)']
        store, port, _ = self.session([event(), next_record])
        store.save(TaskState.from_dict(captured['task']))
        graph = learn.MEMORY['graph']
        graph.nodes.clear()
        for nid in captured['task']['targets']:
            graph.nodes[nid] = Node(nid, 'member', 'GardenBed', region='GardenSouth',
                                   pos=[float(v) for v in nid.split('#')[1].split(',')], scene='Farm')
        def call(**kw):
            return engine.garden_turn(region='GardenSouth', store=TaskStore(store.path), adapter=port, **kw)
        port.snapshot = captured['observation']
        c = call()
        before = store.load().to_dict()
        try:
            c = call(turn_id=c.turn_id, decision=Decision('correct', correction={
                'kind': 'blocked_target', 'data': {'node': 'GardenBed#2.6,-66.9',
                                                  'reason': 'Seeds picker is empty; buying is not authorized'}},
                rationale='resource_constraint', evidence_refs=('650e42170a9375b7', c.frame_path)))
        except ValueError as error:
            self.fail(f'per-target blocked resolution must be supported: {error}')
        saved = TaskStore(store.path).load()
        self.assertEqual(saved.task_id, before['task_id'])
        self.assertEqual(saved.status, 'active')
        self.assertIsNone(saved.active)
        self.assertEqual(saved.covered, before['covered'])
        blocked, = saved.unresolved
        self.assertEqual((blocked['node'], blocked['phase'], blocked['crop']),
                         ('GardenBed#2.6,-66.9', 'plant', 'Tulip'))
        self.assertEqual(blocked['transaction_id'], before['active']['transaction_id'])
        self.assertIn(captured['observation']['frame_path'], blocked['evidence_refs'])
        self.assertEqual(blocked['experience'], '650e42170a9375b7')
        self.assertEqual(port.inputs, [])
        self.assertEqual(integrate.journal(), [])
        self.assertFalse(any(n.state for n in graph.nodes.values()), 'absence must not teach planted/watered facts')
        restarted = call()
        self.assertEqual(restarted.turn_id, c.turn_id)
        self.assertEqual(c.recommendation.action['kind'], 'close')
        c = call(turn_id=c.turn_id, decision=Decision('accept'))  # explicit close, no phantom interaction
        self.assertIsNone(c.transaction)
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        self.assertEqual(c.transaction['actual_node'], 'GardenBed#6.4,-66.9')
        self.assertNotEqual(c.transaction['transaction_id'], before['active']['transaction_id'])
        self.assertEqual(store.load().unresolved, [blocked])

    def test_covered_or_blocked_targets_finish_accounting_as_constrained(self):
        import runwatch
        store, port, call = self.session([event('harvest', 'A', ['Inventory', 'Seeds']), event(), event('water', 'B')])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target('Tulip')))
        try:
            c = call(turn_id=c.turn_id, decision=Decision('correct', correction={
                'kind': 'blocked_target', 'data': {'node': 'A', 'reason': 'no authorized seed available'}}))
        except ValueError as error:
            self.fail(f'per-target blocked resolution must be supported: {error}')
        self.assertEqual(c.task['status'], 'active')
        c = call(turn_id=c.turn_id, decision=Decision('accept'))  # close empty picker
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        c = call(turn_id=c.turn_id, decision=Decision('accept'))  # verify B
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(list(c.coverage['covered']), ['B'])
        self.assertEqual(c.coverage['unresolved'][0]['node'], 'A')
        with open(os.path.join(os.path.dirname(store.path), 'log.jsonl')) as f:
            report = runwatch.garden_table([json.loads(line) for line in f])
        self.assertIn('| Garden | 2 | 1 | 1 | - | A: no authorized seed available | CONSTRAINED |', report)

    def test_blocked_target_requires_event_owned_identity_and_nonempty_reason(self):
        for positioned, data in [(False, {'node': 'A', 'reason': 'no seeds'}),
                                 (True, {'node': 'B', 'reason': 'no seeds'}),
                                 (True, {'node': 'A', 'reason': ''})]:
            with self.subTest(positioned=positioned, data=data):
                store, port, call = self.session([event('harvest' if positioned else None, 'A', ['Inventory', 'Seeds'])])
                c = call()
                c = call(turn_id=c.turn_id, decision=Decision('act', action={**target(), 'projected_node': 'A'}))
                before = store.load().to_dict()['active']
                with self.assertRaises(DecisionRejected):
                    call(turn_id=c.turn_id, decision=Decision('correct', correction={'kind': 'blocked_target', 'data': data}))
                self.assertEqual(store.load().to_dict()['active'], before)
                self.assertEqual(store.load().unresolved, [])

    def test_last_blocked_target_finishes_accounting_without_covering_or_planting_it(self):
        store, port, call = self.session([event('harvest', 'A', ['Inventory', 'Seeds'])])
        task = store.load()
        task.targets = ['A']
        store.save(task)
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target('Tulip')))
        c = call(turn_id=c.turn_id, decision=Decision('correct', correction={
            'kind': 'blocked_target', 'data': {'node': 'A', 'reason': 'no authorized seeds'}}))
        self.assertEqual(c.task['status'], 'complete')
        self.assertEqual(list(c.coverage['covered']), [])
        self.assertEqual(c.coverage['unresolved'][0]['phase'], 'plant')
        self.assertIsNone(c.transaction)
        self.assertEqual(len(port.inputs), 1, 'only the prior harvest action issued input')
        self.assertNotEqual(learn.MEMORY['graph'].state_value('A', 'watered'), True)

    def test_captured_operator_mistake_can_revise_decision_and_collect_without_reset_or_learning(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'garden', 'model-decision-on-collect.json')
        with open(fixture) as f:
            captured = json.load(f)
        # Captured blocked state is real; the later harvest is writer-shaped future actuator evidence.
        store, port, call = self.session([event('harvest', 'A')])
        def call(**kw):
            return engine.garden_turn(region='GardenSouth', store=TaskStore(store.path), adapter=port, **kw)
        store.save(TaskState.from_dict(captured['task']))
        port.snapshot = captured['observation']
        task_before = store.load().to_dict()
        c = call()
        self.assertEqual(c.surprise.experience_id, '75f4d0fad86a4779')
        self.assertEqual(set(c.allowed_decisions), {'look', 'read', 'correct', 'stop'})
        graph_before = {n.id: dict(n.state) for n in learn.MEMORY['graph'].nodes.values()}
        try:
            c = call(turn_id=c.turn_id, decision=Decision('correct', correction={
                'kind': 'revise_decision', 'data': {'reason': 'named Collect control is already open'}},
                rationale='operator_selected_wrong_primitive', evidence_refs=('75f4d0fad86a4779',)))
        except ValueError as error:
            self.fail(f'model decision revision must be supported: {error}')
        saved = TaskStore(store.path).load()  # reopen durable state, not the in-memory decision result
        self.assertEqual(saved.task_id, task_before['task_id'])
        self.assertEqual(saved.to_dict()['active'], task_before['active'])
        self.assertEqual(saved.covered, task_before['covered'])
        self.assertEqual(saved.unresolved, task_before['unresolved'])
        self.assertIsNone(saved.last_surprise)
        self.assertEqual(port.inputs, [])
        self.assertEqual(integrate.journal(), [])
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(store.path), 'gaps')))
        self.assertEqual({n.id: dict(n.state) for n in learn.MEMORY['graph'].nodes.values()}, graph_before)
        with open(os.path.join(os.path.dirname(store.path), 'log.jsonl')) as f:
            correction = next(json.loads(line) for line in f if json.loads(line).get('phase') == 'correction')
        self.assertEqual(correction['kind'], 'revise_decision')
        self.assertEqual(correction['experience'], '75f4d0fad86a4779')
        self.assertEqual(correction['result']['applied'], 0)
        self.assertIn('act', c.allowed_decisions)
        # Exercise the real named-card prepare/guard with model crop metadata; only physical lookup is substituted.
        port.prepare = primitives.GameAdapter().prepare
        with mock.patch.object(core, 'WF', SimpleNamespace(find_text=lambda *a, **kw: [{'cx': 1029, 'cy': 451}])):
            c = call(turn_id=c.turn_id, decision=Decision('act', action={
                'kind': 'press', 'label': 'Collect', 'crop': 'Tulip', 'expects': {'events': ['harvest']}}))
        self.assertEqual(len(port.inputs), 1)
        self.assertEqual(port.inputs[0]['command'], 'click:1029:451')
        self.assertEqual(c.transaction['transaction_id'], task_before['active']['transaction_id'])
        self.assertEqual(c.transaction['crop'], 'Tulip')
        self.assertEqual(c.transaction['phase'], 'plant')
        self.assertIsNone(c.surprise)

    def test_captured_resume_does_not_create_or_mutate_a_garden_transaction(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'garden', 'resume-game.json')
        with open(fixture) as f:
            captured = json.load(f)['record']
        for existing in (False, True):
            with self.subTest(existing_transaction=existing):
                store, port, call = self.session([captured])
                if existing:
                    task = store.load()
                    task.active = Interaction('bed-transaction', phase='water', actual_node='A', crop='Tulip',
                                              provisional={'target_selected': True, 'facts': {'planted': True}},
                                              evidence_ids=['plant-proof'], completed_actions=['plant-proof'])
                    store.save(task)
                before = store.load().to_dict()['active']
                port.snapshot.update(screen={'kind': 'pause', 'texts': dict(captured['before']['state'])['texts']},
                                     frame_path=captured['artifacts']['img0'])
                c = call()
                self.assertEqual(c.recommendation.action['label'], 'Resume Game')
                c = call(turn_id=c.turn_id, decision=Decision('accept'))
                self.assertEqual(store.load().to_dict()['active'], before)
                self.assertEqual(len(port.inputs), 1)
                self.assertEqual(len(integrate.journal()), 1)
                self.assertIsNone(c.surprise)
                self.assertEqual(c.last_outcome['verdict']['value'], 'hit')
                self.assertEqual(list(c.coverage['covered']), [])
                self.assertIsNone(store.load().pending_intent)
                if not existing:
                    self.assertIsNone(c.transaction)
                    self.assertIn('model selects a visible uncovered target', c.recommendation.reasons[0])

    def test_menu_input_reconciles_after_restart_without_repeating_or_creating_target(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'garden', 'resume-game.json')
        with open(fixture) as f:
            captured = json.load(f)['record']
        store, port, call = self.session([captured])
        port.snapshot['screen'] = {'kind': 'pause', 'texts': dict(captured['before']['state'])['texts']}
        c = call()
        original = port.perform
        def interrupted(action):
            # Durable write-ahead state exists before the actuator, including no object transaction.
            persisted = TaskStore(store.path).load()
            self.assertIsNone(persisted.active)
            self.assertEqual(persisted.pending_intent.action['label'], 'Resume Game')
            original(action)
            raise RuntimeError('connection lost after input')
        port.perform = interrupted
        with self.assertRaisesRegex(RuntimeError, 'connection lost'):
            call(turn_id=c.turn_id, decision=Decision('accept'))
        c = call()  # loads persisted task and reconciles without another perform
        self.assertEqual(len(port.inputs), 1)
        self.assertIsNone(c.transaction)
        self.assertIsNone(store.load().pending_intent)
        self.assertEqual(c.surprise.reason, 'pending_intent_reconciled')
        self.assertEqual(len(integrate.journal()), 1)

    def test_resume_requires_gameplay_evidence_without_requiring_world_event(self):
        from game.task_state import Intent
        before = {'screen': {'kind': 'pause', 'texts': ['Game Paused', 'Resume Game']}}
        intent = Intent(1, {'kind': 'press', 'label': 'Resume Game'}, 722907, 1793989735.839668)
        for mode, verdict in [('gameplay', 'hit'), ('pause', 'miss')]:
            with self.subTest(mode=mode):
                e = primitives.experience(intent, before, {'mode': 'gameplay'}, X.Evidence(mode=mode))
                self.assertEqual(e.verdict.value, verdict)
                self.assertEqual(e.verdict.checks[0].field, 'mode')

    def test_obsolete_resume_control_refuses_without_creating_target(self):
        store, port, call = self.session([])
        port.snapshot['screen'] = {'kind': 'pause', 'texts': ['Game Paused', 'Resume Game']}
        c = call()
        port.snapshot['screen'] = {'kind': 'gameplay', 'texts': []}
        adapter = primitives.GameAdapter()
        port.prepare = adapter.prepare
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(len(port.inputs), 0)
        self.assertIsNone(c.transaction)
        self.assertEqual(c.last_outcome['verdict']['value'], 'unsafe')

    def session(self, records, **params):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        graph = Graph()
        for node, pos in [('A', [1., 1.]), ('B', [2., 2.])]:
            graph.nodes[node] = Node(node, 'member', 'GardenBed', region='Garden', pos=pos, scene='Farm')
        store = TaskStore(os.path.join(directory.name, 'task.json'))
        store.create(TaskState('g', 'garden', targets=['A', 'B'], params={
            'region': 'Garden', 'chores': ['plant', 'harvest', 'replant', 'water'], 'flowers': ['Tulip'], **params}))
        for patch in (mock.patch.dict(learn.MEMORY, graph=graph),
                      mock.patch.object(learn, 'GRAPH', os.path.join(directory.name, 'graph.json')),
                      mock.patch.object(integrate, 'JOURNAL_DIR', directory.name)):
            patch.start()
            self.addCleanup(patch.stop)
        port = ReplayPort(records)
        def call(**kw):
            return engine.garden_turn(store=TaskStore(store.path), adapter=port, **kw)
        return store, port, call

    def test_new_target_is_refused_until_current_transaction_is_verified(self):
        for kind in ('target', 'cell', 'bubble', 'space'):
            with self.subTest(kind=kind):
                store, port, call = self.session([event('water', 'A'), event('plant', 'B', ['Inventory', 'Seeds'])])
                c = call()
                c = call(turn_id=c.turn_id, decision=Decision('act', action=target('Carrot')))
                self.assertEqual(c.transaction['actual_node'], 'A')
                c = call(turn_id=c.turn_id, decision=Decision('act', action={
                    **target('Tulip'), 'kind': kind, 'point': [1100, 540]}))
                self.assertEqual(len(port.inputs), 1, 'new target must be refused before any physical input')
                self.assertEqual(c.transaction['actual_node'], 'A')
                self.assertEqual(c.transaction['crop'], 'Carrot')
                self.assertEqual(list(c.coverage['covered']), [])
                self.assertIsNotNone(c.surprise)

    def test_raw_click_alias_cannot_replace_harvested_bed_before_verification(self):
        for alias in ('target', 'cell', 'click'):
            with self.subTest(alias=alias):
                store, port, call = self.session([event('harvest', 'A'), event('plant', 'B', ['Inventory', 'Seeds'])])
                c = call()
                c = call(turn_id=c.turn_id, decision=Decision('act', action=target('Carrot')))
                self.assertEqual(c.transaction['phase'], 'plant')
                inputs_before = len(port.inputs)
                c = call(turn_id=c.turn_id, decision=Decision('act', action={
                    **target('Tulip'), 'kind': alias, 'point': [1100, 540]}))
                self.assertEqual(len(port.inputs) - inputs_before, 0, 'replacement alias must issue zero input')
                self.assertEqual(c.transaction['actual_node'], 'A')
                self.assertEqual(c.transaction['crop'], 'Carrot')
                self.assertTrue(c.transaction['provisional']['facts']['emptied'])
                self.assertEqual(c.task['status'], 'active')
                self.assertIsNotNone(c.surprise)
                self.assertEqual(list(c.coverage['covered']), [])

    def test_raw_click_first_selection_records_ownership_before_a_positioned_event(self):
        store, port, call = self.session([event(texts=['Collect']), event('plant', 'B', ['Inventory', 'Seeds'])])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action={**target('Carrot'), 'kind': 'click'}))
        self.assertIsNone(c.transaction['actual_node'])
        self.assertTrue(c.transaction['provisional'].get('target_selected'))
        c = call(turn_id=c.turn_id, decision=Decision('act', action={**target('Tulip'), 'point': [1100, 540]}))
        self.assertEqual(len(port.inputs), 1)
        self.assertEqual(c.transaction['crop'], 'Carrot')

    def test_waypoint_is_provisional_navigation_and_allows_first_target_after_restart(self):
        store, port, call = self.session([event(), event('plant', 'A', ['Inventory', 'Seeds'])])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action={
            'kind': 'waypoint', 'point': [600, 600], 'walkable': True}))
        self.assertEqual(c.transaction['phase'], 'approach')
        self.assertFalse(c.transaction['provisional'].get('target_selected'))
        self.assertIsNone(c.transaction['actual_node'])
        restarted = call()
        self.assertIsNotNone(restarted.surprise, 'an unproved waypoint cannot count as progress')
        c = call(turn_id=restarted.turn_id, decision=Decision('correct', correction={
            'kind': 'revise_decision', 'data': {'reason': 'fresh frame identifies the visible first target'}}))
        inputs_before = len(port.inputs)
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        self.assertEqual(len(port.inputs) - inputs_before, 1)
        self.assertTrue(c.transaction['provisional']['target_selected'])
        self.assertEqual(c.transaction['actual_node'], 'A')
        self.assertEqual(c.transaction['phase'], 'plant')
        self.assertIsNone(c.surprise)

    def test_verified_transaction_can_finish_before_model_selects_another_target(self):
        store, port, call = self.session([event('water', 'A'), event('plant', 'B', ['Inventory', 'Seeds'])])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target('Carrot')))
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(list(c.coverage['covered']), ['A'])
        c = call(turn_id=c.turn_id, decision=Decision('act', action={**target(), 'point': [1100, 540]}))
        self.assertEqual(c.transaction['actual_node'], 'B')
        self.assertEqual(list(c.coverage['covered']), ['A'])
        self.assertFalse(c.transaction['provisional']['facts'].get('verified'))

    def test_conflicting_positioned_event_quarantines_transaction_without_transferring_facts(self):
        store, port, call = self.session([event('harvest', 'A'), event('plant', 'B', ['Inventory', 'Seeds'])])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target('Carrot')))
        self.assertTrue(c.transaction['provisional']['facts']['emptied'])
        c = call(turn_id=c.turn_id, decision=Decision('act', action={'kind': 'bubble', 'point': [850, 540],
                                                                   'visible_road': True}))
        self.assertEqual(c.transaction['actual_node'], 'A', 'a second event is a conflict, not a rebind')
        self.assertEqual(c.task['status'], 'unresolved')
        self.assertEqual(dict(c.transaction['provisional']['facts']), {})
        self.assertEqual(list(c.coverage['covered']), [])
        self.assertEqual(c.surprise.reason, 'conflicting_positioned_identity')
        with self.assertRaises(DecisionRejected):
            call(turn_id=c.turn_id, decision=Decision('act', action={'kind': 'read'}))

    def test_requested_crop_never_classifies_an_unidentified_collect_card(self):
        for request in ({'crops': 'Carrot'}, {'seed': 'Carrot'}, {'crops': 'Tulip'}):
            with self.subTest(request=request):
                store, port, call = self.session([event(texts=['Collect'])], **request)
                c = call()
                c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
                self.assertIsNone(c.transaction['crop'])
                self.assertEqual(c.recommendation.action['kind'], 'close')
                self.assertEqual(list(c.coverage['covered']), [])

    def test_preexisting_empty_bed_plants_any_available_seed_and_waters_before_coverage(self):
        records = [event('plant', 'A', ['Inventory', 'Seeds', 'Carrot Seeds']),
                   event(texts=['Carrot Seeds', 'Select']), event(lines=['[STATS] totalPlanted.CarrotSeed = 1'],
                       after=[['water', 850, 540, True, False, True]]), event('water', 'A')]
        store, port, call = self.session(records)
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        self.assertEqual(c.recommendation.action['label'], 'Carrot Seeds')
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(c.recommendation.action['label'], 'Select')
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(c.transaction['phase'], 'water')
        self.assertEqual(list(c.coverage['covered']), [])
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(list(c.coverage['covered']), ['A'])
        self.assertEqual(len(port.inputs), 4)

    def test_missing_requested_seed_requires_explicit_unresolved_resolution_without_fallback(self):
        store, port, call = self.session([event('plant', 'A', ['Inventory', 'Seeds', 'Carrot Seeds'])], seed='Tulip')
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        self.assertIsNone(c.recommendation.action)
        self.assertIn('Tulip', c.recommendation.reasons[0])
        self.assertIn('correct', c.allowed_decisions, 'model must be able to resolve a missing-seed ambiguity')
        c = call(turn_id=c.turn_id, decision=Decision('correct', correction={
            'kind': 'unresolved', 'data': {'reason': 'missing Tulip seed', 'node': 'A'}}))
        self.assertEqual(c.task['status'], 'unresolved')
        self.assertEqual(list(c.coverage['covered']), [])
        self.assertEqual(c.coverage['unresolved'][0]['reason'], 'missing Tulip seed')
        self.assertEqual(len(port.inputs), 1)

    def test_available_bulb_seed_detail_card_recommends_confirmation_instead_of_close(self):
        store, port, call = self.session([event('plant', 'A', ['Inventory', 'Seeds', 'Tulip Bulbs']),
                                          event(texts=['Tulip Bulbs', 'Select'])])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        self.assertEqual(c.recommendation.action['label'], 'Tulip Bulbs')
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(c.recommendation.action.get('label'), 'Select')
        self.assertEqual(c.transaction['phase'], 'plant')

    def test_wilted_card_persists_remove_phase_and_crop_across_restart(self):
        store, port, call = self.session([event('unplant', 'A', ['Carrot', 'This plant has wilted.', 'Remove']),
                                          event('unplant_impl', 'A')])
        c = call()
        c = call(turn_id=c.turn_id, decision=Decision('act', action=target()))
        self.assertEqual(c.transaction['phase'], 'remove')
        restarted = call()
        self.assertEqual(restarted.transaction['phase'], 'remove')
        self.assertEqual(restarted.transaction['crop'], 'Carrot')
        self.assertEqual(restarted.recommendation.action['label'], 'Remove')
        c = call(turn_id=c.turn_id, decision=Decision('accept'))
        self.assertEqual(c.transaction['phase'], 'plant')
        self.assertEqual(c.transaction['crop'], 'Carrot')
        self.assertEqual(list(c.coverage['covered']), [])

    def test_model_cell_intent_retains_resolved_point_without_inventing_node_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(os.path.join(directory, 'task.json'))
            store.create(TaskState('g', 'garden', targets=['bed']))
            record = X.Experience.new(action=X.Action('click'), evidence=X.Evidence(mode='gameplay')).to_dict()
            port = ReplayPort([record])
            port.prepare = lambda action, obs: dict(action, point=[760, 371])
            with mock.patch.object(integrate, 'JOURNAL_DIR', directory):
                c = engine.garden_turn(store=store, adapter=port)
                c = engine.garden_turn(store=store, adapter=port, turn_id=c.turn_id,
                                      decision=Decision('act', action={'kind': 'cell', 'cell': 'J6',
                                                                      'visible_road': True, 'crop': 'Carrot'}))
            self.assertEqual(list(c.transaction['provisional']['point']), [760, 371])
            self.assertEqual(c.transaction['phase'], 'inspect')
            self.assertIsNone(c.transaction['actual_node'])

    def test_textless_map_is_an_interrupt_and_cannot_receive_a_world_click(self):
        from game.garden import GardenAdapter
        from game import core
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'frame.jpg')
            with Image.open(os.path.join(os.path.dirname(__file__), 'fixtures', 'play', 'historical-map-panel.png')) as image:
                image.save(path)
            raw = mock.Mock()
            raw.map_pin.return_value = (900, 500)
            obs = {'screen': {'kind': 'gameplay', 'texts': []}, 'frame_path': path, 'interrupts': []}
            adapter = GardenAdapter(lambda: TaskState('g', 'garden'))
            with mock.patch.object(core, 'WF', raw), mock.patch.object(primitives.GameAdapter, 'observe', return_value=obs):
                fresh = adapter.observe()
            self.assertEqual(fresh['screen']['kind'], 'map')
            with self.assertRaises(ValueError):
                adapter.prepare({'kind': 'target', 'point': [850, 540], 'visible_road': True}, fresh)

    def test_fresh_interrupt_guard_blocks_model_override_without_input(self):
        from game.garden import GardenAdapter
        task = TaskState('g', 'garden')
        adapter = GardenAdapter(lambda: task)
        for clue in ({'hour': 23.1}, {'rain': 'Rain'}, {'can': 'empty'}):
            with self.assertRaises(ValueError):
                adapter.prepare({'kind': 'target', 'point': [850, 540], 'visible_road': True},
                                {'screen': {'kind': 'gameplay'}, **clue})

    def test_cli_continuation_keeps_turn_and_executes_only_model_supplied_primitive(self):
        from game import ask
        import wf
        self.assertTrue(callable(getattr(ask, 'garden_decision', None)), 'garden decision parser missing')
        params, answer = wf.garden_cli_args(['turn_id=7', 'answer=accept'])
        self.assertEqual(params['turn_id'], 7)
        self.assertEqual(ask.garden_decision(answer).kind, 'accept')
        d = ask.garden_decision('target J6 crop=Tulip')
        self.assertEqual(d.action['kind'], 'target')
        self.assertEqual(d.action['cell'], 'J6')
        self.assertEqual(d.action['crop'], 'Tulip')
        self.assertEqual(ask.garden_decision('target J6 crop=Green Bean relative=SE distance=inside').action['crop'],
                         'Green Bean')
        with self.assertRaises(ValueError):
            ask.garden_decision('maybe')

    def test_policy_handles_interrupts_empty_beds_hives_and_protected_flowers(self):
        from game import garden_policy as p
        active = {'phase': 'inspect', 'crop': 'Tulip', 'provisional': {'point': [850, 540]}}
        task = {'status': 'active', 'params': {'chores': ['water'], 'flowers': ['Tulip']}, 'active': active}
        obs = {'screen': {'kind': 'picker', 'texts': ['Inventory', 'Seeds', 'Tulip Bulbs']}, 'hour': 9.0}
        self.assertEqual(p.recommend(task, obs).action['kind'], 'close', 'narrow water task must not plant')
        for clue, reason in [({'hour': 23.1}, 'HARD_STOP'), ({'rain': 'Rain'}, 'SLEEP_REQUIRED'),
                             ({'light': 'night'}, 'SLEEP_REQUIRED'), ({'can': 'empty'}, 'REFILL_REQUIRED')]:
            r = p.recommend(task, dict(obs, **clue))
            self.assertIsNone(r.action)
            self.assertIn(reason, r.reasons[0])
        obs['screen'] = {'kind': 'card', 'texts': ['Collect']}
        task['params']['chores'] = ['harvest']
        self.assertEqual(p.recommend(task, obs).action['kind'], 'close')
        task['params']['crops'] = 'Tulip'
        self.assertEqual(p.recommend(task, obs).action['label'], 'Collect')
        active['crop'] = 'Carrot'
        task['params'].pop('crops')
        self.assertEqual(p.recommend(task, obs).action['label'], 'Collect')
        active['crop'] = None
        active['provisional']['facts'] = {'hive': True}
        self.assertEqual(p.recommend(task, obs).action['label'], 'Collect')

    def test_public_observe_does_not_perform_input(self):
        self.assertTrue(callable(getattr(engine, 'garden_turn', None)), 'garden_turn public boundary is missing')
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStore(os.path.join(directory, 'task.json'))
            store.create(TaskState('g', 'garden', targets=['bed']))
            port = ReplayPort([])
            context = engine.garden_turn(store=store, adapter=port)
            self.assertEqual(port.inputs, [])
            self.assertEqual(context.task['task_id'], 'g')
            self.assertIsNone(context.recommendation.action)  # model selects a visible target

    def test_captured_tulip_survives_restart_at_every_boundary_and_covers_event_owned_bed(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures/garden/tulip-collect-plant-water.json')
        with open(fixture) as f:
            rows = json.load(f)['experiences']
        by_id = {r['id']: r for r in rows}
        records = [by_id[i] for i in ('d20558cafd43866e', '6a518d8149d78e2c', '99e8e1a6215bfa84',
                                      '4dd795d2ea31795b', '7ffb52afc9f2271e', '26efcf53881de2e3')]
        with tempfile.TemporaryDirectory() as directory:
            graph = Graph()
            graph.nodes['actual'] = Node('actual', 'member', 'GardenBed', region='GardenSouth',
                                         pos=[6.39, -59.36], scene='Farm')
            store = TaskStore(os.path.join(directory, 'task.json'))
            store.create(TaskState('g', 'garden', params={'region': 'GardenSouth', 'crops': 'Tulip',
                                'flowers': ['Tulip'], 'chores': ['harvest', 'replant', 'water']}, targets=['actual']))
            port = ReplayPort(records)
            def call(**kw):
                # Reconstruct public boundary and durable store after each turn, as separate CLI calls do.
                return engine.garden_turn('GardenSouth', store=TaskStore(store.path), adapter=port, **kw)
            with mock.patch.dict(learn.MEMORY, graph=graph), \
                    mock.patch.object(learn, 'GRAPH', os.path.join(directory, 'graph.json')), \
                    mock.patch.object(integrate, 'JOURNAL_DIR', directory):
                c = call()
                self.assertTrue(any(a['ready'] for a in c.visible_affordances))  # captured ! evidence
                c = call(turn_id=c.turn_id, decision=Decision('act', action={
                    'kind': 'bubble', 'point': [872, 524], 'visible_road': True,
                    'crop': 'Tulip', 'projected_node': 'wrong'}))
                tx = c.transaction['transaction_id']
                self.assertIsNone(c.transaction['actual_node'])
                self.assertEqual(c.recommendation.action['label'], 'Collect')
                c = call(turn_id=c.turn_id, decision=Decision('accept'))
                self.assertEqual((c.transaction['actual_node'], c.transaction['phase'], c.transaction['crop']),
                                 ('actual', 'plant', 'Tulip'))
                # Legacy capture has no post-harvest bubble scan, so the model selects the visible empty bubble.
                c = call(turn_id=c.turn_id, decision=Decision('act', action={
                    'kind': 'bubble', 'point': [864, 540], 'visible_road': True}))
                self.assertEqual(c.transaction['transaction_id'], tx)
                self.assertEqual(c.recommendation.action['label'], 'Tulip Bulbs')
                self.assertIsNone(c.surprise)  # Seeds is expected here; the retired picker expected Collect.
                c = call(turn_id=c.turn_id, decision=Decision('accept'))
                self.assertEqual(c.transaction['crop'], 'Tulip')
                # The captured old selection lacks confirmation-card evidence. Resolve that surprise explicitly
                # before supplying the next input; never invent a successful card observation in the fixture.
                self.assertIsNotNone(c.surprise)
                c = call(turn_id=c.turn_id, decision=Decision('correct', correction={
                    'kind': 'revise_decision', 'data': {'reason': 'inspect confirmation before selecting'}}))
                c = call(turn_id=c.turn_id, decision=Decision('act', action={'kind': 'press', 'label': 'Select',
                                                                          'expects': {'log': 'totalPlanted'}}))
                self.assertEqual(c.transaction['phase'], 'water')
                c = call(turn_id=c.turn_id, decision=Decision('act', action={'kind': 'space',
                                                                  'expects': {'events': ['water']}}))
                self.assertEqual(c.transaction['phase'], 'verify')
                self.assertEqual(list(c.coverage['covered']), [])
                c = call(turn_id=c.turn_id, decision=Decision('accept'))
                self.assertEqual(c.task['status'], 'complete')
                self.assertEqual(list(c.coverage['covered']), ['actual'])
                self.assertEqual(len(port.inputs), 6)
                journal = integrate.journal()
                self.assertEqual(len(journal), 7)
                self.assertEqual(len({e.id for e in journal}), 7)
                self.assertEqual(len({e.artifacts.turn_id for e in journal}), 7)
                with open(os.path.join(directory, 'log.jsonl')) as f:
                    log = [json.loads(l) for l in f]
                self.assertEqual(len([r for r in log if r['phase'] == 'intent']), 7)
                self.assertEqual(graph.state_value('actual', 'watered'), True)


def target(crop=None):
    return {'kind': 'target', 'point': [850, 540], 'visible_road': True, **({'crop': crop} if crop else {})}


def event(kind=None, node='A', texts=(), lines=(), after=()):
    """Writer-shaped raw boundary evidence, with positions using the real game-log spelling."""
    position = '1.0, 0.1, 1.0' if node == 'A' else '2.0, 0.1, 2.0'
    log = [f'[D208 9:00:00 AM] > {kind} me=Player target=GardenBed(Clone) at ({position})'] if kind else []
    return X.Experience.new(action=X.Action('click'), evidence=X.Evidence(
        lines=tuple(log + list(lines)), events=(kind,) if kind else (), texts=tuple(texts), after=tuple(after))).to_dict()


class ReplayPort:
    def __init__(self, records):
        self.records, self.index, self.inputs = records, 0, []
        self.snapshot = {'screen': {'kind': 'gameplay', 'texts': []}, 'frame_path': 'captured.jpg',
                         'visible_affordances': [], 'graph_clues': [], 'interrupts': [], 'hour': 9.0}
        if records:
            self.snapshot['visible_affordances'] = [dict(kind=a[0], point=a[1:3], drop=a[3], ready=a[4],
                                                        highlighted=a[5]) for a in records[0]['before']['affordances']]

    def observe(self):
        return self.snapshot

    def mark(self):
        return self.index

    def prepare(self, action, observation):
        return action

    def perform(self, action):
        self.inputs.append(action)

    def capture(self, intent, before, expects):
        if intent.action['kind'] == 'read':
            return primitives.experience(intent, before, expects, X.Evidence(mode='gameplay'))
        record = self.records[self.index]
        self.index += 1
        evidence = dict(record['evidence'])
        # Parse positioned event from the original writer's line, not its missing legacy at field.
        from game.act import position_of
        evidence['at'] = next((position_of(l) for l in evidence['lines'] if position_of(l)), None)
        evidence['node'] = None
        evidence['mode'] = 'picker' if 'Seeds' in evidence['texts'] else 'card' if evidence['texts'] else 'gameplay'
        self.snapshot = dict(self.snapshot, screen={'kind': evidence['mode'], 'texts': evidence['texts']},
                             visible_affordances=[dict(kind=a[0], point=a[1:3], drop=a[3], ready=a[4],
                                                       highlighted=a[5]) for a in evidence['after']])
        return primitives.experience(intent, before, expects, X.Evidence(**evidence))


if __name__ == '__main__':
    unittest.main()
