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


class ClientDelivery(unittest.TestCase):
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
        log = self.root / 'log.jsonl'
        log.write_text('{"t": 150, "type": "turn", "phase": "outcome"}\n')
        (self.root / 'run.current').write_text(str(log))
        with mock.patch.object(wfc, 'SOCK', str(self.root / 'wf.sock')), mock.patch('time.time', return_value=200):
            wfc.log_end(100, ['garden', 'answer=accept'])
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([r['t'] for r in rows], [150, 200])
        self.assertEqual((rows[-1]['start'], rows[-1]['end']), (100, 200))

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
