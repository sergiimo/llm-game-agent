"""Scene graph (spec 2026-10-30 §3, networkx): areas' places, anchors, exits, proven trail points and entities as
nodes; exits connect areas. Map-only places are not added (S18: their area would be a guess). Routes between areas are
A* over this graph; inside an area the costmap plans the actual path."""
import math

import networkx as nx

import nav


def build(entities, facts, places=None):
    """DiGraph: nodes '<area>:<name>' with area/x/z/src; edges with 'cost' and 'kind' (walk / link)."""
    ns = nav.nodes(facts, None)          # no map places: places known only from map pins are not in the graph
    G = nx.DiGraph()
    for k, n in ns.items():
        G.add_node(k, area=n['scene'], x=n.get('x'), z=n.get('z'), src=n['src'], name=n['name'])
    for e in entities.all:
        G.add_node(f'{e.area}:{e.kind}#{e.id}', area=e.area, x=e.x, z=e.z, src='entity', name=f'{e.kind}#{e.id}')
    for a, b, c, kind in nav.edges_graph(facts, ns):
        G.add_edge(a, b, cost=c, kind=kind)
    by_area = {}
    for k, d in G.nodes(data=True):
        by_area.setdefault(d['area'], []).append(k)
    for k, d in G.nodes(data=True):  # entities reachable from every positioned node of their area (costmap decides how)
        if d['src'] == 'entity':
            for o in by_area[d['area']]:
                od = G.nodes[o]
                if o != k and od['x'] is not None:
                    c = math.dist((d['x'], d['z']), (od['x'], od['z']))
                    G.add_edge(o, k, cost=c, kind='walk')
                    G.add_edge(k, o, cost=c, kind='walk')
    return G


def route(G, start, goal):
    """Node keys from start (area, x, z) to the node `goal` (A* on cost), or None."""
    if goal not in G:
        return None
    area, x, z = start
    H = G.copy()
    H.add_node('@start', area=area, x=x, z=z, src='start', name='@start')
    for k, d in G.nodes(data=True):
        if d['area'] == area and d['x'] is not None:
            H.add_edge('@start', k, cost=math.dist((x, z), (d['x'], d['z'])), kind='walk')
    try:
        path = nx.astar_path(H, '@start', goal, weight='cost')
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    return path[1:]
