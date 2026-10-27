#!/usr/bin/env python3
"""wf — observe and control Wylde Flowers (macOS / Apple Arcade build) from the command line.

Run with the project venv:  .venv/bin/python tools/wf.py <command> [args]
(or the wrapper:            ./wf <command> [args])

All coordinates are GAME POINTS in a virtual 1920x1080 frame: (0,0) = top-left of the game picture, whatever the
real window size (full screen, or windowed e.g. 1600x900 + title bar). Screenshots are scaled to that frame, so pixel
coords in the image == click coords.

Requires macOS permissions for the host terminal (System Settings > Privacy & Security):
  * Screen & System Audio Recording  (screenshots / OCR)
  * Accessibility                    (keyboard / mouse injection)
"""
import argparse
import re
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT_DIR = os.environ.get('WF_SHOT_DIR', os.path.join(ROOT, '.shots'))
APP_NAME = 'Wylde Flowers'
# The game UI language on this machine is Russian; OCR both. Override: WF_OCR_LANGS=en-US
OCR_LANGS = os.environ.get('WF_OCR_LANGS', 'en-US,ru-RU').split(',')  # game UI is English since D4 (L48)
BUNDLE_ID = 'com.studiodrydock.mayflower'

# macOS virtual key codes (ANSI layout)
KEYCODES = {
    'a': 0, 's': 1, 'd': 2, 'f': 3, 'h': 4, 'g': 5, 'z': 6, 'x': 7, 'c': 8, 'v': 9, 'b': 11, 'q': 12,
    'w': 13, 'e': 14, 'r': 15, 'y': 16, 't': 17, '1': 18, '2': 19, '3': 20, '4': 21, '6': 22, '5': 23,
    '=': 24, '9': 25, '7': 26, '-': 27, '8': 28, '0': 29, ']': 30, 'o': 31, 'u': 32, '[': 33, 'i': 34,
    'p': 35, 'return': 36, 'enter': 36, 'l': 37, 'j': 38, "'": 39, 'k': 40, ';': 41, '\\': 42, ',': 43,
    '/': 44, 'n': 45, 'm': 46, '.': 47, 'tab': 48, 'space': 49, '`': 50, 'delete': 51, 'backspace': 51,
    'escape': 53, 'esc': 53, 'shift': 56, 'capslock': 57, 'option': 58, 'alt': 58, 'control': 59,
    'ctrl': 59, 'cmd': 55, 'command': 55, 'left': 123, 'right': 124, 'down': 125, 'up': 126,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96, 'f6': 97, 'f7': 98, 'f8': 100,
    'f9': 101, 'f10': 109, 'f11': 103, 'f12': 111, 'home': 115, 'end': 119, 'pageup': 116, 'pagedown': 121,
}
MODIFIER_FLAGS = {'shift': 1 << 17, 'ctrl': 1 << 18, 'control': 1 << 18, 'alt': 1 << 19, 'option': 1 << 19,
                  'cmd': 1 << 20, 'command': 1 << 20}

# Movement keys (verified in-game; see docs/controls-and-ui.md)
DIRS = {'up': ['w'], 'down': ['s'], 'left': ['a'], 'right': ['d'],
        'n': ['w'], 's': ['s'], 'w': ['a'], 'e': ['d'],
        'ne': ['w', 'd'], 'nw': ['w', 'a'], 'se': ['s', 'd'], 'sw': ['s', 'a']}


def _quartz():
    import Quartz  # noqa: deferred so `wiki` works without pyobjc
    return Quartz


# ---------------------------------------------------------------- window / permissions

def game_windows():
    """All full-size layer-0 windows of the game, largest first (the app owns several)."""
    Q = _quartz()
    wins = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionAll, Q.kCGNullWindowID)
    out = []
    for w in wins:
        if w.get('kCGWindowOwnerName') != APP_NAME or w.get('kCGWindowLayer', 0) != 0:
            continue
        if w.get('kCGWindowAlpha', 1) == 0:
            continue
        b = w['kCGWindowBounds']
        out.append({'id': int(w['kCGWindowNumber']), 'x': int(b['X']), 'y': int(b['Y']),
                    'w': int(b['Width']), 'h': int(b['Height']), 'pid': int(w['kCGWindowOwnerPID'])})
    out.sort(key=lambda d: (-d['w'] * d['h'], d['id']))
    return out


_WIN_CACHE = os.path.join(SHOT_DIR, '.window_id')


def game_window():
    """Return dict(id, x, y, w, h, pid) of the game window that actually renders content.

    The game owns two full-screen windows; one is always black. The rendering one is found by
    capturing candidates and is cached in .shots/.window_id.
    """
    wins = game_windows()
    if not wins:
        return None
    big = [w for w in wins if w['w'] * w['h'] == wins[0]['w'] * wins[0]['h']]
    try:
        cached = int(open(_WIN_CACHE).read())
        for w in big:
            if w['id'] == cached:
                return w
    except (OSError, ValueError):
        pass
    if len(big) == 1:
        return big[0]
    from PIL import Image
    os.makedirs(SHOT_DIR, exist_ok=True)
    for w in big:
        tmp = os.path.join(SHOT_DIR, '.probe.png')
        if _capture_window_quartz(w['id'], tmp) and Image.open(tmp).convert('L').getextrema()[1] > 20:
            open(_WIN_CACHE, 'w').write(str(w['id']))
            os.remove(tmp)
            return w
    return big[0]


FRAME_W, FRAME_H = 1920, 1080  # every wf coordinate is in this virtual frame, whatever the window size


def content_box(w):
    """(x0, y0, scale) of the 16:9 game picture inside window `w`, in window points: windowed mode adds a title bar
    on top (e.g. 1600x928 window = 28 pt bar + 1600x900 picture). game point (gx, gy) -> window (x0 + gx*scale, ...)."""
    scale = min(w['w'] / FRAME_W, w['h'] / FRAME_H)
    cw, ch = FRAME_W * scale, FRAME_H * scale
    return (w['w'] - cw) / 2, w['h'] - ch, scale


def permissions():
    Q = _quartz()
    import ApplicationServices as AS
    return {'screen_recording': bool(Q.CGPreflightScreenCaptureAccess()),
            'accessibility': bool(AS.AXIsProcessTrusted())}


def require_window():
    w = game_window()
    if not w:
        sys.exit('ERROR: Wylde Flowers is not running (launch it: open -a "Wylde Flowers")')
    return w


def focus():
    """Bring the game to the front (switches to its full-screen Space if needed).

    NSRunningApplication.activate is ignored for background callers on recent macOS,
    so go through LaunchServices (`open -a`), which is always honoured.
    """
    subprocess.run(['open', '-b', BUNDLE_ID], check=False)
    for _ in range(100):
        time.sleep(0.03)
        if is_frontmost():
            time.sleep(SPACE_SETTLE())  # let a full-screen Space transition finish
            return True
    return False


def SPACE_SETTLE():
    """Extra wait after a focus change: the full-screen Space slide needs ~0.4 s, a window needs almost none."""
    w = game_window()
    return 0.4 if w and content_box(w) == (0, 0, 1) else 0.05


def is_frontmost():
    from AppKit import NSWorkspace
    from Foundation import NSDate, NSRunLoop
    # frontmostApplication only refreshes when the run loop runs; without this a long-lived process (the daemon)
    # never saw the switch and focus() always waited out its timeout (~3 s per call, L45)
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.005))
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    return app is not None and app.bundleIdentifier() == BUNDLE_ID


_PREV_APP = None   # bundle id of the app that was in front before we focused the game


def ensure_front():
    """Focus the game, remembering which app to give focus back to."""
    global _PREV_APP
    if not is_frontmost():
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        _PREV_APP = app.bundleIdentifier() if app is not None else None
        focus()


