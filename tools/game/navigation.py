"""Bounded graph/compass receipts for model-owned waypoint decisions."""
from collections import deque
import math
import re


COMPASS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')


def _field(value, name, default=None):
    return value.get(name, default) if hasattr(value, 'get') else getattr(value, name, default)


def _compass(dx, screen_dy):
    angle = math.degrees(math.atan2(dx, -screen_dy)) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


def _load_graph(observation):
    from . import engine, world
    graph = engine._open_graph()
    world.landmarks(graph)
    scene = observation.get('region') or observation.get('scene')
    if scene and 'Tara' in graph.nodes:
        graph.nodes['Tara'].region = scene
    return graph


def _node(graph, name):
    folded = str(name).casefold()
    return next((node.id for node in graph.nodes.values()
                 if node.id.casefold() == folded or str(node.kind).casefold() == folded), None)


def _observed_current(graph, observation, task=None):
    """Use explicit region/ancestry proof as route origin; never infer one from numeric proximity."""
    observed = None
    for candidate in (observation.get('region'), observation.get('scene')):
        key = _node(graph, candidate) if candidate else None
        if key:
            observed = key
            break
    params = _field(task, 'params', {}) or {}
    durable = params.get('_nav_current')
    proof = params.get('_nav_current_proof') or {}
    if durable in graph.nodes and proof.get('source') in ('positioned_event', 'transition'):
        ancestry = graph.chain(durable)
        if observed is None or observed in ancestry:
            return durable, proof['source']
    return (observed, 'observed_region') if observed else (None, None)


def _path(graph, start, goal):
    adjacent = {}
    for edge in graph.edges(rel='nav'):
        if edge.get('walkable') is not True:
            raise ValueError(f'non-walkable navigation edge {edge["a"]}->{edge["b"]}')
        adjacent.setdefault(edge['a'], []).append(edge['b'])
    queue, previous = deque([start]), {start: None}
    while queue:
        node = queue.popleft()
        if node == goal:
            out = []
            while node is not None:
                out.append(node)
                node = previous[node]
            return out[::-1]
        for target in adjacent.get(node, ()):
            if target not in previous:
                previous[target] = node
                queue.append(target)
    return None


def receipt(task, observation, graph=None):
    """Resolve one qualitative graph step without metric coordinates, calibration, or dead reckoning."""
    import nav as learned

    params = _field(task, 'params', {}) or {}
    requested = params.get('destination') or params.get('where') or params.get('region')
    scene = observation.get('region') or observation.get('scene')
    graph = graph or _load_graph(observation)
    data = learned.map_load(learned.MAP)
    aliases = {str(key).casefold(): value for key, value in (data.get('aliases') or {}).items()}
    aliases.setdefault('supermarket', 'DahlGeneralStore')
    canonical = aliases.get(str(requested).casefold(), requested) if requested else None
    goal_key = _node(graph, canonical) if canonical else None
    if goal_key is None and canonical:
        goal_key = next((node.id for node in graph.nodes.values()
                         if str(node.kind).casefold() == str(canonical).casefold()), None)
    base = {'requested': requested, 'resolved_as': canonical, 'scene': scene}
    if not goal_key:
        return dict(base, status='unresolved_destination', goal=None, next_edge=None)
    goal = graph.nodes[goal_key]
    goal_receipt = {'node': goal_key, 'scene': scene,
                    'source': goal.extra.get('source'),
                    'enterable': bool(goal.extra.get('enterable'))}
    current, current_source = _observed_current(graph, observation, task)
    if current is None:
        return dict(base, status='unresolved_graph_position', goal=goal_receipt, next_edge=None,
                    graph={'current_node': None, 'destination': goal_key})
    steps = _path(graph, current, goal_key)
    if steps is None:
        return dict(base, status='unresolved_path', goal=goal_receipt, next_edge=None)
    if len(steps) == 1:
        current_node = graph.nodes[current]
        return dict(base, status='arrived', goal=goal_receipt, next_edge=None,
                    graph={'current_node': current, 'destination': goal_key, 'path': steps,
                           'current_source': current_source,
                           'current_navigation_only': bool(current_node.extra.get('navigation_only')),
                           'current_enterable': bool(current_node.extra.get('enterable'))})
    next_key = steps[1]
    edge = next(row for row in graph.edges(current, 'nav') if row['b'] == next_key)
    target = graph.nodes[next_key]
    next_edge = {'from': current, 'to': next_key, 'relation': 'nav',
             'source': edge.get('source'), 'compass': edge.get('compass'), 'range': edge.get('range'),
             'transition': edge.get('transition'),
             'walkable': True, 'navigation_only': bool(target.extra.get('navigation_only')),
             'enterable': bool(target.extra.get('enterable'))}
    current_node = graph.nodes[current]
    return dict(base, status='resolved', goal=goal_receipt, next_edge=next_edge,
                graph={'current_node': current, 'destination': goal_key, 'path': steps,
                       'current_source': current_source,
                       'current_navigation_only': bool(current_node.extra.get('navigation_only')),
                       'current_enterable': bool(current_node.extra.get('enterable'))})


