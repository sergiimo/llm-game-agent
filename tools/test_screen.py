"""Pure modal recognition and universal primitive guards; no automatic modal-recovery workflows."""
import os
import unittest
from PIL import Image, ImageDraw
from game import primitives, screen


class Screens(unittest.TestCase):
    def test_map_header_vector_distinguishes_map_from_gameplay(self):
        fixtures = os.path.join(os.path.dirname(__file__), 'fixtures', 'play')
        with Image.open(os.path.join(fixtures, 'historical-map-panel.png')) as map_frame, \
                Image.open(os.path.join(fixtures, 'resume-gameplay.jpg')) as gameplay_frame:
            self.assertTrue(screen.map_header_vector(map_frame))
            self.assertFalse(screen.map_header_vector(gameplay_frame))

    def test_map_panel_accepts_current_thin_vertical_paper_border(self):
        image = Image.new('RGB', (1920, 1080), '#303030')
        ImageDraw.Draw(image).rectangle((200, 120, 1720, 900), outline='#e6dcc0', width=5)

        self.assertTrue(screen.map_panel(image))

    def test_semantic_controls_override_scenery_and_world_clues(self):
        for mode, texts, visible, wanted in [
            ('overlay', ['NATE'], False, 'unknown'), ('overlay', ['NATE'], True, 'gameplay'),
            ('overlay', ['Collect'], True, 'card'), ('overlay', ['Inventory', 'Seeds'], True, 'picker'),
            ('cutscene', ['Game Paused', 'Resume Game'], True, 'pause'),
            ('overlay', ['Settings', 'Music Volume'], True, 'menu'),
            ('dialogue', ['Hello'], False, 'dialogue')]:
            with self.subTest(mode=mode, texts=texts):
                self.assertEqual(screen.classify(mode, texts, world_visible=visible), wanted)

    def test_world_inputs_refuse_every_nonworld_modal_without_cleanup(self):
        adapter = primitives.GameAdapter()
        for mode in ('pause', 'menu', 'map', 'card', 'picker', 'dialogue', 'popup', 'cutscene', 'unknown'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                adapter.prepare({'kind': 'target', 'point': [1100, 600], 'visible_road': True},
                                {'screen': {'kind': mode}})

    def test_escape_is_guarded_by_recognized_closable_panel(self):
        adapter = primitives.GameAdapter()
        for mode in ('card', 'picker', 'map', 'journal', 'inventory', 'shop'):
            with self.subTest(mode=mode):
                self.assertEqual(adapter.prepare({'kind': 'close'}, {'screen': {'kind': mode}})['command'],
                                 'key:escape')
        for mode in ('gameplay', 'pause', 'unknown', 'menu'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                adapter.prepare({'kind': 'close'}, {'screen': {'kind': mode}})
