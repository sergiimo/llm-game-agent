"""Item icons (L78): Vision feature prints of item cards (pickers, inventory, shops), stored per name in
tools/items/<name>/*.png and labelled for free: whenever a card is opened, its detail card's title names it (the same
self-labelling as bubble kinds, L56). `match()` then finds a card by its icon without opening cards one by one."""
import os
import re
import time

from . import core

ITEM_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'items')
MAX_DIST = 0.6      # feature-print distance above this = not this item
DUP = 0.15          # closer than this to a stored icon = a near duplicate, not stored
CAP = 20            # icons per item
HALF = (50, 55, 50, 45)   # crop around a card's icon centre: left, up, right, down (px, 1920x1080 frame)
_REFS = None        # [(name, file, vector)]


def _key(name):
    return re.sub(r'[^\w]+', '_', name.strip()).strip('_')


def refs():
    global _REFS
    if _REFS is None:
        from PIL import Image
        _REFS = []
        for name in sorted(os.listdir(ITEM_DIR)) if os.path.isdir(ITEM_DIR) else []:
            d = os.path.join(ITEM_DIR, name)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith('.png'):
                    _REFS.append((name, f, core.WF._featureprint(Image.open(os.path.join(d, f)))))
    return _REFS


def crop(img, spot):
    x, y = spot
    left, up, right, down = HALF
    return img.crop((x - left, y - up, x + right, y + down))


def _dist(a, b):
    import numpy as np
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b)))


def match(icon):
    """(name, distance) of the closest stored item icon, or (None, distance) when nothing is close enough."""
    fp = core.WF._featureprint(icon)
    best = (None, 9.0)
    for name, _, v in refs():
        d = _dist(fp, v)
        if d < best[1]:
            best = (name, d)
    return best if best[1] <= MAX_DIST else (None, best[1])


def learn(icon, title):
    """Store an icon under its detail card's title (skips near duplicates; CAP per item). Returns True if stored."""
    name = _key(title)
    if not name:
        return False
    fp = core.WF._featureprint(icon)
    mine = [v for n, _, v in refs() if n == name]
    if len(mine) >= CAP or any(_dist(fp, v) < DUP for v in mine):
        return False
    d = os.path.join(ITEM_DIR, name)
    os.makedirs(d, exist_ok=True)
    f = f'{time.strftime("%Y%m%d-%H%M%S")}-{len(mine)}.png'
    icon.save(os.path.join(d, f))
    refs().append((name, f, fp))
    try:
        core.WF.run_log('learn', what='item_icon', name=name)
    except Exception:  # noqa: BLE001
        pass
    return True
