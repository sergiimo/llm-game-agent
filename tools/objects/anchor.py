"""Vision anchor (spec 2026-11-02 §5): one structured question and one fixed answer format about LABELS, never coordinates.
question() labels the visible tiles A, B, C ... (left->right, top->bottom) on a copy of the frame and asks vision;
answer() parses `group: G  at: B=r2c1  A=r1c1 empty  B=r2c1 wilted(Green Bean)  C=growing dry  E=?`, applies Tara.at and the
member states (source vision, conf 1) and checks totals against the save counts. No positions: detection points only
order/label tiles on the frame."""
import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from objects import graph as G, identity as I  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PENDING = os.path.join(os.environ.get('WF_SHOT_DIR', os.path.join(ROOT, '.shots')), 'anchor-pending.json')
SHAPE = ('group: <group>   at: <L>=r<R>c<C>   <L>=[r<R>c<C> ]<phase>[(<crop>)][ dry|watered] ...   <L>=?   '
         '(phase: empty|growing|ripe|wilted)')
PHASES = ('empty', 'growing', 'ripe', 'wilted')
_HEAD = re.compile(r'^\s*group:\s*(\S+)\s+at:\s*([A-Z])=(r\d+c\d+)\s*(.*)$', re.S)
_TOKEN = re.compile(r'([A-Z])=(\?|(?:(r\d+c\d+)\s+)?(\w+)(?:\(([^)]*)\))?(?:\s+(dry|watered))?)')


class AnchorError(Exception):
    def __init__(self, msg, expected_shape=SHAPE):
        super().__init__(f'{msg}. Expected: {expected_shape}')
        self.expected_shape = expected_shape


@dataclass
class Anchor:
    group: str
    at: tuple
    states: dict = field(default_factory=dict)


def parse(text, labels, graph):
    m = _HEAD.match(text.strip())
    if not m:
        raise AnchorError('malformed answer')
    group, at_label, at_cell, rest = m.groups()
    if group not in graph.nodes or graph.nodes[group].type != 'group':
        raise AnchorError(f'unknown group {group}')

    def member(cellid):
        r, c = int(cellid[1:cellid.index('c')]), int(cellid[cellid.index('c') + 1:])
        n = graph.member_at(group, r, c)
        if n is None:
            raise AnchorError(f'cell {cellid} is outside the pattern of {group}')
        return n.id

    if at_label not in labels:
        raise AnchorError(f'label {at_label} is not on the frame')
    anchor = Anchor(group, (at_label, member(at_cell)))
    pos, rest = 0, rest.strip()
    while pos < len(rest):
        t = _TOKEN.match(rest, pos)
        if not t:
            raise AnchorError(f'cannot read {rest[pos:pos + 20]!r}')
        label, body, cellid, phase, crop, wet = t.groups()
        pos = t.end()
        while pos < len(rest) and rest[pos].isspace():
            pos += 1
        if label not in labels:
            raise AnchorError(f'label {label} is not on the frame')
        if body == '?':
            anchor.states[label] = {'member': None, 'phase': None, 'crop': None, 'watered_today': None}
            continue
        if phase not in PHASES:
            raise AnchorError(f'unknown state word {phase!r}')
        anchor.states[label] = {'member': member(cellid) if cellid else None, 'phase': phase, 'crop': crop or None,
                                'watered_today': None if wet is None else wet == 'watered'}
    return anchor


def _rowcol_index(values, tol):
    """Cluster 1-D values (gaps > tol start a new cluster) -> list of cluster index per value."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, c = [0] * len(values), 0
    for k, i in enumerate(order):
        if k and values[i] - values[order[k - 1]] > tol:
            c += 1
        out[i] = c
    return out


def _grid(labels):
    """{label: (row, col)} relative grid of the labelled detections' screen points."""
    names = list(labels)
    pts = [labels[n].point for n in names]

    def tol(vals):
        s = sorted(vals)
        gaps = [b - a for a, b in zip(s, s[1:]) if b - a > 0]
        return 0.5 * max(gaps) if gaps else 0
    ry = _rowcol_index([p[1] for p in pts], tol([p[1] for p in pts]))
    cx = _rowcol_index([p[0] for p in pts], tol([p[0] for p in pts]))
    return {n: (r, c) for n, r, c in zip(names, ry, cx)}


