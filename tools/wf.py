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
import math
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


TITLE_BAR = 28  # points: macOS title bar of a windowed (non-fullscreen) window


def content_box(w):
    """(x0, y0, scale) of the 16:9 game picture inside window `w`, in window points. A windowed window (w['y'] > 0)
    has a 28 pt title bar on top; the picture is fitted into the rest, centred (bars on the sides or top/bottom).
    game point (gx, gy) -> window (x0 + gx*scale, y0 + gy*scale)."""
    bar = TITLE_BAR if w.get('y', 0) > 0 else 0
    ah = w['h'] - bar
    scale = min(w['w'] / FRAME_W, ah / FRAME_H)
    cw, ch = FRAME_W * scale, FRAME_H * scale
    return (w['w'] - cw) / 2, bar + (ah - ch) / 2, scale


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


def grab(crop=True):
    """Fast in-memory capture of the game window as a PIL RGB image at window-point size (~50 ms).
    crop=False keeps the whole window (title bar included) instead of the 1920x1080 virtual frame."""
    from PIL import Image
    Q = _quartz()
    if screen_locked():
        sys.exit('ERROR: the Mac screen is LOCKED; captures are black and input is blocked. Ask the user to unlock.')
    import objc
    w = require_window()
    with objc.autorelease_pool():
        cg = Q.CGWindowListCreateImage(Q.CGRectNull, Q.kCGWindowListOptionIncludingWindow, w['id'],
                                       Q.kCGWindowImageBoundsIgnoreFraming | Q.kCGWindowImageNominalResolution)
        if cg is None:
            sys.exit('ERROR: capture failed (Screen Recording permission? sandbox?)')
        cw, ch = Q.CGImageGetWidth(cg), Q.CGImageGetHeight(cg)
        bpr = Q.CGImageGetBytesPerRow(cg)
        data = Q.CGDataProviderCopyData(Q.CGImageGetDataProvider(cg))
        # memoryview, NOT bytes(data): bytes() of the CFData leaked the whole frame (~8 MB) per call, so a long
        # bubble-scan loop grew the daemon without bound (D183 replant run hang; measured +8 MB/call → +0)
        img = Image.frombuffer('RGBA', (cw, ch), memoryview(data), 'raw', 'BGRA', bpr, 1).convert('RGB')
        del cg, data
    if img.size != (w['w'], w['h']):
        img = img.resize((w['w'], w['h']), Image.BILINEAR)
    return _to_frame(img, w) if crop else img


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


PARK = (110, 110)   # game coords: over the HUD clock — nothing to hover there. (obj-walk's title bar / overlay / failed
                    # capture came from the user moving the window, not from parking — the clock is just the safer spot)


def park_mouse():
    """Move the cursor off the game view after a click, so hover cards (Bee Hive) don't cover screenshots/clicks."""
    try:
        mouse_move(*PARK)
    except Exception:  # noqa: BLE001
        pass


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
    park_mouse()

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
CLOCK_REGION = (120, 25, 380, 90)      # day name + time next to the analog clock (top-left); from x 120: "12:50 pm" starts left of 150 (objects-seed)
POPUP_WORDS = ('Confirm', 'Hooray', 'Quest Complete', 'Quest complete',  # EN UI (L48; exact EN wording unverified)
               'одтвердить',          # RU "Подтвердить" Confirm (OCR sometimes reads П as Л)
               'Ура!',                # RU completion popup button "Hooray!"
               'Задание выполнено')   # RU "Quest complete" header
SUBTITLE_Y = 940                        # dialogue subtitles ("Name: text") are OCR'd below this y


def _match(img, name, thresh=30.0):  # gameplay <= ~18.4 (dark interior behind the button); menus, journal >= 78
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
        if res['bubble']:
            res['bubble_kind'], res['bubble_dist'] = bubble_kind(img, res['bubble'])
            res['bubble_hl'] = bubble_highlighted(img, res['bubble'])
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
        parts.append(f"bubble@{s['bubble'][0]},{s['bubble'][1]}:{s.get('bubble_kind', '?')}"
                     + ('' if s.get('bubble_hl', True) else '(dim)'))
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
    """The biggest interaction prompt bubble (cx, cy), or None (see find_bubbles)."""
    bs = find_bubbles(img)
    return bs[0] if bs else None


BUBBLE_FILL = 0.2   # share of the badge box that is cream; the icon covers more of it at night (honey jars: 26 %)


