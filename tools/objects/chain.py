"""Graph chain strategy: locate a neighbour tile on screen by pattern fit (no positions: frame pixels only)."""
from game import core

from . import identity, loop
from .graph import cell

CENTRE = (960, 540)   # frame centre in the 1920x1080 virtual frame: the camera follows Tara, so the `at` tile is nearest it


class Unexpected(Exception):
    def __init__(self, why):
        super().__init__(why)
        self.why = why


def _lines(vals, sizes):
    """Cluster index per value (input order): split sorted values only at gaps > half the median tile size, so pixel
    jitter never makes phantom rows/columns even when fewer lines than the pattern has are visible."""
    lim = .5 * sorted(sizes)[len(sizes) // 2]
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    lab, c = [0] * len(vals), 0
    for k, i in enumerate(order):
        if k and vals[i] - vals[order[k - 1]] > lim:
            c += 1
        lab[i] = c
    return lab


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


EVENTS = {'unplant': r'> unplant ', 'removed': r'> unplant_impl ', 'plant': r'> plant ', 'planted': r'totalPlanted\.',
          'water': r'> water ', 'dry_can': r'> out_of_water ', 'pickup': r'> grab_item '}


def event(mark, name, wait):
    """The log line of event `name` since `mark` (no position check: the click already pinned the target)."""
    return core.seen(EVENTS[name], mark, wait)
