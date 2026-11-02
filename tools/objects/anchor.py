"""Vision layout anchor (spec 2026-11-02 §10): vision reads the visible beds off a grid image; the tool fits the layout.
question() saves the full-size frame with the marker at CENTRE (wf.ask_vision draws the A-X x 1-16 grid) and asks vision;
answer() parses `group: G   ref: r1c2@L8` + `r<R>c<C>@<cell> <state>` per bed, fits the group's screen layout
(pitch, ref_offset in frame pixels) by least squares, sets Tara.at = ref and the member states (source vision, conf 1) and
checks totals against the save counts. Frame pixels only, never world coordinates."""
import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from objects import graph as G  # noqa: E402

CENTRE = (960, 540)   # the chain's reference tile = the tile nearest this point (the camera follows Tara)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PENDING = os.path.join(os.environ.get('WF_SHOT_DIR', os.path.join(ROOT, '.shots')), 'anchor-pending.json')
CELL = r'[A-X](?:1[0-6]|[1-9])'
COLS, ROWS = 24, 16
CELL_W, CELL_H = 1920 / COLS, 1080 / ROWS   # 80 x 67.5 px
RESIDUAL_LIMIT = 0.35                       # of the pitch
SHAPE = ('group: <group>   ref: r<R>c<C>@<cell>\n'
         'r<R>c<C>@<cell> <phase>[(<crop>)][ dry|watered]   r<R>c<C>@<cell> ?   ... '
         '(cell = grid cell A1-X16 nearest the bed centre; phase: empty|growing|ripe|wilted; ? = state unknown; '
         'e.g. "group: GardenBed@Garden   ref: r1c2@L8\nr1c1@F8 ripe   r1c2@L8 ripe   r2c1@F12 wilted(Tulip)   '
         'r2c2@L12 wilted(Tulip)   r3c1@F15 ?"; name >= 2 beds in different rows and columns)')
PHASES = ('empty', 'growing', 'ripe', 'wilted')
_HEAD = re.compile(rf'^\s*group:\s*(\S+)\s+ref:\s*(r\d+c\d+)@({CELL})\b\s*(.*)$', re.S)
_TOKEN = re.compile(rf'(r\d+c\d+)@({CELL})\s+(\?|(\w+)(?:\(([^)]*)\))?(?:\s+(dry|watered)\b)?)')


class AnchorError(Exception):
    def __init__(self, msg, expected_shape=SHAPE):
        super().__init__(f'{msg}. Expected: {expected_shape}')
        self.expected_shape = expected_shape


@dataclass
class Anchor:
    group: str
    ref: str
    cells: dict = field(default_factory=dict)    # member id -> grid cell
    states: dict = field(default_factory=dict)   # member id -> {phase, crop, watered_today}


def cell_point(cell):
    """Centre (x, y) of grid cell like `F8` in the 1920x1080 frame."""
    if not re.fullmatch(CELL, cell):
        raise AnchorError(f'bad grid cell {cell!r}')
    return ((ord(cell[0]) - 65) * CELL_W + CELL_W / 2, (int(cell[1:]) - 1) * CELL_H + CELL_H / 2)


def parse(text, graph):
    m = _HEAD.match(text.strip())
    if not m:
        raise AnchorError('malformed answer')
    group, ref_cell, ref_grid, rest = m.groups()
    if group not in graph.nodes or graph.nodes[group].type != 'group':
        raise AnchorError(f'unknown group {group}')

    def member(cellid):
        r, c = int(cellid[1:cellid.index('c')]), int(cellid[cellid.index('c') + 1:])
        n = graph.member_at(group, r, c)
        if n is None:
            raise AnchorError(f'cell {cellid} is outside the pattern of {group}')
        return n.id

    anchor = Anchor(group, member(ref_cell))
    pos, rest = 0, rest.strip()
    while pos < len(rest):
        t = _TOKEN.match(rest, pos)
        if not t:
            raise AnchorError(f'cannot read {rest[pos:pos + 24]!r}')
        cellid, grid, body, phase, crop, wet = t.groups()
        pos = t.end()
        while pos < len(rest) and rest[pos].isspace():
            pos += 1
        mid = member(cellid)
        anchor.cells[mid] = grid
        if body == '?':
            continue
        if phase not in PHASES:
            raise AnchorError(f'unknown state word {phase!r}')
        anchor.states[mid] = {'phase': phase, 'crop': crop or None,
                              'watered_today': None if wet is None else wet == 'watered'}
    if anchor.ref not in anchor.cells:
        anchor.cells[anchor.ref] = ref_grid
    elif anchor.cells[anchor.ref] != ref_grid:
        raise AnchorError(f'ref cell {ref_grid} differs from the bed list ({anchor.cells[anchor.ref]})')
    return anchor


