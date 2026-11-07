"""Offline daemon/data boundaries. No game inputs or heavyweight feature models."""
import json
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wfc
from game import badges, core, icons, items, plan


class RevisionedWorldSnapshot(unittest.TestCase):
    def test_unchanged_revisions_do_not_reload_or_refresh_the_graph(self):
        from game import snapshot
        graph = object()
        load = mock.Mock(return_value=graph)
        refresh = mock.Mock()
        cache = snapshot.WorldSnapshot(refresh_world=refresh)
        save = {'saveCount': 7, 'currentScene': 'Farm'}
        first = cache.refresh(load, save, ['line-1'], graph_revision=('graph', 1))
        second = cache.refresh(load, save, ['line-1'], graph_revision=('graph', 1))
        self.assertIs(first.graph, graph)
        self.assertIs(second.graph, graph)
        load.assert_called_once_with()
        refresh.assert_called_once_with(graph, save, ['line-1'])
        self.assertEqual(second.revision, first.revision)

    def test_log_change_refreshes_once_and_graph_revision_reloads_once(self):
        from game import snapshot
        graphs = [object(), object()]
        load = mock.Mock(side_effect=graphs)
        refresh = mock.Mock()
        cache = snapshot.WorldSnapshot(refresh_world=refresh)
        save = {'saveCount': 7}
        cache.refresh(load, save, ['line-1'], graph_revision=('graph', 1))
        changed = cache.refresh(load, save, ['line-1', 'line-2'], graph_revision=('graph', 1))
        reloaded = cache.refresh(load, save, ['line-1', 'line-2'], graph_revision=('graph', 2))
        self.assertEqual(refresh.call_count, 3)
        self.assertEqual(load.call_count, 2)
        self.assertIs(changed.graph, graphs[0])
        self.assertIs(reloaded.graph, graphs[1])

    def test_replacement_save_and_truncated_log_reload_the_base_graph(self):
        from game import snapshot
        graphs = [object(), object(), object()]
        load = mock.Mock(side_effect=graphs)
        refresh = mock.Mock()
        cache = snapshot.WorldSnapshot(refresh_world=refresh)
        cache.refresh(load, {'saveCount': 7, 'currentScene': 'Farm', 'value': False},
                      ['old', 'water'], graph_revision=('graph', 1))
        replaced = cache.refresh(load, {'saveCount': 7, 'currentScene': 'Farm', 'value': True},
                                 ['old', 'water'], graph_revision=('graph', 1))
        truncated = cache.refresh(load, {'saveCount': 7, 'currentScene': 'Farm', 'value': True},
                                  [], graph_revision=('graph', 1))
        self.assertIs(replaced.graph, graphs[1])
        self.assertIs(truncated.graph, graphs[2])
        self.assertEqual(load.call_count, 3)


class LiveLogEpoch(unittest.TestCase):
    def test_generic_scene_controller_restore_is_not_physical_scene_identity(self):
        import wf
        lines = ('[D4 11:00:00 AM] [SCENE] Restore SceneController',
                 '[D4 11:33:56 AM] [TRIGGER] OnExitBuilding Butcher')
        with tempfile.NamedTemporaryFile() as log, mock.patch.object(wf, 'GAME_LOG', log.name), \
                mock.patch.object(wf, 'game_log', return_value=lines):
            epoch = wf.log_epoch()
        self.assertIsNone(epoch.scene)

    def test_only_explicit_scene_assignment_supplies_scene_identity(self):
        import wf
        lines = ('[D4 11:00:00 AM] [SCENE] Restore SceneController',
                 '[D4 11:40:00 AM] currentScene = Town')
        with tempfile.NamedTemporaryFile() as log, mock.patch.object(wf, 'GAME_LOG', log.name), \
                mock.patch.object(wf, 'game_log', return_value=lines):
            epoch = wf.log_epoch()
        self.assertEqual(epoch.scene, 'Town')


