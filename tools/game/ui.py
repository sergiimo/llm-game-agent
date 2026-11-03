"""Screen interactions (L77): the bubble, buttons, cards, menus. No game logic here."""
import time

from . import core
from .core import Failed, action


def texts():
    return [t.split(') ', 1)[-1] for t in core.WF.state().get('text', [])]


def shows(word, wait=2.0):
    """True when on-screen text contains `word` (case-insensitive), polling up to `wait` s."""
    end = time.time() + wait
    while True:
        if any(word.lower() in t.lower() for t in texts()):
            return True
        if time.time() >= end:
            return False
        time.sleep(0.3)


def _settle():
    core.WF.wait_settle()


@action
def press_bubble():
    """Space on the highlighted bubble (whatever it is: the caller proves the result)."""
    msg = core.WF.run_action('key:space')
    _settle()
    if msg:
        raise Failed(msg)


@action
def press(label):
    """Click the on-screen button/card labelled `label`: an exact text match first (a question like "…remove
    Tulip?" must not count as the Remove button), else the first text containing it."""
    hits = core.WF.find_text(label, exact=True) or core.WF.find_text(label)
    if not hits:
        raise Failed(f'no "{label}" on screen; on screen: {" / ".join(texts())[:160]}')
    core.WF.run_action(f'click:{hits[0]["cx"]}:{hits[0]["cy"]}')
    _settle()


PICKER = (0, 260, 680, 560)   # x, y, w, h: the inventory-style picker on the left (planting panel, D148)
CARD_UP = 60                  # px from a card's count number up to the card's icon
FIRST_CARD = (110, 540)       # the first card's slot (planting-panel.md); the panel opens with it HIGHLIGHTED (D183)


DETAIL_TITLE = (180, 315, 500, 80)   # x, y, w, h: the title band of a picker's detail card ("Green Bean Seeds")


def card_spots(box=PICKER, img=None):
    """Picker cards (icon + count, no name): one per count number, left → right, top → bottom."""
    x, y, w, h = box
    img = img or core.WF.grab()
    hits = [r for r in core.WF.ocr_image(img.crop((x, y, x + w, y + h)), scale=1, offset=(x, y))
            if r['text'].strip().isdigit()]
    return [(int(r['cx']), int(r['cy']) - CARD_UP) for r in sorted(hits, key=lambda r: (round(r['cy'] / 40), r['cx']))]


def detail_title():
    """The open detail card's title, by OCR of its title band ('' if none)."""
    x, y, w, h = DETAIL_TITLE
    lines = core.WF.ocr_image(core.WF.grab().crop((x, y, x + w, y + h)), scale=1, offset=(x, y))
    words = [r['text'].strip() for r in lines if r['text'].strip() and not r['text'].strip().isdigit()]
    return words[0] if words else ''


def _named(title, name):
    return name.lower() in title.lower().replace('_', ' ')


@action
def pick_card(name, box=PICKER):
    """Pick the card for `name` in a picker whose cards show only an icon and a count (planting panel). Cards known
    by their icon (tools/items, L78) are tried first; every card opened teaches its icon under its detail title, so
    the next pick is one click. The picker opens on the first card's detail (D148): if that's `name`, done."""
    from . import items
    if shows('Select', wait=1.0):
        # the list cards carry no names, so a name anywhere on screen is the open detail card's title (D183: the
        # fixed title band read '' while the screen said "Green Bean Seeds" → Escape, then the count "6" was missed)
        if _named(detail_title(), name) or any(_named(t, name) for t in texts()):
            return name
        core.WF.run_action('key:escape')  # back to the list
        _settle()
    img = core.WF.grab()
    spots = card_spots(box, img)
    if not any(abs(s[0] - FIRST_CARD[0]) < 70 and abs(s[1] - FIRST_CARD[1]) < 70 for s in spots):
        spots = [FIRST_CARD] + spots  # a single-digit count isn't read by OCR (Green Bean 6, D183): the slot is fixed
    known = {s: items.match(items.crop(img, s))[0] for s in spots}
    order = ([s for s in spots if known[s] and _named(known[s], name)] + [s for s in spots if not known[s]] +
             [s for s in spots if known[s] and not _named(known[s], name)])
    if any(_named(t, name) for t in texts()):  # the highlighted first card names `name`: open it first
        order = [FIRST_CARD] + [s for s in order if s != FIRST_CARD]
    for x, y in order:
        core.WF.run_action(f'click:{x}:{y}')
        _settle()
        opened = shows('Select', wait=1.0)   # the card's modal with its Select button
        on_screen = texts()
        named = next((t for t in on_screen if _named(t, name)), '')
        if opened:   # the modal's own text names the card (the fixed title band misread 'ılbs', D186)
            title = named or detail_title()
        else:   # D186: the card is highlighted, its name in a tooltip, no detail/Select: picked; confirming is next
            if named:
                return named
            title = ''
        if title and title in on_screen:   # an icon is learned only under a name the screen shows
            items.learn(items.crop(img, (x, y)), title)
        if _named(title, name):
            return title
        core.WF.run_action('key:escape')  # wrong card: its detail closes, the list stays
        _settle()
    raise Failed(f'no "{name}" among {len(spots)} cards; ' + core.ask_vision(f'which card in the picker is {name}?'))



@action
def close():
    """Close a menu/card: one Escape, only on a screen with something to close. The pause menu is resumed, never
    escaped into; an overlay without text (HUD hidden, camera on a bed) gets no Escape; an Escape that opened the pause
    menu is undone (resume) and reported (live D186: Escapes into the pause menu, then world clicks exited the game)."""
    from .observe import paused
    s = core.WF.state()
    ts = [t.split(') ', 1)[-1] for t in s.get('text', [])]
    if paused(ts):
        core.WF.run_action('resume')
        _settle()
        return
    if s['mode'] == 'gameplay' or not ts:
        return
    core.WF.run_action('key:escape')
    _settle()
    after = [t.split(') ', 1)[-1] for t in core.WF.state().get('text', [])]
    if paused(after):
        core.WF.run_action('resume')
        _settle()
        raise Failed(f'Escape opened the pause menu (resumed): the screen ({" / ".join(ts)[:120]}) was not a card '
                     f'Escape closes')
