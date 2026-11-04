"""Affordances (docs/mechanics/basic-actions.md "Interaction bubbles"): every bubble on screen is an action on offer.
`scan()` lists them with their kind (icon vectors, L56), point, highlight and water-drop sub-icon, from the frame only
(no positions). The proof stays the game log line."""
from dataclasses import dataclass

from . import core

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
    entity: object       # always None (no world projection); positional slot kept for callers
    pt: tuple
    highlighted: bool
    dist: float
    drop: bool = False   # the water-drop sub-icon (top right): the crop needs water or has wilted (user, D183)
    ready: bool = False  # the orange "!" sub-icon (top right): its product is ready to collect - NOT an order to collect
                         # (user D185: flowers serve the bees); only `drop` means "needs water"
    badge: str = None    # wave 1 (game/badges.py): 'ready' | 'drop' | 'none' from the badge store; None = colour readers
    icon: str = None     # wave 2: the crop its icon shows (crop-icon memory, badge masked); None = unknown

    def __str__(self):
        return f'{self.kind}{"*" if self.highlighted else ""}{" +drop" if self.drop else ""}{" +ready" if self.ready else ""} @{self.pt[0]},{self.pt[1]}'


DROP_MIN = 300   # pale-blue drop pixels in the top-right corner: drop bubbles 610-750, others 0-55 (tools/bubbles)


def has_drop(crop):
    """The water-drop sub-icon, by colour (any crop icon can carry it): pale blue, unlike the beige bubble."""
    import numpy as np
    a = np.asarray(crop.convert('RGB').resize((140, 140))).astype(int)[5:60, 85:140]
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return int(((b >= 225) & (b > r + 8) & (g > 200)).sum()) >= DROP_MIN


READY_MIN = 70   # orange px: top-right window minus the larger of the top-left/bottom-left ones (the selection ring is
                 # symmetric: <= 44 on 40 samples; the "!" badge: 104-111 on 4 samples, D185)


def has_ready(crop):
    """The orange "!" sub-icon at the top right (a ready product), told from the symmetric orange selection ring."""
    import numpy as np
    a = np.asarray(crop.convert('RGB').resize((140, 140))).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    orange = (r >= 200) & (g >= 100) & (g <= 190) & (b <= 110)
    ys, xs = np.ogrid[:140, :140]

    def win(cx, cy, rad=14):
        return int((orange & ((xs - cx) ** 2 + (ys - cy) ** 2 <= rad * rad)).sum())
    return win(105, 35) - max(win(35, 35), win(35, 105)) >= READY_MIN


def scan():
    """Every bubble on screen: kind, point, highlighted, drop sub-icon (frame only)."""
    W = core.WF
    if not hasattr(W, 'find_bubbles'):
        return []
    img = W.grab()
    out = []
    from . import badges, icons
    for b in W.find_bubbles(img):
        kind, d = W.bubble_kind(img, b)
        crop = W.bubble_crop(img, b) if hasattr(W, 'bubble_crop') else None
        if crop is not None:
            try:
                crop = icons.bubble140(img, b)   # around the disc centre (the finder's point is up to ~20 px off)
            except Exception:   # noqa: BLE001
                pass
        badge = icon = None
        if crop is not None:   # wave 1: the badge corner; wave 2: the icon - both around the disc centre (D189)
            try:
                badge = badges.read(crop)
                icon = icons.match(crop)
            except Exception:   # noqa: BLE001 (reading never breaks the scan)
                badge = icon = None
        blue = has_drop(crop) if crop is not None else False   # the pale-blue drop by colour is reliable
        if badge is not None:
            drop, ready = badge == 'drop' or blue, badge == 'ready' and not blue   # a drop is never "ready" (D189)
        else:   # the store doesn't know this corner yet: the colour readers
            drop = blue
            ready = (has_ready(crop) if crop is not None else False) and not blue
        out.append(Affordance(kind, None, tuple(b), bool(W.bubble_highlighted(img, b)), d, drop, ready, badge, icon))
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


# ---- soil (user D185: light-brown bed soil = needs water, dark brown = watered) ----------------------------------------
SOIL_CELL = 24          # px cells of the soil heat map (1920x1080 frame)
SOIL_MIN = 0.35         # share of soil-coloured pixels in a cell for it to count as bed soil
DRY_TONE = 88           # median grey of a cell's soil pixels: >= dry (light brown) ...
WET_TONE = 80           # ... <= watered (dark brown). D185 1:20 pm frame: dry beds 93-98, watered 73-74 (mixed 87)


def soil_map(img):
    """Per SOIL_CELL cell: 'dry' | 'wet' | None (not soil, or between the tones). Bed soil only (brown: r > g > b, not
    the light wooden frames, not grass). Daylight tones; at night the tones drop and cells read 'wet' or None."""
    import numpy as np
    a = np.asarray(img.convert('RGB'), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    soil = (r > g) & (g > b) & (r - b >= 40) & (r - b <= 115) & (r < 175) & (g - b >= 15) & (g < r - 20)
    grey = (r + g + b) // 3
    h, w = a.shape[0] // SOIL_CELL, a.shape[1] // SOIL_CELL
    out = np.full((h, w), None, dtype=object)
    for j in range(h):
        for i in range(w):
            sl = (slice(j * SOIL_CELL, (j + 1) * SOIL_CELL), slice(i * SOIL_CELL, (i + 1) * SOIL_CELL))
            m = soil[sl]
            if m.mean() < SOIL_MIN:
                continue
            t = float(np.median(grey[sl][m]))
            out[j, i] = 'dry' if t >= DRY_TONE else 'wet' if t <= WET_TONE else None
    return out


def dry_spots(img, min_cells=20):
    """Centres of dry-soil blobs (connected 'dry' cells, >= min_cells: a bed, not a speck), largest first: [(x, y, n)].
    min_cells 20 (D185: 6-12 cell blobs were fence, grass edges and a hive; beds read 29-295 cells)."""
    m = soil_map(img)
    h, w = m.shape
    seen, out = set(), []
    for j in range(h):
        for i in range(w):
            if m[j, i] != 'dry' or (j, i) in seen:
                continue
            stack, cells = [(j, i)], []
            seen.add((j, i))
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and (ny, nx) not in seen and m[ny, nx] == 'dry':
                        seen.add((ny, nx))
                        stack.append((ny, nx))
            if len(cells) >= min_cells:
                cy = sum(c[0] for c in cells) / len(cells)
                cx = sum(c[1] for c in cells) / len(cells)
                out.append((int((cx + .5) * SOIL_CELL), int((cy + .5) * SOIL_CELL), len(cells)))
    return sorted(out, key=lambda t: -t[2])


def soil_counts(img):
    """(dry cells, wet cells) on the frame: the group's soil state as seen now (a hint for the graph)."""
    m = soil_map(img)
    flat = list(m.ravel())
    return flat.count('dry'), flat.count('wet')
