"""Object graph with nested regions (no coordinates: identity = kind, region, pattern cell `Group#r<row>c<col>`). Nodes are regions,
uniques, groups and group members; `in` is the node's `region` field (a member's region is its group); edges carry
`offers` (node, action), `leads_to` (door, region) and the like. States are hints with an age:
{key: {value, game_time, source}}. Frame observations (source `frame`, such as a currently showing bubble) are transient;
other states persist as plain JSON (one file per top region). Unknown keys survive load -> save."""
import json
import os
import re

import networkx as nx

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'graph')
TYPES = ('region', 'unique', 'group', 'member')
NODE_KEYS = ('id', 'type', 'kind', 'region', 'state', 'vec', 'seen')   # known fields; the rest goes to Node.extra


_CELL = re.compile(r'#r(\d+)c(\d+)$')
_DAY = re.compile(r'D(\d+)')
DIRS = {'N': (-1, 0), 'S': (1, 0), 'W': (0, -1), 'E': (0, 1)}


def cell(member_id):
    """(row, col), 1-based, from a pattern-cell member id such as `GardenBed@Garden#r2c3`."""
    m = _CELL.search(member_id)
    if not m:
        raise ValueError(f'not a pattern cell id: {member_id}')
    return int(m.group(1)), int(m.group(2))


def order(node):
    """Sort key of a member: its pattern cell (row, col) when the id is one, else its stored `index`."""
    m = _CELL.search(node.id)
    return (int(m.group(1)), int(m.group(2))) if m else (0, node.extra.get('index', 0))


class Node:
    def __init__(self, id, type, kind=None, region=None, state=None, vec=None, seen=None, **extra):
        self.id, self.type, self.kind, self.region = id, type, kind or id.split('#')[0], region
        self.state, self.vec, self.seen = state or {}, vec, seen
        self.extra = extra

    def __getattr__(self, name):   # pattern, signal, index, exit ... live in extra
        if name != 'extra' and name in self.extra:
            return self.extra[name]
        raise AttributeError(name)

    def to_dict(self):
        d = {'id': self.id, 'type': self.type, 'kind': self.kind, 'region': self.region}
        for k in ('state', 'vec', 'seen'):
            v = getattr(self, k)
            if k == 'state':
                v = {name: obs for name, obs in v.items()
                     if not isinstance(obs, dict) or obs.get('source') != 'frame'}
            if v:
                d[k] = v
        d.update(self.extra)
        return d


class Graph:
    def __init__(self):
        self.nodes = {}
        self._edges = []
        self.extra = {}

    def load(self, path):
        with open(path) as f:
            data = json.load(f)
        self.nodes = {}
        for d in data.pop('nodes', []):
            known = {k: d[k] for k in NODE_KEYS if k in d}
            self.nodes[d['id']] = Node(**known, **{k: v for k, v in d.items() if k not in NODE_KEYS})
        self._edges = [dict(e) for e in data.pop('edges', [])]
        self.extra = data

    def save(self, path):
        data = dict(self.extra)
        data['nodes'] = [n.to_dict() for n in self.nodes.values() if not n.extra.get('transient')]
        data['edges'] = [e for e in self._edges if e.get('source') != 'frame']
        with open(path, 'w') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write('\n')

    def clear_frame(self):
        """Drop the previous frame's dynamic nodes, edges and state before observing the next frame."""
        for n in self.nodes.values():
            n.state = {k: v for k, v in n.state.items()
                       if not isinstance(v, dict) or v.get('source') != 'frame'}
        self._edges = [e for e in self._edges if e.get('source') != 'frame']
        self.nodes = {id: n for id, n in self.nodes.items() if not n.extra.get('transient')}

    def node(self, id):
        return self.nodes.get(id)

    def children(self, region_id):
        return [n for n in self.nodes.values() if n.region == region_id]

    def parent(self, id):
        n = self.nodes.get(id)
        return n.region if n else None

    def chain(self, id):
        out = []
        while id in self.nodes and id not in out:
            out.append(id)
            id = self.nodes[id].region
        return out[::-1]

    def members(self, group_id):
        return sorted((n for n in self.children(group_id) if n.type == 'member'), key=order)

    def add_edge(self, a, b, rel, **attrs):
        e = {'a': a, 'b': b, 'rel': rel, **attrs}
        if e not in self._edges:
            self._edges.append(e)

    def edges(self, a=None, rel=None):
        return [e for e in self._edges if (a is None or e['a'] == a) and (rel is None or e['rel'] == rel)]

    def set_state(self, id, key, value, game_time, source, conf=1.0):
        self.nodes[id].state[key] = {'value': value, 'game_time': game_time, 'source': source, 'conf': conf}

    def state_value(self, id, key):
        n = self.nodes.get(id)
        s = n.state.get(key) if n else None
        return s['value'] if s else None

    def member_at(self, group_id, row, col):
        return self.nodes.get(f'{group_id}#r{row}c{col}')

    def neighbours(self, member_id):
        """{'E'|'W'|'N'|'S': member_id} of the existing grid neighbours; generated from the group pattern, not stored."""
        n = self.nodes.get(member_id)
        if n is None or not _CELL.search(member_id):
            return {}
        r, c = cell(member_id)
        out = {}
        for d, (dr, dc) in DIRS.items():
            m = self.member_at(n.region, r + dr, c + dc)
            if m is not None:
                out[d] = m.id
        return out

    def hops(self, a, b):
        """[(direction, member_id)] steps from a to b inside one group: columns first, then rows. [] if a == b;
        None if either is unknown, the groups differ or a step has no member."""
        na, nb = self.nodes.get(a), self.nodes.get(b)
        if na is None or nb is None or na.region != nb.region or not (_CELL.search(a) and _CELL.search(b)):
            return None
        (r, c), (r2, c2) = cell(a), cell(b)
        out, cur = [], a
        for d, count in (('E' if c2 > c else 'W', abs(c2 - c)), ('S' if r2 > r else 'N', abs(r2 - r))):
            for _ in range(count):
                cur = self.neighbours(cur).get(d)
                if cur is None:
                    return None
                out.append((d, cur))
        return out

    def phase(self, id):
        return self.state_value(id, 'phase')

    def needs(self, group_id, pred):
        return [n.id for n in self.members(group_id) if pred(n)]

    def new_day(self, day):
        """Yesterday's watered_today hints (game_time day != `day`) -> False, source 'event'."""
        for n in self.nodes.values():
            s = n.state.get('watered_today')
            m = _DAY.search(str(s.get('game_time'))) if isinstance(s, dict) else None
            if s and s.get('value') is True and m and int(m.group(1)) != day:
                self.set_state(n.id, 'watered_today', False, f'D{day}', 'event')

    def view(self):
        """networkx DiGraph: `in` edges (node -> region) plus the stored edges."""
        g = nx.DiGraph()
        for n in self.nodes.values():
            g.add_node(n.id, type=n.type, kind=n.kind)
            if n.region:
                g.add_edge(n.id, n.region, rel='in')
        for e in self._edges:
            g.add_edge(e['a'], e['b'], **{k: v for k, v in e.items() if k not in ('a', 'b')})
        return g