def apply(graph, anchor, labels, game_time):
    """Set Tara.at and member states from vision; unnamed labels follow the pattern relative to `at`."""
    changes = []
    at_label, at_member = anchor.at
    graph.set_state('Tara', 'at', at_member, game_time, 'vision')
    changes.append(('Tara', 'at', at_member))
    mapping = {l: s['member'] for l, s in anchor.states.items() if s.get('member')}
    mapping[at_label] = at_member
    grid = _grid(labels) if labels else {}
    if at_label in grid:
        r0, c0 = cell_of(at_member)
        gr, gc = grid[at_label]
        for l, (r, c) in grid.items():
            if l in mapping or (l in anchor.states and anchor.states[l]['phase'] is None):
                continue
            n = graph.member_at(anchor.group, r0 + r - gr, c0 + c - gc)
            if n is not None:
                mapping[l] = n.id
    for l, mid in mapping.items():
        s = anchor.states.get(l)
        if not s or s['phase'] is None:
            continue
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


def _label_letters(n):
    return [chr(65 + i) if i < 26 else f'A{chr(65 + i - 26)}' for i in range(n)]


def question(img, dets, task, graph, unexpected, core=None, tara_point=None):
    """Draw labels A, B, ... (left->right, top->bottom) on a copy of img and ask vision; returns (prompt, {label: Detection}).
    The label map is stored for answer()."""
    from PIL import ImageDraw
    if core is None:
        from game import core
    ordered = sorted(dets, key=lambda d: (round(d.point[1] / 60), d.point[0]))
    labels = dict(zip(_label_letters(len(ordered)), ordered))
    pic = img.copy()
    dr = ImageDraw.Draw(pic)
    for l, d in labels.items():
        x, y = d.point
        dr.rectangle((x - 14, y - 14, x + 14, y + 14), fill=(0, 0, 0), outline=(255, 255, 0), width=2)
        dr.text((x - 5, y - 8), l, fill=(255, 255, 0))
    if tara_point:
        x, y = tara_point
        dr.ellipse((x - 12, y - 12, x + 12, y + 12), outline=(255, 0, 255), width=3)
        dr.text((x + 14, y - 8), 'Tara', fill=(255, 0, 255))
    tara = graph.state_value('Tara', 'at')
    near = []
    if tara:
        near = [f'{m}: {graph.phase(m)}' for m in [tara] + list(graph.neighbours(tara).values())]
    text = (f'Task: {task}. Unexpected: {unexpected}. Predicted near Tara.at={tara}: {"; ".join(near) or "unknown"}. '
            f'Tiles are labelled {", ".join(labels) or "(none)"}; Tara is the magenta circle. '
            f'Answer with ./wf anchor "<answer>" in the format: {SHAPE}')
    prompt = core.WF.ask_vision('anchor', text, pic)
    os.makedirs(os.path.dirname(PENDING), exist_ok=True)
    with open(PENDING, 'w') as f:
        json.dump({'labels': {l: {'point': list(d.point), 'box': list(d.box), 'kind': d.kind} for l, d in labels.items()},
                   'game_time': _clock(core)}, f)
    return prompt, labels


def _clock(core):
    """Current game clock stamp ('D183 1:30:00 PM', the game-log format) or 'vision' if unavailable."""
    try:
        return core.WF.game_stamp() or 'vision'
    except Exception:
        return 'vision'


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


class _Det:
    def __init__(self, d):
        self.point, self.box, self.kind = tuple(d['point']), tuple(d['box']), d['kind']


def answer(text, graph=None, gpath=None, save_counts=None):
    """Parse + apply the pending question; saves the graph; returns a one-line summary (raises AnchorError)."""
    pend = _pending()
    if pend is None:
        raise AnchorError('no pending anchor question (run the question first)')
    labels = {l: _Det(d) for l, d in pend['labels'].items()}
    gpath = gpath or os.environ.get('WF_GRAPH') or os.path.join(G.DEFAULT_DIR, 'Farm.json')
    if graph is None:
        graph = G.Graph()
        graph.load(gpath)
    anchor = parse(text, set(labels), graph)
    changes = apply(graph, anchor, labels, pend.get('game_time') or 'vision')
    graph.save(gpath)
    clear_pending()   # one answer per question
    out = f'anchored Tara at {anchor.at[1]}; {len(changes) - 1} state changes'
    if save_counts:
        mm = count_mismatch(graph, None, save_counts)
        if mm:
            out += '; MISMATCH vs save (graph, save): ' + ', '.join(f'{k}={v}' for k, v in mm.items()) + \
                   ' - ask ONE follow-up naming it'
    return out
