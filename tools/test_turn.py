"""Offline contracts for the durable, model-owned one-turn boundary."""
import dataclasses
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import badges, core, experience as X, icons, integrate as I, learn, primitives, steps, task_state as S, turn
from objects.graph import Graph, Node


class Port:
    """Physical I/O boundary; no policy or persistence is replaced."""
    def __init__(self):
        self.inputs = []
        self.lines = []
        self.fail = False
        self.snapshot = {'screen': {'kind': 'gameplay', 'texts': []}, 'frame_path': 'full.jpg',
                         'visible_affordances': [], 'graph_clues': [], 'interrupts': []}

    def observe(self):
        return self.snapshot

    def mark(self):
        return len(self.lines)

    def prepare(self, action, observation):
        return action

    def perform(self, action):
        self.inputs.append(action)
        if self.fail:
            raise RuntimeError('connection lost after input')

    def capture(self, intent, before, expected):
        lines = tuple(self.lines[intent.log_mark:])
        ev = X.Evidence(lines=lines,
                        events=('water',) if lines else (),
                        at=(1., 2.) if lines else None,
                        node='GardenBed#actual' if lines else None,
                        mode='gameplay')
        return primitives.experience(intent, before, expected, ev, ('after.jpg',))


class Turns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = S.TaskStore(os.path.join(self.tmp.name, 'task.json'))
        self.store.create(S.TaskState('task-1', 'garden', active=S.Interaction('tx-1',
                          provisional={'projected_node': 'GardenBed#wrong', 'frame': 'full.jpg'})))
        self.port = Port()
        self.policy = lambda task, obs: turn.Recommendation({'kind': 'space'}, .9, ('highlighted',),
                                                           {'events': ['water']})
        self.loop = turn.TurnLoop(self.store, self.port, self.policy)
        self.patch = mock.patch.object(I, 'JOURNAL_DIR', self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_roundtrip_and_atomic_failure_preserve_previous_state(self):
        before = self.store.load().to_dict()
        changed = self.store.load()
        changed.active.crop = 'Tulip'
        with mock.patch('os.replace', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.store.save(changed)
        self.assertEqual(self.store.load().to_dict(), before)
        self.store.save(changed)
        self.assertEqual(S.TaskStore(self.store.path).load().active.crop, 'Tulip')

    def test_context_and_look_are_immutable_input_free_and_same_turn(self):
        c = self.loop.context()
        looked = self.loop.decide(c.turn_id, turn.Decision('look'))
        self.assertEqual(looked.turn_id, c.turn_id)
        self.assertEqual(looked.frame_path, 'full.jpg')
        self.assertEqual(self.port.inputs, [])
        with self.assertRaises((TypeError, dataclasses.FrozenInstanceError)):
            c.recommendation.action['kind'] = 'close'
        self.assertEqual(json.loads(json.dumps(c.to_dict()))['task']['task_id'], 'task-1')

    def test_one_accept_persists_intent_before_input_and_rejects_stale(self):
        c = self.loop.context()
        original = self.port.perform
        def perform(action):
            pending = self.store.load().active.pending_intent
            self.assertEqual(pending.turn_id, c.turn_id)
            original(action)
        self.port.perform = perform
        self.port.lines.append('old unrelated line')
        self.policy = None
        next_context = self.loop.decide(c.turn_id, turn.Decision('accept'))
        self.assertEqual(len(self.port.inputs), 1)
        self.assertGreater(next_context.turn_id, c.turn_id)
        with self.assertRaises(turn.StaleTurn):
            self.loop.decide(c.turn_id, turn.Decision('accept'))
        self.assertEqual(len(self.port.inputs), 1)
        with open(os.path.join(self.tmp.name, 'log.jsonl')) as f:
            rows = [json.loads(l) for l in f]
        phases = {r['phase'] for r in rows if r['turn_id'] == c.turn_id}
        self.assertTrue({'clues', 'recommendation', 'decision', 'intent', 'outcome', 'integration'} <= phases)
        self.assertTrue(all(r.get('type') == 'turn' for r in rows))
        checkpoint = next(r for r in rows if r['phase'] == 'clues' and r['turn_id'] == next_context.turn_id)
        self.assertEqual(checkpoint['coverage'], {'targets': [], 'covered': [], 'unresolved': []})
        self.assertEqual(checkpoint['task_status'], 'active')
        self.assertIsNone(self.store.load().active.pending_intent)

    def test_restart_reconciles_pending_input_without_repeating_it(self):
        c = self.loop.context()
        self.port.fail = True
        with self.assertRaises(RuntimeError):
            self.loop.decide(c.turn_id, turn.Decision('accept'))
        self.port.fail = False
        self.port.lines.append('> water target=GardenBed at (1.0, 0.0, 2.0)')
        resumed = turn.TurnLoop(S.TaskStore(self.store.path), self.port, self.policy).context()
        self.assertEqual(len(self.port.inputs), 1)
        self.assertIsNone(self.store.load().active.pending_intent)
        self.assertEqual(resumed.transaction['actual_node'], 'GardenBed#actual')
        self.assertIsNotNone(resumed.surprise)  # recovery requires a model decision even when the event matches
        with self.assertRaises(turn.DecisionRejected):
            self.loop.decide(resumed.turn_id, turn.Decision('accept'))

    def test_projection_never_binds_identity_but_late_positioned_event_does(self):
        c = self.loop.context()
        self.assertIsNone(c.transaction['actual_node'])
        def perform(action):
            self.port.inputs.append(action)
            self.port.lines.append('> water target=GardenBed at (1.0, 0.0, 2.0)')
        self.port.perform = perform
        c = self.loop.decide(c.turn_id, turn.Decision('accept'))
        self.assertEqual(c.transaction['actual_node'], 'GardenBed#actual')
        self.assertEqual(c.transaction['provisional']['projected_node'], 'GardenBed#wrong')

    def test_mismatch_suspends_accept_and_model_routes_idempotent_correction(self):
        c = self.loop.decide(self.loop.context().turn_id, turn.Decision('accept'))
        self.assertIsNotNone(c.surprise)
        exp_id = c.surprise.experience_id
        with self.assertRaises(turn.DecisionRejected):
            self.loop.decide(c.turn_id, turn.Decision('accept'))
        c = self.loop.decide(c.turn_id, turn.Decision('correct', correction={'kind': 'gap',
                                 'data': {'invariant': 'Space did not water', 'owner': 'steps'}}))
        self.assertIsNone(c.surprise)
        self.assertEqual(I.gaps()[0]['experiences'], [exp_id])
        self.assertEqual(len(self.port.inputs), 1)

    def test_wait_is_zero_input_and_captures_one_experience(self):
        c = self.loop.context()
        self.loop.decide(c.turn_id, turn.Decision('act', action={'kind': 'wait'}))
        self.assertEqual(self.port.inputs, [])
        self.assertEqual(len(I.journal()), 1)

    def test_recommendation_is_exact_version_and_does_not_run_row(self):
        row = {'id': 'water', 'kind': 'GardenBed', 'effect': {}, 'steps': [
            {'do': 'press', 'arg': 'Collect', 'expect': {'events': ['grab_item']}},
            {'do': 'press_space'}]}
        rec = steps.recommend(row, {}, 0)
        self.assertEqual(rec.action['kind'], 'press')
        self.assertEqual(rec.action['label'], 'Collect')
        self.assertEqual(self.port.inputs, [])

    def test_saved_outcome_replays_same_experience_after_integration_crash(self):
        c = self.loop.context()
        with mock.patch.object(I, 'apply', side_effect=RuntimeError('crash before integration')):
            with self.assertRaises(RuntimeError):
                self.loop.decide(c.turn_id, turn.Decision('accept'))
        saved_id = self.store.load().active.pending_intent.experience['id']
        self.port.lines.append('late unrelated line')
        resumed = turn.TurnLoop(self.store, self.port, self.policy).context()
        self.assertEqual(resumed.last_outcome['id'], saved_id)
        self.assertEqual(len(self.port.inputs), 1)
        self.assertEqual(len(I.journal()), 1)

    def test_refused_guard_returns_surprise_with_zero_inputs(self):
        self.port.prepare = lambda action, obs: (_ for _ in ()).throw(ValueError('menu blocks world input'))
        c = self.loop.decide(self.loop.context().turn_id, turn.Decision('accept'))
        self.assertEqual(c.surprise.reason, 'mismatch')
        self.assertEqual(c.last_outcome['verdict']['value'], 'unsafe')
        self.assertEqual(self.port.inputs, [])

    def test_model_world_correction_is_durable_and_idempotent(self):
        graph = Graph()
        graph.nodes['bed'] = Node('bed', 'member', 'GardenBed', pos=[1., 2.], scene='Farm')
        path = os.path.join(self.tmp.name, 'graph.json')
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), self.port.snapshot, {}, X.Evidence())
        with mock.patch.dict(learn.MEMORY, graph=graph), mock.patch.object(learn, 'GRAPH', path):
            data = {'node': 'bed', 'state': {'crop': 'Tulip'}}
            self.assertEqual(I.correct(e, 'world', data)['applied'], 1)
            self.assertEqual(I.correct(e, 'world', data)['applied'], 0)
            restored = Graph()
            restored.load(path)
            self.assertEqual(restored.state_value('bed', 'crop'), 'Tulip')

    def test_reconciliation_keeps_event_identity_after_already_applied_integration(self):
        graph = Graph()
        graph.nodes['GardenBed#actual'] = Node('GardenBed#actual', 'member', 'GardenBed', pos=[1., 2.], scene='Farm')
        path = os.path.join(self.tmp.name, 'graph.json')
        original = self.port.perform
        def perform(action):
            original(action)
            self.port.lines.append('> water target=GardenBed at (1.0, 0.0, 2.0)')
        self.port.perform = perform
        # Production capture deliberately has no canonical node; only the positioned-event consumer binds it.
        capture = self.port.capture
        self.port.capture = lambda *args: dataclasses.replace(capture(*args), evidence=dataclasses.replace(
            capture(*args).evidence, node=None))
        with mock.patch.dict(learn.MEMORY, graph=graph), mock.patch.object(learn, 'GRAPH', path):
            c = self.loop.context()
            save = self.store.save
            def crash_on_completion(task):
                if task.active.pending_intent is None:
                    raise RuntimeError('crash after applied integration')
                save(task)
            with mock.patch.object(self.store, 'save', side_effect=crash_on_completion):
                with self.assertRaises(RuntimeError):
                    self.loop.decide(c.turn_id, turn.Decision('accept'))
            recovered = self.loop.context()
            self.assertEqual(recovered.transaction['actual_node'], 'GardenBed#actual')
            self.assertEqual(len(self.port.inputs), 1)

    def test_production_adapter_is_one_input_and_guards_do_not_close_menus(self):
        class Raw:
            def __init__(self):
                self.inputs = []
            def run_action(self, command):
                self.inputs.append(command)
            def find_text(self, label, exact=False):
                return [{'cx': 1100, 'cy': 700}]
        raw = Raw()
        adapter = primitives.GameAdapter()
        with mock.patch.object(core, 'WF', raw), mock.patch.object(core, 'ask_vision', side_effect=AssertionError('vision')):
            prepared = adapter.prepare({'kind': 'target', 'point': [1100, 600], 'visible_road': True}, self.port.snapshot)
            adapter.perform(prepared)
            self.assertEqual(raw.inputs, ['click:1100:600'])
            with self.assertRaises(ValueError):
                adapter.prepare({'kind': 'target', 'point': [1100, 600], 'visible_road': True},
                                {'screen': {'kind': 'pause'}})
            self.assertEqual(raw.inputs, ['click:1100:600'])

    def test_captured_nate_observation_uses_recognized_world_affordances(self):
        from PIL import Image
        from types import SimpleNamespace
        from game import act, observe
        from game.affordances import Affordance
        raw = SimpleNamespace(grab=lambda: Image.new('RGB', (1920, 1080)),
                              state=lambda: {'mode': 'overlay', 'text': ['NATE']})
        seen = [Affordance('plant', None, (1080, 536), True, 120),
                Affordance('plant_growing', None, (864, 540), False, 96)]
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name), \
                mock.patch.object(observe, 'scan', return_value=seen):
            snapshot = primitives.GameAdapter().observe()
        self.assertEqual(snapshot['screen']['kind'], 'gameplay')
        self.assertEqual(snapshot['screen']['texts'], ['NATE'])  # preserve raw clues, don't erase disagreements
        self.assertEqual(len(snapshot['visible_affordances']), 2)

    def test_unrepresentable_appearance_correction_stays_retryable(self):
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), self.port.snapshot, {}, X.Evidence())
        result = I.correct(e, 'appearance', {'op': 'badge', 'label': 'ready'})
        self.assertEqual(result['applied'], 0)
        self.assertTrue(result['errors'])

    def test_current_event_evidence_cannot_be_overwritten_by_model_world_correction(self):
        graph = Graph()
        graph.nodes['bed'] = Node('bed', 'member', 'GardenBed', pos=[1., 2.], scene='Farm')
        # The current event itself is authoritative even before its graph update has run.
        graph.set_state('bed', 'watered', True, 'D1 9:00:00 AM', 'save')
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), self.port.snapshot, {},
                                 X.Evidence(lines=('[D2 9:00:00 AM] > water me=Player target=GardenBed '
                                                   'at (1.0, 0.0, 2.0)',), events=('water',), at=(1., 2.)))
        with mock.patch.dict(learn.MEMORY, graph=graph), \
                mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')):
            result = I.correct(e, 'world', {'node': 'bed', 'state': {'watered': False}})
        self.assertEqual(result['applied'], 0)
        self.assertEqual(graph.state_value('bed', 'watered'), True)
        self.assertTrue(result['errors'])

    def test_new_observation_can_correct_historical_event(self):
        graph = Graph()
        graph.nodes['bed'] = Node('bed', 'member', 'GardenBed', pos=[1., 2.], scene='Farm')
        graph.set_state('bed', 'watered', True, 'D1 9:00:00 AM', 'event')
        before = dict(self.port.snapshot, game_time='D2 9:00:00 AM')
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), before, {},
                                 X.Evidence(mode='card', texts=('Tulip', 'Needs water')))
        with mock.patch.dict(learn.MEMORY, graph=graph), \
                mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')):
            result = I.correct(e, 'world', {'node': 'bed', 'state': {'watered': False}})
        self.assertEqual(result['applied'], 1)
        self.assertEqual(graph.state_value('bed', 'watered'), False)
        self.assertEqual(graph.nodes['bed'].state['watered']['game_time'], 'D2 9:00:00 AM')
        self.assertEqual(graph.nodes['bed'].state['watered']['source'], 'vision')

    def test_recommendation_provenance_survives_primitive_capture_and_transition_log(self):
        row = {'id': 'water', 'kind': 'GardenBed', 'effect': {},
               'steps': [{'do': 'press', 'arg': 'Collect', 'expect': {'card': 'Seeds'}}]}
        self.loop.policy = lambda task, obs: steps.recommend(row, {}, 0)
        path = os.path.join(self.tmp.name, 'observed.jsonl')
        with mock.patch.object(steps, 'OBSERVED', path):
            c = self.loop.decide(self.loop.context().turn_id, turn.Decision('accept'))
        self.assertEqual(c.last_outcome['goal']['row'], 'water')
        self.assertEqual(c.last_outcome['goal']['step'], 0)
        with open(path) as f:
            record = json.loads(f.readline())
        self.assertEqual((record['row'], record['step']), ('water', 0))

    def test_production_resume_reaches_daemon_with_one_physical_input(self):
        import wf
        inputs = []
        paused = [True]
        def state(*args, **kwargs):
            return ({'mode': 'overlay', 'text': ['0) Game Paused', '1) Resume Game']}
                    if paused[0] else {'mode': 'gameplay', 'text': []})
        def click(x, y):
            inputs.append((x, y))
            paused[0] = False
        # Keep the real run_action/run_action_inner dispatch and pause guard. Only physical I/O and its
        # screen/log bookkeeping are stubbed; using the adapter's old click:x:y fails this boundary.
        with mock.patch.object(core, 'WF', wf), \
                mock.patch.object(wf, 'state', state), \
                mock.patch.object(wf, 'find_text', return_value=[{'cx': 960, 'cy': 700}]), \
                mock.patch.object(wf, 'click', click), \
                mock.patch.object(wf, 'ensure_front'), \
                mock.patch.object(wf, 'release_focus'), \
                mock.patch.object(wf, 'key', side_effect=AssertionError('unexpected extra key')), \
                mock.patch.object(wf, 'log_mark', return_value=0), \
                mock.patch.object(wf, 'seg_estimate', return_value=None), \
                mock.patch.object(wf, 'scene_change', return_value=True), \
                mock.patch.object(wf.time, 'sleep'):
            adapter = primitives.GameAdapter()
            action = adapter.prepare({'kind': 'press', 'label': 'Resume Game'},
                                     {'screen': {'kind': 'pause', 'texts': ['Resume Game']}})
            adapter.perform(action)
        self.assertEqual(inputs, [(960, 700)])
        self.assertFalse(paused[0])

    def test_production_bubble_turn_integrates_cards_badges_and_bubble_labels(self):
        import wf
        from PIL import Image
        class Raw:
            event_kind = staticmethod(wf.event_kind)
            learn_bubble = staticmethod(wf.learn_bubble)
            bubble_crop = staticmethod(wf.bubble_crop)
            def __init__(self, directory):
                self.directory, self.lines, self.inputs = directory, [], []
                self.image = Image.new('RGB', (1920, 1080), (90, 140, 60))
            def grab(self):
                return self.image
            def run_dir(self):
                return self.directory
            def game_stamp(self):
                return 'D2 9:00:00 AM'
            def log_mark(self):
                return len(self.lines)
            def log_since(self, mark):
                return '\n'.join(self.lines[mark:])
            def _unhash(self, value):
                return value
            def state(self):
                return ({'mode': 'overlay', 'text': ['0) Tulip', '1) 3 days remaining']}
                        if self.lines else {'mode': 'gameplay', 'text': []})
            def find_bubbles(self, image):
                return [] if self.lines else [(1100, 600)]
            def bubble_kind(self, image, point):
                return 'unknown', 0.
            def bubble_highlighted(self, image, point):
                return True
            def run_action(self, command):
                self.inputs.append(command)
                self.lines.append('[D2 9:00:00 AM] > inspect me=Player target=GardenBed at (1.0, 0.0, 2.0)')
            def wait_settle(self):
                pass
            def run_log(self, *args, **kwargs):
                pass
        graph = Graph()
        graph.nodes['bed'] = Node('bed', 'member', 'GardenBed', pos=[1., 2.], scene='Farm')
        raw = Raw(self.tmp.name)
        self.loop = turn.TurnLoop(self.store, primitives.GameAdapter(), lambda task, obs: turn.Recommendation(
            {'kind': 'bubble', 'point': [1100, 600], 'visible_road': True}, 1., ('inspect visible bubble',),
            {'card': 'days remaining'}))
        bubble_dir = os.path.join(self.tmp.name, 'bubbles')
        badge_dir = os.path.join(self.tmp.name, 'badges')
        with mock.patch.object(core, 'WF', raw), mock.patch.dict(learn.MEMORY, graph=graph), \
                mock.patch.object(learn, 'GRAPH', os.path.join(self.tmp.name, 'graph.json')), \
                mock.patch.object(wf, 'BUBBLE_DIR', bubble_dir), mock.patch.object(wf, '_BUBBLE_REFS', None), \
                mock.patch.object(wf, 'LEARNED_LOG', os.path.join(self.tmp.name, 'learned.log')), \
                mock.patch.object(wf, '_featureprint', side_effect=lambda im: __import__('numpy').ones(8)), \
                mock.patch.object(badges, 'DIR', badge_dir), mock.patch.object(icons, 'DIR', os.path.join(self.tmp.name, 'icons')):
            c = self.loop.decide(self.loop.context().turn_id, turn.Decision('accept'))
            self.assertEqual(graph.state_value('bed', 'crop'), 'Tulip')
            restored = Graph()
            restored.load(learn.GRAPH)
            self.assertEqual(restored.state_value('bed', 'crop'), 'Tulip')
        self.assertEqual(raw.inputs, ['click:1100:600'])
        self.assertIsNone(c.surprise)
        self.assertTrue(os.listdir(os.path.join(bubble_dir, 'inspect')))
        self.assertTrue(os.listdir(os.path.join(badge_dir, 'none')))


if __name__ == '__main__':
    unittest.main()