_STAMP = re.compile(r'^\[(D(\d+)) ([^\]]+)\]')
_ACT = re.compile(r'>\s*(\w+)\b[^\n]*?target=(\w+)')


def apply_log(graph, lines, at, skipped=None):
    """Update node states from game-log lines (source 'event', game_time = the line's stamp 'D148 9:36:36 PM'). Only the
    event type is read, never a position:
    `> fill_watering_can|full_watering_can ... target=Well` -> Well can=full;
    `> plant|water|unplant_impl ... target=GardenBed` -> the member `at` (the chain's current node; None = unknown,
    skipped): plant phase=growing | water watered_today=True | unplant_impl phase=empty + crop=None.
    Garden events that cannot be applied (at unknown) are appended to the `skipped` list, if given, as (act, game_time).
    Returns [(node_id, key, value, game_time)] of the changes in order."""
    out = []
    for line in lines:
        st, m = _STAMP.match(line), _ACT.search(line)
        if not st or not m:
            continue
        act, target = m.group(1), m.group(2)
        when = f'{st.group(1)} {st.group(3)}'
        if act in ('fill_watering_can', 'full_watering_can') and target == 'Well' and 'Well' in graph.nodes:
            chs = [('Well', 'can', 'full')]
        elif target == 'GardenBed' and act in ('plant', 'water', 'unplant_impl'):
            if at is None or at not in graph.nodes:
                if skipped is not None:
                    skipped.append((act, when))
                continue
            chs = [(at, 'phase', 'growing')] if act == 'plant' else [(at, 'watered_today', True)] \
                if act == 'water' else [(at, 'phase', 'empty'), (at, 'crop', None)]
        else:
            continue
        for ch in chs:
            graph.set_state(*ch, when, 'event')
            out.append((*ch, when))
    return out


# ---- interaction laws memory (L124): group-level, no per-bed identity ------------------------------------------
TALLY = {'unplant_impl': 'removed', 'plant': 'planted', 'water': 'watered', 'grab_item': 'harvested',
         'plant_growing': 'growing_seen', 'out_of_water': 'can_ran_dry'}


