"""The garden public boundary: one model decision, durable evidence, no hidden scheduler."""
import json
import os
import tempfile
import unittest
from unittest import mock

from game import engine, experience as X, integrate, learn, primitives
from game.task_state import TaskStore, TaskState
from objects.graph import Graph, Node
from game.turn import Decision, DecisionRejected


class GardenTurns(unittest.TestCase):
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
            Image.new('RGB', (1920, 1080)).save(path)
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
                # The captured old selection did not record the confirmation card; model supplies that input.
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
