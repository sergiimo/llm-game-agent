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

    def add_edge(self, a, b, rel, **attrs):
        if rel == 'toward' and attrs.get('dir') and not attrs.get('compass'):   # user D188: ways keep a compass
            attrs['compass'] = compass(attrs['dir'])
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


COMPASS = {'N': (0.0, -1.0), 'NE': (0.707, -0.707), 'E': (1.0, 0.0), 'SE': (0.707, 0.707), 'S': (0.0, 1.0),
           'SW': (-0.707, 0.707), 'W': (-1.0, 0.0), 'NW': (-0.707, -0.707)}   # screen = map: north is up


def set_edge(graph, a, b, rel, **attrs):
    """The one a -> b edge of `rel`, replaced by these attributes (a distance edge is rewritten each step)."""
    graph._edges = [e for e in graph._edges if not (e['a'] == a and e['b'] == b and e['rel'] == rel)]
    graph.add_edge(a, b, rel, **attrs)


def compass(d):
    """The compass point (N..NW) nearest a screen direction (dx, dy; +y = south)."""
    import math
    ang = math.degrees(math.atan2(d[0], -d[1])) % 360   # 0 = N, clockwise
    return ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')[int((ang + 22.5) // 45) % 8]


def compass_dir(c):
    return COMPASS.get(str(c).strip().upper())


def toward(graph, a, b):
    """Screen direction from node `a` to node `b`: a `toward` edge in the graph, else the TOWARD default, else from
    their world positions (`pos` of the nodes or their regions, e.g. one garden to another, L137); None if unknown."""
    for e in graph.edges(a, 'toward') if graph is not None else []:
        if e['b'] == b and e.get('dir'):
            return tuple(e['dir'])
        if e['b'] == b and compass_dir(e.get('compass')):   # a way known only by its compass point
            return compass_dir(e['compass'])
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