def note_click(graph, group, events, when, crop=None):
    """One click's events -> the group's memory: today's tally per event type (reset on a new game day), the crops grown
    here (from cards/seeds), the last event, and the can (out_of_water -> empty, a fill -> full). Returns the changes."""
    out = []
    day = _DAY_OF.match(when or '')
    day = int(day.group(1)) if day else None
    t = dict(graph.state_value(group, 'today') or {})
    if t.get('day') != day:
        t = {'day': day}
    for e in events:
        if e in TALLY:
            t[TALLY[e]] = t.get(TALLY[e], 0) + 1
    if len(t) > 1 or events:
        graph.set_state(group, 'today', t, when, 'event')
        out.append((group, 'today', t))
    if events:
        graph.set_state(group, 'last_event', events[-1], when, 'event')
        out.append((group, 'last_event', events[-1]))
    if crop:
        crops = list(graph.state_value(group, 'crops') or [])
        if crop not in crops:
            graph.set_state(group, 'crops', crops + [crop], when, 'event')
            out.append((group, 'crops', crops + [crop]))
    can = 'empty' if 'out_of_water' in events else 'full' if any(e in ('fill_watering_can', 'full_watering_can')
                                                                    for e in events) else None
    if can and 'Tara' in graph.nodes:
        graph.set_state('Tara', 'can', can, when, 'event')
        out.append(('Tara', 'can', can))
    return out


def hint(graph, group):
    """What memory tells vision about the group: crops grown, today's tally, the other objects of its region."""
    n = graph.nodes.get(group)
    if n is None:
        return ''
    parts = []
    crops = graph.state_value(group, 'crops')
    if crops:
        parts.append('crops grown here: ' + ', '.join(crops))
    t = graph.state_value(group, 'today') or {}
    tally = ', '.join(f'{k} {v}' for k, v in t.items() if k != 'day')
    if tally:
        parts.append(f'today (D{t.get("day")}): {tally}')
    if n.region and n.region in graph.nodes:
        near = sorted({c.kind for c in graph.children(n.region) if c.id != group and c.kind and c.kind != 'Tara'})
        if near:
            parts.append(f'the {n.region} also has: ' + ', '.join(near))
    can = graph.state_value('Tara', 'can') if 'Tara' in graph.nodes else None
    if can:
        parts.append(f'can: {can}')
    return '; '.join(parts)


_DAY_OF = re.compile(r'D(\d+)')


def _seed_toward():
    """Seeded screen directions between frame nodes (game/kinds.json `_toward`, D185 farm frame): fixed camera looking
    north, so a direction holds at any zoom. (dx, dy) unit vectors in frame px. Learned `toward` edges replace them."""
    import json
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'game', 'kinds.json')
    try:
        with open(p) as f:
            return {tuple(k.split('->')): tuple(v) for k, v in json.load(f).get('_toward', {}).items()}
    except (OSError, ValueError):
        return {}


TOWARD = _seed_toward()


def toward(graph, a, b):
    """Screen direction from node `a` to node `b`: a `toward` edge in the graph, else the TOWARD default, else from
    their world positions (`pos` of the nodes or their regions, e.g. one garden to another, L137); None if unknown."""
    for e in graph.edges(a, 'toward') if graph is not None else []:
        if e['b'] == b and e.get('dir'):
            return tuple(e['dir'])
    if (a, b) in TOWARD:
        return TOWARD[(a, b)]
    pa, pb = pos_of(graph, a), pos_of(graph, b)
    return screen_dir(pa, pb) if pa and pb else None


def node_of_line(line):
    """The graph node a game-log interaction line is about: `target=GardenBed (4)` -> GardenBed@Garden, `target=Well` ->
    Well, `target=BeeHive(Clone)` -> BeeHive. None when it names no target."""
    m = re.search(r'target=([A-Za-z]+)', line)
    if not m:
        return None
    k = m.group(1)
    return {'GardenBed': 'GardenBed@Garden'}.get(k, k)


def learn_toward(graph, a, b, d, rate=0.5):
    """A step from node a in screen direction d reached node b: the a->b `toward` edge moves `rate` of the way to d
    (starting from TOWARD's default), unit length, source 'learned'."""
    import math
    old = toward(graph, a, b) or d
    x, y = old[0] + rate * (d[0] - old[0]), old[1] + rate * (d[1] - old[1])
    n = math.hypot(x, y) or 1.0
    graph._edges = [e for e in graph._edges if not (e['a'] == a and e['b'] == b and e['rel'] == 'toward')]
    graph.add_edge(a, b, 'toward', dir=[round(x / n, 3), round(y / n, 3)], source='learned')


def pos_of(graph, node):
    """World (x, z) of a node or of its nearest ancestor that has one; None."""
    for nid in reversed(graph.chain(node)) if graph is not None and node in graph.nodes else []:
        p = graph.nodes[nid].extra.get('pos')
        if p:
            return tuple(p)
    return None


def screen_dir(a, b):
    """Screen direction (unit dx, dy) from world point a to world point b: the camera looks north, so world +x = right
    and world +z = up (screen -y)."""
    import math
    dx, dy = b[0] - a[0], -(b[1] - a[1])
    n = math.hypot(dx, dy)
    return None if n < 1e-6 else (dx / n, dy / n)
