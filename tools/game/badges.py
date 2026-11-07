"""BADGES: wave 1 of reading a bubble (user D189: "search embeds in waves - first just exclamation marks and water
drops, then other crops. So we don't need to store all combinations").

A bubble = an icon (the crop, the well, the bed...) + a badge at its top right: `ready` (the orange "!"), `drop` (the
pale-blue water drop: needs water or wilted) or `none`. The badge looks the same on every icon, so its corner gets its
own small embedding store - tools/badges/<label>/*.png, nearest neighbour on feature prints (icons._vec) - and the icon
is read in wave 2 with the corner masked (icons.masked). No crop x state combinations are stored.

Labels come only from click results (the integrator's memory consumer): a Collect prompt = ready, a crop card with
days left = none, a water event = drop. An empty store reads nothing (the colour readers in affordances decide)."""
import os
import time

from . import icons

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'badges')
LABELS = ('ready', 'drop', 'none')
CORNER = (76, 0, 140, 64)   # px of the 140-px bubble crop: the badge sits at ~(117, 24) (live D189 crops)
MAX_DIST = 0.6              # feature-print distance above this = an unknown corner
_REFS = []
_LOADED = [None]


def reset():
    _REFS.clear()
    _LOADED[0] = None


def corner(crop140):
    """The badge corner of a bubble crop, taken relative to the disc centre (icons.disc_centre: the finder's point is
    up to ~20 px off, live D189)."""
    from PIL import Image
    c = crop140.convert('RGB')
    if c.size != (140, 140):
        c = c.resize((140, 140))
    cx, cy = icons._centroid(c) or (70, 70)
    pad = Image.new('RGB', (280, 280), (90, 60, 40))
    pad.paste(c, (70, 70))
    x0, y0 = round(cx - 70 + 70), round(cy - 70 + 70)   # the 140 box centred on the disc, in pad coordinates
    return pad.crop((x0 + CORNER[0], y0 + CORNER[1], x0 + CORNER[2], y0 + CORNER[3]))


def _refs():
    from .data import image_revision
    revision = image_revision(DIR)
    if _LOADED[0] != revision:
        from PIL import Image
        reset()
        _LOADED[0] = revision
        for label in LABELS:
            d = os.path.join(DIR, label)
            for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                if f.endswith('.png'):
                    _REFS.append((label, icons._vec(Image.open(os.path.join(d, f)).convert('RGB'))))
    return _REFS


def read(crop140):
    """'ready' | 'drop' | 'none', or None (the store doesn't know this corner, or is empty)."""
    refs = _refs()
    if len({name for name, _ in refs}) < 2:   # one label can't be told from the others yet: the colour readers decide
        return None
    v = icons._vec(corner(crop140))
    d, label = min((icons._dist(v, r), name) for name, r in refs)
    return label if d <= MAX_DIST else None


def add(label, crop140, source):
    """Store the corner of a 140-px bubble crop as an example of `label` (a click result proved it). The path."""
    if label not in LABELS:
        raise ValueError(f'badge label {label!r} is not one of {LABELS}')
    d = os.path.join(DIR, label)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{time.strftime("%Y%m%d-%H%M%S")}-{len(os.listdir(d))}.png')
    corner(crop140).save(p)
    with open(os.path.join(DIR, 'sources.txt'), 'a') as f:
        f.write(f'{os.path.basename(p)}\t{label}\t{source}\n')
    reset()
    return p
