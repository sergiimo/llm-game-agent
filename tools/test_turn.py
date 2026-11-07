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

    def test_every_context_prints_the_compact_model_workflow(self):
        self.port.snapshot['vector_detections'] = [
            {'kind': 'GardenBed', 'point': [700, 500], 'score': 7.1}]
        c = self.loop.context()
        stages = {row['stage']: row for row in c.model_workflow}
        self.assertEqual(tuple(stages), ('observe', 'decide', 'vision', 'act', 'verify', 'learn', 'repeat'))
        self.assertEqual(stages['observe']['vectors'], 1)
        self.assertEqual(stages['decide']['status'], 'awaiting_model')
        self.assertEqual(stages['act']['status'], 'awaiting_decision')
        self.assertEqual(stages['repeat']['goal'], 'garden')
        public = json.dumps(c.to_dict())
        self.assertNotIn('chain_of_thought', public)
        self.assertLess(len(json.dumps(c.to_dict()['model_workflow'])), 1600)
        cached = self.loop.context()
        self.assertEqual(cached.observation_freshness, 'cached')
        self.assertEqual(cached.model_workflow[0]['freshness'], 'cached')

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

    def test_restart_repairs_missing_canonical_intent_before_clearing_wal(self):
        """A crash after the task WAL save but before intent append must not orphan its outcome."""
        from game import history
        c = self.loop.context()
        write = self.loop._log
        def crash_before_intent(task, turn_id, phase, **data):
            if phase == 'intent':
                raise RuntimeError('crash before canonical intent append')
            return write(task, turn_id, phase, **data)
        with mock.patch.object(self.loop, '_log', side_effect=crash_before_intent):
            with self.assertRaises(RuntimeError):
                self.loop.decide(c.turn_id, turn.Decision('accept'))
        self.assertIsNotNone(self.store.load().active.pending_intent)
        self.assertEqual(self.port.inputs, [], 'the crash happened before physical input')

        resumed = turn.TurnLoop(S.TaskStore(self.store.path), self.port, self.policy).context()
        refs = self.store.load().active.evidence_ids
        records = history.records(os.path.join(self.tmp.name, 'log.jsonl'), refs)
        self.assertEqual([row['experience']['id'] for row in records], refs)
        self.assertIsNotNone(resumed.surprise)

    def test_turn_log_fsyncs_each_canonical_append(self):
        with mock.patch.object(turn.os, 'fsync') as sync:
            self.loop._log(self.store.load(), 1, 'intent', intent={'action': {'kind': 'read'}})
        sync.assert_called()

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
        self.assertEqual(c.surprise.checks[0]['field'], 'guard')
        self.assertEqual(c.surprise.checks[0]['got'], 'menu blocks world input')
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
        raw = SimpleNamespace(grab=lambda: Image.new('RGB', (1920, 1080), 'gray'),
                              state=lambda: {'mode': 'overlay', 'text': ['NATE']})
        seen = [Affordance('plant', None, (1080, 536), True, 120),
                Affordance('plant_growing', None, (864, 540), False, 96)]
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name), \
                mock.patch.object(observe, 'scan', return_value=seen):
            snapshot = primitives.GameAdapter().observe()
        self.assertEqual(snapshot['screen']['kind'], 'gameplay')
        self.assertEqual(snapshot['screen']['texts'], ['NATE'])  # preserve raw clues, don't erase disagreements
        self.assertEqual(len(snapshot['visible_affordances']), 2)

    def test_production_observation_classifies_and_scans_exact_saved_grab(self):
        from PIL import Image
        from types import SimpleNamespace
        from game import act
        image = Image.new('RGB', (1920, 1080), 'gray')
        raw = SimpleNamespace(grab=mock.Mock(return_value=image),
                              state=mock.Mock(side_effect=AssertionError('independent capture')),
                              classify=mock.Mock(return_value={'mode': 'gameplay', 'text': ['Road']}),
                              find_bubbles=mock.Mock(return_value=[]))
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name):
            snapshot = primitives.GameAdapter().observe()
        self.assertEqual(snapshot['screen'], {'kind': 'gameplay', 'texts': ['Road']})
        raw.grab.assert_called_once_with()
        raw.classify.assert_called_once_with(image)
        raw.find_bubbles.assert_called_once_with(image)
        with Image.open(snapshot['frame_path']) as saved:
            self.assertEqual(saved.size, (1920, 1080))

    def test_production_observation_runs_vectors_on_the_exact_saved_grab(self):
        from PIL import Image
        from types import SimpleNamespace
        from game import act, observe
        from objects.detect import Detection
        image = Image.new('RGB', (1920, 1080), '#678967')
        raw = SimpleNamespace(grab=mock.Mock(return_value=image),
                              classify=mock.Mock(return_value={'mode': 'gameplay', 'text': []}),
                              find_bubbles=mock.Mock(return_value=[]))
        detected = [Detection('HouseExit', (1500, 500, 1700, 760), 8.2, None, (1600, 630), .81)]
        vectors = mock.Mock(return_value=detected)
        clues = lambda: {'region': 'House', 'vector_scope': {
            'region': 'House', 'kinds': ['Bed', 'HouseExit']}}
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name), \
                mock.patch.object(observe, 'detect_frame', vectors):
            snapshot = primitives.GameAdapter(clues).observe()
        raw.grab.assert_called_once_with()
        vectors.assert_called_once_with(image, region='House', kinds=['Bed', 'HouseExit'])
        self.assertEqual(snapshot['vector_detections'], [{
            'kind': 'HouseExit', 'point': [1600, 630], 'box': [1500, 500, 1700, 760],
            'score': 8.2, 'raw': .81,
        }])
        self.assertEqual(snapshot['vector_status'], {'status': 'ok', 'region': 'House',
                                                     'requested_kinds': ['Bed', 'HouseExit'], 'hits': 1})

    def test_vector_failure_is_explicit_instead_of_looking_like_no_match(self):
        from PIL import Image
        from types import SimpleNamespace
        from game import act, observe
        raw = SimpleNamespace(grab=lambda: Image.new('RGB', (1920, 1080), '#678967'),
                              classify=lambda image: {'mode': 'gameplay', 'text': []},
                              find_bubbles=lambda image: [])
        clues = lambda: {'region': 'House', 'vector_scope': {'region': 'House', 'kinds': ['HouseExit']}}
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name), \
                mock.patch.object(observe, 'detect_frame', side_effect=RuntimeError('model unavailable')):
            snapshot = primitives.GameAdapter(clues).observe()
        self.assertEqual(snapshot['vector_detections'], [])
        self.assertEqual(snapshot['vector_status']['status'], 'error')
        self.assertIn('model unavailable', snapshot['vector_status']['error'])

    def test_black_observation_fails_closed_and_never_becomes_visual_movement(self):
        from PIL import Image
        from types import SimpleNamespace
        from game import act
        before_path = os.path.join(self.tmp.name, 'before.jpg')
        Image.new('RGB', (1920, 1080), 'gray').save(before_path)
        raw = SimpleNamespace(grab=lambda: Image.new('RGB', (1920, 1080), 'black'),
                              classify=mock.Mock(return_value={'mode': 'gameplay', 'text': []}),
                              find_bubbles=mock.Mock(return_value=[]), wait_settle=lambda: None,
                              log_since=lambda mark: '', _unhash=lambda text: text)
        adapter = primitives.GameAdapter()
        with mock.patch.object(core, 'WF', raw), mock.patch.object(act, 'frames_dir', return_value=self.tmp.name):
            observation = adapter.observe()
            self.assertEqual(observation['screen']['kind'], 'unknown')
            self.assertEqual(observation['capture_validity'], 'black')
            with self.assertRaises(ValueError):
                adapter.prepare({'kind': 'waypoint', 'point': [1250, 640], 'walkable': True}, observation)
            before = dict(self.port.snapshot, frame_path=before_path)
            intent = S.Intent(1, {'kind': 'waypoint'}, 0, 1., before, {'moved': True})
            outcome = adapter.capture(intent, before, intent.expects)
            self.assertIsNone(outcome.evidence.moved)
            self.assertEqual(outcome.verdict.value, 'miss')
        raw.classify.assert_not_called()
        raw.find_bubbles.assert_not_called()

    def test_unrepresentable_appearance_correction_stays_retryable(self):
        e = primitives.experience(S.Intent(1, {'kind': 'wait'}, 0, 1.), self.port.snapshot, {}, X.Evidence())
        with self.assertRaisesRegex(ValueError, 'provenance-bearing sample or reembed'):
            I.correct(e, 'appearance', {'op': 'badge', 'label': 'ready'})

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

    def test_confirmed_space_affordance_learns_bubble_and_graph_interaction_hint(self):
        from PIL import Image

        class Raw:
            def __init__(self):
                self.learned = []
            @staticmethod
            def event_kind(lines):
                return 'sleep' if any('> sleep11 ' in line for line in lines) else None
            def learn_bubble(self, crop, kind, seen):
                self.learned.append((kind, seen))
                return True
            @staticmethod
            def bubble_crop(image, point):
                x, y = point
                return image.crop((x - 20, y - 20, x + 20, y + 20))
            @staticmethod
            def run_log(*args, **kwargs):
                pass

        frame = os.path.join(self.tmp.name, 'sleep-before.png')
        Image.new('RGB', (1920, 1080), 'pink').save(frame)
        graph = Graph()
        graph.nodes['House'] = Node('House', 'region', 'House')
        graph.nodes['Bed'] = Node('Bed', 'unique', 'Bed', region='House')
        raw = Raw()
        graph_path = os.path.join(self.tmp.name, 'graph.json')
        vector_store = __import__('objects.store', fromlist=['Store']).Store(os.path.join(self.tmp.name, 'vectors'))
        experience = X.Experience.new(
            before=X.Observation('gameplay', (('sleep', 656, 624, False, False, True),),
                                 (('region', 'House'), ('position', (13.9, -20.8)),
                                  ('game_time', 'D211 8:29:23 PM'))),
            action=X.Action('space'),
            evidence=X.Evidence(lines=('[D211 8:29:48 PM] > sleep11 me=Player target=Bed',),
                                events=('sleep11',), mode='dialogue',
                                state=(('region', 'House'), ('position', (13.9, -20.8)),
                                       ('game_time', 'D211 8:29:48 PM'))),
            artifacts=X.Artifacts((frame,), frame, None, 0, 1., 234))
        with mock.patch.object(core, 'WF', raw), mock.patch.dict(learn.MEMORY, graph=graph), \
                mock.patch.object(learn, 'GRAPH', graph_path), \
                mock.patch('objects.store.Store', return_value=vector_store):
            result = I.apply(experience)

        self.assertEqual(raw.learned, [('sleep', 'sleep')])
        hint = graph.nodes['Bed'].extra['interaction_hint']
        self.assertEqual(hint['position'], [13.9, -20.8])
        self.assertEqual(hint['screen_point'], [656, 624])
        self.assertLess(hint['screen_dir'][0], 0)
        self.assertEqual(hint['region'], 'House')
        self.assertEqual(hint['experience'], experience.id)
        self.assertTrue(graph.nodes['Bed'].extra['appearance_needed'])
        self.assertIn('bubble:sleep', result['learned'])
        restored = Graph()
        restored.load(graph_path)
        self.assertEqual(restored.nodes['Bed'].extra['interaction_hint'], hint)


if __name__ == '__main__':
    unittest.main()
