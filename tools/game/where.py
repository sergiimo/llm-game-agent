"""WHERE: Tara's world position (user D186: "walking should be based on graph or map and should make you closer to
the goal graph node"). Walking logs nothing, so after a walk only the map knows where she is.

- 'event': a positioned log line since the last walk (exact: the object she interacted with)
- 'map':   the map pin (wf.map_snapshot + map_pin) through a calibration learned from (event position, pin) pairs:
           map_x = ox + s * x, map_y = oy - s * z (camera and map both look north; one scale)
Pairs are added by `calibrate_here()` right after a positioned event (before she walks)."""
import json
import os
import re
import time

from . import core

CALIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'map_calib.json')
MIN_SPREAD = 5.0     # world units between pairs for a usable scale
MAX_ERR = 2.0        # world units: a fit whose pairs disagree more than this is no calibration (D187: 10 units off)
WALK_TTL = 30.0      # s: a dead-reckoned walk end is used this long (live D188: a stale one from an earlier attempt)
_AT = re.compile(r' at \(([-\d.]+), [-\d.]+, ([-\d.]+)\)')
_WALK = {}           # {'mark': log mark} of the last walk (also on disk: a daemon restart must not forget it)
WALK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.shots',
                    'where-walk.json')


def pairs():
    try:
        with open(CALIB) as f:
            return json.load(f).get('pairs', [])
    except (OSError, ValueError):
        return []


def add_pair(world, pin):
    ps = pairs() + [[[round(world[0], 2), round(world[1], 2)], [int(pin[0]), int(pin[1])]]]
    with open(CALIB, 'w') as f:
        json.dump({'_doc': 'world (x, z) <-> map pin (px) pairs, learned (game/where.py)', 'pairs': ps[-40:]}, f, indent=1)


def fit():
    """(s, ox, oy) by least squares, or None (fewer than 2 pairs MIN_SPREAD apart)."""
    import math
    import numpy as np
    ps = pairs()
    if len(ps) < 2 or max(math.dist(a[0], b[0]) for a in ps for b in ps) < MIN_SPREAD:
        return None
    A, y = [], []
    for (x, z), (mx, my) in ps:
        A.append([x, 1, 0]); y.append(mx)
        A.append([-z, 0, 1]); y.append(my)
    s, ox, oy = np.linalg.lstsq(np.array(A, float), np.array(y, float), rcond=None)[0]
    if s <= 0:
        return None
    err = max(math.dist((x, z), ((mx - ox) / s, -(my - oy) / s)) for (x, z), (mx, my) in ps)
    return (float(s), float(ox), float(oy)) if err <= MAX_ERR else None


def to_world(pin):
    f = fit()
    if f is None or pin is None:
        return None
    s, ox, oy = f
    return ((pin[0] - ox) / s, -(pin[1] - oy) / s)


def walked(to=None):
    """A walk click: the event position is stale from now until the next positioned event. `to` = where a short
    walk to a visible ground point took her (the game pathfinds to the clicked point): good enough to find a bubble
    by its expected point (engine strategy A), never for navigation."""
    _WALK['mark'] = core.WF.log_mark()
    _WALK['to'] = [round(to[0], 2), round(to[1], 2)] if to else None
    _WALK['at'] = time.time()
    try:
        os.makedirs(os.path.dirname(WALK), exist_ok=True)
        with open(WALK, 'w') as f:
            json.dump({'mark': _WALK['mark'], 'to': _WALK['to'], 'at': _WALK['at']}, f)
    except (OSError, TypeError):
        pass


def _walk_mark():
    if 'mark' not in _WALK:
        try:
            with open(WALK) as f:
                d = json.load(f)
            _WALK['mark'], _WALK['to'], _WALK['at'] = d['mark'], d.get('to'), d.get('at')
        except (OSError, ValueError, KeyError):
            return None
    return _WALK['mark']


def _event_pos():
    mark = _walk_mark()
    if mark is not None:
        try:
            lines = core.log_text(mark).splitlines()
        except Exception:   # noqa: BLE001 (a new log file: the mark is from another session)
            lines = []
    else:
        try:
            lines = core.WF.today_log()[0]
        except Exception:   # noqa: BLE001
            lines = []
    for line in reversed(lines):
        m = _AT.search(line)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def pin_now():
    try:
        img = core.WF.map_snapshot()
        return core.WF.map_pin(img) if img is not None else None
    except Exception:   # noqa: BLE001
        return None


def position(far_ok=True, walk_ok=False):
    """('event' | 'walk' | 'map', (x, z)) or (None, None). 'walk' (with `walk_ok`) = the end of the last short walk
    to a visible point. The map pin only with `far_ok` (user D187: the map is imprecise - use it only for very-far
    navigation; near decisions use events and visible objects)."""
    p = _event_pos()
    if p is not None:
        return 'event', p
    if walk_ok and _walk_mark() is not None and _WALK.get('to') and time.time() - (_WALK.get('at') or 0) <= WALK_TTL:
        return 'walk', tuple(_WALK['to'])
    if not far_ok:
        return None, None
    w = to_world(pin_now())
    return ('map', w) if w is not None else (None, None)


def invalidated_by_unpositioned_walk():
    """True after a walk with no known endpoint and no later positioned event.

    The saved position is stale after movement; without a walk endpoint, object projections must stay unknown.
    """
    return _walk_mark() is not None and _WALK.get('to') is None and _event_pos() is None


def calibrate_here():
    """A fresh event position + the map pin now = one more pair. True when added."""
    p = _event_pos()
    if p is None:
        return False
    pin = pin_now()
    if pin is None:
        return False
    add_pair(p, pin)
    return True
