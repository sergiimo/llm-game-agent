"""ICONS: the crop a bubble shows, by its icon (user D188: "all crops except flowers for bees should be collected").

The save has no crop type and a ripe bed's bubble is the only sign of what it holds, so crop icons get their own
vector memory: tools/crop_icons/<Crop>/*.png, nearest neighbour on feature prints (Apple Vision; a pixel vector when
the tool has none). Labels come from vision's `name` answer once per new crop and from pick events after."""
import os
import re
import time

from . import core

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'crop_icons')
MAX_DIST = 0.6      # feature-print distance above this = not this crop
HALF = 56           # px half-size of the icon crop inside a bubble (1920x1080 frame)
_REFS = []          # [(name, vector)]; loaded once per DIR
_LOADED = [None]


def reset():
    _REFS.clear()
    _LOADED[0] = None


def _key(name):
    return re.sub(r'[^\w]+', '_', str(name).strip()).strip('_')


def _vec(img):
    fp = getattr(core.WF, '_featureprint', None)
    if fp is not None:
        try:
            return list(fp(img))
        except Exception:   # noqa: BLE001
            pass
    import numpy as np
    return list(np.asarray(img.convert('L').resize((16, 16)), dtype=float).ravel() / 255.0)


def _refs():
    if _LOADED[0] != DIR:
        from PIL import Image
        reset()
        _LOADED[0] = DIR
        for name in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
            d = os.path.join(DIR, name)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith('.png'):
                    _REFS.append((name, _vec(Image.open(os.path.join(d, f)))))
    return _REFS


def crop(img, pt):
    x, y = pt
    return img.crop((x - HALF, y - HALF, x + HALF, y + HALF))


def _dist(a, b):
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    return float(np.linalg.norm(a[:n] - b[:n]))


def match(icon):
    v = _vec(icon)
    best = min(((_dist(v, r), name) for name, r in _refs()), default=(9.0, None))
    return best[1].replace('_', ' ') if best[0] <= MAX_DIST else None


def name_of(a):
    """The crop the bubble `a` shows, or None (unknown: ask vision once)."""
    try:
        return match(crop(core.WF.grab(), a.pt))
    except Exception:   # noqa: BLE001
        return None


def save_crop(a):
    """The bubble's icon saved for a vision question; the path."""
    os.makedirs(DIR, exist_ok=True)
    p = os.path.join(DIR, f'_ask-{time.strftime("%H%M%S")}.png')
    crop(core.WF.grab(), a.pt).convert('RGB').save(p)
    return p


def learn_file(path, name):
    """vision named the icon saved at `path`: store it as `name`. True when stored."""
    from PIL import Image
    key = _key(name)
    if not key or not os.path.exists(path):
        return False
    d = os.path.join(DIR, key)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f'{time.strftime("%Y%m%d-%H%M%S")}.png')
    img = Image.open(path)
    img.save(out)
    _refs().append((key, _vec(img)))
    try:
        os.remove(path)
    except OSError:
        pass
    return True
