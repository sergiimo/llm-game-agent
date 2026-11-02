"""Chain helpers (spec 2026-11-02 §10): the layout's screen point of a neighbour bed, the bubble expectation of a predicted
state, and the proof of a one-bed move by phase correlation of the frames. Frame pixels only; no positions."""
import re
import time

from game import ui, core
from . import anchor
from .graph import cell

MIN_PITCH, TOL, MIN_PEAK, DOWN = 40.0, 0.4, 0.06, 4   # px; of the pitch; correlation peak; frame downscale factor

CENTRE = anchor.CENTRE   # the camera follows Tara, so the reference tile is the one nearest the frame centre


class Unexpected(Exception):
    def __init__(self, why):
        super().__init__(why)
        self.why = why


def _layout(graph, node_id):
    """The validated layout of a node's group; Unexpected('no layout') / ('bad layout', dropped) otherwise."""
    group = graph.nodes[graph.nodes[node_id].region]
    lay = group.extra.get('layout')
    if not lay:
        raise Unexpected('no layout')
    try:
        px, py = (float(v) for v in lay['pitch'])
        dx, dy = (float(v) for v in lay['ref_offset'])
    except (KeyError, TypeError, ValueError):
        group.extra.pop('layout', None)
        raise Unexpected('bad layout') from None
    if px < MIN_PITCH or py < MIN_PITCH:
        group.extra.pop('layout', None)
        raise Unexpected(f'bad layout: pitch ({px:.0f}, {py:.0f}) is not a bed spacing')
    return px, py, dx, dy


def layout_point(graph, at, target):
    """Frame pixel of member `target` while Tara stands at `at` (camera follows her): CENTRE + ref_offset + cell delta x pitch."""
    px, py, dx, dy = _layout(graph, at)
    (ar, ac), (tr, tc) = cell(at), cell(target)
    return (CENTRE[0] + dx + (tc - ac) * px, CENTRE[1] + dy + (tr - ar) * py)


def click_tile(pt, bubbles):
    """Pixel to click for a tile at `pt`, nudged off any bubble that sits on it."""
    for ox, oy in ((0, 0), (0, 50), (50, 0), (-50, 0), (0, -50)):
        x, y = pt[0] + ox, pt[1] + oy
        if all((x - b[0]) ** 2 + (y - b[1]) ** 2 >= 45 ** 2 for b in bubbles):
            return (round(x), round(y))
    return (round(pt[0]), round(pt[1]))


