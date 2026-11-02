"""Offline tests for optional node map representations and heatmaps."""
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from objects import graph as G, map_vectors as M, store as S  # noqa: E402

SEED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'graph_seed.json')


class MapVectorsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.g = G.Graph()
        self.g.load(SEED)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_target_inherits_nearest_represented_ancestor(self):
        self.assertEqual(M.representation(self.g, 'GardenBed@Garden#r1c1'),
                         M.Representation('Garden', 'farm-garden', 'MapGarden'))
        self.assertEqual(M.representation(self.g, 'Stove'),
                         M.Representation('House', 'farmhouse', 'MapHouse'))
        self.assertEqual(M.representation(self.g, 'Well').node_id, 'Garden')
        self.assertIsNone(M.representation(self.g, 'Mailbox'))
        self.assertFalse(any(n.id.startswith('@map') for n in self.g.nodes.values()))

    def test_labelled_points_seed_only_represented_nodes(self):
        image = Image.new('RGB', (300, 200), (20, 30, 40))
        store = S.Store(self.tmp)
        rows = M.seed(self.g, image, {'farmhouse': (200, 80), 'farm-garden': (100, 80), 'unused': (10, 10)},
                      store=store, size=28, embed=lambda crop: np.array([1, 0], np.float32))
        self.assertEqual({r['node'] for r in rows}, {'House', 'Garden'})
        self.assertEqual(store.kinds(), ['MapGarden', 'MapHouse'])
        with Image.open(store.example_path('MapGarden', rows[1]['id'])) as crop:
            self.assertEqual(crop.size, (28, 28))

    def test_seed_uses_labelled_patch_from_full_map(self):
        image = Image.new('RGB', (300, 200))
        features = np.arange(2 * 3 * 2, dtype=np.float32).reshape(2, 3, 2)
        store = S.Store(self.tmp)
        M.seed(self.g, image, {'farmhouse': (250, 150), 'farm-garden': (150, 50)}, store=store,
               feature_fn=lambda _: features)
        np.testing.assert_array_equal(store.examples('MapGarden')[0].vec,
                                      features[0, 1] / np.linalg.norm(features[0, 1]))

    def test_locate_returns_peak_and_rendered_heatmap(self):
        image = Image.new('RGB', (300, 200), (20, 30, 40))
        features = np.array([[[0, 1], [1, 0], [.2, .8]],
                             [[.3, .7], [.4, .6], [.5, .5]]], np.float32)
        match = M.locate(self.g, 'GardenBed@Garden#r1c1', image, store=object(),
                         feature_fn=lambda _: features,
                         vector_fn=lambda _store, kind: np.array([[1, 0]], np.float32))
        self.assertEqual(match.representation.node_id, 'Garden')
        self.assertEqual(match.point, (150, 50))
        self.assertGreater(match.score, 1)
        output = os.path.join(self.tmp, 'heatmap.png')
        self.assertEqual(M.render(image, match, output).size, image.size)
        self.assertTrue(os.path.exists(output))

    def test_unrepresented_target_has_no_heatmap(self):
        self.assertIsNone(M.locate(self.g, 'Mailbox', Image.new('RGB', (10, 10)), store=object(),
                                   feature_fn=lambda _: None, vector_fn=lambda *_: None))


if __name__ == '__main__':
    unittest.main()