def find_bubbles(img):
    """Every interaction prompt bubble (round cream badge ~120px) outside the HUD bands, biggest first: [(cx, cy)].
    Several show when several objects are in reach; the highlighted one is what Space acts on."""
    import numpy as np
    W, H = img.size
    f = 4
    a = np.asarray(img.resize((W // f, H // f)), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # cream badge; at night the cream is lit bluish (rim r-b ≈ 19, zoom-walk 9:20 pm): floor 12 still excludes the white
    # fence (r-b ≈ 0–10); size/shape filters below do the rest
    mask = (r >= 195) & (r <= 235) & (g >= 165) & (g <= 215) & (b >= 135) & (b <= 200) & (r - b >= 12) & (r - b <= 65)
    y0 = 230 // f  # skip HUD band (clock, buttons)
    mask[:y0] = False
    sh, sw = mask.shape
    seen = np.zeros_like(mask)
    found = []
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
        if 20 <= bw <= 40 and 20 <= bh <= 40 and 0.75 <= bw / bh <= 1.33 and n >= BUBBLE_FILL * bw * bh:
            found.append(((int((x0 + x1) // 2 * f), int((ya + yb) // 2 * f)), n))
    return [c for c, _ in sorted(found, key=lambda t: -t[1])]


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


# ---------------------------------------------------------------- bubble kinds (L55)
# What a prompt bubble means, from its icon: Apple Vision image feature prints, nearest labelled reference in
# tools/bubbles/<kind>/*.png (crops 140x140 around find_bubble's centre). Kinds so far: pickup (bag "+"), pickaxe,
# axe, talk ("…"), info ("?"). `do` collects new labelled crops automatically (.shots/bubble_samples/<kind>/).
BUBBLE_DIR = os.path.join(ROOT, 'tools', 'bubbles')
BUBBLE_MAX_DIST = 0.6   # feature-print distance above this = unknown icon
_BUBBLE_REFS = None


def _featureprint(img):
    import Vision
    from Foundation import NSData
    import io
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'PNG')
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    req = Vision.VNGenerateImageFeaturePrintRequest.alloc().init()
    h = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    h.performRequests_error_([req], None)
    import numpy as np
    obs = req.results()[0]
    v = np.frombuffer(bytes(obs.data()), dtype=np.float32 if obs.elementType() == 1 else np.float64)
    return v / (np.linalg.norm(v) or 1)


def _bubble_refs():
    global _BUBBLE_REFS
    if _BUBBLE_REFS is None:
        from PIL import Image
        _BUBBLE_REFS = []
        for kind in sorted(os.listdir(BUBBLE_DIR)) if os.path.isdir(BUBBLE_DIR) else []:
            d = os.path.join(BUBBLE_DIR, kind)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith('.png'):
                    _BUBBLE_REFS.append((kind, f, bubble_featureprint(Image.open(os.path.join(d, f)))))
    return _BUBBLE_REFS


def bubble_crop(img, b):
    return img.crop((b[0] - 70, b[1] - 70, b[0] + 70, b[1] + 70))


def bubble_icon(crop):
    """Semantic icon only: exclude the outer orange selection ring, which exists solely for human Space-key UX."""
    from PIL import Image, ImageDraw
    crop = crop.convert('RGB')
    cx, cy = crop.width // 2, crop.height // 2
    radius = max(1, int(min(crop.width, crop.height) * 0.30))  # 42 px for 140 crops; ring begins near radius 48
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    icon = crop.crop(box)
    mask = Image.new('L', icon.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, icon.width - 1, icon.height - 1), fill=255)
    out = Image.new('RGB', icon.size, 'white')
    out.paste(icon, mask=mask)
    return out


def bubble_featureprint(crop):
    return _featureprint(bubble_icon(crop))


def bubble_kind(img, b, exclude=None):
    """(kind, distance) of the bubble at b in a 1920x1080 frame; kind 'unknown' if nothing is close."""
    import numpy as np
    fp = bubble_featureprint(bubble_crop(img, b))
    best = ('unknown', 9.0)
    for kind, name, ref in _bubble_refs():
        if name != exclude:
            d = float(np.linalg.norm(fp - ref))
            if d < best[1]:
                best = (kind, d)
    return best if best[1] <= BUBBLE_MAX_DIST else ('unknown', best[1])


def bubble_highlighted(img, b):
    """Active prompt = orange ring around the bubble (plain ones score 0.00-0.01, highlighted 0.03-0.5)."""
    import numpy as np
    a = np.asarray(bubble_crop(img, b).convert('RGB'), dtype=int)
    r, g, bl = a[..., 0], a[..., 1], a[..., 2]
    yy, xx = np.mgrid[:a.shape[0], :a.shape[1]]
    d = np.hypot(xx - 70, yy - 70)
    ring = (d >= 48) & (d <= 66)
    orange = (r > 200) & (g > 110) & (g < 190) & (bl < 110) & (r - bl > 110)
    return bool(orange[ring].mean() > 0.02)


# Self-labelling (L56): the game logs every player interaction as `> <performance> me=Player target=<object>`.
# That performance is the ground truth for the bubble Space was pressed at; an unseen one becomes a NEW kind (its name).
PERF = re.compile(r'\] > (\w+?) me=Player target=([\w#()-]+)')
PERF_IGNORE = re.compile(r'^(goal_notification|enter_scene|stamina_fail|advance_day|trigger_startday_events|day_start_intro|'
                         r'SaveGameUpgrade|Mining_|scene_change|quest_complete|sleep_transition|grab_item_auto|'
                         r'unplant_impl)')  # unplant_impl = the Remove dialog button, not a bubble
PERF_ALIAS = [(r'^grab_item$', 'pickup'), (r'^hit_rock$', 'pickaxe'), (r'^PlayerGardening', 'axe'), (r'^water$', 'water'),
              (r'^fill_watering_can$', 'fill_can'), (r'^plant$', 'plant'), (r'^sleep\d*$', 'sleep'), (r'^routine_sign$', 'info'),
              (r'_trade', 'talk')]
BUBBLE_CAP = 30         # refs per kind
BUBBLE_DUP = 0.15       # feature-print distance below this = near duplicate, not stored
LEARNED_LOG = os.path.join(SHOT_DIR, 'learned.log')
_PENDING = []  # (crop, kind seen) for Space presses at a bubble during this `do`


def event_kind(lines):
    """Kind named by the first player interaction in these log lines (None if there is none)."""
    for l in lines:
        m = PERF.search(l)
        if m and not PERF_IGNORE.match(m.group(1)):
            perf = m.group(1)
            return next((k for rx, k in PERF_ALIAS if re.search(rx, perf)), re.sub(r'_?\d+$', '', perf).lower())
        if re.search(r'\] [A-Z]\w+: ', l) and 'Player:' not in l:  # an NPC's dialogue line
            return 'talk'
    return None


def learn_bubble(crop, kind, seen):
    """Add a crop to tools/bubbles/<kind>/ unless it's a near duplicate or the kind is full. Returns True if stored."""
    import numpy as np
    global _BUBBLE_REFS
    fp = bubble_featureprint(crop)
    same = [ref for k, _, ref in _bubble_refs() if k == kind]
    if len(same) >= BUBBLE_CAP or any(float(np.linalg.norm(fp - r)) < BUBBLE_DUP for r in same):
        return False
    d = os.path.join(BUBBLE_DIR, kind)
    os.makedirs(d, exist_ok=True)
    name = f'{kind}-{time.strftime("%Y%m%d-%H%M%S")}.png'
    crop.save(os.path.join(d, name))
    _BUBBLE_REFS = None  # reload with the new reference
    with open(LEARNED_LOG, 'a') as f:
        f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")}\t{kind}\t(classifier said {seen})\t{name}\n')
    return True


def act(want):
    """Press Space only if the highlighted bubble is `want` (e.g. act:pickup). Returns None or why it didn't."""
    img = _frame()
    b = find_bubble(img)
    if not b:
        return f'act:{want}: no bubble (not pressed)'
    kind, dist = bubble_kind(img, b)
    hl = bubble_highlighted(img, b)
    if kind != want or not hl:
        return f'act:{want}: bubble@{b[0]},{b[1]} is {kind}{"" if hl else "(dim)"} (dist {dist:.2f}): not pressed'
    _PENDING.append((bubble_crop(img, b), kind))
    key('space')
    return None


def collect_bubble_samples(log_lines):
    """Self-improvement for bubble kinds (L56): label each bubble Space was pressed at by the interaction the game logged
    next; if the classifier was wrong/unknown, learn the crop as a new reference (new kinds are created on the fly)."""
    global _PENDING
    pend, _PENDING = _PENDING, []
    if not pend:
        return
    label = event_kind(log_lines)
    for crop, seen in pend[-1:]:  # the last Space is the one the logged interaction belongs to
        d = os.path.join(SHOT_DIR, 'bubble_samples', label or 'unlabelled')
        os.makedirs(d, exist_ok=True)
        crop.save(os.path.join(d, f'{time.strftime("%Y%m%d-%H%M%S")}-{seen}.png'))
        if label and seen != label and learn_bubble(crop, label, seen):
            print(f'learned: bubble kind {label!r} (classifier said {seen}) → tools/bubbles/{label}/')


def learn_report():
    """`wf learn`: what the self-improving parts know and how well (bubble kinds now; see docs/self-improvement.md)."""
    import numpy as np
    refs = _bubble_refs()
    kinds = {}
    for k, _, _ in refs:
        kinds[k] = kinds.get(k, 0) + 1
    ok, n = 0, 0
    for i, (k, _, v) in enumerate(refs):
        if kinds[k] < 2:
            continue
        near = min(((float(np.linalg.norm(v - w)), kk) for j, (kk, _, w) in enumerate(refs) if j != i))[1]
        ok, n = ok + (near == k), n + 1
    print(f'bubble kinds ({len(refs)} refs): ' + ', '.join(f'{k} {c}' for k, c in sorted(kinds.items())))
    print(f'leave-one-out accuracy (kinds with ≥2 refs): {ok}/{n}')
    try:
        tail = open(LEARNED_LOG).read().splitlines()[-10:]
    except OSError:
        tail = []
    print('recently learned:' + ('\n  ' + '\n  '.join(tail) if tail else ' nothing yet'))
    pend = os.path.join(SHOT_DIR, 'bubble_samples', 'unlabelled')
    if os.path.isdir(pend) and os.listdir(pend):
        print(f'unlabelled samples (Space with no logged interaction): {len(os.listdir(pend))} in {pend}')
    # action outcomes observed in run logs -> compare with docs/actions.md Expect
    obs = {}
    for f in run_logs():
        cur = None
        for l in open(f):
            e = json.loads(l)
            line = e.get('line', '')
            m = re.search(r'Damage (\d+) to (\w+).*\(damage = (\d+)\).*destroying', line)
            if m:
                cur = m.group(2)
                o = obs.setdefault(cur, {'n': 0, 'hits': [], 'picked': []})
                o['n'] += 1
                o['hits'].append(-(-int(m.group(3)) // int(m.group(1))))
                o['picked'].append(0)
            elif 'grab_item' in line and cur:
                obs[cur]['picked'][-1] += 1
    print('road colour sets (area:light): ' + ', '.join(f'{k} ({v.get("samples", 0)} samples)' for k, v in road_sets().items()))
    print(f'remembered hops (taught by the model): {len(hops())}')
    asks = {}
    for f in run_logs():
        for l in open(f):
            e = json.loads(l)
            if e.get('type') == 'vision' and e.get('what') == 'ask':
                k = os.path.relpath(f, RUNS_DIR).replace('/log.jsonl', '').replace('.jsonl', '')
                asks[k] = asks.get(k, 0) + 1
    if asks:
        print('model questions per run: ' + ', '.join(f'{f} {n}' for f, n in asks.items()))
    if obs:
        print('observed in run logs (target: destroyed · hits each · pickups after each) → compare docs/actions.md Expect:')
        for k, o in sorted(obs.items()):
            print(f'  {k}: {o["n"]} · hits {sorted(set(o["hits"]))} · picked {o["picked"]}')


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


def _frame():
    """grab() that also keeps the frame for toast capture in `do`."""
    img = grab()
    if _FRAMES is not None and len(_FRAMES) < 12:
        _FRAMES.append(img)
    return img


def _signature():
    return _frame().convert('L').resize((96, 54))


def _diff(a, b):
    from PIL import ImageChops, ImageStat
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


# ---------------------------------------------------------------- run log (one dir per task, L53, L76)
# runs/<YYYYMMDD-HHMM>-<task>/: plan.md (the supervisor's step-by-step plan for the agent, tools/plan.py), log.jsonl
# (one JSON event per line {"t": unix, "type": ...}), progress.md (written by the tool: step timestamps + budget use),
# retro-<n>.md (escalations). The agent writes the meaning (`wf run step/attempt/issue/escalate/end`); tools write
# timings automatically: every ./wf call (wfc.py), Tara's activity segments (go:/still), key game events.
# Older runs are flat runs/<…>.jsonl files. `wf run report` = timeline + summary.
RUNS_DIR = os.path.join(ROOT, 'runs')
RUN_CUR = os.path.join(SHOT_DIR, 'run.current')
RUN_NOTES = ('attempt', 'issue', 'gap', 'decision', 'note', 'interrupt')  # interrupt = a user interrupt (bench)
RUN_GAME = re.compile(r'\] > \w+ me=Player|totalPlanted|destroying|grab_item|\[QUEST\] (?!Posting)|\[STATS\]|\[REL\]|ChangeScene|OnEnterBuilding|'
                      r'OnExitBuilding|giveloot|out of strength|no strength|Spawning player')


def run_path():
    try:
        return open(RUN_CUR).read().strip() or None
    except OSError:
        return None


def run_dir():
    p = run_path()
    return os.path.dirname(p) if p and os.path.basename(p) == 'log.jsonl' else None


def run_logs():
    """Every run log, old (runs/*.jsonl) and new (runs/*/log.jsonl), oldest first."""
    if not os.path.isdir(RUNS_DIR):
        return []
    out = []
    for f in sorted(os.listdir(RUNS_DIR)):
        p = os.path.join(RUNS_DIR, f)
        if f.endswith('.jsonl'):
            out.append(p)
        elif os.path.isfile(os.path.join(p, 'log.jsonl')):
            out.append(os.path.join(p, 'log.jsonl'))
    return out


def run_events(path=None):
    path = path or run_path()
    try:
        return [json.loads(l) for l in open(path) if l.strip()]
    except (OSError, ValueError, TypeError):
        return []


def plan_state(d=None, hour_now=None):
    """(steps, states) of the open run's plan (tools/plan.py), or ([], [])."""
    import plan
    d = d or run_dir()
    try:
        steps = plan.parse(open(os.path.join(d, 'plan.md')).read())[1]
    except (OSError, TypeError):
        return [], []
    return steps, plan.steps_state(steps, run_events(os.path.join(d, 'log.jsonl')), time.time(), hour_now)


def write_progress(d=None, hour_now=None):
    """runs/<task>/progress.md from plan.md + log.jsonl: status table and the timestamped step log."""
    import plan
    d = d or run_dir()
    if not d:
        return None
    steps, states = plan_state(d, hour_now)
    lines = []
    for e in run_events(os.path.join(d, 'log.jsonl')):
        if e.get('type') == 'plan_step':
            h = e.get('hour')
            game = f' (game {int(h):02d}:{int(h % 1 * 60):02d})' if h is not None else ''
            lines.append(f'{time.strftime("%m-%d %H:%M", time.localtime(e["t"]))}{game} step {e["n"]} '
                         f'{plan.MARK[e["state"]]} {e["state"]}' + (f': {e["text"]}' if e.get('text') else ''))
    task = os.path.basename(d)
    path = os.path.join(d, 'progress.md')
    open(path, 'w').write(plan.progress_md(task, steps, states, lines))
    return path


MOVES = [0]       # go: clicks in this daemon (every move attempt)
TRACK = os.path.join(SHOT_DIR, 'track.json')   # her position after each command that tried to move her (L80)


_WORLD = [None, None]   # (World, LogReader): the world model in shadow mode (M2, spec 2026-10-30 §3)


def world():
    """The daemon's World, created on first use from the facts, the entity cache and the whole current game log."""
    if _WORLD[0] is None:
        import nav
        from runtime.log import LogReader
        from world.model import World
        _WORLD[0] = World(facts=nav.load(), spawn_inside=spawn_inside())
        _WORLD[1] = LogReader(GAME_LOG, start=0, unhash=_unhash)  # the real log hashes names (review C1)
        world_sync()  # replay this session's log first …
        _WORLD[0].end_replay()
        try:  # … then the save, which is newer than old log lines (review I3)
            _, s = read_save()
            p = s.get('currentPlayerPosition') or {}  # as save_summary reads it
            if s.get('currentScene'):
                _WORLD[0].scene = s['currentScene']
                _WORLD[0].belief.scene(s['currentScene'])
                _WORLD[0].belief._set(float(p.get('x', 0)), float(p.get('z', 0)), 5.0)  # the save may be stale
        except Exception:  # noqa: BLE001
            pass
    return _WORLD[0]


def world_sync():
    """Feed new game-log evidence into the world (shadow mode: it only predicts and is scored)."""
    if _WORLD[0] is None:
        return
    n = 0
    for ev in _WORLD[1].new():
        _WORLD[0].observe(ev)
        n += 1
    if n:
        _WORLD[0].save()


class Stuck(Exception):
    """The stuck rule fired (L75, L80): aborts the running command or game function."""


_TRACK_AT = [0]   # MOVES when the last track point was added: a point needs at least one click since


def track_point(scene, x, z):
    """Her position after a move (a reading, a refused attempt, or the end of a command that clicked). Raises Stuck
    when the last nav.STUCK_MOVES moves stayed within nav.STUCK_SPREAD (user rule L75), checked inside long
    commands too (L80)."""
    import nav
    if MOVES[0] == _TRACK_AT[0]:
        return
    _TRACK_AT[0] = MOVES[0]
    try:
        tr = json.load(open(TRACK))
    except (OSError, ValueError):
        tr = []
    tr = (tr + [[scene, round(x, 2), round(z, 2), round(time.time(), 1)]])[-20:]
    json.dump(tr, open(TRACK, 'w'))
    pts = [tuple(p[:3]) for p in tr]
    if not nav.no_progress(pts) or tr[-1][3] - tr[-(nav.STUCK_MOVES + 1)][3] > 3600:
        return
    json.dump([], open(TRACK, 'w'))  # one episode = one alarm; the next 3 moves are counted afresh
    n = next((st['n'] for st in plan_state()[1] if st['state'] == 'start'), None)
    run_log('stuck', at=pts[-1], moves=nav.STUCK_MOVES)
    sid = ''
    try:  # eval (M0): the agent/supervisor marks it hit (really stuck) or miss: ./wf eval mark <id> hit|miss
        import evals
        sid = evals.predict('stuck', 'stuck', True, {'at': list(pts[-1])})
    except Exception:  # noqa: BLE001
        pass
    raise Stuck(f'[eval {sid}] STUCK (L75): position within {nav.STUCK_SPREAD:.0f} units over the last {nav.STUCK_MOVES} moves at '
                f'{scene} ({x:.1f}, {z:.1f}). Stop moving that way; ' +
                (f'`./wf run escalate {n} stuck` and return RESULT: escalate step {n}' if n else
                 'ask for the next step (`./wf ask-step <place>`) or report'))


def step_warning():
    """A line for every ./wf output while the current plan step is over its call budget (L76), else ''."""
    if not run_dir():
        return ''
    _, states = plan_state()
    cur = next((st for st in states if st['state'] == 'start'), None)
    if cur and any('calls' in o for o in cur['over']):
        return (f'STEP {cur["n"]} OVER BUDGET ({", ".join(cur["over"])}): stop, `./wf run escalate {cur["n"]} <why>` '
                f'and return RESULT: escalate step {cur["n"]}')
    return ''


def run_log(type_, **kw):
    """Append one event to the current run (no-op when no run is open); nav events also always go to
    tools/nav/events.jsonl, so a skip is never silent."""
    if type_ == 'nav':
        import nav
        nav.event(**{k: v for k, v in kw.items() if k != 't'})
    p = run_path()
    if p:
        with open(p, 'a') as f:
            f.write(json.dumps({'t': round(kw.pop('t', time.time()), 2), 'type': type_, **kw}, ensure_ascii=False) + '\n')


def run_cmd(sub_, args):
    """wf run start <task> <goal…> | plan | step <n> start|done|fail|skip [note…] | escalate <n> <why…> | status |
    attempt|issue|gap|decision|note <text…> | end <done|partial|blocked|stopped> [text…] | report [path]"""
    import plan
    if sub_ == 'start':
        if not args:
            sys.exit('usage: wf run start <task-id> <goal…>')
        if run_path():
            run_log('end', result='abandoned', text='a new run started')
        d = os.path.join(RUNS_DIR, time.strftime('%Y%m%d-%H%M-') + re.sub(r'[^\w-]', '', args[0]))
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'log.jsonl')
        open(RUN_CUR, 'w').write(path)
        run_log('start', quest=args[0], goal=' '.join(args[1:]))
        pm = os.path.join(d, 'plan.md')
        if not os.path.exists(pm):
            open(pm, 'w').write(plan.template(args[0], ' '.join(args[1:])))
        print(f'run: {os.path.relpath(d, ROOT)}/  (plan.md to write, then `wf run plan` to review)')
    elif sub_ == 'plan':
        d = run_dir()
        if not d:
            sys.exit('no open run with a plan: wf run start <task> <goal…>')
        md = open(os.path.join(d, 'plan.md')).read()
        probs = plan.review(md)
        print(f'{os.path.relpath(d, ROOT)}/plan.md: {len(plan.parse(md)[1])} steps; ' +
              ('review OK' if not probs else 'review problems:\n  ' + '\n  '.join(probs)))
    elif sub_ in ('step', 'escalate'):
        d = run_dir()
        if not d:
            sys.exit('no open run with a plan')
        if sub_ == 'step' and (len(args) < 2 or args[1] not in plan.MARK or args[1] == 'todo'):
            sys.exit('usage: wf run step <n> start|done|fail|skip [note…]')
        if not args:
            sys.exit('usage: wf run escalate <n> <why…>')
        n, state = args[0], ('escalate' if sub_ == 'escalate' else args[1])
        note = ' '.join(args[1:] if sub_ == 'escalate' else args[2:])
        steps, _ = plan_state(d)
        if n not in [s['n'] for s in steps]:
            sys.exit(f'no step {n} in plan.md')
        try:
            hour = game_hour(_frame()) if is_frontmost() else None
        except Exception:
            hour = None
        run_log('plan_step', n=n, state=state, text=note, hour=hour)
        write_progress(d, hour)
        _, states = plan_state(d, hour)
        st = next(x for x in states if x['n'] == n)
        msg = f'step {n} {plan.MARK[state]} {state} · {st["calls"]} calls, {st["real_min"]} real min' + (
            f', {st["game_min"]} game min' if st['game_min'] is not None else '')
        if sub_ == 'escalate':
            k = 1 + sum(1 for f in os.listdir(d) if f.startswith('retro-'))
            msg += (f'\nESCALATED: return RESULT: escalate step {n}. Supervisor: stuck retro (read '
                    f'retros/stuck-ledger.md first) → {os.path.relpath(d, ROOT)}/retro-{k}.md → fix plan.md from step {n}')
        print(msg)
    elif sub_ == 'waits':
        from game import track
        w = track.waits(run_events())
        print('actions (top level and nested): n · seconds · failed')
        for k, (n, sec, bad) in sorted(w['actions'].items(), key=lambda kv: -kv[1][1]):
            print(f'  {k}: {n} · {sec:.0f}s · {bad}')
        th = w['thinking']
        print(f'thinking between ./wf calls: {sum(g for g, _ in th):.0f}s over {len(th)} gaps; longest:')
        for g, scr in sorted(th, reverse=True)[:8]:
            print(f'  {g:5.1f}s after: {scr}')
    elif sub_ == 'status':
        p = write_progress()
        if not p:
            sys.exit('no open run with a plan')
        print(open(p).read())
    elif sub_ in RUN_NOTES:
        if not run_path():
            sys.exit('no open run: wf run start <task-id> <goal…>')
        run_log(sub_, text=' '.join(args))
    elif sub_ == 'end':
        p = run_path()
        if not p:
            sys.exit('no open run')
        run_log('end', result=(args or ['done'])[0], text=' '.join(args[1:]))
        if run_dir():
            write_progress()
        os.remove(RUN_CUR)
        run_report(p)
    elif sub_ == 'report':
        p = args[0] if args else run_path() or max(run_logs(), key=os.path.getmtime)
        if os.path.isdir(p):
            p = os.path.join(p, 'log.jsonl')
        run_report(p)
    else:
        sys.exit(run_cmd.__doc__)


def world_cmd(args):
    """wf world [entities [kind] | tara | route X Z | explain ID]."""
    w = world()
    world_sync()
    sub_ = args[0] if args else 'entities'
    if sub_ == 'entities':
        es = w.entities(kind=args[1]) if len(args) > 1 else w.entities()
        return print('\n'.join(f'{e} uses={",".join(e.uses)} sources={len(e.sources)}' for e in es) or 'no entities')
    if sub_ == 'tara':
        area, x, z, u = w.tara()
        r = w.in_reach()
        return print(f'tara: {area} ({x:.2f}, {z:.2f}) ±{u:.2f}' + (f' · in reach: {r}' if r else '') +
                     (' · NEEDS FIX' if w.needs_fix() else ''))
    if sub_ == 'route' and len(args) == 3:
        area = w.tara()[0]
        wps = w.route((area, float(args[1]), float(args[2])), reach=1.0)
        return print('no way known' if wps is None else ' → '.join(f'({x:.1f}, {z:.1f})' for x, z in wps))
    if sub_ == 'explain' and len(args) == 2:
        return print(w.explain(int(args[1])))
    sys.exit(world_cmd.__doc__)


def bench_cmd(args):
    """wf bench start A|B|C | report [run dir] | compare [A|B|C] (spec 2026-10-30 §7.2)."""
    import shutil
    import bench
    import evals
    sub_ = args[0] if args else ''
    if sub_ == 'start' and len(args) == 2 and args[1] in 'ABC':
        run_cmd('start', [f'bench-{args[1]}', f'benchmark {args[1]}'])
        shutil.copy(os.path.join(bench.DIR, f'{args[1]}.md'), os.path.join(run_dir(), 'plan.md'))
        return run_cmd('plan', [])
    if sub_ == 'report':
        if len(args) > 1:
            d = args[1]
        else:  # the newest bench run (never an ordinary task run, review #3a)
            benches = [p for p in run_logs() if '-bench-' in p and p.endswith('log.jsonl')]
            if not benches:
                return print('no bench runs yet: wf bench start A|B|C')
            d = os.path.dirname(max(benches, key=os.path.getmtime))
        ev = run_events(os.path.join(d, 'log.jsonl'))
        try:
            import nav
            navev = [json.loads(line) for line in open(nav.EVENTS) if line.strip()]
        except OSError:
            navev = []
        t1 = ev[-1].get('end', ev[-1]['t']) if ev else None
        s = bench.score(ev, navev, evals.report(ev[0]['t'], t1) if ev else {})
        task = next((e.get('quest', '') for e in ev if e.get('type') == 'start'), '').replace('bench-', '')
        rev = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                             text=True).stdout.strip()
        row = {'date': time.strftime('%Y-%m-%d %H:%M'), 'task': task, 'toolkit': rev, 'run': os.path.basename(d), **s}
        json.dump(row, open(os.path.join(d, 'bench.json'), 'w'), indent=1)
        bench.upsert_result(row)
        return print(json.dumps(row, indent=1))
    if sub_ == 'compare':
        return print(bench.compare_table(bench.results(args[1] if len(args) > 1 else None)))
    sys.exit(bench_cmd.__doc__)


def objects_cmd(args):
    """wf objects list [kind] | add <kind> x0 y0 x1 y1 [state] | remove <kind> <id> | detect [kind...] | find <kind> (= detect <kind>) |
    eval [frames_dir] | calibrate [frames_dir] | reembed: appearance-based objects
    (tools/objects, DINOv2 patch heatmaps). Reads the current frame only (WF_FRAME=<png> uses a saved one); no focus change, no input."""
    if os.path.join(ROOT, 'tools') not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
    from objects import store as OS, detect as OD, calib as OC
    st = OS.Store(os.environ.get('WF_OBJECTS_DB') or OS.DEFAULT_ROOT)
    if not args or args[0] == 'list':
        if len(args) > 1:
            if not st.count(args[1]):
                return print('no such kind')
            for e in st.examples(args[1]):
                print(f'{e.id}  state={e.state} light={e.light} source={e.source}  {st.example_path(args[1], e.id)}')
            return
        for k in st.kinds():
            print(f'{k}  {st.count(k)}')
        return
    def frame():
        from PIL import Image
        fp = os.environ.get('WF_FRAME')
        return Image.open(fp).convert('RGB') if fp else grab()
    def show(ds):
        for d in ds:
            print(f'{d.kind} box {",".join(str(int(v)) for v in d.box)} z {d.dist:.1f} point {d.point[0]},{d.point[1]}')
        if not ds:
            print('(nothing detected)')
    def light_now(img):
        try:
            return light_period(game_hour(img))
        except Exception:
            return None
    cmd, rest = args[0], args[1:]
    if cmd == 'remove' and len(rest) == 2:
        print(f'removed {rest[0]} {rest[1]}' if st.remove(rest[0], rest[1]) else 'no such example')
        return
    def unknown(ks):
        bad = [k for k in ks if not st.count(k)]
        for k in bad:
            print(f'unknown kind: {k} (known: {", ".join(st.kinds()) or "none"})')
        return bad
    if cmd == 'add':
        usage = 'usage: wf objects add <kind> x0 y0 x1 y1 [state]'
        if not 5 <= len(rest) <= 6:
            sys.exit(usage)
        try:
            box = tuple(int(v) for v in rest[1:5])
        except ValueError:
            sys.exit(usage)
        img = frame()
        W, H = img.size
        if not (0 <= box[0] < box[2] <= W and 0 <= box[1] < box[3] <= H):
            sys.exit(f'box outside the frame ({W}x{H})')
        if not OS.KIND_RE.match(rest[0]):
            sys.exit(f'bad kind name: {rest[0]!r} (letters, digits, _ and - only)')
        state = rest[5] if len(rest) > 5 else None
        try:
            light = light_period(game_hour(img))
        except Exception:
            light = None
        crop = img.crop(box)
        vec = OD.dino.mean_vector(crop)
        ex = st.add(rest[0], crop, vec, state=state, light=light, source='model')
        if ex:
            print(f'added {rest[0]} {ex.id} ({light}, {state})')
        else:
            d, near = st.nearest(vec, rest[0])
            print(f'duplicate of {near.id} (dist {max(d, 0.0):.3f}), skipped')
        return
    if cmd == 'detect':
        if rest and unknown(rest):
            return
        img = frame()
        show(OD.detect(img, st, kinds=rest or None, light=light_now(img)))
        return
    if cmd == 'eval' and len(rest) <= 1:
        print(OC.eval_table(st, rest[0] if rest else None))
        return
    if cmd == 'calibrate' and len(rest) <= 1:
        th, table = OC.calibrate(st, rest[0] if rest else None)
        OC.write_thresholds(st, th)
        print(table)
        print(f'wrote {os.path.join(st.root, OD.THRESHOLDS)}')
        return
    if cmd == 'reembed' and not rest:
        for k, n in OC.reembed(st).items():
            print(f'{k}  {n} re-embedded')
        return
    if cmd == 'find' and len(rest) == 1:
        if unknown(rest):
            return
        img = frame()
        show([d for d in OD.detect(img, st, kinds=rest) if d.kind == rest[0]][:3])
        return
    sys.exit(objects_cmd.__doc__)


def save_bed_counts(crops):
    """Farm-wide bed totals from the save crop list: empty (plantState ##0), ripe (##produced), wilted (isWilted),
    dry (growing, isWatered false, not wilted)."""
    def st(c):
        return (c.get('plantState') or '').strip('#')
    wilted = lambda c: c.get('isWilted') == 'true'
    return {'wilted': sum(wilted(c) for c in crops),
            'ripe': sum(c.get('plantState') == '##produced' and not wilted(c) for c in crops),
            'empty': sum(st(c) in ('', '0') for c in crops),
            'dry': sum(c.get('plantState') in ('##growing', '##producing') and c.get('isWatered') != 'true'
                       and not wilted(c) for c in crops)}


def game_stamp():
    """Latest game-log stamp such as 'D183 1:30:00 PM' (the clock the graph hints use), or None."""
    try:
        with open(GAME_LOG, 'rb') as fh:
            fh.seek(max(0, os.path.getsize(GAME_LOG) - 20000))
            tail = fh.read().decode('utf-8', 'replace')
    except OSError:
        return None
    ms = re.findall(r'^\[(D\d+ [^\]]+)\]', tail, re.M)
    return ms[-1] if ms else None


def anchor_cmd(text):
    """wf anchor "<answer>": parse the vision answer, set Tara.at + states in the graph, check wilted count vs the save. No input."""
    if os.path.join(ROOT, 'tools') not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
    from objects import anchor as OA
    counts = None
    try:
        counts = save_bed_counts(farm_status()['crops'])
    except Exception as e:
        print(f'save counts unavailable ({type(e).__name__}: {e})')
    try:
        print(OA.answer(text, save_counts=counts))
    except OA.AnchorError as e:
        sys.exit(f'REJECTED: {e}')


def graph_cmd(args):
    """wf graph show [region] | where | path <Kind> [key=value ...] | view-add <region> | sync |
    map-seed <map.png> | map-heatmap <node> <map.png> [out.png]: the object graph with nested regions
    (tools/objects/graph). Reads the current frame only (WF_FRAME=<img> uses a saved one); no focus change, no input.
    Env: WF_GRAPH=<json>, WF_VIEWS=<dir>, WF_SCENE=<scene> (tests), WF_OBJECTS_DB=<dir>, WF_MAP_DB=<dir>."""
    if os.path.join(ROOT, 'tools') not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
    from objects import graph as OG, query as OQ, regions as OR, views as OV, store as OS, detect as OD
    g = OG.Graph()
    g.load(os.environ.get('WF_GRAPH') or os.path.join(OG.DEFAULT_DIR, 'Farm.json'))
    if not args or args[0] not in ('show', 'where', 'path', 'view-add', 'sync', 'map-seed', 'map-heatmap'):
        sys.exit(graph_cmd.__doc__)
    cmd, rest = args[0], args[1:]
    if cmd == 'sync':   # game log since the last sync mark -> node states (plant / water / unplant / can), then save
        import game
        gpath = os.environ.get('WF_GRAPH') or os.path.join(OG.DEFAULT_DIR, 'Farm.json')
        if game.core.WF is None:
            game.bind(sys.modules[__name__])
        mark, size = int(g.extra.get('_sync') or 0), log_mark()
        if mark > size:   # the log was rotated
            mark = 0
        lines = _unhash(log_since(mark)).splitlines()
        skipped = []
        changes = OG.apply_log(g, lines, at=g.state_value('Tara', 'at'), skipped=skipped)
        g.extra['_sync'] = size
        g.save(gpath)
        for nid, key, val, when in changes:
            print(f'{nid} {key}={val} @{when}')
        if skipped:
            print(f'skipped {len(skipped)} garden events (Tara.at unknown; vision re-anchors)')
        return print(f'synced {len(lines)} log lines since {mark}: {len(changes)} state changes')
    if cmd in ('map-seed', 'map-heatmap'):
        from PIL import Image
        from objects import map_vectors as OM
        map_store = OS.Store(os.environ.get('WF_MAP_DB') or OM.DEFAULT_ROOT)
        if cmd == 'map-seed':
            if len(rest) != 1:
                sys.exit(graph_cmd.__doc__)
            import nav
            image = Image.open(rest[0]).convert('RGB')
            rows = OM.seed(g, image, nav.map_load().get('places', {}), store=map_store,
                           source=os.path.basename(rest[0]))
            for row in rows:
                status = row['id'] or 'duplicate'
                print(f"{row['node']} -> {row['kind']} label={row['label']} {status}")
            return print(f'seeded {sum(r["id"] is not None for r in rows)}/{len(rows)} map examples')
        if len(rest) not in (2, 3):
            sys.exit(graph_cmd.__doc__)
        node_id, image_path = rest[:2]
        safe = re.sub(r'[^A-Za-z0-9_-]+', '-', node_id)
        output = rest[2] if len(rest) == 3 else os.path.join(SHOTS, f'map-heatmap-{safe}.png')
        image = Image.open(image_path).convert('RGB')
        match = OM.locate(g, node_id, image, store=map_store)
        if match is None:
            return print(f'{node_id}: no map representation')
        OM.render(image, match, output)
        return print(f'{node_id} -> {match.representation.node_id}/{match.representation.kind}: '
                     f'peak={match.point[0]},{match.point[1]} z={match.score:.2f} raw={match.raw:.3f} wrote {output}')

    def frame():
        from PIL import Image
        fp = os.environ.get('WF_FRAME')
        return Image.open(fp).convert('RGB') if fp else grab()

    def states(n):
        return ' '.join(f"{k}={v['value']}@{v['game_time']}({v['source']})" for k, v in n.state.items())

    def tree(id, depth):
        n = g.nodes[id]
        offers = ','.join(e['b'] for e in g.edges(id, 'offers'))
        line = '  ' * depth + id
        extra = [f'[{n.type}]']
        if states(n):
            extra.append(states(n))
        if offers:
            extra.append('offers ' + offers)
        print(line + '  ' + ' '.join(extra))
        for c in sorted(g.children(id), key=lambda c: (c.type == 'member', OG.order(c))):
            if c.id != id:
                tree(c.id, depth + 1)

    if cmd == 'show':
        top = rest[0] if rest else next(n.id for n in g.nodes.values() if n.type == 'region' and n.region is None)
        if top not in g.nodes:
            return print(f'no such node: {top}')
        return tree(top, 0)
    scene = os.environ.get('WF_SCENE') or current_scene()
    img = frame()
    st = OS.Store(os.environ.get('WF_OBJECTS_DB') or OS.DEFAULT_ROOT)
    vs = OV.ViewStore(os.environ.get('WF_VIEWS') or OV.DEFAULT_ROOT)
    if cmd == 'view-add':
        if len(rest) != 1 or rest[0] not in g.nodes or g.nodes[rest[0]].type != 'region':
            return print(f'unknown region: {rest[0] if rest else None} (regions: '
                         f'{", ".join(n.id for n in g.nodes.values() if n.type == "region")})')
        vid = vs.add(rest[0], img, os.environ.get('WF_FRAME') or 'live')
        return print(f'added view {vid} to {rest[0]}' if vid else f'duplicate view of {rest[0]}, skipped')
    # where / path: a view region is inside when (nearly) all members of one of its groups are detected with its thresholds
    near = vs.nearest(img)
    view, vdist = near if near else (None, None)
    probes = {}   # view region id -> detections with that region's thresholds

    def probe_of(rid):
        if rid not in probes:
            probes[rid] = OD.detect(img, st, kinds=OR.scope(g, rid), region=rid)
        return probes[rid]

    region, uncertain = OR.current_region(g, scene, probe_of, view)
    dets = probe_of(region)
    if cmd == 'where':
        vtxt = f'{view} {vdist:.3f}' if view else (f'none {vdist:.3f}' if vdist is not None else 'none')
        seen = ' '.join(f'{d.kind} z{d.dist:.1f} {d.point[0]},{d.point[1]}' for d in dets) or '-'
        return print(f'region {region}{" (uncertain)" if uncertain else ""} · scene {scene} · view {vtxt} · seen: {seen}')
    if not rest:
        sys.exit(graph_cmd.__doc__)
    state = {}
    for kv in rest[1:]:
        k, _, v = kv.partition('=')
        state[k] = None if v == 'None' else v
    q = OQ.Q(kind=rest[0]).where(**state)
    cands = q.run(g, region, visible={d.kind for d in dets})
    if not cands:
        return print(f'no node of kind {rest[0]}' + (f' with {state}' if state else ''))
    best = cands[0]
    steps = OQ.path(g, region, best)
    print(f'from {region}: {best.id} ({len(cands)} candidates)')
    for stp in steps:
        print(f'  {stp.action} {stp.node.id}')
    if steps:
        first = steps[0].node
        hit = next((d for d in dets if d.kind == first.kind), None)
        print(f'  click {hit.point[0]},{hit.point[1]}' if hit else f'  not visible ({first.kind})')


def eval_cmd(args):
    """wf eval [all] | pending | mark <id> hit|miss: hits and misses of predictions (spec 2026-10-30 §7.1)."""
    import evals
    if args and args[0] == 'mark':
        if len(args) != 3 or args[2] not in ('hit', 'miss'):
            sys.exit('usage: wf eval mark <id> hit|miss')
        evals.outcome(args[1], args[2], args[2] == 'hit')
        return print(f'marked {args[1]} {args[2]}')
    if args and args[0] == 'pending':
        rep = evals.report()
        return print('\n'.join(f'{k}: {c["pending"]} pending' for k, c in sorted(rep.items()) if c['pending'])
                     or 'nothing pending')
    since = None
    if not (args and args[0] == 'all'):
        ev = run_events()
        since = ev[0]['t'] if ev else None
    print(('since the start of the open run\n' if since else 'all predictions\n') + evals.format_report(evals.report(since)))


def game_cmd(kind, args):
    """`wf py "<code>"` / `wf call <module.fn> [args…]`: game functions (tools/game, L77), each proven by the game log
    and tracked as an action tree in the run log."""
    import game
    game.bind(sys.modules[__name__])
    game.track.LINES.clear()
    ns = game.namespace()
    res, err = None, None
    try:
        if kind == 'py':
            code = ' '.join(args)
            try:
                res = eval(compile(code, '<wf py>', 'eval'), ns)
            except SyntaxError:
                exec(compile(code, '<wf py>', 'exec'), ns)
        else:
            mod, _, fn = args[0].rpartition('.')
            f = getattr(getattr(game, mod), fn) if mod else ns[fn]
            res = f(*[int(a) if re.fullmatch(r'-?\d+', a) else a for a in args[1:]])
    except game.Failed as e:
        err = str(e)
    for line in game.track.LINES:
        print(line)
    if err:
        print(f'FAILED: {err}')
    elif res is not None:
        print('\n'.join(map(str, res)) if isinstance(res, list) else res)
    return 1 if err else 0


def run_report(path):
    ev = [json.loads(l) for l in open(path) if l.strip()]
    if not ev:
        return print('(empty run)')
    t0 = ev[0]['t']
    t1 = ev[-1].get('end', ev[-1]['t'])
    mmss = lambda t: time.strftime('%M:%S', time.gmtime(t - t0))
    calls = [e for e in ev if e['type'] == 'call']
    acts = [e for e in ev if e['type'] == 'activity']
    in_call = sum(e['end'] - e['start'] for e in calls)
    gaps = sum(max(0, b['start'] - a['end']) for a, b in zip(calls, calls[1:]))
    active = sum(e['end'] - e['start'] for e in acts if e.get('moved'))
    start = ev[0]
    end = next((e for e in reversed(ev) if e['type'] == 'end'), None)
    print(f"run {os.path.basename(path)}: {start.get('quest')}: {start.get('goal')}")
    print(f"result: {end['result'] + (' ' + end['text'] if end.get('text') else '') if end else 'OPEN'}")
    dur = lambda s: f'{int(s // 60)}:{int(s % 60):02d}'
    print(f'time {dur(t1 - t0)} · {len(calls)} ./wf calls · in calls {dur(in_call)} · '
          f'between calls (agent thinking) {dur(gaps)} · Tara active {dur(active)}')
    for k in ('attempt', 'issue', 'gap', 'decision'):
        n = sum(1 for e in ev if e['type'] == k)
        if n:
            print(f'{k}s: {n}', end='  ')
    nomove = sum(1 for e in acts if not e.get('moved'))
    print(f"NO MOVE/idle: {nomove}" if nomove else '')
    print('\ntimeline:')
    for e in ev:
        ty = e['type']
        if ty == 'call':
            continue  # summarised above; `--calls` level detail lives in the file
        if ty == 'activity':
            walk = e.get('what') == 'go'
            print(f"  {mmss(e['start'])} {'walk' if walk else 'action'} {e['end'] - e['start']:.1f}s "
                  f"{e.get('target', '')}{'' if e.get('moved') else (' NO MOVE' if walk else ' (idle, nothing to wait for)')}")
        elif ty == 'game':
            print(f"  {mmss(e['t'])}   · {e['line'][:110]}")
        else:
            print(f"  {mmss(e['t'])} {ty.upper()}: {e.get('text') or e.get('goal') or e.get('result', '')}")


class Tara:
    """Tara tracker (L52): follows her on screen with Apple Vision's object tracker and measures ACTIVITY = mean grey
    diff of her crop vs the previous frame. Scoped to her, so water, NPCs and camera pans elsewhere don't count.
    Verified live (Fri d145): idle 0.2-1 with single blips <= 4.5; walking 10-30; arrive/turn 6-12 for ~1.5 s.
    Seeds at the screen centre (the camera follows her; not at map edges, check `conf`)."""
    SEED = (920, 490, 1000, 690)   # 1920x1080 frame, Tara standing at the camera centre
    ACTIVE = 6.0                   # median of the last 3 activities above this = she is moving/acting (idle fidget <= ~5.5)

    def __init__(self, box=SEED):
        import Vision
        self.V = Vision
        x0, y0, x1, y1 = box
        self.obs = Vision.VNDetectedObjectObservation.observationWithBoundingBox_(
            ((x0 / FRAME_W, 1 - y1 / FRAME_H), ((x1 - x0) / FRAME_W, (y1 - y0) / FRAME_H)))
        self.seq = Vision.VNSequenceRequestHandler.alloc().init()
        self.box, self.conf, self.crop, self.acts = box, 1.0, None, []

    @staticmethod
    def _cg(img):
        Q = _quartz()
        raw = img.convert('RGBA').tobytes()
        prov = Q.CGDataProviderCreateWithData(None, raw, len(raw), None)
        return Q.CGImageCreate(img.width, img.height, 8, 32, img.width * 4, Q.CGColorSpaceCreateDeviceRGB(),
                               Q.kCGImageAlphaLast, prov, None, False, 0)

    def update(self, img):
        """Feed a 1920x1080 frame; returns this frame's activity."""
        from PIL import ImageChops, ImageStat
        small = img.resize((FRAME_W // 2, FRAME_H // 2))
        req = self.V.VNTrackObjectRequest.alloc().initWithDetectedObjectObservation_(self.obs)
        req.setTrackingLevel_(self.V.VNRequestTrackingLevelAccurate)
        self.seq.performRequests_onCGImage_error_([req], self._cg(small), None)
        if req.results():
            self.obs = req.results()[0]
        b = self.obs.boundingBox()
        self.conf = float(self.obs.confidence())
        self.box = (b.origin.x * FRAME_W, (1 - b.origin.y - b.size.height) * FRAME_H,
                    (b.origin.x + b.size.width) * FRAME_W, (1 - b.origin.y) * FRAME_H)
        import numpy as np
        g = np.asarray(small.convert('L'), dtype=np.float32)
        x0, y0, x1, y1 = (int(v / 2) for v in self.box)
        act = 0.0
        if self.crop is not None:
            # best match of the previous crop within +-R px: cancels box jitter and slow camera pans/zooms,
            # so only Tara's own pose change (walk cycle, swing) remains
            pc, R = self.crop, 3
            h, w = pc.shape
            act = min((float(np.abs(g[y0 + dy:y0 + dy + h, x0 + dx:x0 + dx + w] - pc).mean())
                       for dy in range(-R, R + 1) for dx in range(-R, R + 1)
                       if 0 <= y0 + dy and y0 + dy + h <= g.shape[0] and 0 <= x0 + dx and x0 + dx + w <= g.shape[1]),
                      default=0.0)
        self.crop = g[y0:y1, x0:x1].copy()
        self.acts.append(act)
        return act

    def debug_shot(self, img, path=None):
        """Save the frame with the tracked box (WF_DEBUG_MOVE) to check the tracker is on Tara."""
        from PIL import ImageDraw
        img = img.copy()
        ImageDraw.Draw(img).rectangle(self.box, outline=(255, 0, 255), width=5)
        img.resize((768, 432)).save(path or os.path.join(SHOT_DIR, 'tara.jpg'), quality=80)

    def active(self):
        last = sorted(self.acts[-3:])
        return len(last) == 3 and last[1] > self.ACTIVE


def wait_tara(tr=None, timeout=4.0, interval=0.1, start_within=1.0):
    """Wait until Tara's own activity stops (after a swing, pickup, walk). Returns (seconds, was_active).
    If she doesn't start acting within `start_within` s, returns early (nothing to wait for)."""
    tr = tr or Tara()
    t0, seen, t_act = time.time(), False, None
    tr.update(_frame())
    while time.time() - t0 < timeout:
        time.sleep(interval)
        tr.update(_frame())
        if tr.active():
            seen, t_act = True, t_act or time.time()
        elif seen or time.time() - t0 > start_within:
            break
    run_log('activity', what='action', start=t_act or t0, end=time.time(), moved=seen)
    return round(time.time() - t0, 2), seen


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


MENU_WORDS = ('game paused', 'resume game', 'settings', 'volume', 'return to menu', 'exit game', 'inventory',
              'select', 'buy', 'sell', 'not yet', 'remove', 'cancel', 'confirm',
              'пауза', 'продолжить игру', 'настройки', 'громкость', 'вернуться в меню', 'выйти из игры', 'инвентарь',
              'выбрать', 'купить', 'продать', 'удалить', 'отмена', 'подтвердить')


def menu_open(s):
    """Why clicking the world now is unsafe (a menu with buttons, dialogue, popup, cutscene), or None. Passive info
    cards (hive progress, wilted plant) have no buttons and don't block (S13 vs the bench B hive card)."""
    if s['mode'] in ('dialogue', 'popup', 'cutscene'):
        return s['mode']
    if s['mode'] != 'overlay':  # gameplay text (toasts, quest tracker) never blocks walking (review #5)
        return None
    texts = [t.split(') ', 1)[-1] for t in s.get('text', [])]
    hit = next((t for t in texts if any(w == t.strip().lower() or (len(w) >= 6 and w in t.lower())
                                        for w in MENU_WORDS)), None)
    return f'{s["mode"]}: {hit}' if hit else None


UNDER_HER = 1.5   # world units: a click this close to her that lands on an object uses it instead of walking


def object_under_her(x, y):
    """The entity a short click (x, y) would land on next to Tara, when the world is sure where she is; else None."""
    try:
        w = world()
        area, bx, bz, u = w.tara()
        c = calib_load(area) if area else None
        if not c or u > 1.0:
            return None
        import math
        import nav
        dx, dz = nav.screen_to_ground(c['H'], x, y)
        if math.hypot(dx, dz) > UNDER_HER:
            return None
        hit = w.entities(area=area, near=(bx + dx, bz + dz), within=1.0)
        return str(hit[0]) if hit else None
    except Exception:  # noqa: BLE001 (a missing world never blocks a click)
        return None


def go_to(x, y, timeout=15.0, interval=0.15):
    """Click-to-move (L49): left-click a ground point or object; the game pathfinds around fences/objects and Tara
    walks there (clicking an object stops her in front of it, bubble shown, no interaction). Waits until the camera
    stops moving. Returns None on arrival, or a NO MOVE / STILL MOVING message.
    Arrival = Tara's own activity stops (Tara tracker, L52), not the whole screen: water/NPCs don't delay it.
    Refuses to click while a menu/overlay is open (S13: walking clicks moved the user's audio sliders to 0)."""
    why = menu_open(state())
    if why:  # not "NO MOVE": callers must stop, not treat the spot as unwalkable (review #2)
        return f'MENU OPEN ({why}): close it first, never click through menus'
    under = object_under_her(x, y)
    if under:  # a short click onto the object she stands at is an interaction, not a step (world-shadow-2)
        return f'NO MOVE: the click would use {under} right under her (interaction, not a step)'
    tr = Tara()
    tr.update(_frame())
    mark = log_mark()
    click(int(x), int(y))
    t0, moved, t_act = time.time(), False, None
    while time.time() - t0 < timeout:
        time.sleep(interval)
        tr.update(_frame())
        if tr.active():
            moved, t_act = True, t_act or time.time()
        elif moved or time.time() - t0 > 1.5:
            break
    else:
        run_log('activity', what='go', target=f'go:{x}:{y}', start=t_act or t0, end=time.time(), moved=moved,
                note='still moving at timeout')
        note_click(x, y, None, mark)
        return f'STILL MOVING after {timeout:.0f}s (long path?): check with look'
    if os.environ.get('WF_DEBUG_MOVE'):
        print(f'go: tara {"moved" if moved else "idle"} in {time.time() - t0:.1f}s, conf {tr.conf:.2f}, '
              f'acts {" ".join(f"{a:.0f}" for a in tr.acts)}')
        tr.debug_shot(grab())
    run_log('activity', what='go', target=f'go:{x}:{y}', start=t_act or t0, end=time.time(), moved=moved)
    b = None if moved else find_bubble(grab())
    if not b:  # ALREADY THERE = no walk, nothing to learn
        note_click(x, y, moved, mark)
    if not moved:
        if b:  # she was already at the clicked object: its prompt is showing
            return f'ALREADY THERE (no walk needed; bubble@{b[0]},{b[1]})'
        return (f'NO MOVE go:{x}:{y}: not walkable (wall, furniture, water, off-map, or a menu is open). Click a '
                f'ground point nearer to Tara, or the doorway/floor edge to leave a building')
    return None


# ---------------------------------------------------------------- exact position + navigation learning loop (L62)
# The game autosaves when it goes to the background (only if something changed, e.g. Tara moved), and the save
# holds the engine's world position. pos() = background the game for a moment, read the fresh save, focus back.
# Learning loop (docs/superpowers/specs/2026-10-29-nav-learning-loop-design.md): go: clicks build a segment from the
# last reading; a checkpoint takes a reading and appends one fact (predicted vs measured) to tools/nav/facts.jsonl.
# Calibration (screen point -> world offset from Tara, one homography per area: the camera never rotates), place
# positions, blocked spots and edge status are derived from the facts by tools/nav.py. Storage: one folder per
# scene (each scene has its own coordinates, L65), see tools/nav.py.
POS_AWAY_APP = 'com.apple.finder'         # where focus goes for the save when no previous app is known
CALIB_MOVES = [(250, 0), (-250, 0), (0, 180), (0, -180), (200, 150), (-200, -150), (-200, 150), (200, -150)]
CALIB_MAX_ERR = 0.3                       # world units: a worse own fit is not saved (outdoors borrows the shared camera)
CALIB_SMALL = [(150, 100), (-150, -100), (0, 160), (0, -160), (-100, 120), (100, -120), (200, 40), (-200, -40)]  # indoors
SEG_FILE = os.path.join(SHOT_DIR, 'nav_segment.json')
SCENE_EVENT = r'ChangeScene|Spawning player|OnEnterBuilding|OnExitBuilding'
ARRIVE_UNITS = 0.8                        # world units: close enough to a go-world target
HOP_BOX = (200, 200, 1720, 980)           # clicks stay inside this screen box (HUD, edges)


def save_pos(path=None):
    """{'scene','x','y','z','day','hour','season','weather','count','age','path'} from a save (default: latest)."""
    path, s = read_save(path)
    p = s.get('currentPlayerPosition') or {}
    t = s['gameState']['time']
    sec = t['timeOfDay']['totalSeconds']
    wd = t.get('weatherDays') or ['?']
    event = (t.get('weatherEventStartTime') or {}).get('totalSeconds', -1) <= sec <= \
        (t.get('weatherEventEndTime') or {}).get('totalSeconds', -1)
    return {'scene': s.get('currentScene'), 'x': p.get('x', 0.0), 'y': p.get('y', 0.0), 'z': p.get('z', 0.0),
            'day': t['day'], 'hour': round(sec / 3600, 2), 'season': t.get('season'),
            'weather': f'w{wd[0]}' + ('-event' if event else ''),
            'count': s.get('saveCount'), 'age': time.time() - os.path.getmtime(path), 'path': path}


def save_stamp():
    """Monotonic stamp of the latest save (its saveCount): a save newer than an action has a higher one."""
    return read_save()[1].get('saveCount')


def pos(refocus=None, timeout=3.5):
    """Exact world position now: game to the background -> wait for the autosave -> read it -> focus back
    (refocus default: focus-mode front). 'fresh' False = no new save came (nothing changed since the last one,
    so the last save's position should still hold)."""
    global _PREV_APP
    before = latest_save()
    m0 = _mtime(before) if before else 0
    away = _PREV_APP if _PREV_APP and _PREV_APP != BUNDLE_ID else POS_AWAY_APP
    subprocess.run(['open', '-b', away], check=False)
    _PREV_APP = None
    t0, fresh = time.time(), False
    while time.time() - t0 < timeout:
        time.sleep(0.2)
        cur = latest_save()
        if cur and (cur != before or _mtime(cur) > m0):
            fresh = True
            time.sleep(0.3)  # let the write finish
            break
    for _ in range(5):
        try:
            p = save_pos()
            break
        except (ValueError, OSError, subprocess.CalledProcessError):  # caught mid-write
            time.sleep(0.3)
    else:
        raise RuntimeError('pos: latest save unreadable')
    if refocus if refocus is not None else keep_front():
        focus()
        _PREV_APP = away  # release_focus (background mode) gives focus back there at the end of the command
    p['fresh'] = fresh
    run_log('nav', what='pos', scene=p['scene'], x=round(p['x'], 2), z=round(p['z'], 2), fresh=fresh,
            secs=round(time.time() - t0, 1))
    return p


_ZOOM = [0.0, None, 1.0]   # (time, area, k): the measured zoom, cached briefly (one mask request ≈ 0.1–0.3 s)
ZOOM_TTL = 2.0
ZOOM_MIN = 0.08            # |k - 1| below this = the calibrated zoom


def current_zoom(scene):
    """The camera zoom now (L85): Tara's height on screen (foreground mask) over the area's reference height."""
    from world import zoom
    ref = zoom.ref_load(scene)
    if not ref:
        return 1.0
    if time.time() - _ZOOM[0] < ZOOM_TTL and _ZOOM[1] == scene:
        return _ZOOM[2]
    box = zoom.tara_mask(grab())
    area, x, z, u = world().tara()
    if not zoom.plausible(box, ref):  # she's hidden (behind the hives): the zoom measured nearest to her (day-walk)
        k = zoom.nearest(scene, x, z) if area == scene and u <= 3.0 else None
        return k if k else (_ZOOM[2] if _ZOOM[1] == scene else 1.0)
    k = zoom.gauge(box[3] - box[1], ref)
    _ZOOM[:] = [time.time(), scene, k]
    if area == scene and u <= 1.0 and abs(k - 1.0) > ZOOM_MIN:
        zoom.sample_add(scene, x, z, k, 'gauge')
    return k


def calib_load(scene):
    """The area's screen<->ground calibration at the current camera zoom (L85: the garden zooms in)."""
    import nav
    c = nav.calib_load(scene)
    if not c:
        return c
    try:
        from world import zoom
        k = current_zoom(scene)
        if abs(k - 1.0) > ZOOM_MIN:
            c = dict(c, H=zoom.apply(c['H'], k), zoom=round(k, 2))
    except (Exception, SystemExit):  # noqa: BLE001 (no zoom measurement = the calibrated zoom)
        pass
    return c


def _seg():
    try:
        return json.load(open(SEG_FILE))
    except (OSError, ValueError):
        return {'from': None, 'clicks': [], 'dirty': False}


def _seg_save(s):
    json.dump(s, open(SEG_FILE, 'w'))


def seg_dirty():
    """An input that may move Tara without a go: click (Space, act, click:, text:): no prediction for this segment."""
    s = _seg()
    if s['from'] and not s['dirty']:
        s['dirty'] = True
        _seg_save(s)


def seg_from():
    """(scene, x, z) of the last reading: the exit point when the scene has no calibration to dead-reckon with."""
    fr = _seg()['from']
    return (fr['scene'], fr['x'], fr['z']) if fr else None


def seg_estimate():
    """(scene, x, z) dead-reckoned from the last reading + this segment's clicks, or None when unknown."""
    import nav
    s = _seg()
    fr = s['from']
    c = fr and calib_load(fr['scene'])
    if not c or s['dirty']:
        return None
    x, z = nav.predict(c['H'], (fr['x'], fr['z']), s['clicks'])
    return fr['scene'], x, z


def refit(scene):
    """Recompute the area's calibration from all clean facts (auto, L62); cached in tools/nav/<area>/calib.json."""
    import nav
    fit = nav.fit_robust(nav.calib_samples(nav.load(), scene))
    if not fit or fit['err'] > CALIB_MAX_ERR:  # long pathfinding walks aren't straight: keep borrowing (D148 RuralBeach)
        return None
    fit['day'] = time.strftime('%Y-%m-%d')
    nav.calib_save(scene, fit)
    return fit


def place_print(img=None):
    """Feature print of the game view without the HUD (place fingerprint, phase 2)."""
    from PIL import Image
    img = (img or _frame()).crop((0, 180, FRAME_W, FRAME_H)).resize((640, 300), Image.BILINEAR)
    import numpy as np
    return np.asarray(_featureprint(img), np.float32)


def area():
    """'<scene>' outdoors, '<scene>/<building>' inside (from the log; the save only knows the scene)."""
    inside = current_scene()
    try:
        scene = save_pos()['scene']
    except Exception:  # save mid-write
        return inside
    return scene if inside in (None, scene) else f'{scene}/{inside}'


def img_locate(scene=None, img=None):
    """Image-only position guess: ({'pred': [x, z], 'd'}, vector) or (None, vector)."""
    import nav
    v = place_print(img)
    scene = scene or (_seg()['from'] or {}).get('scene') or area()
    return nav.img_predict(nav.load(), nav.prints_load(scene), scene, v), v


def fill_pin(p):
    """Continuous 'where am I' on the map layer (L67): if this reading's coverage cell has no map pin yet and Tara
    stands on a road (the pin snaps to roads), open the map once and return the pin; else None."""
    import nav
    if not nav.outdoor(p['scene']):
        return None
    if not is_frontmost():
        time.sleep(0.5)  # pos() just gave focus back
        if not is_frontmost():
            run_log('nav', what='fill-pin', skip='game not frontmost')
            return None
    try:
        facts = nav.load()
        fits = nav.map_load()['fits']
        cell = nav.cell_of(p['scene'], p['x'], p['z'], fits)
        pins = sum(1 for f in facts if f.get('scene') == p['scene'] and f.get('pin'))
        if cell is None and pins >= 3:
            run_log('nav', what='fill-pin', skip='no map fit yet, pins all on one line')
            return None
        if cell and 'L4' in nav.coverage(facts, fits, set()).get(cell, set()):
            return None  # this cell already has a pin
        frame = grab()
        if on_road(frame) < ON_ROAD:
            run_log('nav', what='fill-pin', skip='not on a road', cell=cell)
            return None
        img = map_snapshot()
        pin = img is not None and map_pin(img)
        run_log('nav', what='fill-pin', scene=p['scene'], cell=cell, pin=pin or None)
        return pin or None
    except Exception as e:  # never let coverage break a checkpoint
        run_log('nav', what='fill-pin', error=str(e))
        return None


def checkpoint(result=None, goal=None, edge=None, target=None, refocus=True, pin=None, extra=None, radius=None,
               fill=True):
    """Take a reading, append one fact (segment since the last reading: predicted vs measured), start a new
    segment. result None + target (x, z) = 'arrived' within ARRIVE_UNITS else 'short'; with a radius (a coarse map
    target) 'near' within it, never 'arrived', so a coarse point doesn't become the place. Before the reading, the
    place fingerprint predicts the position (checked by the reading, phase 2). Returns (reading, fact)."""
    import math
    import nav
    try:
        img_guess, vec = img_locate() if is_frontmost() else (None, None)
    except Exception:  # Vision hiccup: the reading still counts
        img_guess, vec = None, None
    try:
        world_sync()  # the world's prediction includes all evidence up to this reading
    except Exception:  # noqa: BLE001 (shadow mode never breaks play)
        pass
    p = pos(refocus=refocus)
    inside = current_scene()  # buildings share the outdoor scene's world coords (D147: House = Farm at y 1.1)
    if inside and inside != p['scene']:
        p['scene'] = f"{p['scene']}/{inside}"
    try:
        world().reading(p['scene'], p['x'], p['z'])  # eval world_belief, then the exact fix
    except Exception:  # noqa: BLE001
        pass
    stuck = None
    try:
        track_point(p['scene'], p['x'], p['z'])
    except Stuck as e:
        stuck = e  # record this reading's fact first, then abort
    s = _seg()
    fr = s['from']
    same = bool(fr) and fr['scene'] == p['scene']
    c = calib_load(p['scene'])
    pred = None
    if same and c and not s['dirty'] and s['clicks']:
        pred = [round(v, 3) for v in nav.predict(c['H'], (fr['x'], fr['z']), s['clicks'])]
    if result is None:
        left = target and math.dist((p['x'], p['z']), target)
        if target and radius:
            result = 'near' if left <= radius else 'short'
        elif target:
            result = 'arrived' if left <= ARRIVE_UNITS else 'short'
        else:
            result = 'moved' if s['clicks'] else 'idle'
    fact = {'t': round(time.time(), 1), 'day': p['day'], 'hour': p['hour'], 'season': p['season'],
            'weather': p['weather'], 'scene': p['scene'], 'from': [round(fr['x'], 3), round(fr['z'], 3)] if same else None,
            'to': [round(p['x'], 3), round(p['z'], 3)], 'pred': pred, 'clicks': s['clicks'], 'goal': goal,
            'edge': edge, 'result': result, 'dirty': s['dirty'] or not same}
    if s['clicks'] and not p['fresh']:
        fact['stale'] = True  # clicked, yet no new save: 'to' may be old
    if pin is None and fill and result not in ('scene', 'still'):
        pin = fill_pin(p)
    if pin and nav.outdoor(p['scene']):  # map pins only mean something outdoors (L4)
        fact['pin'] = [int(pin[0]), int(pin[1])]
    if img_guess and img_guess.get('pred') and (s['from'] or {}).get('scene', p['scene']) == p['scene']:
        fact['img'] = img_guess
    fact.update(extra or {})
    nav.append(fact)
    if pred:  # eval (M0): dead reckoning vs the reading
        try:
            import evals
            to = [p['x'], p['z']]
            evals.record('belief', 'position', pred, to, evals.belief_hit(pred, to),
                         {'scene': p['scene'], 'pred': pred, 'to': [round(v, 2) for v in to]})
        except Exception:  # noqa: BLE001
            pass
    if vec is not None and result != 'scene':  # a scene-change frame may still show the loading screen
        nav.print_append(p['scene'], fact['t'], vec)
    if fact.get('pin'):
        nav.map_refit(nav.load())
    _seg_save({'from': {k: p[k] for k in ('scene', 'x', 'z', 'day', 'hour')}, 'clicks': [], 'dirty': False})
    if len(fact['clicks']) == 1 and fact['from'] and not fact['dirty'] and not fact.get('stale'):
        refit(p['scene'])
    if stuck:
        raise stuck
    return p, fact


def note_click(x, y, moved, mark):
    """Called by go_to after every click: grow the segment, record NO MOVE targets (no reading: she didn't move),
    checkpoint when the click changed scene (spawn/door point = a free anchor) or the walk got stuck."""
    import nav
    MOVES[0] += 1
    try:
        world_sync()  # evidence from before/at this click first, in order (review C2)
    except Exception:  # noqa: BLE001
        pass
    if moved is not None:  # eval (M0): did the click move her
        try:
            import evals
            evals.record('click', 'moves her', True, bool(moved), bool(moved), {'click': [x, y]})
        except Exception:  # noqa: BLE001
            pass
    try:  # objects the log names with a position = obstacles for the planner (L79)
        fr0 = _seg()['from'] or {}
        nav.objects_learn(fr0.get('scene'), nav.objects_from_log(_unhash(log_since(mark))))
    except Exception:  # noqa: BLE001
        pass
    if moved is None:  # STILL MOVING at timeout
        _seg_add(x, y)
        checkpoint('still')
        return
    if not moved:
        est = seg_estimate()
        fr = _seg()['from']
        if fr:
            target = None
            pf = nav.log_pathfail(_unhash(log_since(mark)))
            if pf:  # the game says exactly where the refused click landed (L73)
                target = [round(v, 3) for v in pf[1]]
            elif est:
                c = calib_load(est[0])
                dx, dz = nav.screen_to_ground(c['H'], x, y)
                target = [round(est[1] + dx, 3), round(est[2] + dz, 3)]
            hour = game_hour(_frame())
            nav.append({'t': round(time.time(), 1), 'day': fr['day'], 'hour': round(hour, 2) if hour else fr['hour'],
                        'scene': fr['scene'], 'clicks': [[x, y]], 'target': target, 'result': 'no_move'})
            if est:  # a refused click is a move without progress (S12: 52 of 60 clicks hit hives, unnoticed)
                track_point(*est)
        return
    _seg_add(x, y)
    try:  # shadow world: our click predicts her move
        est0 = seg_estimate()
        c0 = calib_load(est0[0]) if est0 else None
        if c0 and moved:
            world().clicked(*nav.screen_to_ground(c0['H'], x, y))
            world_sync()  # what the walk itself logged (actions at the target) comes after the click
    except Exception:  # noqa: BLE001
        pass
    if not scene_change(mark, seg_estimate()):  # an exit is stored only when traced, never guessed
        lp = nav.log_position(_unhash(log_since(mark)))
        if lp:
            log_reading(*lp)


def log_reading(scene, x, z):
    """A walk stopped against a barrier and the log gave her exact position: a free checkpoint (no save needed).
    The fact ('stuck') marks a wall spot; the segment restarts there."""
    import nav
    s = _seg()
    fr = s['from']
    if not fr or (scene and fr['scene'].split('/')[0] != scene):
        return None
    c = calib_load(fr['scene'])
    pred = [round(v, 3) for v in nav.predict(c['H'], (fr['x'], fr['z']), s['clicks'])] if c and not s['dirty'] else None
    fact = {'t': round(time.time(), 1), 'day': fr['day'], 'hour': fr['hour'], 'scene': fr['scene'],
            'from': [round(fr['x'], 3), round(fr['z'], 3)], 'to': [round(x, 3), round(z, 3)], 'pred': pred,
            'clicks': s['clicks'], 'result': 'stuck', 'src': 'log', 'dirty': s['dirty']}
    nav.append(fact)
    _seg_save({'from': dict(fr, x=x, z=z, src='log'), 'clicks': [], 'dirty': False})
    run_log('nav', what='log-reading', scene=fr['scene'], x=x, z=z)
    return fact


def _stuck():
    """True when the last click ended at a wall (log_reading restarted the segment there)."""
    s = _seg()
    return bool(s['from']) and s['from'].get('src') == 'log' and not s['clicks']


def scene_anchor(txt):
    """Anchor name from scene events in log text: last `Spawning player at X` -> X, `OnEnterBuilding B` -> B:in,
    `OnExitBuilding B` -> B:out; None when there is none."""
    name = None
    for m in re.finditer(r'Spawning player at ([\w/]+)|OnEnterBuilding (\w+)|OnExitBuilding (\w+)', _unhash(txt)):
        name = m.group(1) or (m.group(2) and m.group(2) + ':in') or (m.group(3) + ':out')
    return name


def scene_change(mark, exit_est):
    """If the log shows a scene event since mark: checkpoint at the new anchor; the fact keeps where in the old
    scene the move was aimed (exit_est = (scene, x, z) or None) -> a graph link exit -> anchor."""
    txt = _unhash(log_since(mark))
    if re.search(r'WaypointTrigger|scene_change me=Player', txt) and not re.search(SCENE_EVENT, txt):
        for _ in range(30):  # a scene link was hit: the load takes up to ~10 s before ChangeScene is logged (L67)
            time.sleep(0.5)
            txt = _unhash(log_since(mark))
            if re.search(SCENE_EVENT, txt):
                break
    if not re.search(SCENE_EVENT, txt):
        return False
    time.sleep(1.5)  # scene load
    extra = {'from_scene': exit_est[0], 'exit': [round(exit_est[1], 3), round(exit_est[2], 3)]} if exit_est else None
    checkpoint('scene', goal=scene_anchor(log_since(mark)), extra=extra)
    return True


def _seg_add(x, y):
    s = _seg()
    s['clicks'].append([int(x), int(y)])
    _seg_save(s)


def go_world(gx, gz, goal=None, max_rounds=2, radius=None, read=True):
    """Walk to a world point (x, z) in the current scene by calibrated clicks: dead-reckon hops (clamped to the
    screen box, around blocked spots), then one reading; a corrective round if still off. ≤ max_rounds readings.
    radius = a coarse target (map node): within it = NEAR, done. read=False: no reading (a proven trail point on
    the way, L73): PASSED. Every click refused before she moved = BLOCKED at once, no reading."""
    import math
    import nav
    est = seg_estimate() or start_estimate()
    scene, x, z = est
    c = calib_load(scene)
    if not c:
        return f'go-world: no calibration for {scene}: run `wf calib` on open ground there first'
    for rnd in range(max_rounds):
        blocked = nav.blocks(nav.load(), scene, _seg()['from'] or {})
        moved_any = False
        for _ in range(12):
            dx, dz = gx - x, gz - z
            if math.hypot(dx, dz) < ARRIVE_UNITS / 2:
                break
            hop = None
            for rot in (0, 35, -35, 70, -70):
                a = math.radians(rot)
                rx, rz = dx * math.cos(a) - dz * math.sin(a), dx * math.sin(a) + dz * math.cos(a)
                k = 1.0
                while k > 0.05:
                    sx, sy = nav.ground_to_screen(c['H'], rx * k, rz * k)
                    if HOP_BOX[0] <= sx <= HOP_BOX[2] and HOP_BOX[1] <= sy <= HOP_BOX[3]:
                        break
                    k *= 0.8
                if not any(math.dist((x + rx * k, z + rz * k), b) < ARRIVE_UNITS for b in blocked):
                    hop = (sx, sy, rx * k, rz * k)
                    break
            if not hop:
                return f'go-world: every direction toward ({gx:.1f}, {gz:.1f}) is blocked near ({x:.1f}, {z:.1f})'
            sx, sy, hx, hz = hop
            msg = go_to(sx, sy)
            if msg and msg.startswith('MENU OPEN'):
                return msg
            tries = 0
            while msg and msg.startswith('NO MOVE') and tries < 2:  # half the hop
                hx, hz, tries = hx / 2, hz / 2, tries + 1
                sx, sy = nav.ground_to_screen(c['H'], hx, hz)
                msg = go_to(sx, sy)
            if msg and msg.startswith('NO MOVE'):
                if not moved_any:  # she didn't move at all: no reading needed to know it (L73)
                    track_point(scene, x, z)
                    return f'BLOCKED toward ({gx:.1f}, {gz:.1f}) at ({x:.1f}, {z:.1f}) in {scene}: every click refused'
                break
            moved_any = True
            if _seg()['clicks'] == [] and _seg()['from'] and _seg()['from']['scene'] != scene:
                return f'go-world: changed scene to {_seg()["from"]["scene"]} on the way'
            if _stuck():  # stopped against a wall: exact position from the log; step around it
                x, z = _seg()['from']['x'], _seg()['from']['z']
                d = detour(c, x, z, gx, gz)
                if not d:
                    return f'go-world: wall at ({x:.1f}, {z:.1f}), no way around it found (tried 4 sideways hops)'
                x, z = d
                continue
            x, z = x + hx, z + hz
        if not read:
            return f'PASSED ({gx:.1f}, {gz:.1f}) in {scene} (estimate, no reading)'
        p, f = checkpoint(goal=goal, target=(gx, gz), radius=radius)
        if p['scene'] != scene:
            return f'go-world: now in {p["scene"]}, not {scene}'
        left = math.dist((p['x'], p['z']), (gx, gz))
        if f['result'] == 'arrived':
            return f'ARRIVED ({gx:.1f}, {gz:.1f}) in {scene}: {left:.2f} units off, {rnd + 1} reading(s)'
        if f['result'] == 'near':
            return (f'NEAR ({gx:.1f}, {gz:.1f}) in {scene}: {left:.2f} units off (coarse ±{radius:.1f}), '
                    f'{rnd + 1} reading(s)')
        x, z = p['x'], p['z']
    return f'SHORT of ({gx:.1f}, {gz:.1f}): {left:.2f} units off at ({x:.1f}, {z:.1f}) after {max_rounds} readings'


DETOUR_UNITS = 3.0


def detour(c, x, z, gx, gz):
    """Stopped against a wall at (x, z) on the way to (gx, gz): try sideways hops (70°, then 110° off the goal
    direction, both sides) until one walks freely; its end becomes a graph node ('via' fact, exact reading), so the
    next plan goes around the wall by itself (L67). Returns the new (x, z) or None."""
    import math
    import nav
    dx, dz = gx - x, gz - z
    L = math.hypot(dx, dz) or 1
    for rot in (70, -70, 110, -110):
        a = math.radians(rot)
        rx, rz = (dx * math.cos(a) - dz * math.sin(a)) / L * DETOUR_UNITS, (dx * math.sin(a) + dz * math.cos(a)) / L * DETOUR_UNITS
        msg = go_to(*nav.ground_to_screen(c['H'], rx, rz))
        if msg and msg.startswith('MENU OPEN'):
            return None
        if msg and msg.startswith('NO MOVE'):
            continue
        if _stuck():  # this side is walled too
            x, z = _seg()['from']['x'], _seg()['from']['z']
            continue
        p, _ = checkpoint('via')
        run_log('nav', what='detour', rot=rot, x=round(p['x'], 2), z=round(p['z'], 2))
        return p['x'], p['z']
    return None


def start_estimate():
    """Position when the segment can't tell (after a scene change, Space, a daemon restart): a trusted place
    fingerprint match (phase 2), else one reading."""
    import nav
    guess, _ = img_locate()
    scene = (_seg()['from'] or {}).get('scene') or area()
    if guess and nav.img_trusted(nav.load(), scene, guess['d']):
        s = _seg()
        s.update({'from': {'scene': scene, 'x': guess['pred'][0], 'z': guess['pred'][1], 'day': (s['from'] or {}).get('day', 0),
                           'hour': (s['from'] or {}).get('hour', 0)}, 'clicks': [], 'dirty': False})
        _seg_save(s)
        run_log('nav', what='img-start', scene=scene, pred=guess['pred'], d=guess['d'])
        return scene, guess['pred'][0], guess['pred'][1]
    p, _ = checkpoint()
    return p['scene'], p['x'], p['z']


SIDESTEP = 3.0   # world units: candidate first steps around her when the way is blocked right beside her


def goto_point(scene, x, z, r=None):
    """goto_point_old, scored against the shadow world's route (eval `world_route`: the world said a way exists and
    the walk arrived, or neither = hit)."""
    try:
        import nav
        w = world()
        w.facts = nav.load()  # refused clicks and walls learned since the daemon started (review I7)
        fr = _seg()['from'] or {}
        status, _ = w.route_status((scene, x, z), reach=r or 0.0,
                                   now_hour=nav.game_hours(fr) if fr.get('hour') is not None else float('inf'))
        predicted = None if status == 'unknown' else status == 'way'
    except Exception:  # noqa: BLE001
        predicted = None
    msg = goto_point_old(scene, x, z, r)
    if predicted is not None:
        try:
            import evals
            arrived = msg.startswith(('ARRIVED', 'NEAR'))
            evals.record('world_route', 'a way exists', predicted, arrived, predicted == arrived,
                         {'goal': [scene, round(x, 2), round(z, 2)], 'msg': msg[:80]})
        except Exception:  # noqa: BLE001
            pass
    return msg


def goto_point_old(scene, x, z, r=None):
    """Walk to a world point in `scene` through the world graph (doors, proven trail, back links; L79): a temporary
    node at the point, planned like a place. A short straight hop in the same area goes directly. r = arrival
    radius (an object only needs to be within reach)."""
    import math
    import nav
    start = seg_estimate() or start_estimate()
    c = calib_load(scene) if start and start[0] == scene else None
    if c:  # on screen: click the target itself, the game pathfinds around everything (L49, L81)
        sx, sy = nav.ground_to_screen(c['H'], x - start[1], z - start[2])
        if HOP_BOX[0] <= sx <= HOP_BOX[2] and HOP_BOX[1] <= sy <= HOP_BOX[3]:
            msg = go_to(sx, sy)
            if msg and msg.startswith('MENU OPEN'):
                return msg
            if not (msg and msg.startswith('NO MOVE')):
                p, f = checkpoint(target=(x, z), radius=r)
                left = math.dist((p['x'], p['z']), (x, z))
                if f['result'] in ('arrived', 'near') or (r and left <= r):
                    return f'NEAR ({x:.1f}, {z:.1f}) in {scene}: {left:.2f} units off (clicked on screen, game pathfinding)'
                start = (p['scene'], p['x'], p['z'])
    facts = nav.load()
    ws = nav.walls(facts)
    d = math.dist(start[1:], (x, z)) if start and start[0] == scene else None
    if d is not None and d <= nav.STRAIGHT_OK and nav.walk_cost(start[1:], (x, z), ws.get(scene, ())) < d + 1:
        return go_world(x, z, max_rounds=2, radius=r)  # a short, clear hop
    ns = nav.nodes(facts, places())
    key = f'{scene}:@point'
    ns[key] = {'scene': scene, 'name': '@point', 'x': x, 'z': z, 'src': 'point', 'r': r}
    if start:  # side-steps around her: the way round an object right beside her (L79)
        for i in range(8):
            a = math.radians(45 * i)
            sx, sz = start[1] + SIDESTEP * math.cos(a), start[2] + SIDESTEP * math.sin(a)
            if nav.walk_cost(start[1:], (sx, sz), ws.get(start[0], ())) < SIDESTEP + 1:
                ns[f'{start[0]}:@side{i}'] = {'scene': start[0], 'name': f'@side{i}', 'x': sx, 'z': sz, 'src': 'point'}
    steps = nav.plan(ns, nav.edges_graph(facts, ns, list(edges()), _seg()['from']), start, key, ws)
    if not steps or any(kind == 'walk' and not calib_load(ns[k]['scene']) for kind, k in steps):
        return go_world(x, z, max_rounds=2, radius=r)  # no graph way: the straight line is all we have
    return run_route(f'({x:.1f}, {z:.1f}) in {scene}', [(kind, k, ns[k]) for kind, k in steps])


def graph_route(place):
    """World-graph plan to a place/anchor name (phase 2): [(kind, node_key, node)] or None when the graph can't
    get there (unknown name, or a walk through a scene without calibration)."""
    import nav
    facts = nav.load()
    ns = nav.nodes(facts, places())
    if not any(k == place or n['name'] == place for k, n in ns.items()):
        return None
    start = seg_estimate() or start_estimate()
    steps = nav.plan(ns, nav.edges_graph(facts, ns, list(edges()), _seg()['from']), start, place, nav.walls(facts))
    if not steps or any(kind == 'walk' and not calib_load(ns[k]['scene']) for kind, k in steps):
        return None
    return [(kind, k, ns[k]) for kind, k in steps]


def run_route(place, steps):
    """Execute a world-graph plan: walk = go_world; link = already crossed, or push past the exit; replay =
    edge_replay. Every step ends at a checkpoint, so each run teaches the graph."""
    import math
    import nav
    starts = []  # where each step began (the push past an exit keeps the walk's direction)
    unread = 0   # proven trail points passed without a reading
    track = [seg_estimate()]  # her position after each move: 3 moves without progress = stuck (L75)
    for i, (kind, k, n) in enumerate(steps):
        fr0 = _seg()['from'] or {}
        starts.append((fr0.get('x', 0), fr0.get('z', 0)))
        here = fr0.get('scene')
        if kind == 'walk':
            if here != n['scene']:
                return f'ROUTE {place}: expected to be in {n["scene"]}, now in {here} (step {i + 1}/{len(steps)})'
            goal = n['name'] if n['src'] in ('arrived', 'map') else None
            tgt = nav.target_of(n)
            if not tgt:  # an exit we crossed once but couldn't trace: no position, no direction
                return (f'ROUTE {place}: step {i + 1}/{len(steps)} needs exploring: the way to {n["to"]} from '
                        f'{n["scene"]} has no known position; find it by looking, the crossing then records it')
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            read = not (n['src'] == 'trail' and unread < TRAIL_UNREAD and nxt and nxt[0] == 'walk'
                        and nxt[2]['scene'] == n['scene'])
            r = n.get('r') or (WAYPOINT_NEAR if n['src'] in ('trail', 'via') else None)  # waypoints: near is enough
            msg = go_world(*tgt, goal=goal, radius=r, read=read)
            unread = 0 if read else unread + 1
            crossed = (_seg()['from'] or {}).get('scene') != n['scene']
            d = (tgt[0] - starts[i][0], tgt[1] - starts[i][1])
            why = f'step {i + 1}/{len(steps)} walk to {k}: {msg}'
            if msg.startswith('BLOCKED'):
                mark_blocked(place, d, why)  # a wall that way; one failed step alone isn't "stuck" (L75)
            track.append(seg_estimate())
            if nav.no_progress(track) or (i + 1 == len(steps) and not msg.startswith(('ARRIVED', 'NEAR'))
                                          and not crossed):
                ahead = [nav.target_of(m) for kd, _, m in steps[i:] if kd == 'walk' and m['scene'] == n['scene']
                         and nav.target_of(m)]
                if nav.no_progress(track):
                    why = f'{nav.STUCK_MOVES} moves without progress; last: {why}'
                return stuck_vision(place, d, why, ahead)
        elif kind == 'link':
            if here != n['scene']:  # still before the exit: push on in the same direction
                c = calib_load(here)
                ex = steps[i - 1][2] if i else None
                fr = _seg()['from']
                if ex and here.split('/')[0] == n['scene'].split('/')[0]:  # building door: same coords (L64),
                    d = (n['x'] - ex['x'], n['z'] - ex['z'])                # so push toward the other side's anchor
                else:
                    d = (ex['x'] - starts[i - 1][0], ex['z'] - starts[i - 1][1]) if ex else (0, 1)
                L = math.hypot(*d) or 1
                for _ in range(2):
                    go_to(*nav.ground_to_screen(c['H'], d[0] / L * 1.5, d[1] / L * 1.5))
                    if (_seg()['from'] or {}).get('scene') == n['scene']:
                        break
                if (_seg()['from'] or {}).get('scene') != n['scene']:
                    return f'ROUTE {place}: exit to {n["scene"]} did not change scene (at {fr and (fr["x"], fr["z"])})'
        elif kind == 'replay':
            msg = edge_replay(steps[i - 1][2]['name'] if i else '', n['name'])
            if not msg.startswith('ARRIVED'):
                return f'ROUTE {place}: replay to {k}: {msg}'
    run_log('nav', what='route', place=place, steps=len(steps))
    via = ' → '.join(f'{kind}:{k}' for kind, k, _ in steps)
    if steps[-1][2].get('r'):  # a coarse map node (L4): the place is somewhere around here
        return (f'NEAR {place} (map point ±{steps[-1][2]["r"]:.1f} units) via world graph ({via}): look, click the '
                f'last bit, then `wf pos --learn {place}` so the next trip is exact')
    return f'ARRIVED {place} via world graph ({via})'


TRAIL_UNREAD = 2  # proven trail points walked through on dead reckoning before the next reading
WAYPOINT_NEAR = 3.0  # world units: a trail/detour point on the way counts as reached this close


def stuck_vision(place, d, why, ahead=()):
    """Stuck (L73): mark the way she couldn't go as a wall (the next plan avoids it), then ask the model for the
    next step toward the goal (ask_step); `wf teach step X:Y` walks there and stores the walk as proven."""
    mark_blocked(place, d, why)
    run_log('nav', what='stuck', place=place, why=why)
    return ask_step(place, d, why, ahead)


def mark_blocked(place, d, why):
    """She couldn't go direction d (world) from her last reading: a 'blocked' fact = a wall the planner avoids."""
    import math
    import nav
    fr = _seg()['from'] or {}
    L = math.hypot(*d) or 1.0
    if fr.get('x') is not None and math.hypot(*d) > 0:
        nav.append({'t': round(time.time(), 1), 'day': fr.get('day'), 'hour': fr.get('hour'), 'scene': fr['scene'],
                    'from': [round(fr['x'], 3), round(fr['z'], 3)],
                    'to': [round(fr['x'] + d[0] / L, 3), round(fr['z'] + d[1] / L, 3)], 'result': 'blocked',
                    'goal': place, 'why': why})


ASK_SCALE = 0.5  # the question image is the frame at half size: game coords = image px x 2


def task_text():
    """The current task for a vision question: the open run's name and its last attempt/step note."""
    p = run_path()
    if not p:
        return None
    last = None
    for e in run_events(p):
        if e.get('type') == 'attempt':
            last = e.get('text')
    steps, states = plan_state()
    cur = next((f'step {st["n"]}: {st["title"]}' for st in states if st['state'] == 'start'), None)
    name = os.path.basename(run_dir()) if run_dir() else os.path.splitext(os.path.basename(p))[0]
    last = cur or last
    return f'{name}' + (f' (current step: {last})' if last else '')


def ask_step(place, d, why, ahead=()):
    """The vision question when code can't make the next step toward a goal (L74): the goal, the route ahead and
    what the 4 layers know, drawn on the screenshot (blue roads, green proven walks, red walls/refused clicks,
    yellow planned direction and numbered route points, coordinate ticks). The model answers the next click:
    `wf teach step X:Y`. ahead = [(x, z)] next route points in this area (world)."""
    import math
    import nav
    from PIL import Image, ImageDraw
    img = grab()
    img.save(ASK_FRAME)
    est = seg_estimate() or start_estimate()
    scene, ex, ez = est if est else (None, 0.0, 0.0)
    c = calib_load(scene) if scene else None
    fx, fy = tara_feet(img)
    base = img.convert('RGBA')
    over = Image.new('RGBA', base.size, (0, 0, 0, 0))
    o = ImageDraw.Draw(over)
    g = screen_road(img)  # L2 screen: road cells
    for y, x in zip(*g.nonzero()):
        o.rectangle((x * ROAD_CELL, y * ROAD_CELL, (x + 1) * ROAD_CELL - 1, (y + 1) * ROAD_CELL - 1),
                    fill=(40, 120, 255, 70))
    shown = {'trail': 0, 'walls': 0}
    if c:
        def scr(x, z):
            return nav.ground_to_screen(c['H'], x - ex, z - ez)

        def on(p):
            return 0 <= p[0] < img.width and 0 <= p[1] < img.height
        facts = nav.load()
        for (s0, x, z), ends in nav.trail(facts).items():  # L3: proven walks
            if s0 != scene or math.dist((x, z), (ex, ez)) > 30:
                continue
            a = scr(x, z)
            for bx, bz in ends:
                o.line((a, scr(bx, bz)), fill=(40, 220, 80, 200), width=4)
            if on(a):
                o.ellipse((a[0] - 9, a[1] - 9, a[0] + 9, a[1] + 9), fill=(40, 220, 80, 230))
                shown['trail'] += 1
        bad = [w[:2] for w in nav.walls(facts).get(scene, [])] + nav.blocks(facts, scene, _seg()['from'] or {})
        for x, z in bad:  # walls and refused clicks
            a = scr(x, z)
            if on(a) and math.dist((x, z), (ex, ez)) < 30:
                o.line((a[0] - 14, a[1] - 14, a[0] + 14, a[1] + 14), fill=(255, 40, 40, 255), width=6)
                o.line((a[0] - 14, a[1] + 14, a[0] + 14, a[1] - 14), fill=(255, 40, 40, 255), width=6)
                shown['walls'] += 1
        tip = nav.ground_to_screen(c['H'], d[0] / (math.hypot(*d) or 1) * 4, d[1] / (math.hypot(*d) or 1) * 4)
        for i, (x, z) in enumerate(ahead[:5]):  # the route ahead, numbered (may be off screen)
            a = scr(x, z)
            if on(a):
                o.ellipse((a[0] - 16, a[1] - 16, a[0] + 16, a[1] + 16), fill=(255, 220, 0, 230))
                o.text((a[0] - 4, a[1] - 7), str(i + 1), fill=(0, 0, 0, 255))
    else:
        ang = math.atan2(-d[1], d[0])
        tip = (fx + 300 * math.cos(ang), fy - 300 * math.sin(ang))
    o.line(((fx, fy), tip), fill=(255, 220, 0, 255), width=8)  # planned direction
    o.ellipse((tip[0] - 12, tip[1] - 12, tip[0] + 12, tip[1] + 12), fill=(255, 220, 0, 255))
    o.ellipse((fx - 30, fy - 30, fx + 30, fy + 30), outline=(255, 0, 255, 255), width=6)  # Tara
    for gx in range(240, img.width, 240):  # coordinate ticks in game coords
        o.line((gx, 0, gx, img.height), fill=(255, 255, 255, 60), width=2)
        o.text((gx + 4, 4), str(gx), fill=(255, 255, 255, 255))
    for gy in range(180, img.height, 180):
        o.line((0, gy, img.width, gy), fill=(255, 255, 255, 60), width=2)
        o.text((4, gy + 4), str(gy), fill=(255, 255, 255, 255))
    small = Image.alpha_composite(base, over).convert('RGB').resize(
        (round(img.width * ASK_SCALE), round(img.height * ASK_SCALE)))
    small.save(ASK_IMG, quality=85)
    ang = math.atan2(-d[1], d[0])
    ns = nav.nodes(nav.load(), places())
    gn = next((n for k, n in ns.items() if k == place or n['name'] == place), None)
    if gn and gn['scene'] == scene and gn.get('x') is not None:
        where = (f'{math.dist((gn["x"], gn["z"]), (ex, ez)):.0f} world units '
                 f'{compass(math.atan2(-(gn["z"] - ez), gn["x"] - ex))} of her here in {scene}')
    elif gn:
        where = f'in {gn["scene"]}; the route leaves {scene} {compass(ang)}'
    else:
        where = f'{compass(ang)} (map direction)'
    task = task_text()
    q = (f'GOAL: walk Tara to {place} ({where})' + (f', for the task {task}' if task else '') + '. '
         f'She is at ({ex:.1f}, {ez:.1f}) in {scene}, magenta ring, feet at {fx}:{fy}; code cannot make the next step '
         f'({why}). Drawn from what we know: yellow arrow = planned direction, yellow numbered dots = next route points '
         f'(1 = next), blue = road, green dots/lines = where she has walked before ({shown["trail"]} points), '
         f'red X = walls / refused clicks ({shown["walls"]}). What is the NEXT CLICK toward the goal? Open walkable '
         f'ground she can reach from where she stands, within ~400 px of her; follow roads and green where they lead '
         f'toward the goal; if she is enclosed, the way out toward a road that leads there. Never fences, rails, '
         f'hedges, rocks, water, a fenced plot, or a red X. Estimate game coordinates from the white tick labels '
         f'(image px x 2).')
    json.dump({'kind': 'step', 'question': q, 'place': place, 'feet': [fx, fy]}, open(ASK_CTX, 'w'))
    run_log('vision', what='ask', kind='step', question=q)
    return f'NEED_VISION step: {q}\n  look: {ASK_IMG}\n  answer: ./wf teach step X:Y   e.g. ./wf teach step {fx - 300}:{fy + 120}'


def calibrate(moves=CALIB_MOVES):
    """Walk short hops around Tara on open ground; each hop is checkpointed, so it becomes a clean one-click fact;
    then refit the scene from all its facts."""
    p0, _ = checkpoint()
    scene = p0['scene']
    for dx, dy in moves:
        feet = tara_feet(grab())
        msg = go_to(feet[0] + dx, feet[1] + dy)
        if msg:
            print(f'  hop {dx:+d},{dy:+d}: {msg.split(":")[0]}, skipped')
            continue
        p, f = checkpoint()
        if p['scene'] != scene:
            return f'calib: scene changed {scene} -> {p["scene"]}: walk back onto open ground and retry'
        d = (f['to'][0] - f['from'][0], f['to'][1] - f['from'][1]) if f['from'] else None
        print(f'  hop click {f["clicks"]} -> world d={d and tuple(round(v, 2) for v in d)}'
              + (' (stale save)' if f.get('stale') else ''))
    fit = refit(scene)
    if not fit:
        return f'calib: fewer than 5 clean samples in {scene}: find open ground (no fences/water) and retry'
    import nav
    tx, ty = fit['tara']
    ux = abs(nav.screen_to_ground(fit['H'], tx + 100, ty)[0])
    uz_up, uz_dn = (abs(nav.screen_to_ground(fit['H'], tx, ty + dy)[1]) for dy in (-100, 100))
    return (f'CALIBRATED {scene}: kept {fit["kept"]}/{fit["n"]} samples, median error {fit["err"]} world units | Tara '
            f'at screen {tx},{ty} | per 100 px: x {ux:.2f}, z up {uz_up:.2f} / down {uz_dn:.2f}')


def _xz(n):
    if n.get('x') is not None:
        return f'({n["x"]:.1f}, {n["z"]:.1f})'
    return f'(no position; aim {n["aim"][0]:.1f}, {n["aim"][1]:.1f})' if n.get('aim') else '(no position: explore)'


def learn_nav():
    import nav
    facts = nav.load()
    calib = nav.calib_all(facts)
    now = _seg()['from'] or (facts[-1] if facts else {})
    ns = nav.nodes(facts, places())
    es = nav.edges_graph(facts, ns, list(edges()), now)
    kinds = {}
    for *_, kind in es:
        kinds[kind] = kinds.get(kind, 0) + 1
    srcs = {}
    for n in ns.values():
        srcs[n['src']] = srcs.get(n['src'], 0) + 1
    graph = (f'graph: {len(ns)} nodes (' + ', '.join(f'{k} {v}' for k, v in sorted(srcs.items())) + '), edges ('
             + ', '.join(f'{k} {v}' for k, v in sorted(kinds.items())) + ')\n  '
             + '\n  '.join(f'{k} {_xz(n)} {n["src"]}' for k, n in sorted(ns.items())))
    prints_n = {a: len(nav.prints_load(a)) for a in {f['scene'] for f in facts if f.get('scene')}}
    lay = 'layers per area (L4 map → L3 graph → L2 calib → L1 prints):\n  ' + '\n  '.join(
        nav.layers(facts, calib, ns, prints_n))
    return lay + '\n' + nav.report(facts, calib, now) + '\n' + graph


# ---------------------------------------------------------------- map navigation (L57)
# Localise with the map overlay (M): Tara = the pink pin (numpy colour mask, tip = her position). Plan on the map
# image itself: roads are drawn in two beige tones -> boolean road grid (4 px cells) -> BFS shortest path from the pin
# to a place (tools/nav/map.json places, map coords). Follow it with go: clicks in the map direction (the camera never
# rotates: map-up = screen-up), re-localising after every hop.
MAP_PANEL = (200, 110, 1760, 970)        # inner map area (the frame border shares the road colour)
NAV_CELL = 4                              # px per BFS cell
NAV_STEP = 420                            # screen px per go: hop (from Tara at the screen centre)
NAV_ARRIVE = 24                           # map px: close enough to a place (40 was too loose: roads pass near doors)
TARA_SCREEN = (960, 600)                  # where the camera keeps Tara (not at map edges)


def map_pin(img):
    """Pin tip (Tara's map position) in a frame with the map open, or None."""
    import numpy as np
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r >= 248) & (g >= 140) & (g <= 200) & (b >= 140) & (b <= 205) & (r - g >= 55) & (abs(g - b) <= 30)  # pin body ≈ (255, 157-179, 153-185)
    x0, y0, x1, y1 = MAP_PANEL
    m[:y0], m[y1:], m[:, :x0], m[:, x1:] = False, False, False, False
    ys, xs = np.nonzero(m)
    if len(xs) < 200:
        return None
    # densest 40 px cell = the pin (pink roofs are smaller), then its own pixels around it
    H = np.zeros((m.shape[0] // 40 + 1, m.shape[1] // 40 + 1), dtype=np.int32)
    np.add.at(H, (ys // 40, xs // 40), 1)
    cy, cx = np.unravel_index(H.argmax(), H.shape)
    keep = (abs(xs - (cx * 40 + 20)) < 70) & (abs(ys - (cy * 40 + 20)) < 90)
    if keep.sum() < 200:
        return None
    return int(np.median(xs[keep])), int(ys[keep].max())


def map_roads(img):
    """Boolean road grid (NAV_CELL px cells) of the map overlay, dilated by one cell to close small gaps."""
    import numpy as np
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    road = ((r >= 215) & (g >= 170) & (g <= 232) & (b >= 105) & (b <= 192) & (r - b >= 45) & (r - b <= 125)
            & (r - g >= 15) & (r - g <= 55))
    x0, y0, x1, y1 = MAP_PANEL
    mask = np.zeros_like(road)
    mask[y0:y1, x0:x1] = road[y0:y1, x0:x1]
    h, w = mask.shape[0] // NAV_CELL, mask.shape[1] // NAV_CELL
    grid = mask[:h * NAV_CELL, :w * NAV_CELL].reshape(h, NAV_CELL, w, NAV_CELL).any(axis=(1, 3))  # max-pool
    d = grid.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d |= np.roll(np.roll(grid, dy, 0), dx, 1)
    return d


def map_route(img, start, goal):
    """Shortest road path (list of map points) from `start` to the road cell nearest `goal`; None if unreachable."""
    import numpy as np
    from collections import deque
    grid = map_roads(img)
    h, w = grid.shape
    sx, sy = start[0] // NAV_CELL, start[1] // NAV_CELL
    grid[max(0, sy - 3):sy + 4, max(0, sx - 3):sx + 4] = True  # the pin hides the road Tara stands on
    dist = np.full(grid.shape, -1, dtype=np.int32)
    par = np.full(grid.shape + (2,), -1, dtype=np.int32)
    dist[sy, sx] = 0
    q = deque([(sy, sx)])
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and grid[ny, nx] and dist[ny, nx] < 0:
                dist[ny, nx] = dist[y, x] + 1
                par[ny, nx] = (y, x)
                q.append((ny, nx))
    ys, xs = np.nonzero(dist >= 0)
    if not len(xs):
        return None
    gx, gy = goal[0] / NAV_CELL, goal[1] / NAV_CELL
    i = int(np.argmin((xs - gx) ** 2 + (ys - gy) ** 2))  # reachable cell nearest the goal
    y, x = int(ys[i]), int(xs[i])
    path = []
    while (y, x) != (sy, sx):
        path.append((x * NAV_CELL + NAV_CELL // 2, y * NAV_CELL + NAV_CELL // 2))
        y, x = (int(v) for v in par[y, x])
    return path[::-1]


# On screen, paths (gravel, dirt, cobbles) are low-saturation and mid-bright; grass is green, walls/rocks saturated,
# doors dark. HSV thresholds are lighting-robust (calibrated at dusk, D145 19:20). Small blobs (lit windows, crates)
# are dropped by keeping only big connected regions. The map pin snaps to the nearest road, so Tara must stand ON a
# road before the pin is her position (user, 2026-10-29).
ROAD_CELL = 8          # px per cell of the screen road grid
ROAD_MIN_CELLS = 250   # connected road region at least this big (cells)
ON_ROAD = 0.2          # on_road() at/above this = Tara stands on or right at a road (grass = 0.0)
ROAD_COLORS = os.path.join(ROOT, 'tools', 'road_colors.json')
GREEN_HUE = (50, 115)  # PIL HSV hue band of grass/bushes in every light


def game_hour(img):
    """Hour (0-23.99) from the HUD clock ("Friday 8:10 pm"), or None."""
    cx, cy, cw, ch = CLOCK_REGION
    txt = ' '.join(r['text'] for r in ocr_image(img.crop((cx, cy, cx + cw, cy + ch)), scale=1))
    m = re.search(r'(\d{1,2})[:.](\d{2})\s*([ap])\.?m', txt.lower())
    if not m:
        return None
    h = int(m.group(1)) % 12 + (12 if m.group(3) == 'p' else 0)
    return h + int(m.group(2)) / 60


def light_period(hour):
    if hour is None:
        return None
    return 'day' if 7 <= hour < 17 else 'dusk' if 17 <= hour < 20 else 'night'


def road_sets():
    return {k: v for k, v in json.load(open(ROAD_COLORS)).items() if not k.startswith('_')}


def current_scene():
    """Area Tara is in (engine log tail): the last `ChangeScene <Area>/…`, or the building entered after it."""
    try:
        with open(GAME_LOG, 'rb') as fh:
            fh.seek(max(0, os.path.getsize(GAME_LOG) - 400_000))
            txt = fh.read().decode('utf-8', 'replace')
    except OSError:
        return None
    scene = inside = spawn = None
    # raw log names are hashed (#-12345), even the trigger names (OnExitBuilding): decode the candidate lines first
    txt = _unhash('\n'.join(l for l in txt.splitlines() if 'ChangeScene' in l or '[TRIGGER]' in l))
    known = spawn_inside()
    for m in re.finditer(r'ChangeScene (\w+)/(\w+)|OnEnterBuilding (\w+)|OnExitBuilding (\w+)', txt):
        if m.group(1):
            scene, spawn = m.group(1), f'{m.group(1)}/{m.group(2)}'
            inside = known.get(spawn)  # some spawn points are indoors (Farm/Bed = House, D147)
        elif m.group(3):
            inside, spawn = m.group(3), None
        else:
            if inside is None and spawn and spawn not in known:  # left a building we never entered: spawned inside
                learn_spawn_inside(spawn, m.group(4))
                known[spawn] = m.group(4)
            inside, spawn = None, None
    return inside or scene


SPAWN_INSIDE = os.path.join(ROOT, 'tools', 'nav', 'spawn_inside.json')


def spawn_inside():
    """Spawn anchors that are inside a building (learned when Tara exits a building she never entered)."""
    try:
        return json.load(open(SPAWN_INSIDE))
    except (OSError, ValueError):
        return {'Farm/Bed': 'House'}


def learn_spawn_inside(spawn, building):
    data = spawn_inside()
    data[spawn] = building
    json.dump(data, open(SPAWN_INSIDE, 'w'), indent=1)


def road_key(img):
    """Colour-set key '<area>:<light>' (e.g. Farm:night); light from the HUD clock."""
    return f'{current_scene()}:{light_period(game_hour(img))}'


def road_set(key):
    """The set for this area+light, else any set for this light, else None (relative fallback)."""
    sets = road_sets()
    return sets.get(key) or sets.get(key.split(':')[-1])


def learn_road_colors(period, s_vals, v_vals):
    """Widen (or create) the colour set `period` (a key like 'Farm:night') from ground pixels known to be road."""
    import numpy as np
    data = json.load(open(ROAD_COLORS))
    s90, v10, v90 = float(np.percentile(s_vals, 90)), float(np.percentile(v_vals, 10)), float(np.percentile(v_vals, 90))
    cur = data.get(period)
    new = {'s_max': int(s90 + 8), 'v_min': int(max(0, v10 - 12)), 'v_max': int(min(255, v90 + 15))}
    if cur:
        new = {'s_max': max(cur['s_max'], new['s_max']), 'v_min': min(cur['v_min'], new['v_min']),
               'v_max': max(cur['v_max'], new['v_max'])}
    new['samples'] = (cur or {}).get('samples', 0) + 1
    data[period] = new
    json.dump(data, open(ROAD_COLORS, 'w'), indent=1)
    return new


def screen_road(img, period=None):  # period: a road_key ('Farm:night') or a light ('night')
    """Boolean grid (ROAD_CELL px cells) of road on the game screen, big connected regions only.
    Colour set by lighting period (game clock); without a set: 'clearly less saturated than the grass in view'."""
    import numpy as np
    from collections import deque
    hsv = np.asarray(img.convert('HSV').resize((img.width // ROAD_CELL, img.height // ROAD_CELL)), dtype=np.int16)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    green = (h >= GREEN_HUE[0]) & (h <= GREEN_HUE[1])
    cs = road_set(period or road_key(img))
    if cs:
        road = ~green & (s <= cs['s_max']) & (v >= cs['v_min']) & (v <= cs['v_max'])
    else:  # relative fallback: grass saturation in this very frame sets the bar
        gs = float(np.median(s[green & (s > 30)])) if (green & (s > 30)).any() else 80.0
        road = ~green & (s <= 0.75 * gs) & (v >= np.percentile(v, 15)) & (v <= np.percentile(v, 97))
    road[:230 // ROAD_CELL] = False  # HUD band
    seen = np.zeros_like(road)
    keep = np.zeros_like(road)
    H, W = road.shape
    for y, x in zip(*np.nonzero(road)):
        if seen[y, x]:
            continue
        comp, q = [], deque([(y, x)])
        seen[y, x] = True
        while q:
            cy, cx = q.popleft()
            comp.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < H and 0 <= nx < W and road[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(comp) >= ROAD_MIN_CELLS:
            ys, xs = zip(*comp)
            keep[list(ys), list(xs)] = True
    return keep


def tara_feet(img):
    """Tara's feet on screen: bottom-centre of the tracker box (seeded at the camera centre)."""
    tr = Tara()
    tr.update(img)
    x0, y0, x1, y1 = tr.box
    return int((x0 + x1) / 2), int(y1)


def calibrate_road(img=None, feet=None):
    """Tara is known to stand on a road: learn this lighting period's colours from the ground under her feet."""
    import numpy as np
    img = img or grab()
    period = road_key(img)
    if period.endswith(':None'):
        return 'calibrate: no clock on screen'
    fx, fy = feet or tara_feet(img)
    hsv = np.asarray(img.convert('HSV').crop((fx - 44, fy + 16, fx + 44, fy + 56)), dtype=np.int16).reshape(-1, 3)
    hsv = hsv[~((hsv[:, 0] >= GREEN_HUE[0]) & (hsv[:, 0] <= GREEN_HUE[1]))]  # flowers/grass blades at the edge
    if len(hsv) < 200:
        return 'calibrate: the ground under her feet looks green (not a road?)'
    cs = learn_road_colors(period, hsv[:, 1], hsv[:, 2])
    run_log('nav', what='road_colors', period=period, set=cs)
    return f'road colours [{period}]: {cs}'


def on_road(img, feet=None, radius=72):
    """Share of road in a disc around Tara's feet, minus her own body column (≥ 0.5 = on/at a road). A disc, not a
    window below the feet: at a path's edge the road is beside her, and the pin's snap error there is tiny."""
    import numpy as np
    g = screen_road(img)
    fx, fy = feet or tara_feet(img)
    ys, xs = np.mgrid[:g.shape[0], :g.shape[1]]
    dx, dy = xs * ROAD_CELL + ROAD_CELL // 2 - fx, ys * ROAD_CELL + ROAD_CELL // 2 - fy
    disc = (np.hypot(dx, dy) <= radius) & ~((np.abs(dx) < 28) & (dy < 8))  # not her body/shadow
    return min(1.0, float(g[disc].mean() * 2)) if disc.any() else 0.0  # ×2: half the disc road = fully at it


def to_road(tries=3):
    """Make sure Tara stands on a road: if not, click the nearest big road region on screen. Returns a status."""
    import numpy as np
    for i in range(tries):
        img = grab()
        feet = tara_feet(img)
        share = on_road(img, feet)
        if share >= ON_ROAD:
            return f'ON ROAD ({share:.0%} under her feet)'
        g = screen_road(img)
        ys, xs = np.nonzero(g)
        if not len(xs):
            return 'NO ROAD ON SCREEN'
        px, py = xs * ROAD_CELL + ROAD_CELL // 2, ys * ROAD_CELL + ROAD_CELL // 2
        d = (px - feet[0]) ** 2 + (py - feet[1]) ** 2
        j = int(np.argsort(d)[min(len(d) - 1, 6)])  # a few cells into the road, not its very edge
        msg = go_to(int(px[j]), int(py[j]))
        run_log('nav', what='to_road', try_=i + 1, share=round(share, 2), click=(int(px[j]), int(py[j])), msg=msg or 'ok')
    img = grab()
    share = on_road(img)
    return f'ON ROAD ({share:.0%})' if share >= ON_ROAD else f'NOT ON ROAD after {tries} tries ({share:.0%})'


def road_target(img, ang, feet=None, reach=(120, 470), avoid=()):
    """A visible road point to click: the road cell farthest along direction `ang` (radians, screen) from Tara's feet,
    within a cone that widens 35° → 60° → 90°. Trees/roofs over the road aren't road-coloured, so they're never
    clicked (user, 2026-10-29). None if no road is visible that way."""
    import math
    import numpy as np
    g = screen_road(img)
    fx, fy = feet or tara_feet(img)
    ys, xs = np.nonzero(g)
    if not len(xs):
        return None
    px, py = xs * ROAD_CELL + ROAD_CELL // 2, ys * ROAD_CELL + ROAD_CELL // 2
    dx, dy = px - fx, py - fy
    dist = np.hypot(dx, dy)
    for ax, ay in avoid:  # road-coloured but rejected by the game (NO MOVE): wall tops, paving behind fences
        dist = np.where(np.hypot(px - ax, py - ay) < 80, 1e9, dist)
    dev = np.abs((np.arctan2(dy, dx) - ang + math.pi) % (2 * math.pi) - math.pi)
    along = dx * math.cos(ang) + dy * math.sin(ang)
    for cone in (math.radians(35), math.radians(60), math.radians(90)):
        ok = (dist >= reach[0]) & (dist <= reach[1]) & (dev <= cone)
        if ok.any():
            i = int(np.argmax(np.where(ok, along - 0.3 * dist * dev, -1e9)))
            return int(px[i]), int(py[i])
    return None


# ---- model-in-the-loop (L59): code first; when it's unsure, ask the model ONE grid question and store the answer
ASK_IMG = os.path.join(SHOT_DIR, 'ask.jpg')
ASK_FRAME = os.path.join(SHOT_DIR, 'ask_frame.png')
ASK_CTX = os.path.join(SHOT_DIR, 'ask.json')
GRID_COLS, GRID_ROWS = 12, 8   # cells A-L × 1-8 over the 1920x1080 frame (160 × 135 px)
HOPS = os.path.join(ROOT, 'tools', 'hops.json')


def cell_box(cell):
    col, row = ord(cell[0].upper()) - 65, int(cell[1:]) - 1
    w, h = FRAME_W / GRID_COLS, FRAME_H / GRID_ROWS
    return int(col * w), int(row * h), int((col + 1) * w), int((row + 1) * h)


def ask_vision(kind, question, img, **ctx):
    """Save a small gridded frame + context and return the NEED_VISION prompt for the agent."""
    from PIL import ImageDraw
    img.save(ASK_FRAME)
    small = img.resize((768, 432))
    d = ImageDraw.Draw(small)
    cw, ch = 768 / GRID_COLS, 432 / GRID_ROWS
    for c in range(GRID_COLS):
        for r in range(GRID_ROWS):
            d.rectangle((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch), outline=(255, 255, 0))
            d.text((c * cw + 3, r * ch + 2), f'{chr(65 + c)}{r + 1}', fill=(255, 255, 0))
    small.save(ASK_IMG, quality=80)
    json.dump({'kind': kind, 'question': question, **ctx}, open(ASK_CTX, 'w'))
    run_log('vision', what='ask', kind=kind, question=question)
    ex = {'road': 'C5 D5 D6', 'next': 'D6'}.get(kind, '…')
    return (f'NEED_VISION {kind}: {question}\n  look: {ASK_IMG} (grid A-L × 1-8)\n'
            f'  answer: ./wf teach {kind} <cells>   e.g. ./wf teach {kind} {ex}')


def hop_key(pin, ang):
    import math
    return f'{pin[0] // 20 * 20},{pin[1] // 20 * 20},{round(math.degrees(ang) / 45) % 8}'


def hops():
    try:
        return json.load(open(HOPS))
    except (OSError, ValueError):
        return {}


def teach(kind, cells):
    """Store the model's answer to the last NEED_VISION question (and act on it for `next`)."""
    import numpy as np
    from PIL import Image
    try:
        ctx = json.load(open(ASK_CTX))
        img = Image.open(ASK_FRAME).convert('RGB')
    except (OSError, ValueError):
        return 'teach: no open question'
    if kind == 'exit':
        kind = 'step'
    if kind != ctx['kind']:
        return f'teach: the open question is {ctx["kind"]!r}, not {kind!r}'
    if kind == 'road':
        hsv = np.asarray(img.convert('HSV'), dtype=np.int16)
        px = []
        for c in cells:
            x0, y0, x1, y1 = cell_box(c)
            mx, my = (x1 - x0) // 5, (y1 - y0) // 5  # central part of the cell
            px.append(hsv[y0 + my:y1 - my, x0 + mx:x1 - mx].reshape(-1, 3))
        px = np.concatenate(px)
        px = px[~((px[:, 0] >= GREEN_HUE[0]) & (px[:, 0] <= GREEN_HUE[1]))]
        if len(px) < 200:
            return 'teach road: those cells look green (grass), not road'
        cs = learn_road_colors(ctx['key'], px[:, 1], px[:, 2])
        run_log('vision', what='teach', kind=kind, cells=cells, key=ctx['key'])
        os.remove(ASK_CTX)
        return f'taught road colours [{ctx["key"]}]: {cs}. Re-run your command.'
    if kind == 'next':
        x0, y0, x1, y1 = cell_box(cells[0])
        pt = ((x0 + x1) // 2, (y0 + y1) // 2)
        msg = go_to(*pt)
        if not msg or msg.startswith('ALREADY'):
            data = hops()
            data[ctx['hop']] = list(pt)  # next time at this map spot, this direction: click here, no question
            json.dump(data, open(HOPS, 'w'), indent=1)
        run_log('vision', what='teach', kind=kind, cells=cells, hop=ctx['hop'], msg=msg or 'ok')
        os.remove(ASK_CTX)
        return f'taught hop {ctx["hop"]} → {pt}: {msg or "moved"}. Re-run your command.'
    if kind == 'step':  # the model's next click toward the goal: walk there; a real move = a proven walk (L74)
        import math
        if ':' in cells[0]:  # X:Y game coords (L74)
            pt = tuple(int(v) for v in cells[0].split(':'))
        else:
            x0, y0, x1, y1 = cell_box(cells[0])
            pt = ((x0 + x1) // 2, (y0 + y1) // 2)
        fr = dict(_seg()['from'] or {})
        msg = go_to(*pt)
        if msg and msg.startswith('MENU OPEN'):
            return f'teach step {cells[0]}: {msg}; then answer again (nothing learned)'
        if msg and msg.startswith('NO MOVE'):
            return f'teach step {cells[0]}: {msg} (not walkable): pick another cell'
        p, _ = checkpoint('via')
        moved = fr.get('x') is not None and math.dist((fr['x'], fr['z']), (p['x'], p['z']))
        run_log('vision', what='teach', kind=kind, cells=cells, moved=moved)
        try:  # eval (M0): did the model's answer move her
            import evals
            evals.record('ask', 'answer moves her', cells[0], moved, bool(moved and moved >= 1.0),
                         {'answer': cells[0], 'question': ctx.get('question', '')[:120]})
        except Exception:  # noqa: BLE001
            pass
        if not moved or moved < 1.0:
            return f'teach step {cells[0]}: she did not move: pick another cell'
        os.remove(ASK_CTX)
        return f'taught step {cells[0]}: walked {moved:.1f} units to ({p["x"]:.1f}, {p["z"]:.1f}). Re-run your command.'
    return f'teach: unknown kind {kind!r}'


def compass(ang):
    import math
    return ['east', 'south-east', 'south', 'south-west', 'west', 'north-west', 'north', 'north-east'][
        round(math.degrees(ang) / 45) % 8]


def log_mark():
    try:
        return os.path.getsize(GAME_LOG)
    except OSError:
        return 0


def log_since(pos):
    try:
        with open(GAME_LOG, 'rb') as fh:
            fh.seek(pos)
            return fh.read().decode('utf-8', 'replace')
    except OSError:
        return ''


# ---- anchored route graph (L60): nodes = anchors the engine confirms exactly (spawn points, building doors);
# edges = short recorded go: chains between neighbouring anchors; any trip = shortest path of edges, replayed.
EDGES = os.path.join(ROOT, 'tools', 'edges.json')
ANCHOR_EVENT = {  # anchor name -> engine-log evidence that Tara is exactly there
    'Farm/LinkTown': r'Spawning player at Farm/LinkTown', 'Town/LinkFarm': r'Spawning player at Town/LinkFarm',
    'House': r'OnEnterBuilding House', 'House-door': r'OnExitBuilding House', 'Bed': r'Spawning player at Farm/Bed'}


def edges():
    try:
        return json.load(open(EDGES))
    except (OSError, ValueError):
        return {}


def anchor_event(name):
    return ANCHOR_EVENT.get(name) or re.escape(name)


def edge_add(a, b, clicks):
    data = edges()
    data[f'{a}>{b}'] = {'clicks': [list(map(int, c.split(':'))) for c in clicks], 'ok': 0, 'fail': 0}
    json.dump(data, open(EDGES, 'w'), indent=1)
    return f'edge {a} → {b}: {len(clicks)} clicks stored'


def edge_replay(a, b):
    """Replay a stored edge from anchor a; success = b's engine event appears. Updates the edge's ok/fail counts."""
    data = edges()
    e = data.get(f'{a}>{b}')
    if not e:
        return f'no edge {a} → {b}; known: {", ".join(data) or "none"}'
    mark = log_mark()
    msgs = []
    for x, y in e['clicks']:
        msg = go_to(x, y)
        msgs.append(msg or 'ok')
        if re.search(anchor_event(b), _unhash(log_since(mark))):
            break
    time.sleep(1.5)  # scene loads / door transitions
    ok = bool(re.search(anchor_event(b), _unhash(log_since(mark))))
    e['ok' if ok else 'fail'] += 1
    json.dump(data, open(EDGES, 'w'), indent=1)
    run_log('nav', what='edge', edge=f'{a}>{b}', ok=ok, clicks=len(msgs), msgs=msgs)
    import nav
    p, _ = checkpoint('arrived' if ok else 'failed', edge=f'{a}>{b}')
    st = nav.edge_status(nav.load(), p).get(f'{a}>{b}', {})
    return (f'{"ARRIVED" if ok else "FAILED"} {a} → {b} ({len(msgs)} clicks; {st.get("status")}: {st.get("ok")} ok / '
            f'{st.get("fail")} fail)')


def places():
    """Named places in map px (L4 map layer, tools/nav/map.json)."""
    import nav
    return {k: tuple(v) for k, v in nav.map_load()['places'].items()}


def map_snapshot():
    """Open the map, grab it, close it. Returns the frame (map visible) or None if the map didn't open."""
    key('m')
    time.sleep(0.9)
    img = grab()
    if map_pin(img):
        key('escape')
        time.sleep(0.6)
        img.save(MAP_LAST)  # the last map picture: road cells for the coverage matrix (L67)
        return img
    s = state()  # map didn't open: a blind Escape would open the pause menu
    if s['mode'] != 'gameplay' and not is_paused(s):
        key('escape')
        time.sleep(0.6)
    return None


MAP_LAST = os.path.join(SHOT_DIR, 'map_last.png')


def map_road_cells():
    """Coverage cells (COVER_CELL map px) that contain road on the last map picture, or an empty set."""
    import nav
    import numpy as np
    from PIL import Image
    try:
        g = map_roads(Image.open(MAP_LAST))
    except OSError:
        return set()
    ys, xs = np.nonzero(g)
    k = nav.COVER_CELL // NAV_CELL
    cnt = {}
    for cx, cy in zip(xs // k, ys // k):
        cnt[(int(cx), int(cy))] = cnt.get((int(cx), int(cy)), 0) + 1
    return {c for c, n in cnt.items() if n >= k}  # at least a road line through the cell


def coverage_report():
    """Matrix per coverage grid + gaps of Tara's cell (L67)."""
    import nav
    facts = nav.load()
    fits = nav.map_load()['fits']
    printed = set()
    for a in {f['scene'] for f in facts if f.get('scene')}:
        printed |= set(nav.prints_load(a))
    period = light_period(game_hour(_frame())) if is_frontmost() else None
    cov = nav.coverage(facts, fits, printed, period)
    fr = _seg()['from']
    here = fr and nav.cell_of(fr['scene'], fr['x'], fr['z'], fits)
    out = [f'L1 prints counted for: {period or "any light"}']
    keys = ['map'] + sorted({c[0] for c in cov if c[0] != 'map'})
    for k in keys:
        cells = [c for c in cov if c[0] == k]
        full = sum(1 for c in cells if not nav.missing(c, cov))
        out.append(f'== {k}: {len(cells)} cells with data, {full} complete '
                   f'({"4" if k == "map" else "3"} layers; digit = layers present, · = road without data, @ = Tara)')
        out.append(nav.coverage_matrix(cov, k, map_road_cells() if k == 'map' else None,
                                       here[1:] if here and here[0] == k else None))
    no_fit = sorted({f['scene'] for f in facts if f.get('scene') and nav.outdoor(f['scene'])} - set(fits))
    if no_fit:
        out.append(f'not on the map yet (no map fit: need 2 pins apart): {", ".join(no_fit)}')
    if here:
        out.append(f'Tara {fr["scene"]} cell {here[1:]}: missing {", ".join(nav.missing(here, cov)) or "nothing"}')
    return '\n'.join(out)


REC = None  # (thread, stop event, out path) of the running video recording


def record(cmd, fps=8, width=1280):
    """Video of the game window, recorded by a daemon thread (only the daemon may capture, L71); tools/record.py."""
    global REC
    import threading
    import record as rec
    if cmd == 'start':
        if REC and REC[0].is_alive():
            return f'already recording: {REC[2]}'
        os.makedirs(rec.OUT_DIR, exist_ok=True)
        out = os.path.join(rec.OUT_DIR, time.strftime('play-%Y%m%d-%H%M%S.mp4'))
        stop = threading.Event()
        th = threading.Thread(target=rec.run, args=(fps, width, out, stop, sys.modules[__name__]), daemon=True)
        th.start()
        REC = (th, stop, out)
        return out
    if not REC:
        return 'not recording'
    th, stop, out = REC
    if cmd == 'status':
        return f'{"recording" if th.is_alive() else "ended"}: {out}'
    stop.set()
    th.join(20)
    REC = None
    size = os.path.getsize(out) if os.path.exists(out) else 0
    return f'{out} {size / 1e6:.1f} MB' + ('' if size > 10000 else '  FAILED (no frames captured)')


def improve(n=3):
    """Auto-improver (L67): fill the gaps of Tara's cell (L4 map pin, L2 one short checked hop; L3/L1 come with
    every reading), then walk to the nearest road cell with no data and repeat, n cells. Outdoors only."""
    import math
    import nav
    done, tried = [], set()
    for i in range(n):
        p, f = checkpoint()  # reading + L3/L1 (+ L4 by fill_pin)
        if p['hour'] >= 23 or p['hour'] < 6:  # clock guard: optional work stops late (retro 2026-10-29, L27)
            done.append(f'{p["hour"]:.1f}h: too late for optional work; go to bed')
            break
        if not nav.outdoor(p['scene']):
            done.append(f'{p["scene"]}: indoors, L3/L1 recorded; walk around for L2')
            break
        fits = nav.map_load()['fits']
        facts = nav.load()
        printed = set(nav.prints_load(p['scene']))
        period = nav.light(p['hour'])
        cov = nav.coverage(facts, fits, printed, period)
        cell = nav.cell_of(p['scene'], p['x'], p['z'], fits)
        if cell and 'L2' in nav.missing(cell, cov) and calib_load(p['scene']):
            c = calib_load(p['scene'])
            tx, ty = c['tara']
            for dx, dy in ((150, 0), (-150, 0), (0, 120), (0, -120)):  # one short hop: a checked prediction
                if not go_to(tx + dx, ty + dy):
                    checkpoint(fill=False)
                    break
            cov = nav.coverage(nav.load(), fits, set(nav.prints_load(p['scene'])), period)
        done.append(f'cell {cell and cell[1:]}: missing {", ".join(nav.missing(cell, cov)) or "nothing"}' if cell
                    else f'{p["scene"]}: no map fit yet (pins so far are too close together)')
        if i == n - 1 or not cell:
            break
        fit = fits[p['scene']]
        roads = map_road_cells() or (map_snapshot() is not None and map_road_cells())
        todo = [r for r in roads if ('map', *r) not in cov and r != cell[1:] and r not in tried]
        if not todo:
            done.append('no uncovered road cell on the last map picture')
            break
        here = cell[1:]
        nxt = min(todo, key=lambda r: math.dist(r, here))
        tried.add(nxt)  # a coarse fit may land her short of it: don't aim at the same cell twice
        mx, my = (nxt[0] + 0.5) * nav.COVER_CELL, (nxt[1] + 0.5) * nav.COVER_CELL
        gx, gz = nav.map_to_world(fit, mx, my)
        msg = go_world(gx, gz, radius=nav.COVER_CELL * abs(fit['a']) / 2)
        done.append(f'→ cell {nxt}: {msg}')
        if not msg.startswith(('ARRIVED', 'NEAR')):
            break
    return 'IMPROVE\n  ' + '\n  '.join(done)


def where(learn=None):
    """Tara's map position + nearest known place. learn=<name>: store the current position as that place."""
    img = map_snapshot()
    if img is None:
        return 'where: map did not open (or no pin): check state'
    pin = map_pin(img)
    pl = places()
    if learn:
        import nav
        data = nav.map_load()
        data['places'][learn] = list(pin)
        nav.map_save(data)
        pl[learn] = pin
    name, p = min(pl.items(), key=lambda kv: (kv[1][0] - pin[0]) ** 2 + (kv[1][1] - pin[1]) ** 2)
    d = ((p[0] - pin[0]) ** 2 + (p[1] - pin[1]) ** 2) ** 0.5
    run_log('nav', what='where', pin=pin, near=name, dist=round(d))
    p, _ = checkpoint(pin=pin)  # map -> world pair (phase 2)
    return f'where: map {pin[0]},{pin[1]} · nearest place {name} ({d:.0f} map px) · world {p["scene"]} ({p["x"]:.1f}, {p["z"]:.1f})'


def nav_places():
    """Learned places (exact readings) as nodes: [{'name', 'scene', 'x', 'z'}] (for game functions)."""
    import nav
    return [{'name': n['name'], 'scene': n['scene'], 'x': n['x'], 'z': n['z']}
            for n in nav.nodes(nav.load()).values() if n['src'] == 'arrived' and n.get('x') is not None]


class _Point:
    KINDS = {'well': 'Well'}   # learned place → the object kind there (its unique bubbles mean "arrived")

    def __init__(self, name, scene, x, z):
        self.name, self.scene, self.x, self.z = name, scene, x, z
        self.kind = self.KINDS.get(name)

    def __str__(self):
        return self.name


def _goto_world(place):
    """walk() to a learned place (an exact reading) in the world's current area; None if it doesn't apply."""
    try:
        import nav
        from game import walk
        area = world().tara()[0]
        n = next((v for v in nav.nodes(nav.load()).values() if v['name'] == place and v['src'] == 'arrived'
                  and v['scene'] == area and v.get('x') is not None), None)
    except Exception:  # noqa: BLE001 (the old route still works without the world)
        return None
    if not n:
        return None
    import game
    game.bind(sys.modules[__name__])
    pt = _Point(place, area, n['x'], n['z'])
    ent = next(iter(world().entities(kind=pt.kind, area=area)), None) if pt.kind else None
    try:
        if ent and walk.click_object(ent):  # the place's object is visible: click it, the game pathfinds (user)
            return walk.walk(ent)
        return walk.walk(ent or pt)
    except game.Failed as e:
        return f'goto {place}: {e}'


def goto(place, max_hops=30):
    """Walk to a known place: the world graph when it knows the place, else the coarse map walk (map_walk, L72),
    else (map won't open) a reading + the graph. Returns ARRIVED / NEAR / NOT REACHED messages.
    A learned place in Tara's current area is walked on the world model (M3 walk): its belief, not the old estimate."""
    via_world = _goto_world(place)
    if via_world:
        return via_world
    steps = graph_route(place)
    if steps:  # world graph (phase 2): walk / link / replay steps
        return run_route(place, steps)
    pl = places()
    if place not in pl:
        return f'goto: unknown place {place!r}; known: {", ".join(sorted(pl))}'
    goal = pl[place]
    r = map_walk(place, goal, max_hops)
    if r is not None:
        return r
    # graph first, map last: never retry a map that failed (retro 2026-10-29)
    checkpoint(fill=False)
    steps = graph_route(place)
    if steps:
        return run_route(place, steps)
    return (f'goto {place}: map did not open and the world graph has no route: check state, then '
            f'`wf plan <node>` / `wf go-world X Z`; do not retry the map')


MAP_REANCHOR = 3   # coarse hops between map looks (dead reckoning drifts with the ±50 % map scale)
MAP_HOP_NEAR = 3.0  # world units: a coarse hop is done this close to its point
MAP_SIDESTEP = (90, -90, 180)  # degrees off the route: half hops tried when a hop didn't move her


def map_walk(place, goal, max_hops=30):
    """Coarse map route (L72): the map gives direction and distance, readings give the truth. Open the map → road
    route → hop MAP_HOP units toward the route point ahead (go_world ends in a reading) → dead-reckon the map position
    from the measured move → look at the map again every MAP_REANCHOR hops, when stuck, or after a scene change. A
    scene border is walked through: the hop keeps its direction and the crossing is traced. None = map didn't open."""
    import math
    import nav
    p, _ = checkpoint(fill=False)
    m = path = None
    since = MAP_REANCHOR
    track = [(p['scene'], p['x'], p['z'])]  # 3 moves without progress = stuck (L75)
    for hop in range(max_hops):
        if since >= MAP_REANCHOR:
            img = map_snapshot()
            if img is None:
                return None
            m = map_pin(img)
            path, since = map_route(img, m, goal), 0
            if not path:
                return f'goto {place}: no road route from map {m}: use go: to reach a road'
        left = math.dist(m, goal)
        if left <= NAV_ARRIVE:
            if since:  # only dead-reckoned: confirm on the map
                since = MAP_REANCHOR
                continue
            run_log('nav', what='goto', place=place, result='arrived', hops=hop)
            p, _ = checkpoint('near', goal=place, pin=m)  # a map pin pair (L4); coarse, so not 'arrived'
            return (f'NEAR {place} in {hop} hops (map {m[0]},{m[1]}; world {p["x"]:.1f}, {p["z"]:.1f}): look, '
                    f'click the last bit, then `wf pos --learn {place}`')
        h = nav.map_heading(m, nav.path_ahead(path, m, nav.MAP_HOP / nav.MAP_SCALE)) or nav.map_heading(m, goal)
        if not calib_load(p['scene']):  # e.g. a porch the game counts as a building: no clicks to plan here
            return stuck_vision(place, h, f'in {p["scene"]}, which has no calibration')
        msg = go_world(p['x'] + h[0], p['z'] + h[1], max_rounds=1, radius=MAP_HOP_NEAR)
        q = _seg()['from']
        if q['scene'] != p['scene'] or 'changed scene' in msg:
            q, _ = checkpoint(fill=False)  # exact spawn point in the new area
            calibrate_road()  # the spawn point is ON a road: free colour sample
            run_log('nav', what='map-hop', place=place, new_area=q['scene'], msg=msg)
            steps = graph_route(place)  # the new scene may know the place (a finer layer)
            if steps:
                return run_route(place, steps)
            p, since = q, MAP_REANCHOR
            continue
        dx, dz = q['x'] - p['x'], q['z'] - p['z']
        track.append((q['scene'], q['x'], q['z']))
        if math.hypot(dx, dz) < 1.0:
            mark_blocked(place, h, msg)
        for rot in MAP_SIDESTEP if math.hypot(dx, dz) < 1.0 else ():  # blocked (porch rail, fence): step aside
            if nav.no_progress(track):
                break
            a = math.radians(rot)
            sx, sz = (h[0] * math.cos(a) - h[1] * math.sin(a)) / 2, (h[0] * math.sin(a) + h[1] * math.cos(a)) / 2
            msg = go_world(q['x'] + sx, q['z'] + sz, max_rounds=1, radius=MAP_HOP_NEAR)
            q = _seg()['from']
            track.append((q['scene'], q['x'], q['z']))
            dx, dz = q['x'] - p['x'], q['z'] - p['z']
            if q['scene'] != p['scene'] or math.hypot(dx, dz) >= 1.0:
                break
        if q['scene'] != p['scene']:  # the sidestep crossed a border: look at the map in the new area
            p, since = q, MAP_REANCHOR
            continue
        run_log('nav', what='map-hop', place=place, map=[round(v) for v in m], left=round(left),
                hop=[round(h[0], 1), round(h[1], 1)], moved=[round(dx, 1), round(dz, 1)], msg=msg)
        if nav.no_progress(track):  # 3 moves without progress: one model look, not more blind hops
            return stuck_vision(place, h, f'{nav.STUCK_MOVES} moves without progress; last: {msg}')
        if math.hypot(dx, dz) < 1.0:
            since = MAP_REANCHOR  # no move but not stuck yet: look at the map again
            p = q
            continue
        m, since = nav.map_dead_reckon(m, dx, dz), since + 1
        p = q
    run_log('nav', what='goto', place=place, result='not reached', hops=max_hops)
    return f'NOT REACHED {place} after {max_hops} hops (map {m[0]:.0f},{m[1]:.0f}, {math.dist(m, goal):.0f} px left)'


def is_paused(s=None):
    s = s or state()
    return s['mode'] == 'overlay' and any(any(word in t.casefold() for word in ('game paused', 'пауза'))
                                          for t in s['text'])


def set_paused(want):
    """Idempotent pause/resume: look first, press Escape only if needed (Escape toggles; blind presses un-pause)."""
    for _ in range(3):
        s = state()
        if is_paused(s) == want:
            return f'{"paused" if want else "running"}: {brief(s)}'
        key('escape')
        time.sleep(0.7)
    return f'could not {"pause" if want else "resume"}: {brief(state())}'


def run_action(spec):
    """Execute one action spec: go:<x>:<y> (click-to-move, game pathfinds; the ONLY way to move, L54) | key:<k> |
    click:<x>:<y> | text:<label> (click-text) | wait:<s> | still[:<max_s>] (until Tara's action/walk ends, L52) |
    act:<kind> (Space only if the highlighted bubble is <kind>: pickup/axe/pickaxe/talk/info/stairs, L55)"""
    kind, _, arg = spec.partition(':')
    if kind in ('act', 'click', 'text') or spec == 'key:space':  # may move Tara without a go: click (L62)
        mark, est = log_mark(), seg_estimate()
        msg = run_action_inner(spec)
        time.sleep(0.5)
        if not scene_change(mark, est):
            seg_dirty()
        return msg
    return run_action_inner(spec)


def run_action_inner(spec):
    kind, _, arg = spec.partition(':')
    if kind == 'key':
        if arg == 'space':
            img = _frame()
            b = find_bubble(img)
            if b:
                _PENDING.append((bubble_crop(img, b), bubble_kind(img, b)[0]))
        key(arg)
    elif kind == 'act':
        return act(arg)
    elif kind in ('pause', 'resume'):
        msg = set_paused(kind == 'pause')
        return None if msg.startswith(('paused', 'running')) else msg
    elif kind == 'goto':
        msg = goto(arg)
        return None if msg.startswith('ARRIVED') else msg
    elif kind == 'go':
        x, y = arg.split(':')
        return go_to(int(x), int(y))
    elif kind in ('walk', 'path', 'route', 'bubble'):
        return f'{kind}: KEYBOARD MOVEMENT DISABLED (mouse only, user rule L54): use go:<x>:<y> on the target, the ground next to it, or a doorway'

    elif kind == 'click':
        x, y = arg.split(':')
        x, y = int(x), int(y)
        img = _frame()
        bubbles = find_bubbles(img)
        b = min(bubbles, key=lambda p: math.dist(p, (x, y))) if bubbles else None
        if b and math.dist(b, (x, y)) <= 70:
            _PENDING.append((bubble_crop(img, b), bubble_kind(img, b)[0]))
        click(x, y)
    elif kind == 'text':
        hits = find_text(arg)
        if not hits:
            return f'NOT FOUND: {arg}'
        click(hits[0]['cx'], hits[0]['cy'])
    elif kind == 'wait':
        time.sleep(float(arg))
    elif kind == 'still':
        s, active = wait_tara(timeout=float(arg or 4))
        return None if active else f'still: Tara idle ({s}s)'

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
    if sum(sp.startswith('go:') for sp in specs) > 1:
        print('ONE go: PER do: go: coords are screen coords and the camera scrolls while Tara walks, so a 2nd go: '
              'hits a stale spot (retro 2026-10-28). Look between hops.')
        specs = specs[:[i for i, sp in enumerate(specs) if sp.startswith('go:')][1]]
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


def actions(tags, require_all=False):
    """Print rows of docs/actions.md (action -> expected outcome -> verify) matching tags (any by default)."""
    want = {t.lower().strip(',') for t in tags}
    n = 0
    for l in open(os.path.join(ROOT, 'docs', 'actions.md')):
        if not re.match(r'\| A\d+ ', l):
            continue
        rid, name, tg, do, expect, verify, ifnot, status = ([c.strip() for c in l.strip().strip('|').split('|')] + [''] * 8)[:8]
        have = {t.strip() for t in tg.split(',')}
        if want <= have if require_all else (not want or want & have):
            print(f'{rid} {name} [{status}]\n  do:     {do}\n  expect: {expect}\n  verify: {verify}')
            if ifnot and ifnot != '—':
                print(f'  if not: {ifnot}')
            n += 1
    if not n:
        print('no actions for', ' '.join(sorted(want)))


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


EXTRA_NAMES = ('BeanSeed',)  # D183: #-145752244 = Green Bean Seeds (inventory x6, totalPlanted)


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
    for n in EXTRA_NAMES:  # ids the asset scan misses, found by hand (CRC32 of the guessed name matched)
        h = zlib.crc32(n.encode())
        _NAMES.setdefault(h - (1 << 32) if h >= 1 << 31 else h, n)
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
    collect_bubble_samples(lines)
    for l in lines:
        if RUN_GAME.search(l):
            run_log('game', line=l)
    for l in lines[-limit:]:
        print(prefix + l)
    if len(lines) > limit:
        print(f'{prefix}(+{len(lines) - limit} earlier lines; `wf log --tail N`)')


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:  # the game rotates save files: an old one can vanish between listing and stat (L62)
        return 0


def latest_save():
    files = [os.path.join(d, f) for d, _, fs in os.walk(SAVE_DIR) for f in fs if f.endswith('.local')]
    return max(files, key=_mtime) if files else None


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


# ---------------------------------------------------------------- routines (L61): daily chores before quests
def farm_status():
    """Garden crops from the save (actors with plant state). Crops = plants that track lastTimeRefreshed (beds);
    trees/flowers don't. Returns dict(beds, wilted, ripe, growing, dry, positions)."""
    _, d = read_save()
    crops = []

    def walk(o):
        if isinstance(o, dict):
            a = o.get('actorState')
            us = a.get('userState', {}).get('entries') if isinstance(a, dict) else None
            if us and any(e.get('name') == 'isWatered' for e in us):
                st = {e['name']: e['value'] for e in us}
                if 'lastTimeRefreshed' in st:
                    p = o.get('position', {})
                    crops.append({'x': p.get('x'), 'z': p.get('z'), **st})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    return {'beds': len(crops),
            'wilted': sum(c.get('isWilted') == 'true' for c in crops),
            'ripe': sum(c.get('plantState') == '##produced' for c in crops),
            'growing': sum(c.get('plantState') in ('##growing', '##producing') for c in crops),
            'dry': sum(c.get('isWatered') != 'true' and c.get('plantState') != '##produced' for c in crops),
            'crops': crops}


def today_log():
    """Today's engine-log lines (since the last OnDayStarted) and the day number."""
    lines = game_log(tail=4000)
    starts = [i for i, l in enumerate(lines) if 'OnDayStarted' in l]
    day = re.match(r'\[D(\d+)', lines[starts[-1]]).group(1) if starts else None
    return (lines[starts[-1]:] if starts else lines), day, lines


def routines():
    """Today's routines with status, from the save (what exists) and today's log (what was done). docs/routines.md"""
    today, day, lines = today_log()
    fc = next((l for l in reversed(lines) if f'[D{day} ' in l and 'Forecast is' in l), '')
    rain = bool(re.search(r'Forecast is (Rain|Storm|Thunder)', fc))
    fs = farm_status()
    watered = sum(1 for l in today if re.search(r'> (water|hazel_waterplant) me=Player target=GardenBed', l))
    harvested = sum(1 for l in today if re.search(r'> harvest\w* me=Player', l))
    need = fs['beds'] - fs['ripe']
    out = [f'day {day} · {fc.split("] ")[-1] if fc else "forecast ?"} · garden {fs["beds"]} beds: '
           f'{fs["growing"]} growing, {fs["ripe"]} ripe, {fs["wilted"]} wilted (save)']
    if rain:
        out.append('R1 water garden: SKIP (rain waters everything)')
    else:
        out.append(f'R1 water garden: {"DONE" if watered >= need else "DUE"} {watered}/{need} beds watered today'
                   + (f' · {fs["wilted"]} WILTED: water first' if fs['wilted'] else ''))
    out.append(f'R2 harvest ripe crops: {"DONE" if fs["ripe"] == 0 or harvested >= fs["ripe"] else "DUE"} '
               f'{fs["ripe"]} ripe per save, {harvested} harvested today')
    out.append('R3 bee hives (8): ❓ not modelled yet')
    run_log('routine', status=out[1:3])
    return '\n'.join(out)


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
    p = sub.add_parser('run', help='one dir per task (L76): wf run start <task> <goal…> | plan | step <n> start|done|'
                                   'fail|skip [note…] | escalate <n> <why…> | status | waits | attempt|issue|gap|decision|'
                                   'note <text…> | end <result> [text…] | report [path]')
    p.add_argument('sub')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('where', help='Tara on the map (pin) + nearest known place; --learn <name> stores it (L57)')
    p.add_argument('--learn')
    p = sub.add_parser('pos', help='EXACT world position now (checkpoint: game to background -> autosave -> read -> '
                                   'focus back); --learn <name> = this spot is that place (L62)')
    p.add_argument('--learn')
    p = sub.add_parser('calib', help='8 short hops on open ground -> refit screen -> world mapping for this scene (L62); '
                                     '--small = shorter hops for rooms (furniture clicks interact)')
    p.add_argument('--small', action='store_true')
    p = sub.add_parser('plan', help='world-graph plan to a place/anchor (no walking): steps walk/link/replay (L62)')
    p.add_argument('place')
    p = sub.add_parser('go-world', help='walk to world point X Z in this scene by calibrated clicks (L62)')
    p.add_argument('x', type=float)
    p.add_argument('z', type=float)
    sub.add_parser('coverage', help='coverage matrix: which map/area cells have all 4 nav layers; gaps of Tara\'s cell '
                                    '(no input, L67)')
    p = sub.add_parser('improve', help='auto-improver: fill the gaps of Tara\'s cell, walk to the nearest road cell '
                                       'without data, repeat N cells (L67)')
    p.add_argument('n', type=int, nargs='?', default=3)
    p = sub.add_parser('road', help='is Tara on a road? (screen road mask under her feet); --go = step onto the nearest '
                                    'road; --calibrate = she IS on a road: learn this lighting period\'s colours')
    p.add_argument('--go', action='store_true')
    p.add_argument('--calibrate', action='store_true')
    sub.add_parser('tara-box', help="Tara's box on screen (tracker): the zoom gauge (L85), no game input")
    p = sub.add_parser('world', help='the world model (shadow, M2): wf world [entities [kind]|tara|route X Z|explain ID]')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('bench', help='benchmark runs: wf bench start A|B|C | report [run dir] | compare [A|B|C]')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('objects', help='object examples + detection: wf objects list | add <kind> x0 y0 x1 y1 [state] | detect [kind..] | find <kind> | eval [dir] | calibrate [dir] | reembed')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('graph', help='object graph: show/where/path/view-add/sync/map-seed/map-heatmap')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('anchor', help='apply a structured vision answer to the object graph (no game input): wf anchor "<answer>"')
    p.add_argument('answer')
    p = sub.add_parser('eval', help='hits/misses of predictions: wf eval [all] | pending | mark <id> hit|miss')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('py', help='run game functions (tools/game, L77): wf py "for b in beds(wilted=True): replant(b)"')
    p.add_argument('args', nargs='+')
    p = sub.add_parser('call', help='run one game function: wf call garden.water 3')
    p.add_argument('args', nargs='+')
    p = sub.add_parser('ask-step', help='vision question with the goal and the 4 layers drawn on it: next click toward <place>')
    p.add_argument('place')
    p = sub.add_parser('record', help='video of the game window (daemon thread): record start|stop|status')
    p.add_argument('sub', choices=['start', 'stop', 'status'])
    p.add_argument('--fps', type=int, default=8)
    p.add_argument('--width', type=int, default=1280)
    sub.add_parser('pause', help='pause the game if it is running (checks first; Escape toggles)')
    sub.add_parser('resume', help='resume the game if it is paused (checks first)')
    sub.add_parser('routines', help="today's daily chores and their status (save + today's log); docs/routines.md")
    p = sub.add_parser('edge', help='anchored route edges: wf edge add <A> <B> x:y x:y … | replay <A> <B> | list')
    p.add_argument('sub')
    p.add_argument('args', nargs='*')
    p = sub.add_parser('teach', help='answer the last NEED_VISION question: wf teach road C5 D5 | wf teach next D6 | wf teach step X:Y')
    p.add_argument('kind')
    p.add_argument('cells', nargs='+')
    p = sub.add_parser('goto', help='walk to a known place by map route (localise → road BFS → go: hops): wf goto farmhouse')
    p.add_argument('place')
    p.add_argument('--hops', type=int, default=30)
    p = sub.add_parser('learn', help='self-improvement status: learned bubble kinds, accuracy, recent additions; '
                                     '`learn nav` = navigation loop (calibration, places, edges, blocks, L62)')
    p.add_argument('what', nargs='?')
    p = sub.add_parser('actions', help='action DB rows from docs/actions.md by tag (do/expect/verify): wf actions chop pickup [--all]')
    p.add_argument('tags', nargs='*')
    p.add_argument('--all', action='store_true')
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
    if a.cmd == 'actions':
        return actions(a.tags, a.all)
    if a.cmd == 'run':
        return run_cmd(a.sub, a.args)
    if a.cmd == 'tara-box':  # zoom gauge check (L85): her box on screen, no game input
        tr = Tara()
        for _ in range(4):
            tr.update(grab())
            time.sleep(0.1)
        x0, y0, x1, y1 = tr.box
        from world import zoom
        m = zoom.tara_mask(grab())
        print(f'tracker box ({x0:.0f}, {y0:.0f}, {x1:.0f}, {y1:.0f}) · height {y1 - y0:.0f} px (does not follow the zoom)')
        area = (seg_estimate() or (None,))[0] or 'Farm'
        ref = zoom.ref_load(area.split('/')[0] if '/' not in area else area)
        return print(f'mask box {m} · height {m[3] - m[1] if m else "?"} px · reference {ref} · zoom '
                     f'{zoom.gauge(m[3] - m[1], ref) if m and ref else "?"}')
    if a.cmd == 'world':  # inspection of the shadow world model, no game input
        return world_cmd(a.args)
    if a.cmd == 'bench':  # bookkeeping: no focus, no game input (review #1)
        return bench_cmd(a.args)
    if a.cmd == 'objects':
        return objects_cmd(a.args)
    if a.cmd == 'graph':
        return graph_cmd(a.args)
    if a.cmd == 'anchor':
        return anchor_cmd(a.answer)
    if a.cmd == 'eval':
        return eval_cmd(a.args)
    if a.cmd == 'learn':
        return print(learn_nav()) if a.what == 'nav' else learn_report()
    if a.cmd == 'coverage':
        return print(coverage_report())
    if a.cmd == 'routines':
        return print(routines())
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
    elif a.cmd == 'where':
        print(where(a.learn))
    elif a.cmd == 'goto':
        print(goto(a.place, a.hops))
    elif a.cmd == 'teach':
        print(teach(a.kind, a.cells))
    elif a.cmd == 'edge':
        if a.sub == 'add':
            print(edge_add(a.args[0], a.args[1], a.args[2:]))
        elif a.sub == 'replay':
            print(edge_replay(a.args[0], a.args[1]))
        else:
            print('\n'.join(f'{k}: {len(v["clicks"])} clicks, {v["ok"]} ok / {v["fail"]} fail' for k, v in edges().items())
                  or 'no edges')
    elif a.cmd == 'pos':
        import math
        p, f = checkpoint('arrived' if a.learn else None, goal=a.learn)
        print(f"POS {p['scene']} ({p['x']:.2f}, {p['y']:.2f}, {p['z']:.2f}) "
              f"{'fresh' if p['fresh'] else 'NO NEW SAVE (unchanged since last save, ' + str(round(p['age'])) + ' s old)'}"
              f" | D{p['day']} {p['hour']:.2f}h {p['weather']}" + (f" | pred error {math.dist(f['pred'], f['to']):.2f}"
                                                                    if f['pred'] else '')
              + (f" | learned place {a.learn}" if a.learn else ''))
    elif a.cmd == 'plan':
        st = graph_route(a.place)
        print('\n'.join(f'{kind:6} {k} {_xz(n)} {n["src"]}' for kind, k, n in st) if st
              else f'no world-graph route to {a.place}: goto falls back to the map route')
    elif a.cmd == 'go-world':
        print(go_world(a.x, a.z))
    elif a.cmd == 'improve':
        print(improve(a.n))
    elif a.cmd == 'calib':
        print(calibrate(CALIB_SMALL if a.small else CALIB_MOVES))
    elif a.cmd == 'road':
        img = grab()
        print(calibrate_road(img) if a.calibrate else to_road() if a.go else
              f'on road: {on_road(img):.0%} around her feet [{road_key(img)}]')
    elif a.cmd in ('py', 'call'):
        if game_cmd(a.cmd, a.args):
            sys.exit(1)
        return
    elif a.cmd == 'ask-step':
        import math
        import nav
        steps = graph_route(a.place) or []
        est = seg_estimate() or start_estimate()
        ahead = [nav.target_of(n) for kind, _, n in steps if kind == 'walk' and n['scene'] == est[0]
                 and nav.target_of(n) and math.dist(nav.target_of(n), est[1:]) > 1]
        d = (ahead[0][0] - est[1], ahead[0][1] - est[2]) if ahead else (0.0, -1.0)
        print(ask_step(a.place, d, 'asked on purpose', ahead))
        return
    elif a.cmd == 'record':
        print(record(a.sub, a.fps, a.width))
        return
    elif a.cmd in ('pause', 'resume'):
        print(set_paused(a.cmd == 'pause'))
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
    elif a.cmd in ('walk', 'path') or (a.cmd == 'hold' and set(a.keys) & set('wasd')):
        print(f'{a.cmd}: KEYBOARD MOVEMENT DISABLED (mouse only, user rule L54): use ./wf do go:<x>:<y>')
        return 2
    elif a.cmd == 'hold':
        hold_keys(a.keys, a.seconds)
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
        print('route: KEYBOARD MOVEMENT DISABLED (mouse only, user rule L54): use ./wf do go:<x>:<y>')
        return 2


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
            moves0 = MOVES[0]
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    main(argv)
                except SystemExit as e:
                    if isinstance(e.code, str):
                        print(e.code)
                        code = 1
                    else:
                        code = e.code or 0
                except Stuck as e:
                    print(e)
                    code = 1
                except Exception as e:  # keep serving
                    print(f'ERROR: {type(e).__name__}: {e}')
                    code = 1
                try:  # shadow world (M2): evidence after every command; its own try (review I8)
                    world_sync()
                except Exception:  # noqa: BLE001
                    pass
                if argv and argv[0] not in ('run', 'stop', 'status', 'eval', 'bench'):
                    try:
                        w = step_warning()
                        if w:
                            print(w)
                        if MOVES[0] > _TRACK_AT[0]:  # clicks without a reading (e.g. `do go:`)
                            est = seg_estimate() or start_estimate()
                            if est:
                                track_point(*est)
                    except Stuck as e:
                        print(e)
                    except Exception:
                        pass
            try:
                conn.sendall(json.dumps({'out': buf.getvalue(), 'code': code}).encode() + b'\n')
            except OSError:
                pass


if __name__ == '__main__':
    main()
