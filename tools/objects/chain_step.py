"""Chain helpers (spec 2026-11-02): pattern fit of a neighbour tile on the frame, the bubble expectation of a predicted state, and the
geometric proof of a one-tile move. Frame pixels only; no positions."""
from game import ui, core
from . import anchor, identity, loop
from .graph import cell
from .lines import lines as _lines

CENTRE = anchor.CENTRE   # the camera follows Tara, so the reference tile is the one nearest the frame centre


class Unexpected(Exception):
    def __init__(self, why):
        super().__init__(why)
        self.why = why


def locate(graph, at, target, dets):
    """The detection of `target`, fitted to the group grid relative to `at` (the tile nearest the frame centre)."""
    group = graph.nodes[graph.nodes[at].region]
    dets = identity.dedupe_for(group, list(dets))
    if len(dets) < 2:
        raise Unexpected(f'pattern fit: only {len(dets)} tile(s) visible')
    ry = _lines([d.point[1] for d in dets], [d.box[3] - d.box[1] for d in dets])
    cx = _lines([d.point[0] for d in dets], [d.box[2] - d.box[0] for d in dets])
    cells = list(zip(ry, cx))
    if len(set(cells)) < len(cells):
        raise Unexpected('pattern fit: ambiguous (two tiles in one grid cell)')
    i0 = min(range(len(dets)), key=lambda i: (dets[i].point[0] - CENTRE[0]) ** 2 + (dets[i].point[1] - CENTRE[1]) ** 2)
    (ar, ac), (tr, tc) = cell(at), cell(target)
    want = (ry[i0] + tr - ar, cx[i0] + tc - ac)
    for d, rc in zip(dets, cells):
        if rc == want:
            return d
    raise Unexpected(f'pattern fit: target not visible (offset {tr - ar},{tc - ac} from {at})')


def click_tile(det, bubbles):
    """Pixel to click on a tile, kept away from unwanted bubbles."""
    return loop.click_point(det, bubbles)


def expected_bubble(graph, node_id):
    """Predicate on an Affordance: does it look like what the predicted state of the node shows?"""
    ph = graph.phase(node_id)
    if ph == 'wilted' or (ph == 'growing' and not graph.state_value(node_id, 'watered_today')):
        return lambda a: bool(a.drop)
    if ph == 'growing':   # watered: the crop icon, no water drop
        return lambda a: not a.drop
    if ph == 'empty':
        return lambda a: a.kind == 'plant'
    if ph == 'ripe':
        return lambda a: a.kind == 'pickup'
    return lambda a: True


def bubble_near(affs, tile_pt, max_dx=110, max_up=(40, 260)):
    """The bubble above the clicked tile (screen-relative), closest one; None if none qualifies."""
    best, bd = None, None
    for a in affs:
        dx, up = abs(a.pt[0] - tile_pt[0]), tile_pt[1] - a.pt[1]
        if dx <= max_dx and max_up[0] <= up <= max_up[1]:
            d = dx * dx + up * up
            if bd is None or d < bd:
                best, bd = a, d
    return best


def _pitch(dets, axis):
    """Tile pitch along axis 0 (x) / 1 (y): median gap between adjacent tile lines; one line -> the tile's own size."""
    sizes = [d.box[axis + 2] - d.box[axis] for d in dets]
    lab = _lines([d.point[axis] for d in dets], sizes)
    by = {}
    for l, d in zip(lab, dets):
        by.setdefault(l, []).append(d.point[axis])
    ms = sorted(sum(v) / len(v) for v in by.values())
    gaps = sorted(b - a for a, b in zip(ms, ms[1:]))
    return gaps[len(gaps) // 2] if gaps else sorted(sizes)[len(sizes) // 2]


SHIFT = {'E': (-1, 0), 'W': (1, 0), 'S': (0, -1), 'N': (0, 1)}   # grid shift (in pitches) after Tara moves one tile that way


def _prove_shift(group, dets0, dets1, d):
    """Screen geometry (frame pixels only): after a one-tile move toward `d` the camera follows, so the whole visible grid
    shifts by one pitch the opposite way. The shift is the whole-pitch displacement k that best maps the tiles seen
    before onto the tiles seen after; it must be exactly the expected one (a tie or any other k = not proved)."""
    d0, d1 = identity.dedupe_for(group, list(dets0)), identity.dedupe_for(group, list(dets1))
    px, py = _pitch(d0, 0), _pitch(d0, 1)
    scores = {}
    for kx in range(-3, 4):
        for ky in range(-3, 4):
            scores[(kx, ky)] = sum(1 for p in d0 if any(abs(p.point[0] + kx * px - q.point[0]) < .3 * px and
                                                        abs(p.point[1] + ky * py - q.point[1]) < .3 * py for q in d1))
    top = max(scores.values())
    best = [k for k, v in scores.items() if v == top]
    if top < 1 or len(best) != 1 or best[0] != SHIFT[d]:
        raise Unexpected(f'move not proved: grid shifted {best[0] if len(best) == 1 else "ambiguously"} pitches '
                         f'(expected {SHIFT[d]} for {d})')


def _implies_bubble(g, nid):
    ph = g.phase(nid)
    return ph in ('wilted', 'empty', 'ripe') or (ph == 'growing' and g.state_value(nid, 'watered_today') is not True)




def opened_screen():
    """Name of the non-gameplay screen the last click opened (card, panel, dialogue ...), or None when it is the plain world."""
    try:
        mode = core.WF.state().get('mode')
        return None if mode == 'gameplay' else str(mode)
    except Exception:   # noqa: BLE001 (no state: fall back to on-screen texts)
        t = ui.texts()
        return ' / '.join(t[:2]) if t else None