class ClientDelivery(unittest.TestCase):
    def test_default_deadline_allows_bounded_game_action_response(self):
        response = json.dumps({'out': 'gameplay\n', 'code': 0}).encode() + b'\n'
        endpoint = mock.MagicMock()
        endpoint.__enter__.return_value = endpoint

        def receive(_size):
            allowed = endpoint.settimeout.call_args.args[0]
            if allowed < 30:
                raise TimeoutError('legal bounded action still running')
            return response

        endpoint.recv.side_effect = receive
        with mock.patch.object(wfc.socket, 'socket', return_value=endpoint), \
                contextlib.redirect_stdout(io.StringIO()) as result:
            self.assertEqual(wfc.via_daemon(['do', 'go:350:510']), 0)
        self.assertEqual(result.getvalue(), 'gameplay\n')

    def test_timeout_eof_or_invalid_response_after_send_is_not_retried(self):
        for response in ('timeout', 'eof', 'invalid', 'partial_send'):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                endpoint = mock.MagicMock()
                endpoint.__enter__.return_value = endpoint
                if response == 'timeout':
                    endpoint.recv.side_effect = TimeoutError('slow daemon')
                elif response == 'partial_send':
                    endpoint.sendall.side_effect = OSError('partial send')
                else:
                    endpoint.recv.return_value = b'' if response == 'eof' else b'invalid json\n'
                with mock.patch.object(wfc, 'SOCK', os.path.join(directory, 'wf.sock')), \
                     mock.patch.object(wfc.socket, 'socket', return_value=endpoint), \
                     mock.patch.object(wfc, 'parent_cmdline', return_value=''), \
                     mock.patch.object(wfc, 'code_mtimes', return_value=[]), \
                     mock.patch.object(wfc, 'log_call', return_value=None), \
                     mock.patch.object(wfc.os.path, 'exists', return_value=True), \
                     mock.patch.object(wfc.subprocess, 'Popen', side_effect=AssertionError('uncertain request resent')), \
                     mock.patch.object(wfc.os, 'execv', side_effect=AssertionError('uncertain request fell back')), \
                     mock.patch.object(sys, 'argv', ['wfc', 'play', 'turn_id=188', 'answer={"kind":"read"}']), \
                     contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(wfc.main(), 1)
                self.assertIn('unknown', error.getvalue())
                self.assertEqual(endpoint.sendall.call_count, 1)
                endpoint.close.assert_called()

    def test_pre_delivery_connect_failure_can_start_daemon_once(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(wfc, 'SOCK', os.path.join(directory, 'wf.sock')), \
             mock.patch.object(wfc, 'via_daemon', side_effect=[ConnectionRefusedError('not listening'), 0]) as call, \
             mock.patch.object(wfc, 'parent_cmdline', return_value=''), \
             mock.patch.object(wfc, 'log_call', return_value=None), \
             mock.patch.object(wfc.subprocess, 'Popen') as start, \
             mock.patch('time.sleep'), \
             mock.patch.object(sys, 'argv', ['wfc', 'status']):
            self.assertEqual(wfc.main(), 0)
        self.assertEqual(call.call_count, 2)
        start.assert_called_once()

    def test_fragmented_response_preserves_all_evidence_and_utf8(self):
        output = 'NEXT ' + json.dumps({'source': 'source frame\n', 'text': 'Tara café', 'evidence': list(range(5000))})
        encoded = (json.dumps({'out': output, 'code': 0}, ensure_ascii=False) + '\n').encode()
        endpoint = mock.MagicMock()
        endpoint.__enter__.return_value = endpoint
        endpoint.recv.side_effect = [encoded[i:i+127] for i in range(0, len(encoded), 127)]
        with mock.patch.object(wfc.socket, 'socket', return_value=endpoint), contextlib.redirect_stdout(io.StringIO()) as result:
            self.assertEqual(wfc.via_daemon(['play']), 0)
        self.assertEqual(result.getvalue(), output)

    def test_response_deadline_covers_slow_dribble_not_each_chunk_separately(self):
        clock = [0.]
        endpoint = mock.MagicMock()
        endpoint.__enter__.return_value = endpoint
        def receive(size):
            clock[0] += .6
            if endpoint.recv.call_count > 3:
                raise AssertionError('unbounded dribble receive')
            return b' '
        endpoint.recv.side_effect = receive
        with mock.patch.object(wfc.socket, 'socket', return_value=endpoint), \
                mock.patch('time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, 'unknown'):
                wfc.via_daemon(['play'], timeout=1.)
        self.assertLessEqual(endpoint.recv.call_count, 2)


class StopLocalAutomation(unittest.TestCase):
    @staticmethod
    def result(code):
        return mock.Mock(returncode=code)

    def test_watcher_target_is_limited_to_live_follow_processes(self):
        self.assertEqual(dict(wfc.LOCAL_AUTOMATION)['watcher'], r'tools/runwatch\.py .*--follow')

    def test_stop_attempts_every_owned_process_and_removes_the_socket(self):
        calls = []
        def run(argv, **_kwargs):
            calls.append(argv)
            return self.result(0 if argv[0] == 'pkill' else 1)
        unlink = mock.Mock()

        attempted, errors = wfc.stop_local_automation(run=run, unlink=unlink)

        self.assertEqual(attempted, ['controller', 'watcher'])
        self.assertEqual(errors, [])
        self.assertEqual([call[:2] for call in calls],
                         [['pkill', '-f'], ['pkill', '-f'], ['pgrep', '-f'], ['pgrep', '-f']])
        self.assertEqual([call[-1] for call in calls[:2]], [pattern for _label, pattern in wfc.LOCAL_AUTOMATION])
        unlink.assert_called_once_with(wfc.SOCK)

    def test_stop_reports_a_survivor_after_attempting_every_target(self):
        def run(argv, **_kwargs):
            if argv[0] == 'pgrep' and argv[-1] == dict(wfc.LOCAL_AUTOMATION)['watcher']:
                return self.result(0)
            return self.result(0 if argv[0] == 'pkill' else 1)

        attempted, errors = wfc.stop_local_automation(run=run, unlink=mock.Mock())

        self.assertEqual(attempted, ['controller', 'watcher'])
        self.assertEqual(errors, ['watcher still running'])

    def test_stop_allows_a_signalled_process_a_bounded_exit_window(self):
        watcher_checks = [0, 1]
        def run(argv, **_kwargs):
            if argv[0] == 'pgrep' and argv[-1] == dict(wfc.LOCAL_AUTOMATION)['watcher']:
                return self.result(watcher_checks.pop(0))
            return self.result(0 if argv[0] == 'pkill' else 1)
        sleep = mock.Mock()

        _attempted, errors = wfc.stop_local_automation(run=run, unlink=mock.Mock(), sleep=sleep)

        self.assertEqual(errors, [])
        sleep.assert_called_once_with(0.05)

    def test_stop_reports_process_query_failure_instead_of_claiming_success(self):
        calls = []
        def run(argv, **_kwargs):
            calls.append(argv)
            if argv[0] == 'pkill' and argv[-1] == 'tools/wf.py serve':
                raise OSError('pkill unavailable')
            return self.result(1)

        attempted, errors = wfc.stop_local_automation(run=run, unlink=mock.Mock())

        self.assertEqual(attempted, ['controller', 'watcher'])
        self.assertIn('controller stop failed: pkill unavailable', errors)
        self.assertEqual(sum(call[0] == 'pkill' for call in calls), 2)
        self.assertEqual(sum(call[0] == 'pgrep' for call in calls), 2)

    def test_stop_cli_uses_local_shutdown_without_starting_the_daemon(self):
        with mock.patch.object(wfc, 'parent_cmdline', return_value=''), \
             mock.patch.object(wfc, 'log_call', return_value=None), \
             mock.patch.object(wfc, 'stop_local_automation', return_value=(['controller', 'watcher'], [])) as stop, \
             mock.patch.object(wfc.subprocess, 'Popen', side_effect=AssertionError('stop started daemon')), \
             mock.patch.object(wfc.os, 'execv', side_effect=AssertionError('stop fell through')), \
             mock.patch.object(sys, 'argv', ['wfc', 'stop']), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(wfc.main(), 0)
        stop.assert_called_once_with()
        self.assertEqual(output.getvalue(), 'stopped: controller, watcher\n')

    def test_stop_cli_returns_failure_when_local_automation_survives(self):
        with mock.patch.object(wfc, 'parent_cmdline', return_value=''), \
             mock.patch.object(wfc, 'log_call', return_value=None), \
             mock.patch.object(wfc, 'stop_local_automation',
                               return_value=(['controller', 'watcher'], ['watcher still running'])), \
             mock.patch.object(sys, 'argv', ['wfc', 'stop']), \
             contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(wfc.main(), 1)
        self.assertIn('STOP FAILED: watcher still running', error.getvalue())


class HotData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_optional_timing_survives_exception_without_recording_request_payload(self):
        from runtime.timing import measure
        path = self.root / 'timing.jsonl'
        with mock.patch.dict(os.environ, WF_TIMING_FILE=str(path)):
            with self.assertRaisesRegex(ValueError, 'example failure'):
                with measure('test.boundary', command='play'):
                    raise ValueError('example failure')
        row = json.loads(path.read_text())
        self.assertEqual(row['phase'], 'test.boundary')
        self.assertGreaterEqual(row['seconds'], 0)
        self.assertEqual(row['command'], 'play')
        self.assertEqual(row['status'], 'error')
        self.assertNotIn('payload', row)

    def test_diagnostic_encoding_failure_does_not_change_operation_success(self):
        from runtime.timing import measure
        with mock.patch.dict(os.environ, WF_TIMING_FILE=str(self.root / 'timing.jsonl')):
            with measure('test.diagnostic', unsupported=object()):
                completed = True
        self.assertTrue(completed)

    def test_isolated_wrapper_help_imports_owned_timing_module_without_game_access(self):
        import subprocess
        result = subprocess.run([sys.executable, '-I', wfc.__file__, '--help'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: wf', result.stdout)

    def test_learning_does_not_restart_but_python_and_configuration_do(self):
        game = self.root / 'game'
        game.mkdir()
        source = game / 'turn.py'
        source.write_text('# code')
        config = game / 'kinds.json'
        config.write_text('{}')
        for p in (source, config):
            os.utime(p, (50, 50))
        with mock.patch.object(wfc, 'CODE', [str(game)]):
            for name in ('actions.json', 'observed-steps.jsonl', 'graph/Farm.json', 'db/Bed/index.npz'):
                learned = game / name
                learned.parent.mkdir(parents=True, exist_ok=True)
                learned.write_text('learned')
                os.utime(learned, (150, 150))
            self.assertFalse(wfc.stale(100, wfc.code_mtimes()))
            os.utime(source, (150, 150))
            self.assertTrue(wfc.stale(100, wfc.code_mtimes()))
            os.utime(source, (50, 50))
            os.utime(config, (150, 150))
            self.assertTrue(wfc.stale(100, wfc.code_mtimes()))

    def test_transition_learning_is_visible_in_same_process(self):
        path = self.root / 'actions.json'
        path.write_text('{"rows": []}')
        with mock.patch.object(plan, 'DB', str(path)):
            self.assertEqual(plan.rows(), [])
            path.write_text(json.dumps({'rows': [{'id': 'learned', 'kind': 'Bed'}]}))
            self.assertEqual(plan.rows('Bed'), [{'id': 'learned', 'kind': 'Bed'}])

    def test_completed_call_timestamp_keeps_append_timeline_chronological(self):
        from runtime.db import Database
        from runtime.run_store import RunStore
        database = self.root / 'wf.sqlite3'
        store = RunStore(Database(database))
        run_id = store.start('test', 'call timing', self.root / 'run')
        store.append_event('turn', {}, phase='outcome', t=150)
        with mock.patch.object(wfc, 'SOCK', str(self.root / 'wf.sock')), \
                mock.patch.dict(os.environ, WF_DB=str(database)), mock.patch('time.time', return_value=200):
            wfc.log_end(100, ['garden', 'answer=accept'])
        rows = [row for row in store.events(run_id) if row['type'] in ('turn', 'call')]
        self.assertEqual([r['t'] for r in rows], [150, 200])
        self.assertEqual((rows[-1]['start'], rows[-1]['end']), (100, 200))
        self.assertFalse((self.root / 'run.current').exists())
        self.assertFalse((self.root / 'run' / 'log.jsonl').exists())

    def test_completed_command_survives_sqlite_accounting_failure(self):
        database = self.root / 'wf.sqlite3'
        database.touch()
        with mock.patch.object(wfc, 'SOCK', str(self.root / 'wf.sock')), \
                mock.patch.dict(os.environ, WF_DB=str(database)), \
                mock.patch.object(wfc.RunStore, 'append_event', side_effect=RuntimeError('bad database')):
            self.assertIsNone(wfc.log_end(100, ['play'], delivery='delivered'))

    def test_production_runtime_has_no_replaced_structured_file_fallbacks(self):
        root = Path(__file__).resolve().parent
        sources = [root / 'wf.py', root / 'wfc.py', root / 'runwatch.py']
        sources += list((root / 'game').glob('*.py')) + list((root / 'runtime').glob('*.py'))
        retired = ('task.json', 'garden-task.json', 'log.jsonl', 'experiences.jsonl',
                   'applied.txt', 'run.current')
        offenders = [(path.name, name) for path in sources for name in retired
                     if name in path.read_text()]
        self.assertEqual(offenders, [])

    def test_external_icon_add_replace_remove_is_hot(self):
        path = self.root / 'Tulip' / 'one.png'
        path.parent.mkdir()
        dark, light = Image.new('RGB', (140, 140), 'black'), Image.new('RGB', (140, 140), 'white')
        # Feature extraction is the external boundary; matching and file invalidation remain real.
        with mock.patch.object(icons, 'DIR', self.tmp.name), mock.patch.object(core, 'WF', None):
            icons.reset()
            self.addCleanup(icons.reset)
            self.assertIsNone(icons.match(dark))
            dark.save(path)
            self.assertEqual(icons.match(dark), 'Tulip')
            light.save(path)
            self.assertIsNone(icons.match(dark))
            self.assertEqual(icons.match(light), 'Tulip')
            path.unlink()
            self.assertIsNone(icons.match(light))

    def test_external_badge_relabel_is_hot(self):
        dark, light = Image.new('RGB', (140, 140), 'black'), Image.new('RGB', (140, 140), 'white')
        for label, image in (('ready', dark), ('drop', light)):
            (self.root / label).mkdir()
            image.save(self.root / label / 'one.png')
        with mock.patch.object(badges, 'DIR', self.tmp.name), mock.patch.object(core, 'WF', None):
            badges.reset()
            self.addCleanup(badges.reset)
            self.assertEqual(badges.read(dark), 'ready')
            dark.save(self.root / 'drop' / 'one.png')
            light.save(self.root / 'ready' / 'one.png')
            self.assertEqual(badges.read(dark), 'drop')

    def test_external_bubble_addition_is_hot(self):
        import numpy as np
        import wf
        image = Image.new('RGB', (140, 140), 'black')
        # Apple Vision is replaced only at its feature-extraction boundary.
        vector = lambda im: np.asarray(im.resize((1, 1)), dtype=float).ravel() / 255
        with mock.patch.object(wf, 'BUBBLE_DIR', self.tmp.name), \
                mock.patch.object(wf, '_BUBBLE_REFS', None), \
                mock.patch.object(wf, '_featureprint', vector):
            self.assertEqual(wf.bubble_kind(image, (70, 70))[0], 'unknown')
            (self.root / 'plant').mkdir()
            image.save(self.root / 'plant' / 'one.png')
            self.assertEqual(wf.bubble_kind(image, (70, 70))[0], 'plant')

    def test_external_item_icon_addition_is_hot(self):
        import numpy as np
        from types import SimpleNamespace
        image = Image.new('RGB', (140, 140), 'black')
        vector = lambda im: np.asarray(im.resize((1, 1)), dtype=float).ravel() / 255
        with mock.patch.object(items, 'ITEM_DIR', self.tmp.name), mock.patch.object(items, '_REFS', None), \
                mock.patch.object(core, 'WF', SimpleNamespace(_featureprint=vector)):
            self.assertIsNone(items.match(image)[0])
            (self.root / 'Tulip_Bulbs').mkdir()
            image.save(self.root / 'Tulip_Bulbs' / 'one.png')
            self.assertEqual(items.match(image)[0], 'Tulip_Bulbs')

    def test_detector_reloads_replaced_example_with_same_id(self):
        import numpy as np
        from objects import detect, store
        s = store.Store(self.tmp.name)
        ex = s.add('Bed', Image.new('RGB', (8, 8), 'black'), [1., 0.])
        def vector(im):
            return np.asarray(im.resize((1, 1)), dtype=float).reshape(1, 3)
        with mock.patch.object(detect.dino, 'crop_vectors', vector):
            self.assertEqual(detect.kind_vectors(s, 'Bed').tolist(), [[0., 0., 0.]])
            Image.new('RGB', (8, 8), 'white').save(s.example_path('Bed', ex.id))
            self.assertEqual(detect.kind_vectors(s, 'Bed').tolist(), [[255., 255., 255.]])


if __name__ == '__main__':
    unittest.main()
