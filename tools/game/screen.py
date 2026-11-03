"""SCREEN: the one reader of the screen state, with hard rules (design review D186: five places guessed it, Escape
toggled the pause menu, world clicks hit Exit Game).

States: gameplay | card (an info/detail card, e.g. "Tulip Bulbs … Select") | picker (the Inventory / Seeds panel) |
pause (Game Paused menu) | menu (settings or other buttons) | dialogue | popup | cutscene.
Rules:
- a world click only in gameplay (`require_world`): a card/picker is closed first, the pause menu resumed; anything
  else that stays = terminal (LawsStuck), never clicked through;
- Escape only on a known card or picker, once, and checked; the pause menu is never escaped into.
A textless overlay is gameplay (the HUD hides while the camera zooms on a bed, L144)."""
from dataclasses import dataclass, field

from . import core
from .observe import LawsStuck, paused

PICKER = ('inventory',)
MENU = ('settings', 'volume', 'return to menu', 'exit game', 'настройки', 'громкость')


def classify(mode, texts):
    low = [str(t).lower() for t in texts]
    if mode in ('dialogue', 'popup', 'cutscene'):
        return mode
    if mode == 'gameplay' or not texts:
        return 'gameplay'
    if paused(texts):
        return 'pause'
    if any(any(w in t for w in MENU) for t in low):
        return 'menu'
    if any(t.strip() in PICKER for t in low):
        return 'picker'
    return 'card'


@dataclass
class Screen:
    kind: str
    texts: list = field(default_factory=list)


def read():
    try:
        s = core.WF.state()
    except Exception:   # noqa: BLE001 (fakes / no frame): gameplay
        return Screen('gameplay', [])
    ts = [t.split(') ', 1)[-1] for t in s.get('text', [])]
    return Screen(classify(s.get('mode', 'gameplay'), ts), ts)


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
        core.WF.run_action('resume')
        _settle()
        return read()
    if s.kind not in ('card', 'picker'):
        return s
    core.WF.run_action('key:escape')
    _settle()
    after = read()
    if after.kind == 'pause':
        core.WF.run_action('resume')
        _settle()
        raise core.Failed(f'Escape opened the pause menu (resumed): the screen ({" / ".join(s.texts)[:120]}) was not '
                          f'a card Escape closes')
    return after


def require_world():
    """Before a world click: gameplay, or close what is open (twice at most); else terminal."""
    for _ in range(2):
        s = read()
        if s.kind == 'gameplay':
            return s
        close()
    s = read()
    if s.kind != 'gameplay':
        raise LawsStuck(f'SCREEN {s.kind.upper()}: {" / ".join(s.texts)[:120]} stays open; no world click is safe. '
                        f'Stop and report.')
    return s