def _gray(img):
    import numpy as np
    from PIL import Image
    g = img.convert('L')
    g = g.resize((max(1, g.width // DOWN), max(1, g.height // DOWN)), Image.BOX)
    return np.asarray(g, dtype=float)


def camera_shift(img0, img1):
    """How the scene moved between two full frames: (dx, dy, peak) in frame pixels (content at x in img0 is at x+dx in img1);
    phase correlation on 1/4-size grayscale. peak = normalised correlation peak (~1 pure shift, ~0 no common texture)."""
    import numpy as np
    a, b = _gray(img0), _gray(img1)
    if a.shape != b.shape:
        return 0.0, 0.0, 0.0
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    a, b = (a - a.mean()) * win, (b - b.mean()) * win
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0, 0.0, 0.0
    cross = np.fft.fft2(b) * np.conj(np.fft.fft2(a))
    r = np.fft.ifft2(cross / (np.abs(cross) + 1e-9 * np.abs(cross).max())).real
    iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape
    dy, dx = (iy - h if iy > h // 2 else iy), (ix - w if ix > w // 2 else ix)
    return float(dx * DOWN), float(dy * DOWN), float(r[iy, ix])


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


SHIFT = {'E': (-1, 0), 'W': (1, 0), 'S': (0, -1), 'N': (0, 1)}   # grid shift (in pitches) after Tara moves one tile that way


def prove_move(layout, shift, d):
    """The camera must have moved one pitch opposite to the step direction `d` (+-0.4 pitch; < 0.4 pitch on the other axis)
    with a real correlation peak, else Unexpected('move not proved: ...')."""
    dx, dy, peak = shift
    if not layout:
        raise Unexpected('no layout')
    px, py = (float(v) for v in layout['pitch'])
    if px < MIN_PITCH or py < MIN_PITCH:
        raise Unexpected('bad layout')
    sx, sy = SHIFT[d]
    ex, ey = sx * px, sy * py
    if peak < MIN_PEAK:
        raise Unexpected(f'move not proved: no common texture between the frames (peak {peak:.2f})')
    if abs(dx - ex) > TOL * px or abs(dy - ey) > TOL * py:
        raise Unexpected(f'move not proved: camera shifted ({dx:.0f}, {dy:.0f}) px, expected ({ex:.0f}, {ey:.0f}) for {d}')


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


def ensure_gameplay():
    """Close a card/panel/menu that is open (a 2nd Escape in gameplay would open the pause menu, so only when not in it)."""
    try:
        mode = core.WF.state().get('mode')
    except Exception:   # noqa: BLE001
        mode = 'gameplay'
    if mode != 'gameplay':
        ui.close()


INTERACT = r'> (unplant|water|out_of_water|grab_item|plant_growing) .*target=GardenBed'   # a click on a bed in reach logs one
ARRIVE_WAIT, POLL, STABLE = 8.0, 0.3, 12   # s to wait for the click's outcome; poll interval; px the shift may move between polls


def click_target(g, cur, target, bubble_pts):
    """Ruling 28: click the TARGET bed's layout point (no hops) and wait up to ARRIVE_WAIT s for its outcome. Returns
    ('event', type, mark) when the click interacted (a bed in reach: the log shows an interaction event on a GardenBed), or
    ('walk', ref_offset, mark) when the camera shift proves Tara now stands at the target (layout point + shift lands
    within 0.4 pitch of CENTRE + ref_offset, stable over two polls). Else Unexpected (layout dropped)."""
    px, py, dx, dy = _layout(g, cur)
    lay_pt = layout_point(g, cur, target)
    if not (0 <= lay_pt[0] < 1920 and 0 <= lay_pt[1] < 1080):
        raise Unexpected(f'the layout puts {target} off screen at ({lay_pt[0]:.0f}, {lay_pt[1]:.0f})')
    pt = click_tile(lay_pt, bubble_pts)
    img0, mark = core.WF.grab(), core.WF.log_mark()
    core.WF.run_action(f'click:{pt[0]}:{pt[1]}')
    core.WF.wait_settle()
    end, prev, shift, polls = time.monotonic() + ARRIVE_WAIT, None, (0.0, 0.0, 0.0), 0
    while True:
        line = core.seen(INTERACT, mark, 0)
        if line:
            return 'event', re.search(INTERACT, line).group(1), mark
        shift = camera_shift(img0, core.WF.grab())
        want = (CENTRE[0] + dx, CENTRE[1] + dy)
        got = (lay_pt[0] + shift[0], lay_pt[1] + shift[1])
        near = abs(got[0] - want[0]) <= TOL * px and abs(got[1] - want[1]) <= TOL * py and shift[2] >= MIN_PEAK
        if near and prev is not None and abs(shift[0] - prev[0]) <= STABLE and abs(shift[1] - prev[1]) <= STABLE:
            return 'walk', (got[0] - CENTRE[0], got[1] - CENTRE[1]), mark
        prev = shift if near else None
        polls += 1
        if polls >= 2 and time.monotonic() >= end:   # at least two looks: a shift must be seen stable
            break
        time.sleep(POLL)
    g.nodes[g.nodes[target].region].extra.pop('layout', None)
    scr = opened_screen()
    if scr:
        ui.close()
        raise Unexpected(f'the click on {target} opened {scr}, no interaction event, no move')
    raise Unexpected(f'move not proved: the click on {target} logged no interaction and the camera shifted '
                     f'({shift[0]:.0f}, {shift[1]:.0f}) px (peak {shift[2]:.2f}), expected about '
                     f'({CENTRE[0] + dx - lay_pt[0]:.0f}, {CENTRE[1] + dy - lay_pt[1]:.0f})')
