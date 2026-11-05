#!/usr/bin/env python3
"""State-brief contract for model-decided near navigation."""
import os
import sys
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game import brief, core, engine
from game.affordances import Affordance
from objects.detect import Detection
from objects.graph import Graph, Node


class StateBrief(unittest.TestCase):
    def setUp(self):
        self.g = Graph()
        self.g.nodes['Tara'] = Node('Tara', 'unique', region='Farm', pos=[0.0, 0.0])
        self.g.nodes['Garden'] = Node('Garden', 'region', region='Farm', area=True, pos=[0.0, 0.0])
        self.g.nodes['bed-today'] = Node('bed-today', 'member', kind='GardenBed', region='Garden',
                                             pos=[2.0, 1.0], scene='Farm')
        self.g.nodes['bed-save'] = Node('bed-save', 'member', kind='GardenBed', region='Garden',
                                            pos=[-1.0, -2.0], scene='Farm')
        self.g.set_state('bed-today', 'ready', False, 'D185 9:00:00 AM', 'card')
        self.g.set_state('bed-today', 'crop', 'Tulip', 'D185 9:00:00 AM', 'card')
        self.g.set_state('bed-save', 'ready', True, 'D185 7:00:00 AM', 'save')
        self.g.set_state('bed-save', 'crop', 'Green Bean', 'D185 7:00:00 AM', 'save')
        self.res = {
            'spec': {'where': {'ready': True}},
            'params': {},
            'recent': [{'pt': (i, i + 1), 'what': 'step', 'events': [], 'result': 'walked'} for i in range(8)],
        }

    def make(self, bubbles=(), detections=()):
        patches = (
            mock.patch('game.where.position', return_value=('event', (0.0, 0.0))),
            mock.patch('game.observe.scan', return_value=list(bubbles)),
            mock.patch('game.observe.see_all', return_value=list(detections)),
            mock.patch.object(engine, '_today', return_value=185),
        )
        with patches[0], patches[1], patches[2], patches[3]:
            return brief.build(self.g, 'GardenBed', ['bed-today', 'bed-save'], self.res)

    def test_objects_carry_status_freshness_need_and_screen_points(self):
        out = self.make()
        objects = {o['id']: o for o in out['objects']}
        self.assertEqual(objects['bed-today']['status'], {'ready': False, 'crop': 'Tulip'})
        self.assertEqual(objects['bed-today']['fresh'], 'today')
        self.assertFalse(objects['bed-today']['need'])
        self.assertEqual(objects['bed-today']['screen'], engine.screen_point((0.0, 0.0), (2.0, 1.0)))
        self.assertEqual(objects['bed-save']['fresh'], 'save')
        self.assertTrue(objects['bed-save']['need'])
        self.assertEqual(objects['bed-save']['screen'], engine.screen_point((0.0, 0.0), (-1.0, -2.0)))
        self.assertEqual(out['recent'], self.res['recent'][-6:])

    def test_bubbles_are_mapped_to_their_objects(self):
        pt = engine.screen_point((0.0, 0.0), (2.0, 1.0))
        bubble = Affordance('pickup', None, (pt[0] + engine.OWN_PX - 1, pt[1]), False, 0.0,
                            ready=True, badge='ready', icon='Tulip')
        out = self.make(bubbles=[bubble])
        self.assertEqual(out['bubbles'], [{
            'pt': bubble.pt, 'kind': 'pickup', 'icon': 'Tulip', 'badge': 'ready', 'owner': 'bed-today'
        }])

    def test_the_drawing_is_full_scale_with_labels(self):
        detection = Detection('GardenBed', (1, 2, 3, 4), 8.0, None, (400, 300), 0.8)
        wf = mock.Mock()
        old = core.WF
        core.bind(wf)
        self.addCleanup(core.bind, old)
        out = self.make(detections=[detection])
        frame = Image.new('RGB', (1920, 1080), 'white')
        drawn = brief.draw(frame, out)
        pt = out['objects'][0]['screen']
        self.assertEqual(drawn.size, frame.size)
        self.assertNotEqual(drawn.getpixel(pt), frame.getpixel(pt))
        self.assertEqual(out['heatmap'], [{'kind': 'GardenBed', 'pt': (400, 300)}])
        wf.run_log.assert_called_once_with('perception', source='object_heatmap',
                                           detections=[{'kind': 'GardenBed', 'pt': [400, 300]}])

    def test_position_source_is_shown(self):
        self.assertIn(self.make()['tara']['source'], {'event', 'walk', 'save', 'unknown'})
        self.assertIn('Tara event', brief.text(self.make()))


if __name__ == '__main__':
    unittest.main()
