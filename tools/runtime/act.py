"""Actuators (spec 2026-10-30 §4): the only code that sends input to the game. Clicks are refused while a menu is
open (S13); pause and resume look at the screen before and after, never a blind Escape."""
WF = None
PAUSE_WORDS = ('game paused', 'пауза')


def bind(wf):
    global WF
    WF = wf


def _paused(s):
    return any(any(word in t.casefold() for word in PAUSE_WORDS) for t in s.get('text', []))


def click(x, y):
    """Click to move / interact; 'MENU OPEN (…)' when a menu is open (nothing is clicked)."""
    why = WF.menu_open(WF.state())
    if why:
        return f'MENU OPEN ({why}): close it first, never click through menus'
    return WF.go_to(x, y)


def key(k):
    WF.key(k)


def settle():
    WF.wait_settle()


def pause():
    """Pause from gameplay (one Escape); already paused = done. True when the pause menu is showing."""
    s = WF.state()
    if _paused(s):
        return True
    if s['mode'] != 'gameplay':
        return False  # another menu/dialogue: an Escape would close it, not pause
    WF.key('escape')
    settle()
    return _paused(WF.state())


def resume():
    """Resume only from the pause menu (one Escape). True when back in gameplay."""
    s = WF.state()
    if s['mode'] == 'gameplay':
        return True
    if not _paused(s):
        return False
    WF.key('escape')
    settle()
    return WF.state()['mode'] == 'gameplay'
