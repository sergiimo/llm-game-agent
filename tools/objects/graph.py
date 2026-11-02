"""Object graph with nested regions (no coordinates: identity = kind, region, pattern index). Nodes are regions,
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

    def members(self, group_id):
        return sorted((n for n in self.children(group_id) if n.type == 'member'), key=lambda n: n.extra.get('index', 0))

    def add_edge(self, a, b, rel, **attrs):
        e = {'a': a, 'b': b, 'rel': rel, **attrs}
        if e not in self._edges:
            self._edges.append(e)

    def edges(self, a=None, rel=None):
        return [e for e in self._edges if (a is None or e['a'] == a) and (rel is None or e['rel'] == rel)]

    def set_state(self, id, key, value, game_time, source):
        self.nodes[id].state[key] = {'value': value, 'game_time': game_time, 'source': source}

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


_STAMP = re.compile(r'^\[(D(\d+)) ([^\]]+)\]')
_ACT = re.compile(r'>\s*(\w+)\b[^\n]*?target=(\w+)')


def apply_log(graph, lines, beds):
    """Update node states from game-log lines (source 'log', game_time = the line's stamp 'D148 9:36:36 PM'):
    `> fill_watering_can|full_watering_can ... target=Well` -> Well can=full;
    `> plant|water|unplant_impl ... target=GardenBed ... at (x, y, z)`
    -> that bed member (identity.member_from_log) crop=planted | watered=<game day> | crop=None. Returns
    [(node_id, key, value, game_time)] of the changes in order."""
    from .identity import member_from_log
    out = []
    for line in lines:
        st, m = _STAMP.match(line), _ACT.search(line)
        if not st or not m:
            continue
        act, target = m.group(1), m.group(2)
        when = f'{st.group(1)} {st.group(3)}'
        if act in ('fill_watering_can', 'full_watering_can') and target == 'Well' and 'Well' in graph.nodes:
            ch = ('Well', 'can', 'full')
        elif target == 'GardenBed' and act in ('plant', 'water', 'unplant_impl'):
            mid = member_from_log(line, beds)
            if mid is None or mid not in graph.nodes:
                continue
            ch = (mid, 'crop', 'planted') if act == 'plant' else (mid, 'watered', int(st.group(2))) \
                if act == 'water' else (mid, 'crop', None)
        else:
            continue
        graph.set_state(ch[0], ch[1], ch[2], when, 'log')
        out.append((*ch, when))
    return out
