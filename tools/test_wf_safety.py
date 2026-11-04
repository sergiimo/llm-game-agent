"""Safety tests for tools/wf.py input (S13: clicks landed on the pause/Settings menu and changed the user's audio).
Run: .venv/bin/python tools/test_wf_safety.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ['x']
import wf  # noqa: E402


class NoClickThroughMenus(unittest.TestCase):
    def setUp(self):
        self.clicks = []
        self._orig = (wf.state, wf.click)
        wf.click = lambda x, y, *a, **k: self.clicks.append((x, y))

    def tearDown(self):
        wf.state, wf.click = self._orig

    def test_refuses_on_pause_menu(self):
        wf.state = lambda save=False: {'mode': 'overlay', 'text': ['0) Game Paused', '1) Settings']}
        msg = wf.go_to(900, 600)
        self.assertTrue(msg.startswith('MENU OPEN'), msg)
        self.assertIn('menu', msg)
        self.assertEqual(self.clicks, [])

    def test_refuses_on_russian_pause_menu_and_recognises_paused(self):
        s = {'mode': 'overlay', 'text': ['0) Пауза', '1) Продолжить игру', '2) Настройки']}
        wf.state = lambda save=False: s
        self.assertTrue(wf.is_paused(s))
        self.assertTrue(wf.go_to(900, 600).startswith('MENU OPEN'))
        self.assertEqual(self.clicks, [])

    def test_a_raw_click_refuses_on_the_pause_menu(self):
        """Live engine run D186: world clicks landed on the pause menu (Resume / Settings / Return to Menu / Exit Game)
        and the game exited. `click:` (the engine's clicks) refuses like `go:`."""
        wf.state = lambda save=False: {'mode': 'overlay', 'text': ['0) Game Paused', '1) Resume Game', '2) Exit Game']}
        msg = wf.run_action_inner('click:960:840')
        self.assertTrue(msg.startswith('PAUSE MENU OPEN'), msg)
        self.assertEqual(self.clicks, [])

    def test_refuses_on_settings_sliders(self):
        wf.state = lambda save=False: {'mode': 'overlay', 'text': ['0) Settings', '1) Music Volume']}
        self.assertTrue(wf.go_to(900, 600).startswith('MENU OPEN'))
        self.assertEqual(self.clicks, [])

    def test_passive_info_card_does_not_block(self):
        wf.state = lambda save=False: {'mode': 'overlay', 'text': [
            '0) Bee Hive', '1) Plant flowers nearby to encourage the bees to produce honey for you']}
        self.assertIsNone(wf.menu_open(wf.state()))

    def test_volume_without_settings_header(self):          # review #4
        self.assertIsNotNone(wf.menu_open({'mode': 'overlay', 'text': ['0) Master Volume', '1) Music']}))

    def test_gameplay_toast_does_not_block(self):           # review #5
        self.assertIsNone(wf.menu_open({'mode': 'gameplay', 'text': ['0) Inventory full']}))

    def test_refusal_is_not_no_move(self):                  # review #2: callers must not treat it as unwalkable
        wf.state = lambda save=False: {'mode': 'overlay', 'text': ['0) Game Paused']}
        self.assertTrue(wf.go_to(900, 600).startswith('MENU OPEN'))

    def test_short_click_on_the_object_under_her_refused(self):   # shadow-2: clicks at her feet opened the bed
        import nav
        from world import model
        H = [[8.659732, -0.005814, -0.001597], [0.074748, -21.414692, 5.617554], [-0.005491, 0.509604, 1.0]]
        w = model.World(facts=[], cache=os.devnull)
        w.belief.scene('Farm', 3.34, -25.34)
        w.ents.add('GardenBed', 'Farm', 3.34, -25.34, 'test')
        self._w = (wf.world, wf.calib_load)
        wf.world, wf.calib_load = (lambda: w), (lambda a: {'H': H})
        try:
            wf.state = lambda save=False: {'mode': 'gameplay', 'text': []}
            sx, sy = nav.ground_to_screen(H, 0.3, -0.2)              # a click 0.4 units from her, on the bed
            msg = wf.go_to(sx, sy)
            self.assertTrue(msg and msg.startswith('NO MOVE'), msg)
            self.assertIn('GardenBed', msg)
            self.assertEqual(self.clicks, [])
        finally:
            wf.world, wf.calib_load = self._w


class Bubbles(unittest.TestCase):
    def test_embedding_crop_excludes_the_human_orange_highlight_ring(self):
        from PIL import Image, ImageDraw
        plain = Image.new('RGB', (140, 140), 'white')
        ImageDraw.Draw(plain).rectangle((55, 55, 85, 85), fill='blue')
        highlighted = plain.copy()
        ImageDraw.Draw(highlighted).ellipse((12, 12, 128, 128), outline='orange', width=12)
        self.assertEqual(wf.bubble_icon(plain).tobytes(), wf.bubble_icon(highlighted).tobytes())

    def test_night_bubbles_found(self):                     # zoom-walk 9:20 pm: 3 honey bubbles, detector found 0
        from PIL import Image
        img = Image.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures',
                                      'bubbles_night_look.jpg')).convert('RGB').resize((1920, 1080))
        bs = wf.find_bubbles(img)
        # a 0.4-scale JPEG upscaled: the highlighted (orange-ringed) third bubble needs a real night frame to tune
        self.assertGreaterEqual(len([b for b in bs if 430 <= b[1] <= 540]), 2, bs)


