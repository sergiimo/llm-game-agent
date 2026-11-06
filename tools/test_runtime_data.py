"""Offline daemon/data boundaries. No game inputs or heavyweight feature models."""
import json
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


class HotData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

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
