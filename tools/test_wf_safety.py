"""Safety tests for tools/wf.py input (S13: clicks landed on the pause/Settings menu and changed the user's audio).
Run: .venv/bin/python tools/test_wf_safety.py"""
import os
import sys
import tempfile
import unittest
import contextlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv = ['x']
import wf  # noqa: E402


class ImportedCliIsolation(unittest.TestCase):
    def test_calling_imported_main_does_not_enable_real_eval_writes(self):
        from evals import store
        store.ENABLED = True
        self.addCleanup(setattr, store, 'ENABLED', False)
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(__import__('io').StringIO()):
            wf.main(['--help'])
        self.assertFalse(store.ENABLED)


class NoClickThroughMenus(unittest.TestCase):
    def setUp(self):
        self.clicks = []
        self._orig = (wf.state, wf.click, wf.key, wf.find_text, wf.time.sleep)
        wf.click = lambda x, y, *a, **k: self.clicks.append((x, y))

    def tearDown(self):
        wf.state, wf.click, wf.key, wf.find_text, wf.time.sleep = self._orig

    def test_resume_reports_a_failed_named_click_without_issuing_a_second_input(self):
        paused = [True]
        keys = []
        wf.state = lambda save=False: ({'mode': 'overlay', 'text': ['0) Game Paused', '1) Resume Game']}
                                       if paused[0] else {'mode': 'gameplay', 'text': []})
        wf.find_text = lambda *a, **k: [{'cx': 960, 'cy': 700}]
        wf.key = keys.append
        wf.time.sleep = lambda _: None
        self.assertTrue(wf.set_paused(False).startswith('could not resume:'))
        self.assertTrue(paused[0])
        self.assertEqual(self.clicks, [(960, 700)])
        self.assertEqual(keys, [])

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


class GotoByLook(unittest.TestCase):
    def test_a_place_whose_object_is_seen_next_to_her_is_arrived(self):
        """Live D187: goto said SHORT 10 units off, the frame showed her at the well (its old estimate was stale)."""
        Det = __import__('collections').namedtuple('Det', 'kind point')
        saved = (wf._goto, wf._seen_near)
        wf._goto = lambda place, max_hops=30: 'SHORT of well: 10.44 units off'
        wf._seen_near = lambda kind: Det('Well', (730, 390)) if kind == 'Well' else None
        try:
            self.assertTrue(wf.goto('well').startswith('ARRIVED well (seen'), wf.goto('well'))
            wf._seen_near = lambda kind: None
            self.assertTrue(wf.goto('well').startswith('SHORT'))
        finally:
            wf._goto, wf._seen_near = saved


class MapSnapshot(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.map_frame = Image.new('RGB', (1920, 1080), 'red')
        self.game_frame = Image.new('RGB', (1920, 1080), 'green')
        self.map_open, self.toggle_closes, self.keys = False, True, []
        for name, value in (
                ('key', self.key), ('grab', lambda: self.map_frame if self.map_open else self.game_frame),
                ('map_pin', lambda img: (900, 500) if img is self.map_frame else None),
                ('MAP_LAST', os.path.join(self.tmp.name, 'map.png')),
                ('ASK_FRAME', os.path.join(self.tmp.name, 'vision.png')),
                ('ASK_CTX', os.path.join(self.tmp.name, 'vision.json')),
                ('run_log', lambda *a, **kw: None)):
            patch = mock.patch.object(wf, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(wf.time, 'sleep', lambda _: None)
        patch.start()
        self.addCleanup(patch.stop)

    def key(self, name):
        self.keys.append(name)
        if name == 'm' and (not self.map_open or self.toggle_closes):
            self.map_open = not self.map_open
        # Escape deliberately fails, as in the live failure.

    def test_escape_failure_uses_map_toggle_before_returning_to_vision(self):
        from PIL import Image
        self.assertIs(wf.map_snapshot(), self.map_frame)
        self.assertEqual(self.keys, ['m', 'escape', 'm'])
        self.assertFalse(self.map_open)
        with Image.open(wf.MAP_LAST) as saved:
            self.assertEqual(saved.getpixel((0, 0)), (255, 0, 0))
        wf.ask_vision('game', 'Which bed should be clicked?', wf.grab())
        with Image.open(wf.ASK_FRAME) as vision:
            self.assertEqual(vision.getpixel((0, 0)), (0, 128, 0))

    def test_unclosable_map_aborts_before_any_target_decision_and_keeps_capture(self):
        from PIL import Image
        self.toggle_closes = False
        decisions = []
        with self.assertRaisesRegex(SystemExit, 'map.*clos|MAP.*OPEN'):
            wf.map_snapshot()
            decisions.append('world target decision')
        self.assertEqual(decisions, [])
        self.assertEqual(self.keys, ['m', 'escape', 'm'])
        with Image.open(wf.MAP_LAST) as saved:
            self.assertEqual(saved.getpixel((0, 0)), (255, 0, 0))


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


class FullScaleVision(unittest.TestCase):
    """User D188: "Scale was a major cause - let's always screenshot full scale" (the map was ~280 px wide)."""

    def test_every_vision_question_gets_its_image_at_full_size(self):
        import re
        import tempfile
        from unittest import mock
        from PIL import Image
        d = tempfile.mkdtemp()
        with mock.patch.object(wf, 'ASK_IMG', os.path.join(d, 'ask.jpg')), \
                mock.patch.object(wf, 'ASK_FRAME', os.path.join(d, 'ask_frame.png')), \
                mock.patch.object(wf, 'ASK_CTX', os.path.join(d, 'ask.json')), \
                mock.patch.object(wf, 'run_log', lambda *a, **k: None):
            for size in ((1920, 1080), (1920, 2160)):
                msg = wf.ask_vision('game', 'Which way?', Image.new('RGB', size, (10, 20, 30)), answer='N..NW')
                path = re.search(r'look: (\S+)', msg).group(1)
                self.assertEqual(Image.open(path).size, size, msg)
                self.assertNotIn('wf teach', msg)


if __name__ == '__main__':
    unittest.main()