FRONT_FLAG = os.path.join(SHOT_DIR, 'keep_front')


def keep_front():
    """True when the game should stay in front between calls (`./wf focus-mode front`, user's choice)."""
    return os.environ.get('WF_KEEP_FRONT') == '1' or os.path.exists(FRONT_FLAG)


def release_focus():
    """Give focus back to the previous app. The game (Unity) pauses when unfocused: game time stops and
    screen checks get ~10x faster. Disabled by `./wf focus-mode front` (or WF_KEEP_FRONT=1)."""
    global _PREV_APP
    if keep_front() or not _PREV_APP or _PREV_APP == BUNDLE_ID:
        return False
    subprocess.run(['open', '-b', _PREV_APP], check=False)
    _PREV_APP = None
    for _ in range(20):
        time.sleep(0.1)
        if not is_frontmost():
            break
    return True


# ---------------------------------------------------------------- screenshots

def _capture_window_quartz(window_id, out_png):
    """In-process window capture (works for full-screen windows on another Space)."""
    Q = _quartz()
    try:
        img = Q.CGWindowListCreateImage(Q.CGRectNull, Q.kCGWindowListOptionIncludingWindow, window_id,
                                        Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageNominalResolution)
    except Exception:
        return False
    if img is None:
        return False
    from Foundation import NSURL
    url = NSURL.fileURLWithPath_(out_png)
    dest = Q.CGImageDestinationCreateWithURL(url, 'public.png', 1, None)
    Q.CGImageDestinationAddImage(dest, img, None)
    return bool(Q.CGImageDestinationFinalize(dest))


def screen_locked():
    Q = _quartz()
    d = Q.CGSessionCopyCurrentDictionary() or {}
    return bool(d.get('CGSSessionScreenIsLocked', False))


def grab():
    """Fast in-memory capture of the game window as a PIL RGB image at window-point size (~50 ms)."""
    from PIL import Image
    Q = _quartz()
    if screen_locked():
        sys.exit('ERROR: the Mac screen is LOCKED; captures are black and input is blocked. Ask the user to unlock.')
    w = require_window()
    cg = Q.CGWindowListCreateImage(Q.CGRectNull, Q.kCGWindowListOptionIncludingWindow, w['id'],
                                   Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageNominalResolution)
    if cg is None:
        sys.exit('ERROR: capture failed (Screen Recording permission? sandbox?)')
    cw, ch = Q.CGImageGetWidth(cg), Q.CGImageGetHeight(cg)
    bpr = Q.CGImageGetBytesPerRow(cg)
    data = Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(cg))
    img = Image.frombuffer('RGBA', (cw, ch), bytes(data), 'raw', 'BGRA', bpr, 1).convert('RGB')
    if img.size != (w['w'], w['h']):
        img = img.resize((w['w'], w['h']), Image.BILINEAR)
    return _to_frame(img, w)


def _to_frame(img, w):
    """Crop the title bar and scale to the 1920x1080 virtual frame (no-op in 1080p full screen)."""
    from PIL import Image
    x0, y0, sc = content_box(w)
    if (x0, y0, sc) != (0, 0, 1):
        img = img.crop((round(x0), round(y0), round(x0 + FRAME_W * sc), round(y0 + FRAME_H * sc)))
        img = img.resize((FRAME_W, FRAME_H), Image.BILINEAR)
    return img


def screenshot(path=None, region=None):
    """Capture the game window to an image file at window-point resolution. Returns path.

    region = (x, y, w, h) in game points crops the result. Fast path: in-memory grab + low-compression PNG.
    """
    os.makedirs(SHOT_DIR, exist_ok=True)
    path = path or os.path.join(SHOT_DIR, time.strftime('shot-%H%M%S.png'))
    try:
        img = grab()
    except Exception:
        img = None
    if img is None:
        from PIL import Image
        w = require_window()
        raw = path + '.raw.png'
        if not _capture_window_quartz(w['id'], raw):
            r = subprocess.run(['screencapture', '-x', '-o', '-l', str(w['id']), raw], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(raw):
                sys.exit('ERROR: capture failed (Screen Recording permission?): ' + (r.stderr or r.stdout).strip())
        img = _to_frame(Image.open(raw).convert('RGB').resize((w['w'], w['h'])), w)
        os.remove(raw)
    if region:
        x, y, rw, rh = region
        img = img.crop((x, y, x + rw, y + rh))
    if path.lower().endswith(('.jpg', '.jpeg')):
        img.save(path, quality=85)
    else:
        img.save(path, compress_level=1)
    return path


# ---------------------------------------------------------------- OCR (Apple Vision)

OCR_SCALE = float(os.environ.get('WF_OCR_SCALE', '0.5'))


def ocr(path, region_offset=(0, 0), min_conf=0.3, fast=False, scale=None):
    """Return [{'text','conf','x','y','w','h','cx','cy'}] in image (== game) coords.

    OCR runs on a copy downscaled by `scale` (default 0.5): ~3.5x faster and, for this game's large UI font,
    more accurate. Vision's fast mode is useless here (no Russian).
    """
    import Vision
    from Foundation import NSURL
    from PIL import Image
    im = Image.open(path)
    W, H = im.size
    scale = OCR_SCALE if scale is None else scale
    src = path
    if scale != 1 and W * scale >= 200:
        src = path + '.ocr.png'
        im.convert('RGB').resize((int(W * scale), int(H * scale)), Image.BILINEAR).save(src, compress_level=1)
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(src), None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1 if fast else 0)  # 0 = accurate
    req.setUsesLanguageCorrection_(False)
    req.setRecognitionLanguages_(OCR_LANGS)
    ok, err = handler.performRequests_error_([req], None)
    if src != path:
        os.remove(src)
    if not ok:
        raise RuntimeError(str(err))
    out = []
    ox, oy = region_offset
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        c = cand[0]
        if c.confidence() < min_conf:
            continue
        bb = obs.boundingBox()  # normalized, origin bottom-left
        x = bb.origin.x * W
        y = (1 - bb.origin.y - bb.size.height) * H
        w, h = bb.size.width * W, bb.size.height * H
        out.append({'text': c.string(), 'conf': round(float(c.confidence()), 2),
                    'x': int(x + ox), 'y': int(y + oy), 'w': int(w), 'h': int(h),
                    'cx': int(x + w / 2 + ox), 'cy': int(y + h / 2 + oy)})
    out.sort(key=lambda r: (r['y'] // 12, r['x']))
    return out


def ocr_image(img, scale=None, offset=(0, 0)):
    """OCR a PIL image in memory: writes only a downscaled temp file. Coords returned in full-image space."""
    scale = OCR_SCALE if scale is None else scale
    os.makedirs(SHOT_DIR, exist_ok=True)
    tmp = os.path.join(SHOT_DIR, '.ocr_mem.png')
    small = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    small.save(tmp, compress_level=1)
    res = ocr(tmp, scale=1)
    k = 1 / scale
    ox, oy = offset
    for r in res:
        for f in ('x', 'cx', 'w'):
            r[f] = int(r[f] * k) + (ox if f != 'w' else 0)
        for f in ('y', 'cy', 'h'):
            r[f] = int(r[f] * k) + (oy if f != 'h' else 0)
    return res


def find_text(needle, path=None, region=None, exact=False):
    if path:
        lines = ocr(path, (region[0], region[1]) if region else (0, 0))
    else:
        img = grab()
        off = (0, 0)
        if region:
            x, y, w, h = region
            img = img.crop((x, y, x + w, y + h))
            off = (x, y)
        lines = ocr_image(img, scale=1 if region else None, offset=off)
    n = needle.lower()
    hits = [r for r in lines if (r['text'].lower().strip() == n if exact else n in r['text'].lower())]
    return hits


# ---------------------------------------------------------------- input

def _to_screen(x, y):
    w = require_window()
    x0, y0, sc = content_box(w)
    return w['x'] + x0 + x * sc, w['y'] + y0 + y * sc


def _post_key(code, down, flags=0):
    Q = _quartz()
    ev = Q.CGEventCreateKeyboardEvent(None, code, down)
    if flags:
        Q.CGEventSetFlags(ev, flags)
    Q.CGEventPost(Q.kCGHIDEventTap, ev)


def _code(k):
    k = k.lower()
    if k not in KEYCODES:
        sys.exit(f'ERROR: unknown key {k!r}. Known: {", ".join(sorted(KEYCODES))}')
    return KEYCODES[k]


def key(combo, hold=0.2):
    """Press a key or modifier combo like 'e', 'escape', 'shift+tab', 'cmd+q'."""
    parts = combo.lower().split('+')
    mods, main = parts[:-1], parts[-1]
    flags = 0
    for m in mods:
        flags |= MODIFIER_FLAGS[m]
        _post_key(_code(m), True, flags)
    _post_key(_code(main), True, flags)
    time.sleep(hold)
    _post_key(_code(main), False, flags)
    for m in reversed(mods):
        _post_key(_code(m), False, 0)
    time.sleep(0.05)


def hold_keys(keys, seconds):
    """Hold several keys simultaneously (e.g. ['w','d'] to walk diagonally)."""
    codes = [_code(k) for k in keys]
    for c in codes:
        _post_key(c, True)
    end = time.time() + seconds
    # re-post key-down periodically; some engines miss a single long press
    while time.time() < end:
        time.sleep(min(0.25, max(0, end - time.time())))
    for c in codes:
        _post_key(c, False)
    time.sleep(0.05)


def mouse_move(x, y):
    Q = _quartz()
    sx, sy = _to_screen(x, y)
    ev = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (sx, sy), Q.kCGMouseButtonLeft)
    Q.CGEventPost(Q.kCGHIDEventTap, ev)


def click(x, y, button='left', count=1, hold=0.06):
    Q = _quartz()
    sx, sy = _to_screen(x, y)
    if button == 'right':
        down, up, btn = Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp, Q.kCGMouseButtonRight
    else:
        down, up, btn = Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp, Q.kCGMouseButtonLeft
    mouse_move(x, y)
    time.sleep(0.05)
    for i in range(count):
        e1 = Q.CGEventCreateMouseEvent(None, down, (sx, sy), btn)
        Q.CGEventSetIntegerValueField(e1, Q.kCGMouseEventClickState, i + 1)
        Q.CGEventPost(Q.kCGHIDEventTap, e1)
        time.sleep(hold)
        e2 = Q.CGEventCreateMouseEvent(None, up, (sx, sy), btn)
        Q.CGEventSetIntegerValueField(e2, Q.kCGMouseEventClickState, i + 1)
        Q.CGEventPost(Q.kCGHIDEventTap, e2)
        time.sleep(0.08)


def scroll(dy, x=None, y=None):
    Q = _quartz()
    if x is not None:
        mouse_move(x, y)
    ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitLine, 1, int(dy))
    Q.CGEventPost(Q.kCGHIDEventTap, ev)


