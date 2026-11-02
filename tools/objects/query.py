"""Goal queries and region paths on the object graph. Q picks target nodes (by kind / offered action / state hints),
path() lists the region steps to reach one: exit each region up to the common ancestor (via its exit node when it has
one), enter each region down, then reach the node."""
from collections import namedtuple

from .graph import order

Step = namedtuple('Step', 'action node')   # action: exit | enter | reach; node: graph Node


def _regions(graph, id):
    """Region nodes (type 'region') on the chain of `id`, top first, `id` itself included when it is a region."""
    return [c for c in graph.chain(id) if graph.nodes[c].type == 'region']


def path(graph, from_region, to_node):
    """[Step]: exit regions of from_region up to the common ancestor, enter regions down to the target's region, reach it.
    `to_node` is a node id or Node (a region target ends with `enter`; already there -> []); unknown ids -> []."""
    tid = getattr(to_node, 'id', to_node)
    if tid not in graph.nodes or from_region not in graph.nodes:
        return []
    src = _regions(graph, from_region)
    is_region = graph.nodes[tid].type == 'region'
    dst = _regions(graph, tid) if is_region else [r for r in _regions(graph, tid) if r != tid]
    n = 0
    while n < min(len(src), len(dst)) and src[n] == dst[n]:
        n += 1
    steps = []
    for r in reversed(src[n:]):
        node = graph.nodes[r]
        ex = node.extra.get('exit')
        steps.append(Step('exit', graph.nodes.get(ex) or node))
    steps += [Step('enter', graph.nodes[r]) for r in dst[n:]]
    if not is_region:
        steps.append(Step('reach', graph.nodes[tid]))
    return steps


class Q:
    """Query: Q(kind='GardenBed', offers='plant').where(crop=None). A state filter matches the hint's value (None =
    no hint or None value). Candidates are unique nodes and group members."""

    def __init__(self, kind=None, offers=None, state=None):
        self.kind, self.offers, self.state = kind, offers, dict(state or {})

    def where(self, **state):
        return Q(self.kind, self.offers, {**self.state, **state})

    def _offered(self, graph, n):
        for id in (n.id, n.region, n.kind):
            if any(e['b'] == self.offers for e in graph.edges(id, 'offers')):
                return True
        return False

    def run(self, graph, current_region, visible=frozenset()):
        out = []
        for n in graph.nodes.values():
            if n.type not in ('unique', 'member'):
                continue
            if self.kind is not None and n.kind != self.kind:
                continue
            if self.offers is not None and not self._offered(graph, n):
                continue
            if any(graph.state_value(n.id, k) != v for k, v in self.state.items()):
                continue
            out.append(n)
        key = lambda n: (n.id not in visible, len(path(graph, current_region, n)), order(n))  # noqa: E731
        return sorted(out, key=key)