def assess(action, navigation):
    """Compare one captured-view point with qualitative graph guidance; coordinates never leave this observation."""
    point = action.get('point') or ()
    if not point and action.get('cell'):
        match = re.fullmatch(r'([A-Xa-x])(1[0-6]|[1-9])', action['cell'])
        if match:
            point = ((ord(match[1].upper()) - 65 + .5) * 80, (int(match[2]) - .5) * 67.5)
    if len(point) != 2:
        return {'allowed': False, 'alignment': 'invalid', 'reason': 'waypoint needs a two-coordinate point'}
    sx, sy = point
    dx, dy = sx - 960, sy - 540
    screen_compass = _compass(dx, dy)
    radius = math.hypot(dx, dy)
    observed_range = 'near' if radius < 180 else 'mid' if radius < 420 else 'far'
    edge = (navigation or {}).get('next_edge') or {}
    graph_compass, graph_range = edge.get('compass'), edge.get('range')
    alignment = 'unknown'
    allowed = True
    if graph_compass in COMPASS:
        sectors = abs(COMPASS.index(screen_compass) - COMPASS.index(graph_compass))
        sectors = min(sectors, len(COMPASS) - sectors)
        allowed = sectors <= 1
        alignment = 'aligned' if allowed else 'mismatch'
    if allowed and graph_range in ('near', 'mid', 'far') and observed_range != graph_range:
        allowed, alignment = False, 'range_mismatch'
    return {'allowed': allowed, 'alignment': alignment, 'screen_compass': screen_compass,
            'range': observed_range, 'graph_compass': graph_compass, 'graph_range': graph_range}


def advance(task, experience):
    """Remember only a transition-proven region; waypoint movement alone never advances graph position."""
    if experience.verdict.value != 'hit':
        return
    before = dict(experience.before.state)
    after = dict(experience.evidence.state)
    navigation = before.get('navigation') or {}
    edge = navigation.get('next_edge') or {}
    before_region = before.get('region') or before.get('scene')
    after_region = after.get('region') or after.get('scene')
    proof = after.get('region_provenance') or {}
    regions = list(after.get('regions') or ())
    owner = task.stack[-1] if task.stack and task.stack[-1].goal == 'navigate' else task
    if (proof.get('source') == 'positioned_event' and
            (edge.get('to') == proof.get('node') or edge.get('to') in regions)):
        owner.params['_nav_current'] = edge['to']
        owner.params['_nav_current_proof'] = dict(proof)
    elif edge.get('transition') and after_region == edge['transition'] and after_region != before_region:
        owner.params['_nav_current'] = edge['to']
        owner.params['_nav_current_proof'] = {'source': 'transition', 'experience': experience.id,
                                              'region': after_region}
