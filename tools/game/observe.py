"""OBSERVE: read the frame, never act (framework: observe -> act -> learn -> nav, docs/mechanics/interaction-laws.md).

Everything here is derived fresh from the current frame/screen; nothing is carried between frames (law: no positions).
- bubbles (`affordances.scan`): kind, drop (needs water / wilted), ready ("!": product ready, not an order to collect)
- soil heat map: light-brown = needs water, dark = watered (daylight)
- the closest graph node to Tara (she is always at CENTRE)
- object detections by appearance vectors (objects/detect)
- the screen mode/texts, the clock (hour + light period), the UI language"""
import re

from . import affordances, core

CENTRE = (960, 540)
W_, H_ = 1920, 1080
HUD = ((0, 0, 520, 230), (1440, 0, 1920, 230))   # clock / map-journal-inventory buttons: never a world click
MOVED = 6.0          # mean abs grey difference (0-255) between first and last burst frame = the view changed
SEE_NEAR = 160       # px: a detection this close to Tara is where she already is (its bubble would show)
NEAR_NODE = 420      # px: a detected object this close to Tara is the node she stands at


def _kinds():
    import json
    import os
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kinds.json')) as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith('_')}
    except (OSError, ValueError):
        return {}


NODE_OF = {k: v['node'] for k, v in _kinds().items() if v.get('node')}       # detection kind -> graph node (kinds.json)
CROP_KINDS = tuple(b for v in _kinds().values() for b in v.get('bubbles', []))   # bubbles only a bed shows (kinds.json)
BED_NODE = next((v['node'] for v in _kinds().values() if v.get('bubbles')), None)
CYRILLIC = re.compile('[Ѐ-ӿ]{3,}')


class LawsStuck(Exception):
    """Terminal: vision was asked MAX_ASKS times without progress. Stop and report."""


class WrongLanguage(LawsStuck):
    """Terminal: the game UI is not English (L129). Stop and ask the user; never change it."""


# ---- geometry -------------------------------------------------------------------------------------------------
def d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def hud(pt):
    return any(x0 <= pt[0] < x1 and y0 <= pt[1] < y1 for x0, y0, x1, y1 in HUD)


def on_frame(pt):
    return 0 <= pt[0] < W_ and 0 <= pt[1] < H_ and not hud(pt)


def nearest(affs, pt, pred=lambda a: True, max_d=None):
    best = None
    for a in affs:
        if not pred(a):
            continue
        dd = (a.pt[0] - pt[0]) ** 2 + (a.pt[1] - pt[1]) ** 2
        if (max_d is None or dd <= max_d ** 2) and (best is None or dd < best[0]):
            best = (dd, a)
    return best[1] if best else None


# ---- screen -------------------------------------------------------------------------------------------------
def texts():
    """(mode, texts) of the screen: 'gameplay' or a card/panel/menu."""
    try:
        s = core.WF.state()
        return s.get('mode', 'gameplay'), [t.split(') ', 1)[-1] for t in s.get('text', [])]
    except Exception:   # noqa: BLE001
        return 'gameplay', []


def check_language():
    """Raise WrongLanguage when the on-screen text (clock day name, cards) is not English."""
    try:
        ts = core.WF.state().get('text', [])
    except Exception:   # noqa: BLE001
        return
    bad = [t for t in ts if CYRILLIC.search(str(t))]
    if bad:
        raise WrongLanguage(f'WRONG_LANGUAGE: the game UI is not English (saw {bad[0]!r}). Stop: ask the user to switch '
                            'the game language to English (Settings); do not change it yourself (AGENTS rule 3).')


def clock():
    """(hour 0-23.99, light 'day'|'dusk'|'night') from the HUD clock, or (None, None)."""
    W = core.WF
    try:
        h = W.game_hour(W.grab())
        return h, (W.light_period(h) if h is not None else None)
    except Exception:   # noqa: BLE001
        return None, None


def view_changed(a, b):
    """True/False: two frames differ (she walked / the camera moved); None when they have no pixels."""
    try:
        import numpy as np
        ga = np.asarray(a.convert('L').resize((240, 135)), dtype=float)
        gb = np.asarray(b.convert('L').resize((240, 135)), dtype=float)
        return float(np.abs(ga - gb).mean()) > MOVED
    except Exception:   # noqa: BLE001
        return None


def bubble_set(affs):
    return sorted((a.kind, a.drop, round(a.pt[0] / 40), round(a.pt[1] / 40)) for a in affs)


def burst_texts(imgs):
    """Short-lived texts OCR'd from burst frames (outside the HUD)."""
    out = []
    for img in imgs[1:]:
        try:
            items = core.WF.ocr_image(img)
        except Exception:   # noqa: BLE001
            return out
        for it in items:
            x, y = it.get('cx', 0), it.get('cy', 0)
            t = (it.get('text') or '').strip()
            if t and t not in out and not hud((x, y)):
                out.append(t)
    return out


# ---- objects -------------------------------------------------------------------------------------------------
def scan():
    return affordances.scan()


def see(kind, tried=()):
    """Detections of `kind` by appearance vectors, nearest to Tara first, without the one she stands at, the HUD and
    points already tried. [Detection]"""
    from objects import detect as D, store as S
    img = core.WF.grab()
    dets = [x for x in D.detect(img, S.Store(), kinds=[kind])
            if d(x.point, CENTRE) > SEE_NEAR and not hud(x.point) and not any(d(x.point, p) < 80 for p in tried)]
    return sorted(dets, key=lambda x: d(x.point, CENTRE))


def see_all():
    """Every object the detector sees (any kind)."""
    try:
        from objects import detect as D, store as S
        return D.detect(core.WF.grab(), S.Store())
    except Exception:   # noqa: BLE001
        return []


def node_of_bubble(a):
    """The graph node a bubble belongs to: an owner-only kind (well can, hive jar), a crop/drop bubble = the beds."""
    k = affordances.OWNER.get(a.kind)
    if k:
        return NODE_OF.get(k, k)
    if a.drop or a.kind in CROP_KINDS:
        return BED_NODE
    return None


def closest_node(affs=None):
    """Where she is = the graph node closest to Tara (user D185), fresh from the frame: the owner of the bubble nearest
    the centre, else the detected object nearest the centre within NEAR_NODE px; None when the frame shows none."""
    affs = scan() if affs is None else affs
    owned = [(d(a.pt, CENTRE), n) for a in affs for n in [node_of_bubble(a)] if n]
    if owned:
        return min(owned)[1]
    dets = [(d(x.point, CENTRE), NODE_OF[x.kind]) for x in see_all() if x.kind in NODE_OF]
    dets = [t for t in dets if t[0] <= NEAR_NODE]
    return min(dets)[1] if dets else None


def soil(tried=()):
    """(dry spots nearest first [(x, y, cells)], (dry cells, wet cells)) from the soil heat map; ([], None) without a frame."""
    img = core.WF.grab()
    if img is None:
        return [], None
    try:
        spots = affordances.dry_spots(img)
        counts = affordances.soil_counts(img)
    except Exception:   # noqa: BLE001
        return [], None
    spots = [t for t in spots if not hud(t[:2]) and d(t[:2], CENTRE) > SEE_NEAR
             and not any(d(t[:2], p) < 80 for p in tried)]
    return sorted(spots, key=lambda t: d(t[:2], CENTRE)), counts
