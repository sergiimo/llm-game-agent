"""Affordances (docs/mechanics/basic-actions.md "Interaction bubbles"): every bubble on screen is an action on offer.
`scan()` lists them with their kind (icon vectors, L56) and the object each sits above (world entities projected to
the screen); `use(action, target)` clicks the bubble relevant to the goal — a click works on any bubble, the highlight
only marks what Space would do — so the right one of several beds is used, and a bubble already showing (the well's
can) saves the walk. The proof stays the game log line."""
import math
from dataclasses import dataclass

from . import core
from .walk import PRECISE  # one threshold for "the belief is too loose to click/match by projection"

BUBBLE_UP = (40, 260)   # px: a bubble sits this far above its object's ground point (to verify live, image-checked)
BUBBLE_DX = 110         # px: horizontal tolerance between a bubble and its object
SAME = 1.0              # world units: the bubble's object is the target
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
    entity: object
    pt: tuple
    highlighted: bool
    dist: float
    drop: bool = False   # the water-drop sub-icon (top right): the crop needs water or has wilted (user, D183)


DROP_MIN = 300   # pale-blue drop pixels in the top-right corner: drop bubbles 610-750, others 0-55 (tools/bubbles)


def has_drop(crop):
    """The water-drop sub-icon, by colour (any crop icon can carry it): pale blue, unlike the beige bubble."""
    import numpy as np
    a = np.asarray(crop.convert('RGB').resize((140, 140))).astype(int)[5:60, 85:140]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return int(((b >= 225) & (b > r + 8) & (g > 200)).sum()) >= DROP_MIN

    def __str__(self):
        return (f'{self.kind}{"*" if self.highlighted else ""} @{self.pt[0]},{self.pt[1]} → '
                f'{self.entity if self.entity else "object unknown"}')


def _owner(w, H, a, b):
    from world import view
    best = None
    for e in w.entities(area=a):
        sx, sy = view._scr(H, w.belief, e.x, e.z)
        dy = sy - b[1]
        if abs(sx - b[0]) <= BUBBLE_DX and BUBBLE_UP[0] <= dy <= BUBBLE_UP[1]:
            score = abs(sx - b[0]) + abs(dy - sum(BUBBLE_UP) / 2)
            if best is None or score < best[0]:
                best = (score, e)
    return best[1] if best else None


def scan():
    """Every bubble on screen: kind, the entity it belongs to (None if the world can't tell), point, highlighted."""
    W = core.WF
    if not hasattr(W, 'find_bubbles'):
        return []
    w = W.world()
    img = W.grab()
    bubbles = W.find_bubbles(img)
    if bubbles and w.needs_fix() and hasattr(W, 'checkpoint'):  # stale belief → no owner matches (±5, D183)
        W.checkpoint(fill=False)
    a, _, _, _ = w.tara()
    c = W.calib_load(a) if a else None
    out = []
    for b in bubbles:
        kind, d = W.bubble_kind(img, b)
        ent = _owner(w, c['H'], a, b) if c and not w.needs_fix() else None
        drop = has_drop(W.bubble_crop(img, b)) if hasattr(W, 'bubble_crop') else False
        out.append(Affordance(kind, ent, tuple(b), bool(W.bubble_highlighted(img, b)), d, drop))
    return out


def relevant(aff, action, target=None):
    """Same action and, if a target is given, the bubble's object is that target. An unknown icon counts only for a
    given target it is matched to; never without one (day-walk: the hive's "unknown" honey bubble was clicked as the
    well's can)."""
    known = aff.kind in KINDS.get(action, {action})
    if not known and aff.kind != 'unknown':
        return False
    if target is None:
        return known
    return aff.entity is not None and math.dist((aff.entity.x, aff.entity.z), (target.x, target.z)) <= SAME


def in_reach(kind):
    """True when a bubble only an object of `kind` offers is on screen: that object is in reach, whatever the position
    estimate says (zoom-walk-2: at the well with the can bubble up, the belief was 9 units off)."""
    return any(OWNER.get(a.kind) == kind for a in scan())


def use(action, target=None):
    """Click the bubble relevant to (action, target) if one is on screen. True if clicked."""
    W = core.WF
    if target is not None and hasattr(W, 'checkpoint') and W.world().tara()[3] > PRECISE:
        W.checkpoint(fill=False)  # exact position first: a loose belief projects a neighbour's bubble onto the target
    for a in scan():
        if relevant(a, action, target):
            if a.kind == 'unknown':
                W.run_log('bubble_resolve', seen='unknown', inferred=action,
                          owner=getattr(a.entity, 'kind', None), point=list(a.pt), source='target-context')
            click(a)
            return True
    return False


def click(a):
    """Click a bubble and let the screen settle; returns the log mark taken just before (for the caller's proof)."""
    W = core.WF
    mark = W.log_mark()
    W.run_action(f'click:{a.pt[0]}:{a.pt[1]}')
    W.wait_settle()
    return mark


def press(action, target):
    """Use the target's bubble: click it if the world can match it, else walk there and Space on the highlighted one
    (the caller proves the result from the log)."""
    from . import ui
    from .move import goto
    if use(action, target):
        return
    goto(target)
    if not use(action, target):
        seen = scan()
        unknown = [a for a in seen if a.kind == 'unknown']
        if unknown:
            pts = ', '.join(f'{a.pt[0]},{a.pt[1]} owner={getattr(a.entity, "kind", None) or "unresolved"}'
                            for a in unknown)
            raise core.Failed(f'UNKNOWN_BUBBLE while seeking {action}: {pts}; resolve kind/owner before acting')
        if seen:  # Space would press a bubble that is not the target's (L109: the hive; replant-wilted-3: bed 8)
            raise core.Failed(f'no {action} bubble of {target} after walking; visible: '
                              + ', '.join(str(a) for a in seen))
        ui.press_bubble()


def no_click_zones():
    """Screen points of every bubble: a walking click must stay away from them (a click there is an action)."""
    return [a.pt for a in scan()]