def type_text(text):
    Q = _quartz()
    for ch in text:
        ev = Q.CGEventCreateKeyboardEvent(None, 0, True)
        Q.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)
        ev2 = Q.CGEventCreateKeyboardEvent(None, 0, False)
        Q.CGEventKeyboardSetUnicodeString(ev2, len(ch), ch)
        Q.CGEventPost(Q.kCGHIDEventTap, ev2)
        time.sleep(0.03)


# ---------------------------------------------------------------- HUD

# HUD regions in game points for a 1920x1080 window (scaled for other sizes). Calibrated in-game;
# see docs/controls-and-ui.md. Each region is OCR'd independently.
HUD_REGIONS_1080 = {
    'clock': (1500, 0, 420, 200),      # top-right: day / date / time / weather
    'money': (1500, 150, 420, 140),    # coins under the clock
    'top_left': (0, 0, 520, 220),      # quest tracker / notifications
    'bottom': (300, 820, 1320, 260),   # dialogue / prompts
}


def hud(path=None):
    sx = sy = 1  # screenshots are always in the 1920x1080 frame
    path = path or screenshot()
    from PIL import Image
    img = Image.open(path)
    res = {'screenshot': path}
    for name, (x, y, rw, rh) in HUD_REGIONS_1080.items():
        box = (int(x * sx), int(y * sy), int((x + rw) * sx), int((y + rh) * sy))
        crop = path + f'.{name}.png'
        img.crop(box).save(crop)
        res[name] = ' | '.join(r['text'] for r in ocr(crop, (box[0], box[1])))
        os.remove(crop)
    return res


# ---------------------------------------------------------------- cheap state / low-res looks

TEMPLATES = os.path.join(ROOT, 'tools', 'templates')
# Fixed-position HUD templates (1920x1080 frame). ANY match => gameplay. The HUD changes during the tutorial:
#   hud_pause    - pause button top-left (game start, before the clock appears)
#   hud_journal3 - journal button when map/journal/inventory are shown (after farm arrival)
HUD_TEMPLATES = {'hud_pause': (50, 50, 120, 120), 'hud_journal3': (1605, 55, 110, 110)}
MONEY_REGION = (1700, 130, 200, 70)
MONEY_BOX = (1700, 130, 1900, 200)      # same, as a PIL crop box
CLOCK_REGION = (150, 25, 350, 90)      # day name + time next to the analog clock (top-left, after clock appears)
POPUP_WORDS = ('Confirm', 'Hooray', 'Quest Complete', 'Quest complete',  # EN UI (L48; exact EN wording unverified)
               'одтвердить',          # RU "Подтвердить" Confirm (OCR sometimes reads П as Л)
               'Ура!',                # RU completion popup button "Hooray!"
               'Задание выполнено')   # RU "Quest complete" header
SUBTITLE_Y = 940                        # dialogue subtitles ("Name: text") are OCR'd below this y


def _match(img, name, thresh=18.0):
    """Mean abs pixel difference of a fixed-position template (lower = better). Returns (ok, score)."""
    from PIL import Image, ImageChops, ImageStat
    p = os.path.join(TEMPLATES, name + '.png')
    if not os.path.exists(p):
        return False, None
    x, y, w, h = HUD_TEMPLATES[name]
    tpl = Image.open(p).convert('L')
    crop = img.crop((x, y, x + w, y + h)).convert('L')
    score = sum(ImageStat.Stat(ImageChops.difference(tpl, crop)).mean)
    return score < thresh, round(score, 1)


def _in(r, region):
    x, y, w, h = region
    return x <= r['cx'] <= x + w and y <= r['cy'] <= y + h


def _meaningful(r):
    """Drop OCR noise from scenery (e.g. '11 12 >', '* vŽni'): keep confident text with a real word or an n/m counter."""
    t = r['text']
    if re.search(r'\d+\s*/\s*\d+', t):
        return True
    words = re.findall(r'[A-Za-zА-Яа-яЁё]{3,}', t)
    return bool(words) and r.get('conf', 1) >= 0.5


