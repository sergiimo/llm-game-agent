"""SCREEN: the one reader of the screen state, with hard rules (design review D186: five places guessed it, Escape
toggled the pause menu, world clicks hit Exit Game).

States: gameplay | card (an info/detail card, e.g. "Tulip Bulbs … Select") | picker (the Inventory / Seeds panel) |
pause (Game Paused menu) | menu (settings or other buttons) | dialogue | popup | cutscene | unknown.
Rules:
- a world click only in gameplay (`require_world`): a card/picker is closed first, the pause menu resumed; anything
  else that stays = terminal (LawsStuck), never clicked through;
- Escape only on a known card or picker, once, and checked; the pause menu is never escaped into.
A textless overlay is gameplay unless both the full paper map panel and its pin are proved (the HUD also hides on beds, L144)."""
import re
import os
from functools import lru_cache
from dataclasses import dataclass, field

from . import core
from .observe import LawsStuck, paused

PICKER = ('inventory',)
BUTTONS = ('select', 'remove', 'cancel', 'confirm', 'buy', 'sell', 'collect', 'yes', 'no', 'ok')
# Numeric object-progress/detail markers; descriptions alone also occur in transient hints.
DETAIL = re.compile(r'\b\d+ days? remaining\b|\bmakes\s+\d+\b', re.I)
HINTS = ('fill watering can', 'rusty watering can')  # verified passive watering hints, not arbitrary OCR text
HINT_WAIT = 4.0   # s a short hint gets to fade (the watering-can hint lasts longer than one settle, D186)
MAP_HEADER_TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'map-header.png')
MAP_HEADER_COSINE = .80


def passive(s):
    """Buttonless hints/toasts may fade without Escape; object progress details must be checked and closed."""
    return (s.kind == 'card' and not any(t.strip().lower() in BUTTONS for t in s.texts)
            and not any(DETAIL.search(t) for t in s.texts))


def _wait_hint(s):
    import time
    end = time.time() + HINT_WAIT
    while passive(s) and time.time() < end:
        _settle()
        time.sleep(0.3)
        s = read()
    return s
MENU = ('settings', 'volume', 'return to menu', 'exit game', 'настройки', 'громкость')


def map_panel(image):
    """Positive full-modal layout evidence, independent of pin-colored pixels in world scenery/HUD.

    The large map has a continuous pale paper border on all four sides. Check broad normalized border
    bands, not the M hotkey icon or a pink candidate alone. Missing layout remains unproved.
    """
    import numpy as np
    pixels = np.asarray(image.convert('RGB'), dtype=np.int16)
    r, g, b = pixels[..., 0], pixels[..., 1], pixels[..., 2]
    paper = (r >= 190) & (g >= 175) & (b >= 145) & (r >= g) & (g >= b) & (r - b <= 80)
    height, width = paper.shape
    if height < 100 or width < 100:
        return False
    rows = paper[:, int(.2 * width):int(.8 * width)].mean(axis=1)
    columns = paper[int(.2 * height):int(.8 * height), :].mean(axis=0)
    bands = ((rows[int(.08 * height):int(.25 * height)], height, .005),
             (rows[int(.75 * height):int(.92 * height)], height, .005),
             (columns[int(.1 * width):int(.25 * width)], width, .0025),
             (columns[int(.75 * width):int(.9 * width)], width, .0025))
    return all(int((band >= .95).sum()) >= max(2, int(ratio * extent))
               for band, extent, ratio in bands)


@lru_cache(maxsize=1)
def _map_header_reference():
    """The user-labelled paper/cloud map header as an appearance vector and its aspect ratio."""
    from PIL import Image
    from objects import dino
    with Image.open(MAP_HEADER_TEMPLATE) as image:
        rgb = image.convert('RGB')
        return rgb.width / rgb.height, dino.mean_vector(rgb)


def map_header_vector(image):
    """Whether the fixed top strip matches the labelled world-map header appearance."""
    from objects import dino
    aspect, reference = _map_header_reference()
    height = round(image.width / aspect)
    if height <= 0 or height > image.height:
        return False
    candidate = dino.mean_vector(image.convert('RGB').crop((0, 0, image.width, height)))
    return float(reference @ candidate) >= MAP_HEADER_COSINE


