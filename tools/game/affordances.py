"""Affordances (docs/mechanics/basic-actions.md "Interaction bubbles"): every bubble on screen is an action on offer.
`scan()` lists them with their kind (icon vectors, L56), point, highlight and water-drop sub-icon, from the frame only
(no positions). The proof stays the game log line."""
from dataclasses import dataclass

from . import core

SAME = 1.0              # world units; kept only for game/walk.py (_bubble_up), removed with it in the follow-up plan
KINDS = {               # action -> bubble kinds (learned labels, L56) that offer it
    'water': {'water'}, 'fill_can': {'fill_can', 'full_watering_can'}, 'plant': {'plant'},
    'unplant': {'unplant'}, 'harvest': {'pickup'}, 'pickup': {'pickup'}, 'talk': {'talk'},
    'sleep': {'sleep'}, 'honey': {'honey', 'beehive_progress'}, 'beehive_progress': {'beehive_progress'},
}


OWNER = {'fill_can': 'Well', 'full_watering_can': 'Well', 'sleep': 'Bed',
         'beehive_progress': 'BeeHive'}  # bubble kinds only one kind of object offers


@dataclass
class Affordance:
    kind: str
    entity: object       # always None now (no world projection); kept for game/walk.py
    pt: tuple
    highlighted: bool
    dist: float
    drop: bool = False   # the water-drop sub-icon (top right): the crop needs water or has wilted (user, D183)

    def __str__(self):
        return f'{self.kind}{"*" if self.highlighted else ""}{" +drop" if self.drop else ""} @{self.pt[0]},{self.pt[1]}'


DROP_MIN = 300   # pale-blue drop pixels in the top-right corner: drop bubbles 610-750, others 0-55 (tools/bubbles)


def has_drop(crop):
    """The water-drop sub-icon, by colour (any crop icon can carry it): pale blue, unlike the beige bubble."""
    import numpy as np
    a = np.asarray(crop.convert('RGB').resize((140, 140))).astype(int)[5:60, 85:140]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return int(((b >= 225) & (b > r + 8) & (g > 200)).sum()) >= DROP_MIN


def scan():
    """Every bubble on screen: kind, point, highlighted, drop sub-icon (frame only)."""
    W = core.WF
    if not hasattr(W, 'find_bubbles'):
        return []
    img = W.grab()
    out = []
    for b in W.find_bubbles(img):
        kind, d = W.bubble_kind(img, b)
        drop = has_drop(W.bubble_crop(img, b)) if hasattr(W, 'bubble_crop') else False
        out.append(Affordance(kind, None, tuple(b), bool(W.bubble_highlighted(img, b)), d, drop))
    return out


def in_reach(kind):
    """True when a bubble only an object of `kind` offers is on screen: that object is in reach, whatever the position
    estimate says (zoom-walk-2: at the well with the can bubble up, the belief was 9 units off)."""
    return any(OWNER.get(a.kind) == kind for a in scan())


def click(a):
    """Click a bubble and let the screen settle; returns the log mark taken just before (for the caller's proof)."""
    W = core.WF
    mark = W.log_mark()
    W.run_action(f'click:{a.pt[0]}:{a.pt[1]}')
    W.wait_settle()
    return mark


def no_click_zones():
    """Screen points of every bubble: a walking click must stay away from them (a click there is an action)."""
    return [a.pt for a in scan()]