def classify(path_or_img, with_bubble=True, full_text=False):
    """Classify a frame without looking at it.

    mode: cutscene  - black letterbox bars, no HUD (Space advances)
          gameplay  - HUD visible, Tara controllable
          dialogue  - subtitle line at the bottom ("Name: text"); Space advances
          popup     - quest popup with a confirm button (Подтвердить); Space confirms
          overlay   - anything else: journal/map/menu/shop/inventory (read `text`)
    """
    from PIL import Image, ImageStat
    if isinstance(path_or_img, str):
        path, img = path_or_img, Image.open(path_or_img).convert('RGB')
    else:
        path, img = None, path_or_img
    W, H = img.size
    top = ImageStat.Stat(img.crop((0, 0, W, int(H * 0.09))).convert('L')).mean[0]
    bot = ImageStat.Stat(img.crop((0, int(H * 0.9), W, H)).convert('L')).mean[0]
    letterbox = top < 6 and bot < 6
    scores = {n: _match(img, n) for n in HUD_TEMPLATES}
    hud_ok = any(ok for ok, _ in scores.values())
    if hud_ok and not letterbox and not full_text and os.environ.get('WF_FAST_OCR') == '1':
        # optional gameplay fast path (misses quest-tracker popups, e.g. "Древесина: 5/6"; learnings L34).
        # Default is full OCR: observation runs with the game in the background (paused), where it's cheap.
        cx, cy, cw, ch = CLOCK_REGION
        lines = ocr_image(img.crop((cx, cy, cx + cw, cy + ch)), scale=1, offset=(cx, cy))
        lines += [r for r in ocr_image(img.crop((0, SUBTITLE_Y, W, H)), scale=0.5, offset=(0, SUBTITLE_Y))]
        lines += [r for r in ocr_image(img.crop(MONEY_BOX), scale=1, offset=MONEY_BOX[:2])]
    else:
        lines = [r for r in ocr_image(img) if not _in(r, CLOCK_REGION)]
        if hud_ok:  # the small clock text needs full resolution
            cx, cy, cw, ch = CLOCK_REGION
            lines += ocr_image(img.crop((cx, cy, cx + cw, cy + ch)), scale=1, offset=(cx, cy))
    money = [r['text'] for r in lines if _in(r, MONEY_REGION) and re.fullmatch(r'\d{1,6}', r['text'].strip())]
    clock = [r['text'] for r in lines if _in(r, CLOCK_REGION)]
    subs = [r['text'] for r in lines if r['cy'] >= SUBTITLE_Y and r['text'] not in money]
    text = [r for r in lines if r['text'] not in money and r['text'] not in clock and _meaningful(r)]
    joined = ' '.join(r['text'] for r in text)
    if letterbox:
        mode = 'cutscene'
    elif subs and ':' in ' '.join(subs):
        mode = 'dialogue'
    elif any(w in joined for w in POPUP_WORDS):  # confirm-type popup buttons / headers
        mode = 'popup'
    elif hud_ok:
        mode = 'gameplay'
    else:
        mode = 'overlay'
    res = {'mode': mode, 'money': int(money[0]) if money else None,
           'clock': ' '.join(clock) or None,
           'tracker': [r['text'] for r in text if re.search(r'\d+\s*/\s*\d+', r['text'])] or None,
           'text': [f"({r['cx']},{r['cy']}) {r['text']}" for r in text],
           'hud_scores': {n: s for n, (_, s) in scores.items()}, 'screenshot': path}
    if hud_ok:
        res['energy'] = read_energy(img)
    if with_bubble and mode == 'gameplay':
        res['bubble'] = find_bubble(img)
    return res