def classify(mode, texts, *, world_visible=False):
    low = [str(t).lower() for t in texts]
    # The daemon can retain its pre-pause mode (notably ``cutscene``) while the
    # pause overlay is on top.  Visible pause controls are stronger evidence
    # than that stale underlying mode.
    if paused(texts):
        return 'pause'
    # End-of-day exhaustion is a one-action modal.  The daemon reports its
    # overlay mode as unknown, but the visible copy/button is positive modal
    # evidence and must remain actionable rather than being mistaken for the
    # world behind it.
    if (any(('exhausted' in t or 'out of time' in t or "time's up" in t) for t in low)
            and any(('zzz' in t) for t in low)):
        return 'popup'
    if mode in ('dialogue', 'popup', 'cutscene'):
        return mode
    if mode == 'gameplay' or not any(str(t).strip() for t in texts):
        return 'gameplay'
    if any(any(w in t for w in MENU) for t in low):
        return 'menu'
    if any(t.strip() in PICKER for t in low):
        return 'picker'
    # Text length never proves a card (live "ain" / "NATE"). Require semantic controls/detail/hint structure.
    if any(t.strip() in BUTTONS or DETAIL.search(t) or any(t.startswith(h) for h in HINTS) for t in low):
        return 'card'
    # Recognized world affordances are a positive clue, subordinate to real modal controls above. Without
    # either signal, preserve uncertainty: neither Escape nor a world click is safe on an unknown overlay.
    return 'gameplay' if world_visible else 'unknown'


@dataclass
class Screen:
    kind: str
    texts: list = field(default_factory=list)
    controls: list = field(default_factory=list)


def read(*, world_visible=False, image=None):
    try:
        s = core.WF.classify(image) if image is not None and hasattr(core.WF, 'classify') else core.WF.state()
    except Exception:   # noqa: BLE001 (legacy fakes / no frame retain compatibility)
        return Screen('unknown' if image is not None else 'gameplay', [])
    raw = s.get('text', [])
    ts = [t.split(') ', 1)[-1] for t in raw]
    controls = []
    for text in raw:
        match = re.match(r'^\((\d+),(\d+)\)\s+(.+)$', str(text))
        if match:
            controls.append({'label': match[3].strip(), 'point': [int(match[1]), int(match[2])]})
    return Screen(classify(s.get('mode', 'gameplay'), ts, world_visible=world_visible), ts, controls)


def _settle():
    try:
        core.WF.wait_settle()
    except Exception:   # noqa: BLE001
        pass


def close():
    """Back toward gameplay by the rules: pause -> resume; card/picker -> one Escape (checked: an Escape that opened
    the pause menu is undone and reported). Returns the screen after; raises core.Failed when Escape misbehaved."""
    s = read()
    if s.kind == 'pause':
        # Escape is nominally a pause toggle, but live cutscene/pause overlays
        # can ignore it while still accepting their explicit button.  Clicking
        # the named control also cannot accidentally open the pause menu.
        msg = core.WF.run_action('text:Resume Game')
        _settle()
        if msg or read().kind == 'pause':   # locale/OCR fallback: idempotent daemon resume
            core.WF.run_action('resume')
            _settle()
        return read()
    if s.kind not in ('card', 'picker'):
        return s
    if s.kind == 'card' and any(DETAIL.search(t) for t in s.texts):
        # Burst crop info can fade too. Only Escape a detail card still present after settling.
        _settle()
        s = read()
        if s.kind not in ('card', 'picker'):
            return s
    if passive(s):   # a hint ("Fill watering can at the / Well", D186): wait, never Escape
        _settle()
        return _wait_hint(read())
    core.WF.run_action('key:escape')
    _settle()
    after = read()
    if after.kind == 'pause':
        core.WF.run_action('resume')
        _settle()
        raise core.Failed(f'Escape opened the pause menu (resumed): the screen ({" / ".join(s.texts)[:120]}) was not '
                          f'a card Escape closes')
    return after


def _world_screen():
    """Recheck the live map signal whenever an overlay transition may have revealed it."""
    map_pin = getattr(core.WF, 'map_pin', None)
    if map_pin is not None and map_pin(core.WF.grab()):
        for control in ('escape', 'm'):
            core.WF.run_action(f'key:{control}')
            _settle()
            if not map_pin(core.WF.grab()):
                break
        else:
            raise LawsStuck('SCREEN MAP: Escape and M did not close the map; no world perception or click is safe. '
                            'Stop and report.')
    return read()


def require_world():
    """Before a world click: gameplay, or close what is open (twice at most); else terminal."""
    for _ in range(2):
        s = _world_screen()
        if s.kind == 'gameplay':
            return s
        if passive(s):   # a tooltip / hint ("Rusty Watering Can", D186): wait it out; a world click is safe under it
            _settle()
            _wait_hint(s)
            s = _world_screen()
            return s if s.kind == 'gameplay' or passive(s) else require_world()
        close()
    s = _world_screen()
    if s.kind != 'gameplay':
        raise LawsStuck(f'SCREEN {s.kind.upper()}: {" / ".join(s.texts)[:120]} stays open; no world click is safe. '
                        f'Stop and report.')
    return s