class Mapping(unittest.TestCase):
    def check(self, w, x0, y0, sc):
        got = wf.content_box(w)
        for a, b in zip(got, (x0, y0, sc)):
            self.assertAlmostEqual(a, b, delta=0.001 if b < 5 else 0.1, msg=str(got))

    def test_second_display_window(self):
        self.check({'x': 1958, 'y': 65, 'w': 1920, 'h': 978}, 115.6, 28.0, 0.8796)

    def test_windowed_16_9(self):
        self.check({'x': 0, 'y': 38, 'w': 1600, 'h': 928}, 0.0, 28.0, 0.8333)

    def test_fullscreen_no_bar(self):
        self.check({'x': 0, 'y': 0, 'w': 1920, 'h': 1080}, 0.0, 0.0, 1.0)

    def test_tall_window_centred(self):
        self.check({'x': 0, 'y': 40, 'w': 1600, 'h': 1100}, 0.0, 114.0, 0.8333)


class ChainedCalls(unittest.TestCase):
    """AGENTS.md rule 8: an input command must not be chained with another ./wf call in one tool call."""

    @classmethod
    def setUpClass(cls):
        import wfc
        cls.wfc = wfc

    def refused(self, argv, parent):
        return self.wfc.chain_refusal(argv, parent) is not None

    def test_input_chained_is_refused(self):
        self.assertTrue(self.refused(['do', 'go:1:2'], './wf resume; ./wf do go:1:2'))
        self.assertTrue(self.refused(['do', 'go:1:2'], 'cd x && ./wf pause && ./wf do go:1:2'))
        self.assertTrue(self.refused(['resume'], './wf resume\n./wf do go:1:2'))
        self.assertIn('REFUSED', self.wfc.chain_refusal(['do'], './wf resume; ./wf do go:1:2'))

    def test_read_only_chain_allowed(self):
        self.assertFalse(self.refused(['log'], './wf log; ./wf state'))
        self.assertFalse(self.refused(['run', 'step', '1', 'done'], './wf run step 1 done && ./wf shot'))
        self.assertFalse(self.refused(['focus-mode'], './wf focus-mode || ./wf status'))

    def test_claude_code_eval_wrapper(self):   # the Bash tool runs `zsh -c … && eval '<command>'`: ./wf right after a quote
        wrap = "/bin/zsh -c source s.sh 2>/dev/null || true && eval '%s' < /dev/null && pwd -P >| /tmp/cwd"
        self.assertTrue(self.refused(['pause'], wrap % './wf state | head -1; ./wf pause; echo "exit $?"'))
        self.assertFalse(self.refused(['pause'], wrap % './wf pause'))

    def test_single_call_allowed(self):
        self.assertFalse(self.refused(['do', 'go:1:2'], './wf do go:1:2'))
        self.assertFalse(self.refused(['do', 'go:1:2'], '/bin/zsh -c ./wf do go:1:2 | tail -3'))
        self.assertFalse(self.refused(['do', 'go:1:2'], ''))

    def test_focus_mode_with_args_is_not_read_only(self):
        self.assertTrue(self.refused(['focus-mode', 'front'], './wf focus-mode front; ./wf state'))

    def test_other_wf_text_is_not_a_call(self):
        self.assertFalse(self.refused(['do', 'go:1:2'], 'echo "./wf" ; ./wf do go:1:2'))


class LocalImportsInScope(unittest.TestCase):
    """wf.py imports many modules inside functions; a function that uses one without importing it fails only live
    (replant-wilted-3: `click:` used math.dist → NameError before the click)."""

    def test_every_used_module_is_imported_in_scope(self):
        import ast
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wf.py')
        tree = ast.parse(open(path).read())

        def names(node):
            return {a.asname or a.name.split('.')[0] for x in ast.walk(node) if isinstance(x, ast.Import)
                    for a in x.names}
        top = {a.asname or a.name.split('.')[0] for x in tree.body if isinstance(x, ast.Import) for a in x.names}
        local_mods = names(tree) - top
        bad = []

        def walk(node, have):
            for n in ast.iter_child_nodes(node):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    h = have | names(n)
                    assigned = {x.id for x in ast.walk(n) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
                    used = {x.id for x in ast.walk(n) if isinstance(x, ast.Name)} & local_mods - assigned
                    bad.extend(f'{n.name}:{n.lineno} uses {m}' for m in used - h)
                    walk(n, h)
                else:
                    walk(n, have)
        walk(tree, top)
        self.assertEqual(bad, [])


class BubbleLabels(unittest.TestCase):
    """A dialog confirmation is not a bubble interaction (10-30: Remove → `> unplant_impl` labelled the bed's new plant
    bubble as `unplant_impl`; replant-wilted-3 then saw no plant bubble and walked away)."""

    def test_remove_confirmation_labels_no_bubble(self):
        import wf
        self.assertIsNone(wf.event_kind(['[D183 12:24:32 PM] > unplant_impl me=Player target=GardenBed(Clone) at (3.34, 0.10, -29.09)']))
        self.assertEqual(wf.event_kind(['[D183 12:24:32 PM] > unplant me=Player target=GardenBed(Clone) at (3.34, 0.10, -29.09)']), 'unplant')


if __name__ == '__main__':
    unittest.main()