def state(save=False):
    """Cheap state from an in-memory frame. save=True also writes .shots/state.jpg (half-res) for reference."""
    img = grab()
    s = classify(img)
    if save:
        p = os.path.join(SHOT_DIR, 'state.jpg')
        img.resize((img.width // 2, img.height // 2)).save(p, quality=70)
        s['screenshot'] = p
    return s


def brief(s):
    """One compact line for humans/LLMs."""
    parts = [s['mode']]
    if s.get('clock'):
        parts.append(s['clock'])
    if s.get('money') is not None:
        parts.append(f"{s['money']}c")
    if s.get('energy') is not None:
        parts.append(f"⚡{s['energy']}%")
    if s.get('bubble'):
        parts.append(f"bubble@{s['bubble'][0]},{s['bubble'][1]}")
    if s.get('tracker'):
        parts.append('tracker: ' + '; '.join(s['tracker']))
    txt = ' / '.join(t.split(') ', 1)[1] for t in s['text'])
    return ' | '.join(parts) + (f' | {txt}' if txt else '')


# ---------------------------------------------------------------- meters (concepts readable from the HUD)

ENERGY_RING = {'center': (116, 116), 'radius': 96, 'start_deg': 82, 'end_deg': 205}  # clockwise from 12 o'clock


def read_energy(img):
    """Energy as 0-100 from the orange arc next to the clock (⚡ marks its start). None if the ring isn't visible.
    Orange = filled; pale brown track = empty. See docs/mechanics/energy.md."""
    import math
    cx, cy = ENERGY_RING['center']
    r = ENERGY_RING['radius']
    filled = empty = 0
    a = ENERGY_RING['start_deg']
    while a <= ENERGY_RING['end_deg']:
        x = int(cx + r * math.sin(math.radians(a)))
        y = int(cy - r * math.cos(math.radians(a)))
        R, G, B = img.getpixel((x, y))[:3]
        if R >= 225 and 150 <= G <= 195 and B <= 115:
            filled += 1
        elif 180 <= R <= 215 and 145 <= G <= 175 and 115 <= B <= 150:
            empty += 1
        a += 2.5
    total = filled + empty
    return round(100 * filled / total) if total >= 20 else None


# ---------------------------------------------------------------- prompt bubble detection

def find_bubble(img):
    """Find the interaction prompt bubble (round cream badge ~120px) outside the HUD bands. Returns (cx, cy) or None."""
    import numpy as np
    W, H = img.size
    f = 4
    a = np.asarray(img.resize((W // f, H // f)), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = (r >= 195) & (r <= 235) & (g >= 165) & (g <= 215) & (b >= 135) & (b <= 195) & (r - b >= 25) & (r - b <= 65)
    y0 = 230 // f  # skip HUD band (clock, buttons)
    mask[:y0] = False
    sh, sw = mask.shape
    seen = np.zeros_like(mask)
    best = None
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        stack, n = [(y, x)], 0
        seen[y, x] = True
        x0 = x1 = x
        ya = yb = y
        while stack:
            cy, cx = stack.pop()
            n += 1
            x0, x1, ya, yb = min(x0, cx), max(x1, cx), min(ya, cy), max(yb, cy)
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < sh and 0 <= nx < sw and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        bw, bh = x1 - x0 + 1, yb - ya + 1
        # bubble ≈ 100-140 px wide at full res => 22-38 px at 1/4; roughly round; fairly filled (icon inside)
        if 20 <= bw <= 40 and 20 <= bh <= 40 and 0.75 <= bw / bh <= 1.33 and n >= 0.35 * bw * bh:
            c = (int((x0 + x1) // 2 * f), int((ya + yb) // 2 * f))
            if best is None or n > best[1]:
                best = (c, n)
    return best[0] if best else None


MOVE_DIFF = 3.0  # verified: moving 0.2 s+ = 8-10, blocked = 1.1-1.6 (water animating). Mean grey diff (96x54) between frames before/after a walk; below = the camera didn't move


def _walk_checked(direction, seconds):
    """Walk and report when the screen didn't change (Tara blocked by a rock/fence/water edge). The camera follows
    Tara, so a real move shifts the whole frame; idle animation stays well below MOVE_DIFF."""
    before = _signature()
    hold_keys(DIRS[direction], float(seconds))
    time.sleep(0.15)
    d = _diff(before, _signature())
    if os.environ.get('WF_DEBUG_MOVE'):
        print(f'move diff {direction}:{seconds} = {d:.2f}')
    return f'BLOCKED walk:{direction} (screen unchanged; go around: side-step, then approach from another side)' \
        if d < MOVE_DIFF else None


def walk_until_bubble(direction, max_seconds=4.0, step=0.25, fade=0.35):
    """Walk in short steps until a prompt bubble shows. Returns bubble position or None.

    Bubbles fade in only after Tara stops, so wait `fade` s before each check. Don't keep walking into the
    target: pushing against a bed for seconds opened its panel without pressing Space (learnings).
    """
    t = 0.0
    while True:
        time.sleep(fade)
        b = find_bubble(grab())
        if b or t >= max_seconds:
            return b
        if _walk_checked(direction, step):
            return 'BLOCKED'
        t += step


# ---------------------------------------------------------------- change detection / one-call actions

_FRAMES = None  # when a list, _signature() also keeps full frames (for toast capture in `do`)


def _signature():
    img = grab()
    if _FRAMES is not None and len(_FRAMES) < 12:
        _FRAMES.append(img)
    return img.convert('L').resize((96, 54))


def _diff(a, b):
    from PIL import ImageChops, ImageStat
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def wait_settle(before=None, timeout=3.0, interval=0.1, still=1.5, min_wait=0.25):
    """After an action: wait until the frame stops changing (2 consecutive still polls) or `timeout`.

    Idle animations (grass, NPC idle) give diffs ~0.2-0.5, so `still` tolerates them. `before` is unused but kept
    for callers that want to compare. Returns elapsed seconds.
    """
    t0 = time.time()
    time.sleep(min_wait)
    prev = _signature()
    calm = 0
    while time.time() - t0 < timeout:
        time.sleep(interval)
        cur = _signature()
        calm = calm + 1 if _diff(prev, cur) < still else 0
        if calm >= 2:
            break
        prev = cur
    return round(time.time() - t0, 2)


def go_to(x, y, timeout=15.0, interval=0.15):
    """Click-to-move (L49): left-click a ground point or object; the game pathfinds around fences/objects and Tara
    walks there (clicking an object stops her in front of it, bubble shown, no interaction). Waits until the camera
    stops moving. Returns None on arrival, or a NO MOVE / STILL MOVING message."""
    before = _signature()
    click(int(x), int(y))
    t0 = time.time()
    time.sleep(0.4)  # start-up
    prev, calm = _signature(), 0
    while time.time() - t0 < timeout:
        time.sleep(interval)
        cur = _signature()
        calm = calm + 1 if _diff(prev, cur) < 1.5 else 0
        if calm >= 2:
            break
        prev = cur
    else:
        return f'STILL MOVING after {timeout:.0f}s (long path?): check with look'
    if os.environ.get('WF_DEBUG_MOVE'):
        print(f'go diff = {_diff(before, cur):.2f} in {time.time() - t0:.1f}s')
    if _diff(before, cur) < MOVE_DIFF:
        return f'NO MOVE go:{x}:{y} (not walkable or already there; pick a ground point nearer, or use walk)'
    return None


def run_action(spec):
    """Execute one action spec: go:<x>:<y> (click-to-move, game pathfinds) | key:<k> | walk:<dir>:<s> |
    path:<dir:s,dir:s> | click:<x>:<y> | text:<label> (click-text) | route:<name> |
    bubble:<dir>[:<max_s>] (walk until prompt) | wait:<s>"""
    kind, _, arg = spec.partition(':')
    if kind == 'key':
        key(arg)
    elif kind == 'go':
        x, y = arg.split(':')
        return go_to(int(x), int(y))
    elif kind == 'walk':
        d, s = arg.split(':')
        return _walk_checked(d, float(s))
    elif kind == 'path':
        msgs = [_walk_checked(*st.split(':')) for st in arg.split(',')]
        return ' / '.join(m for m in msgs if m) or None
    elif kind == 'click':
        x, y = arg.split(':')
        click(int(x), int(y))
    elif kind == 'text':
        hits = find_text(arg)
        if not hits:
            return f'NOT FOUND: {arg}'
        click(hits[0]['cx'], hits[0]['cy'])
    elif kind == 'route':
        route(arg)
    elif kind == 'bubble':
        d, _, m = arg.partition(':')
        b = walk_until_bubble(d, float(m or 4))
        if b == 'BLOCKED':
            return f'NO BUBBLE: BLOCKED walking {d} (go around: side-step, then approach from another side)'
        return f'bubble at {b}' if b else 'NO BUBBLE'
    elif kind == 'wait':
        time.sleep(float(arg))
    else:
        return f'UNKNOWN ACTION {spec}'
    return None


def _toasts(frames, final_text):
    """OCR captured frames (game already in background) and return short-lived texts not in the final state."""
    seen = []
    for img in frames[::2]:
        for r in ocr_image(img):
            t = r['text'].strip()
            if _meaningful(r) and t not in final_text and t not in seen and not _in(r, CLOCK_REGION):
                seen.append(t)
    return seen


def do(specs, look_scale=None, crop=None):
    """Run actions, wait for the screen to settle, print a one-line state (+ optional low-res look).
    Short-lived toasts (e.g. "Гриб: 1/2" after a pickup) seen while settling are reported as `saw: …`."""
    global _FRAMES
    before = _signature()
    _FRAMES = []
    for sp in specs:
        msg = run_action(sp)
        if msg:
            print(msg)
    waited = wait_settle(before)
    frames, _FRAMES = _FRAMES, None
    if release_focus():  # game pauses in background => fast, time-frozen observation
        time.sleep(SPACE_SETTLE())  # let the Space transition finish before capturing
    s = state()
    print(brief(s) + f'  [settled {waited}s]')
    final = ' '.join(t.split(') ', 1)[1] for t in s['text'])
    saw = _toasts(frames, final)
    if saw:
        print('saw: ' + ' / '.join(saw))
    print_log()
    if look_scale:
        out, sc, (ox, oy) = look(look_scale, crop)
        print(f'look: {out} (game = {ox}+img/{sc}, {oy}+img/{sc})')
    return s


def look(scale=0.5, crop=None, quality=70):
    """Low-token screenshot for a vision model: JPEG at `scale` (optionally cropped first).

    Prints the path and the factor to convert image coords back to game coords.
    """
    from PIL import Image
    img = grab()
    ox, oy = 0, 0
    if crop:
        x, y, w, h = crop
        img = img.crop((x, y, x + w, y + h))
        ox, oy = x, y
    if scale != 1:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    out = os.path.join(SHOT_DIR, 'look.jpg')
    img.convert('RGB').save(out, quality=quality)
    return out, scale, (ox, oy)


def until(text=None, mode=None, timeout=30.0, interval=1.0):
    """Poll cheap state until OCR contains `text` and/or mode == `mode`. Returns final state or None."""
    end = time.time() + timeout
    while True:
        s = state()
        ok_t = text is None or any(text.lower() in t.lower() for t in s['text'])
        ok_m = mode is None or s['mode'] == mode
        if ok_t and ok_m:
            return s
        if time.time() >= end:
            return None
        time.sleep(interval)


ADVANCE_MODES = ('cutscene', 'dialogue', 'popup')


def advance(max_steps=40):
    """Press Space only while a cutscene, dialogue subtitle or confirm-popup is showing.

    Stops (without pressing) on gameplay, any other overlay (menus, day/clock banners, choices), or when the
    same frame text repeats twice. Prints one line per step. Never clicks choices.
    """
    last = None
    for i in range(max_steps):
        s = state()
        line = brief(s)
        print(f'[{i}] {line}')
        if s['mode'] not in ADVANCE_MODES:
            print(f"STOP: mode={s['mode']}")
            return s
        sig = (s['mode'], tuple(s['text']))
        if sig == last and s['text']:
            print('STOP: frame not changing (choice/button needs a decision?)')
            return s
        last = sig
        before = _signature()
        key('space')
        wait_settle(before, timeout=2.5)
    print('STOP: max steps')
    return state()


ROUTES = os.path.join(ROOT, 'routes')


def route(name):
    """Replay a recorded walking route: routes/<name>.txt (lines of `dir:seconds`, '#' comments)."""
    p = os.path.join(ROUTES, name + '.txt')
    if not os.path.exists(p):
        sys.exit('no route ' + name + '; have: ' + ', '.join(f[:-4] for f in sorted(os.listdir(ROUTES))))
    for line in open(p):
        line = line.split('#')[0].strip()
        for step in line.split():
            if step.startswith('wait:'):
                time.sleep(float(step[5:]))
                continue
            d, s = step.split(':')
            hold_keys(DIRS[d], float(s))


# ---------------------------------------------------------------- wiki lookup

def wiki(query, limit=15, show=False):
    """Search reference/wiki: exact/partial title matches first, then content hits."""
    wdir = os.path.join(ROOT, 'reference', 'wiki')
    files = sorted(os.listdir(wdir))
    q = query.lower()
    titles = [f for f in files if f[:-3].lower() == q] + [f for f in files if q in f.lower() and f[:-3].lower() != q]
    if show and titles:
        print(open(os.path.join(wdir, titles[0])).read())
        return
    print('# title matches')
    for f in titles[:limit]:
        print('  reference/wiki/' + f)
    print('# content matches (file: line)')
    n = 0
    for f in files:
        if f in titles[:limit]:
            continue
        for line in open(os.path.join(wdir, f)):
            if q in line.lower():
                print(f'  {f[:-3]}: {line.strip()[:160]}')
                n += 1
                break
        if n >= limit:
            break


# ---------------------------------------------------------------- tips

def tips(tags, require_all=False):
    """Print rows of docs/tips.md matching tags (any by default)."""
    want = {t.lower().strip(',') for t in tags}
    rows = [l for l in open(os.path.join(ROOT, 'docs', 'tips.md')) if re.match(r'\| T\d+ ', l)]
    n = 0
    for l in rows:
        cells = [c.strip() for c in l.strip().strip('|').split('|')]
        rid, tip, tg, src, links = (cells + [''] * 5)[:5]
        have = {t.strip() for t in tg.split(',')}
        ok = want <= have if require_all else (not want or want & have)
        if ok:
            print(f'{rid} [{src}] {tip}  (tags: {tg}; see {links})')
            n += 1
    if not n:
        print('no tips for', ' '.join(sorted(want)))


# ---------------------------------------------------------------- game files: event log + save (L41)
# Cheaper and more exact than screenshots. Read outside the sandbox (the files are in the game's container).

CONTAINER = os.path.expanduser(f'~/Library/Containers/{BUNDLE_ID}/Data/Library')
GAME_LOG = os.path.join(CONTAINER, 'Logs', 'Studio Drydock', 'Wylde Flowers', 'Player.log')
SAVE_DIR = os.path.join(CONTAINER, 'Application Support', BUNDLE_ID, 'save')
APP_DATA = f'/Applications/{APP_NAME}.app/Contents/Resources/Data'
NAMES_CACHE = os.path.join(SHOT_DIR, 'hashnames.tsv')
LOG_POS = os.path.join(SHOT_DIR, 'gamelog.pos')
LOG_NOISE = re.compile(r'\[(SHELL|CLOUD|SAVE|MSG|DEVICE|VIEW)\]|no applicable performances|\[TRIGGER\] Dequeue|'
                       r'nav mesh|Restoring scene persistence|\] < \w')
_NAMES = None


def _names():
    """CRC32(internal name) -> name. The game stores ids as signed CRC32 of names like 'GrandmaFaveFood'; the
    candidate names are the identifier strings in the app's asset files (cached in .shots, ~20 s to build)."""
    global _NAMES
    if _NAMES is not None:
        return _NAMES
    import zlib
    if not os.path.exists(NAMES_CACHE):
        ident = re.compile(r'^[A-Za-z][A-Za-z0-9_]{2,60}$')
        names = set()
        for dirpath, _, files in os.walk(APP_DATA):
            for f in files:
                p = os.path.join(dirpath, f)
                if f.endswith(('.resS', '.vp', '.sp')) or os.path.getsize(p) > 400e6:
                    continue
                out = subprocess.run(['strings', '-n', '3', p], capture_output=True, text=True, errors='replace').stdout
                names.update(s for s in out.splitlines() if ident.match(s))
        os.makedirs(SHOT_DIR, exist_ok=True)
        with open(NAMES_CACHE, 'w') as fh:
            for n in sorted(names):
                h = zlib.crc32(n.encode())
                fh.write(f'{h - (1 << 32) if h >= 1 << 31 else h}\t{n}\n')
    _NAMES = {}
    with open(NAMES_CACHE) as fh:
        for line in fh:
            h, n = line.rstrip('\n').split('\t')
            _NAMES.setdefault(int(h), n)
    return _NAMES


def _unhash(text):
    """Replace '#-123' ids in log text with names where known."""
    names = _names()
    return re.sub(r'#{1,2}(-?\d{3,})', lambda m: names.get(int(m.group(1)), m.group(0)), text)


def game_log(tail=None, raw=False):
    """New event-log lines since the previous call (quests, dialogue, scene/building changes, loot, purchases).
    tail=N: the last N lines instead (also resets the read position). Returns a list of strings."""
    try:
        st = os.stat(GAME_LOG)
    except OSError as e:
        return [f'(no game log: {e})']
    try:
        ino, pos = json.load(open(LOG_POS))
    except (OSError, ValueError):
        ino, pos = None, None
    if ino is None and tail is None:  # first read ever: show recent context
        tail = 20
    if tail is not None or ino != st.st_ino or pos > st.st_size:  # game restarted => new file
        pos = 0
    with open(GAME_LOG, 'rb') as fh:
        fh.seek(pos)
        data = fh.read()
    end = data.rfind(b'\n') + 1  # keep a half-written last line for next time
    with open(LOG_POS, 'w') as fh:
        json.dump([st.st_ino, pos + end], fh)
    lines = data[:end].decode('utf-8', 'replace').splitlines()
    if not raw:
        lines = [_unhash(l) for l in lines if l.startswith('[D') and not LOG_NOISE.search(l)]
    return lines[-tail:] if tail else lines


def print_log(prefix='log: ', limit=40):
    lines = game_log()
    for l in lines[-limit:]:
        print(prefix + l)
    if len(lines) > limit:
        print(f'{prefix}(+{len(lines) - limit} earlier lines; `wf log --tail N`)')


def latest_save():
    files = [os.path.join(d, f) for d, _, fs in os.walk(SAVE_DIR) for f in fs if f.endswith('.local')]
    return max(files, key=os.path.getmtime) if files else None


def read_save(path=None):
    """Latest save as JSON with hashed ids replaced by names ('#123' when unknown; '##Name' = id reference)."""
    path = path or latest_save()
    raw = open(path, 'rb').read()
    try:
        import zstandard
        data = zstandard.ZstdDecompressor().stream_reader(raw).read()
    except ImportError:
        data = subprocess.run(['zstd', '-dc'], input=raw, capture_output=True, check=True).stdout
    names = _names()

    def dec(o):
        if isinstance(o, dict):
            if len(o) == 1 and '_hash' in o:
                return names.get(o['_hash'], f"#{o['_hash']}") if o['_hash'] else None
            return {k: dec(v) for k, v in o.items()}
        if isinstance(o, list):
            return [dec(v) for v in o]
        if isinstance(o, str) and o.startswith('##') and o[2:].lstrip('-').isdigit():
            return '##' + names.get(int(o[2:]), o[2:])
        return o
    return path, dec(json.loads(data))


def _hhmm(sec):
    return f'{int(sec) // 3600:02d}:{int(sec) % 3600 // 60:02d}'


def save_summary(path=None):
    path, s = read_save(path)
    g = s['gameState']
    t = g['time']
    player = next(c for c in g['characters'] if c['name'] == 'Player')
    pv = {e['name']: e['value'] for e in player['state']['userState']['entries']}
    age = time.time() - os.path.getmtime(path)
    pos = s.get('currentPlayerPosition') or {}
    out = [f"save {os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} ({age / 60:.0f} min ago, "
           f"saveCount {s['saveCount']})",
           f"Y{t['year']} {t['season']} day {t['day']} {_hhmm(t['timeOfDay']['totalSeconds'])} | money {pv.get('money')} "
           f"| stamina {pv.get('stamina')}/{pv.get('maxStaminaUpgrade')} mana {pv.get('mana')}/{pv.get('maxMana')} "
           f"| scene {s.get('currentScene')} at ({pos.get('x', 0):.1f}, {pos.get('y', 0):.1f}, {pos.get('z', 0):.1f})"]
    qs = g['quests']['quests']
    active = [q for q in qs if q['dayQuestStarted'] >= 0 and q['dayQuestCompleted'] < 0 and q['dayQuestFailed'] < 0]
    out.append('quests active: ' + '; '.join(
        f"{q['questNameHash']} goal {q['goalIndex']}" + (f" {q['goalValues']}" if q['goalValues'] else '')
        for q in active))
    done = sorted((q for q in qs if q['dayQuestCompleted'] >= 0), key=lambda q: q['dayQuestCompleted'])
    out.append('quests done: ' + ', '.join(f"{q['questNameHash']}(d{q['dayQuestCompleted']})" for q in done))
    out.append('inventory: ' + ', '.join(f"{i['nameHash']} x{i['count']}" for i in g['player']['inventory']['items']))
    rel = []
    for c in g['characters']:
        e = {x['name']: x['value'] for x in c['state']['userState']['entries']}
        if 'friendship' in e:
            rel.append(f"{c['name']} {e['friendship']}")
    out.append('friendship: ' + (', '.join(rel) or '-'))
    return '\n'.join(out)


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(prog='wf', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status', help='game running? window bounds, permissions, frontmost')
    sub.add_parser('focus', help='bring game to front')
    p = sub.add_parser('focus-mode', help='front = the game stays in front between calls (game time RUNS); '
                                          'background = focus only during input (time frozen between calls)')
    p.add_argument('mode', nargs='?', choices=['front', 'background'])
    p = sub.add_parser('shot', help='screenshot game window; prints path')
    p.add_argument('--out')
    p.add_argument('--region', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'))
    p = sub.add_parser('ocr', help='screenshot (or --image) and OCR; prints text with coords')
    p.add_argument('--image')
    p.add_argument('--region', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'))
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('find', help='find on-screen text; prints matches with center coords')
    p.add_argument('text')
    p.add_argument('--region', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'))
    p.add_argument('--exact', action='store_true')
    p = sub.add_parser('click', help='click at game coords')
    p.add_argument('x', type=int)
    p.add_argument('y', type=int)
    p.add_argument('--right', action='store_true')
    p.add_argument('--double', action='store_true')
    p = sub.add_parser('click-text', help='OCR, find text, click its center')
    p.add_argument('text')
    p.add_argument('--index', type=int, default=0, help='which match (default first)')
    p.add_argument('--region', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'))
    p.add_argument('--exact', action='store_true')
    p = sub.add_parser('move-mouse', help='move cursor to game coords')
    p.add_argument('x', type=int)
    p.add_argument('y', type=int)
    p = sub.add_parser('key', help="press key(s) in order: wf key e  |  wf key escape  |  wf key shift+tab 1 2")
    p.add_argument('keys', nargs='+')
    p.add_argument('--hold', type=float, default=0.2, help='Unity misses presses shorter than ~1 frame; 0.2s is reliable')
    p.add_argument('--gap', type=float, default=0.15, help='pause between keys')
    p = sub.add_parser('hold', help='hold keys together for N seconds: wf hold 1.5 w d')
    p.add_argument('seconds', type=float)
    p.add_argument('keys', nargs='+')
    p = sub.add_parser('walk', help='walk a direction for N seconds: wf walk up 2 (up/down/left/right/ne/nw/se/sw)')
    p.add_argument('direction', choices=sorted(DIRS))
    p.add_argument('seconds', type=float)
    p = sub.add_parser('path', help='walk a sequence: wf path up:1.2 right:3 se:0.5')
    p.add_argument('steps', nargs='+')
    p = sub.add_parser('scroll', help='scroll wheel lines (+up / -down)')
    p.add_argument('dy', type=int)
    p.add_argument('--at', nargs=2, type=int, metavar=('X', 'Y'))
    p = sub.add_parser('type', help='type unicode text')
    p.add_argument('text')
    sub.add_parser('hud', help='OCR HUD regions (clock/day/money/prompts)')
    p = sub.add_parser('state', help='CHEAP: classify screen (gameplay/dialogue/popup/cutscene/overlay) + clock, money, bubble, OCR text')
    p.add_argument('--json', action='store_true', help='full JSON instead of one line')
    p = sub.add_parser('do', help="ONE CALL PER STEP: run actions, wait until the screen settles, print state line "
                                  "(+ --look). Actions: go:x:y (click-to-move, game pathfinds) key:space walk:left:0.5 path:up:1,left:2 click:x:y "
                                  "text:<label> route:<name> bubble:<dir>[:max_s] wait:<s>")
    p.add_argument('actions', nargs='+')
    p.add_argument('--look', type=float, nargs='?', const=0.4, default=None, help='also save a low-res look (scale, default 0.4)')
    p.add_argument('--crop', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'))
    p = sub.add_parser('bubble', help='detect the interaction prompt bubble on the current frame (prints x,y or NONE)')
    p = sub.add_parser('look', help='low-res JPEG for viewing (default scale 0.4 = 768x432); prints path + coord factor')
    p.add_argument('--scale', type=float, default=0.4)
    p.add_argument('--crop', nargs=4, type=int, metavar=('X', 'Y', 'W', 'H'), help='crop first (game coords)')
    p = sub.add_parser('until', help='poll until text appears and/or mode reached')
    p.add_argument('--text')
    p.add_argument('--mode', choices=['cutscene', 'gameplay', 'dialogue', 'popup', 'overlay'])
    p.add_argument('--timeout', type=float, default=30)
    p.add_argument('--interval', type=float, default=1.0)
    p = sub.add_parser('advance', help='Space ONLY while cutscene/dialogue/confirm-popup; stops on anything else')
    p.add_argument('--max', type=int, default=40)
    p.add_argument('--look', type=float, nargs='?', const=0.4, default=None, help='also save a low-res look at the end')
    p = sub.add_parser('route', help='replay recorded walking route from routes/<name>.txt (--list)')
    p.add_argument('name', nargs='?')
    p.add_argument('--list', action='store_true')
    p = sub.add_parser('save-template', help='save HUD template from current frame (calibration)')
    p.add_argument('name', choices=sorted(HUD_TEMPLATES))
    p = sub.add_parser('wiki', help='search offline wiki (reference/wiki)')
    p.add_argument('query')
    p.add_argument('--show', action='store_true', help='print best title match in full')
    p.add_argument('--limit', type=int, default=15)
    p = sub.add_parser('tips', help='list tips from docs/tips.md by tag: wf tips energy mining [--all]')
    p.add_argument('tags', nargs='*')
    p.add_argument('--all', action='store_true', help='require every tag')
    p = sub.add_parser('log', help='CHEAP + EXACT: new game event-log lines since last read (quests, dialogue, '
                                   'scenes, buildings, loot, purchases). `do`/`advance`/input commands print them too')
    p.add_argument('--tail', type=int, help='last N lines instead of new ones')
    p.add_argument('--raw', action='store_true', help='no noise filter / name decoding')
    p.add_argument('--grep', help='only lines matching this regex')
    p = sub.add_parser('save', help='EXACT state from the latest autosave: day/time, money, stamina, scene, '
                                    'quests+goals, inventory, friendship (as of the last save)')
    p.add_argument('--json', action='store_true', help='dump the whole decoded save to .shots/save.json (for jq/grep)')
    p = sub.add_parser('wait', help='sleep N seconds (game time keeps running!)')
    p.add_argument('seconds', type=float)
    sub.add_parser('serve', help='run the warm daemon (normally auto-started by ./wf); keeps Vision/Quartz loaded')
    a = ap.parse_args(argv)
    if a.cmd == 'serve':
        return serve()

    if a.cmd == 'wiki':
        return wiki(a.query, a.limit, a.show)
    if a.cmd == 'tips':
        return tips(a.tags, a.all)
    if a.cmd == 'wait':
        time.sleep(a.seconds)
        return
    if a.cmd == 'log':
        lines = game_log(a.tail, a.raw)
        if a.grep:
            lines = [l for l in lines if re.search(a.grep, l)]
        print('\n'.join(lines) if lines else '(no new log lines)')
        return
    if a.cmd == 'save':
        if a.json:
            path, s = read_save()
            out = os.path.join(SHOT_DIR, 'save.json')
            json.dump(s, open(out, 'w'), ensure_ascii=False, indent=1)
            print(out, '<-', path)
        else:
            print(save_summary())
        return
    if a.cmd == 'status':
        w = game_window()
        print(json.dumps({'running': bool(w), 'window': w, 'permissions': permissions(), 'screen_locked': screen_locked(),
                          'frontmost': is_frontmost() if w else False}, indent=1))
        return
    if a.cmd == 'focus-mode':
        if a.mode == 'front':
            open(FRONT_FLAG, 'w').close()
            focus()
        elif a.mode == 'background' and os.path.exists(FRONT_FLAG):
            os.remove(FRONT_FLAG)
        print('front (game stays focused, time runs)' if keep_front() else 'background (focus only during input)')
        return
    if a.cmd == 'focus':
        print('frontmost' if focus() else 'WARNING: could not activate game')
        return
    if a.cmd == 'shot':
        print(screenshot(a.out, a.region))
        return
    if a.cmd == 'ocr':
        if a.image:
            res = ocr(a.image)
        else:
            path = screenshot(region=a.region)
            res = ocr(path, (a.region[0], a.region[1]) if a.region else (0, 0))
        if a.json:
            print(json.dumps(res))
        else:
            for r in res:
                print(f"({r['cx']:4d},{r['cy']:4d}) {r['text']}")
        return
    if a.cmd == 'find':
        hits = find_text(a.text, region=a.region, exact=a.exact)
        for r in hits:
            print(f"({r['cx']},{r['cy']}) {r['text']}")
        sys.exit(0 if hits else 1)
    if a.cmd == 'hud':
        print(json.dumps(hud(), indent=1))
        return
    if a.cmd == 'state':
        s = state()
        print(json.dumps(s, ensure_ascii=False, indent=1) if a.json else brief(s))
        return
    if a.cmd == 'bubble':
        b = find_bubble(grab())
        print(f'{b[0]},{b[1]}' if b else 'NONE')
        sys.exit(0 if b else 1)
    if a.cmd == 'look':
        out, sc, (ox, oy) = look(a.scale, a.crop)
        print(f'{out}  (game_x = {ox} + img_x / {sc}, game_y = {oy} + img_y / {sc})')
        return
    if a.cmd == 'until':
        s = until(a.text, a.mode, a.timeout, a.interval)
        print(json.dumps(s, ensure_ascii=False, indent=1) if s else 'TIMEOUT')
        sys.exit(0 if s else 1)
    if a.cmd == 'save-template':
        from PIL import Image
        os.makedirs(TEMPLATES, exist_ok=True)
        x, y, w, h = HUD_TEMPLATES[a.name]
        Image.open(screenshot()).crop((x, y, x + w, y + h)).save(os.path.join(TEMPLATES, a.name + '.png'))
        print('saved', a.name)
        return
    if a.cmd == 'route' and (a.list or not a.name):
        for f in sorted(os.listdir(ROUTES)):
            print(f[:-4] + ':', open(os.path.join(ROUTES, f)).readline().strip('# \n'))
        return

    # --- input commands: game must be frontmost (focus is given back afterwards; see release_focus)
    if a.cmd == 'click-text':
        # OCR while the game is still in the background (fast), then focus only to click
        a.hits = find_text(a.text, region=a.region, exact=a.exact)
    ensure_front()
    try:
        _dispatch_input(a)
        if a.cmd != 'do':
            wait_settle(timeout=2.0)  # let the result render before the game pauses in background
    finally:
        released = release_focus()
    if a.cmd not in ('do', 'advance'):
        if released:
            time.sleep(SPACE_SETTLE())
        print(brief(state()))  # every input command reports the settled state (one call per step)
        print_log()


def _dispatch_input(a):
    if a.cmd == 'do':
        do(a.actions, a.look, a.crop)
        return
    if a.cmd == 'click':
        click(a.x, a.y, 'right' if a.right else 'left', 2 if a.double else 1)
    elif a.cmd == 'click-text':
        hits = a.hits
        if len(hits) <= a.index:
            sys.exit(f'NOT FOUND: {a.text!r}')
        h = hits[a.index]
        click(h['cx'], h['cy'])
        print(f"clicked ({h['cx']},{h['cy']}) {h['text']}")
    elif a.cmd == 'move-mouse':
        mouse_move(a.x, a.y)
    elif a.cmd == 'key':
        for k in a.keys:
            key(k, a.hold)
            time.sleep(a.gap)
    elif a.cmd == 'hold':
        hold_keys(a.keys, a.seconds)
    elif a.cmd == 'walk':
        hold_keys(DIRS[a.direction], a.seconds)
    elif a.cmd == 'path':
        for step in a.steps:
            d, s = step.split(':')
            hold_keys(DIRS[d], float(s))
    elif a.cmd == 'scroll':
        scroll(a.dy, *(a.at or (None, None)))
    elif a.cmd == 'type':
        type_text(a.text)
    elif a.cmd == 'advance':
        advance(a.max)
        print_log()
        if a.look:
            release_focus()
            time.sleep(SPACE_SETTLE())
            out, sc, (ox, oy) = look(a.look)
            print(f'look: {out} (game = {ox}+img/{sc}, {oy}+img/{sc})')
    elif a.cmd == 'route':
        route(a.name)


# ---------------------------------------------------------------- warm daemon

SOCK = os.path.join(SHOT_DIR, 'wf.sock')


def serve():
    """Serve CLI calls over a unix socket so Vision/Quartz stay warm (first OCR in a process costs ~5 s)."""
    import contextlib
    import io
    import socket
    os.makedirs(SHOT_DIR, exist_ok=True)
    # Background processes get App-Napped (throttled ~2x); opt out for the daemon's lifetime.
    from Foundation import NSProcessInfo
    _activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(  # noqa: F841 (keep reference)
        0x00FFFFFF | 0xFF00000000, 'wf daemon serving game automation')
    if os.path.exists(SOCK):
        os.remove(SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    srv.listen(4)
    # warm up the expensive frameworks
    try:
        ocr(screenshot(os.path.join(SHOT_DIR, 'warm.png')))
    except BaseException:
        pass
    while True:
        conn, _ = srv.accept()
        with conn:
            data = b''
            while not data.endswith(b'\n'):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            try:
                argv = json.loads(data.decode())
            except ValueError:
                continue
            buf = io.StringIO()
            code = 0
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    main(argv)
                except SystemExit as e:
                    if isinstance(e.code, str):
                        print(e.code)
                        code = 1
                    else:
                        code = e.code or 0
                except Exception as e:  # keep serving
                    print(f'ERROR: {type(e).__name__}: {e}')
                    code = 1
            try:
                conn.sendall(json.dumps({'out': buf.getvalue(), 'code': code}).encode() + b'\n')
            except OSError:
                pass


if __name__ == '__main__':
    main()