def _axis(vals, idx, prev_pitch):
    """Least squares v = o + (idx - idx0) * p over one axis -> (o at idx0, p, max abs residual); idx0 = idx[0]."""
    import numpy as np
    i0 = idx[0]
    d = np.array([i - i0 for i in idx], float)
    v = np.array(vals, float)
    if len(set(idx)) >= 2:
        p, o = np.polyfit(d, v, 1)
    elif prev_pitch is not None:
        p = prev_pitch
        o = float(np.mean(v - d * p))
    else:
        raise AnchorError('need beds in different rows and columns to fit the layout')
    return float(o), float(p), float(np.max(np.abs(o + d * p - v)))


def fit_layout(beds, ref, prev=None):
    """beds {member id: (x, y) frame px}, ref member id -> {'pitch': (px, py), 'ref_offset': (dx, dy), 'residual': (rx, ry)}.
    Needs >= 2 distinct columns and rows (else the previous layout's pitch on the missing axis); raises AnchorError when the
    worst residual exceeds 0.35 x pitch (inconsistent beds)."""
    ids = [ref] + [m for m in beds if m != ref]
    rc = [G.cell(m) for m in ids]
    prev_p = (prev or {}).get('pitch') or (None, None)
    ox, px, rx = _axis([beds[m][0] for m in ids], [c for _, c in rc], prev_p[0])
    oy, py, ry = _axis([beds[m][1] for m in ids], [r for r, _ in rc], prev_p[1])
    if px == 0 or py == 0 or abs(rx) > RESIDUAL_LIMIT * abs(px) or abs(ry) > RESIDUAL_LIMIT * abs(py):
        raise AnchorError(f'beds are inconsistent with one grid (pitch ({px:.0f}, {py:.0f}), residual ({rx:.0f}, {ry:.0f}) px)')
    # the reference bed's own fitted screen point is (ox, oy)
    return {'pitch': (px, py), 'ref_offset': (ox - CENTRE[0], oy - CENTRE[1]), 'residual': (rx, ry)}


def apply(graph, anchor, game_time, scene=None):
    """Fit the layout (raises AnchorError before anything changes), then Tara.at = ref, member states, group layout."""
    g = graph.nodes[anchor.group]
    beds = {m: cell_point(c) for m, c in anchor.cells.items()}
    lay = fit_layout(beds, anchor.ref, g.extra.get('layout'))
    g.extra['layout'] = {'pitch': list(lay['pitch']), 'ref_offset': list(lay['ref_offset'])}
    changes = []
    graph.set_state('Tara', 'at', anchor.ref, game_time, 'vision')
    if scene:
        graph.set_state('Tara', 'at_scene', scene, game_time, 'vision')
    changes.append(('Tara', 'at', anchor.ref))
    for mid, s in anchor.states.items():
        for key, val in (('phase', s['phase']), ('crop', s['crop']), ('watered_today', s['watered_today'])):
            if val is not None:
                graph.set_state(mid, key, val, game_time, 'vision', 1.0)
                changes.append((mid, key, val))
    return changes


def cell_of(member_id):
    return G.cell(member_id)


def _bed_members(graph, group):
    """Members of `group`; group None or a bare kind (no '@') -> members of every group of that kind (default GardenBed)."""
    if group and '@' in group:
        return graph.members(group)
    kind = group or 'GardenBed'
    return [m for n in graph.nodes.values() if n.type == 'group' and n.kind == kind for m in graph.members(n.id)]


def count_mismatch(graph, group, save_counts):
    """{state: (graph count, save count)} where they differ. States: empty|growing|ripe|wilted by phase, `dry` = growing
    and watered_today not True (unknown counts as dry). group None or a kind -> farm-wide sum over all its groups (the save has no per-group split)."""
    members = _bed_members(graph, group)
    out = {}
    for state, want in save_counts.items():
        if state == 'dry':
            have = sum(1 for m in members if graph.phase(m.id) == 'growing' and graph.state_value(m.id, 'watered_today') is not True)
        else:
            have = sum(1 for m in members if graph.phase(m.id) == state)
        if have != want:
            out[state] = (have, want)
    return out


FONTS = ('/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/System/Library/Fonts/Helvetica.ttc',
         '/Library/Fonts/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')
LABEL_PX = 44   # label letters are at least this tall so they stay readable on the full-size frame


def _font(px=LABEL_PX):
    from PIL import ImageFont
    for f in FONTS:
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _scene(core):
    try:
        return core.WF.current_scene()
    except Exception:   # noqa: BLE001
        return None


def draw_grid(img):
    """Copy of img with the A-X x 1-16 grid (thin lines, a small cell name in each cell) for the anchor question."""
    from PIL import Image, ImageDraw
    pic = img.convert('RGBA')
    ov = Image.new('RGBA', pic.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    font = _font(15)
    for c in range(COLS + 1):
        dr.line((c * CELL_W, 0, c * CELL_W, pic.size[1]), fill=(255, 255, 0, 150), width=1)
    for r in range(ROWS + 1):
        dr.line((0, r * CELL_H, pic.size[0], r * CELL_H), fill=(255, 255, 0, 150), width=1)
    for c in range(COLS):
        for r in range(ROWS):
            dr.text((c * CELL_W + 3, r * CELL_H + 2), f'{chr(65 + c)}{r + 1}', fill=(255, 255, 0, 230), font=font)
    return Image.alpha_composite(pic, ov).convert('RGB')


def question(img, task, graph, unexpected, core=None):
    """Mark the chain's reference point (the frame CENTRE, magenta circle) on a full-size copy of img and ask vision for the
    layout (wf.ask_vision draws the grid); returns the prompt. task/game_time/scene are stored for answer()."""
    from PIL import ImageDraw
    if core is None:
        from game import core
    pic = img.copy()
    x, y = CENTRE
    ImageDraw.Draw(pic).ellipse((x - 26, y - 26, x + 26, y + 26), outline=(255, 0, 255), width=5)
    tara = graph.state_value('Tara', 'at')
    near = []
    if tara:
        near = [f'{m}: {graph.phase(m)}' for m in [tara] + list(graph.neighbours(tara).values())]
    text = (f'Task: {task}. Unexpected: {unexpected}. Predicted near Tara.at={tara}: {"; ".join(near) or "unknown"}. '
            f'The image has a grid (columns A-X, rows 1-16). Name every visible bed by its pattern cell rXcY, the grid cell '
            f'nearest the centre of that bed, and its state; `ref:` = the bed nearest the magenta marker. '
            f'Answer with ./wf anchor "<answer>" in the format: {SHAPE}')
    prompt = core.WF.ask_vision('anchor', text, pic)
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    with open(PENDING, 'w') as f:
        json.dump({'task': task, 'game_time': _clock(core), 'scene': _scene(core)}, f)
    return prompt


def _clock(core):
    """Current game clock stamp ('D183 1:30:00 PM', the game-log format); else today's day from the save/log ('D183');
    else 'vision'."""
    try:
        st = core.WF.game_stamp()
        if st:
            return st
    except Exception:   # noqa: BLE001
        pass
    try:
        day = core.WF.today_log()[1]
        if day:
            return f'D{day}'
    except Exception:   # noqa: BLE001
        pass
    return 'vision'


def incomplete(graph, kind='GardenBed'):
    """Why the farm-wide save-count check cannot be trusted (a group of `kind` has no members/pattern, or a member's phase is
    unknown), or None when the graph covers every bed."""
    for n in graph.nodes.values():
        if n.type == 'group' and n.kind == kind:
            ms = graph.members(n.id)
            if not ms or not n.extra.get('pattern'):
                return f'{n.id} has no members/pattern'
            if any(graph.phase(m.id) is None for m in ms):
                return f'{n.id} has members with unknown phase'
    return None


def clear_pending():
    """Forget the pending question: an answer applies only to the question it was asked for."""
    try:
        os.remove(PENDING)
    except OSError:
        pass


def _pending():
    try:
        with open(PENDING) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def answer(text, graph=None, gpath=None, save_counts=None):
    """Parse + apply the pending question; saves the graph; returns a one-line summary (raises AnchorError)."""
    pend = _pending()
    if pend is None:
        raise AnchorError('no pending anchor question (run the question first)')
    gpath = gpath or os.environ.get('WF_GRAPH') or os.path.join(G.DEFAULT_DIR, 'Farm.json')
    if graph is None:
        graph = G.Graph()
        graph.load(gpath)
    anchor = parse(text, graph)
    changes = apply(graph, anchor, pend.get('game_time') or 'vision', pend.get('scene'))
    graph.save(gpath)
    clear_pending()   # one answer per question
    out = f'anchored Tara at {anchor.ref}; {len(changes) - 1} state changes'
    if save_counts:
        why = incomplete(graph)
        mm = {} if why else count_mismatch(graph, None, save_counts)
        if why:
            out += '; count check skipped (graph incomplete)'
        elif mm:
            out += '; MISMATCH vs save (graph, save): ' + ', '.join(f'{k}={v}' for k, v in mm.items()) + \
                   ' - ask ONE follow-up naming it'
    return out
