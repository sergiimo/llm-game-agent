"""Bounded graph/compass receipts for model-owned waypoint decisions."""
from collections import deque
import math
import re


COMPASS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')
MAX_LOCALIZATION_LANDMARKS = 8
MAX_LOCALIZATION_ROUTE_NODES = 8


def _field(value, name, default=None):
    return value.get(name, default) if hasattr(value, 'get') else getattr(value, name, default)


def _compass(dx, screen_dy):
    angle = math.degrees(math.atan2(dx, -screen_dy)) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


def map_route(origin, target):
    """Derive a qualitative map-space route from two model-labelled map points."""
    if (not isinstance(origin, (list, tuple)) or not isinstance(target, (list, tuple)) or
            len(origin) != 2 or len(target) != 2 or
            any(type(value) not in (int, float) for value in (*origin, *target))):
        raise ValueError('map route needs two numeric [x,y] points')
    if any(value < 0 for value in (*origin, *target)) or origin[0] > 1920 or target[0] > 1920 or \
            origin[1] > 1080 or target[1] > 1080:
        raise ValueError('map route points must be inside the full-scale frame')
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    distance = math.hypot(dx, dy)
    if distance < 24:
        raise ValueError('map route points are too close to establish a direction')
    route_range = 'near' if distance < 140 else 'mid' if distance < 320 else 'far'
    return {'compass': _compass(dx, dy), 'range': route_range,
            'origin_point': list(origin), 'target_point': list(target),
            'map_distance': round(distance, 1)}


def movement_alignment(before, after, navigation):
    """Compare save-position movement with a map-space hint after the game has moved Tara."""
    hint = (navigation or {}).get('route_hint') or {}
    if hint.get('source') != 'model_map':
        return None
    old_pos, new_pos = before.get('position'), after.get('position')
    if (not isinstance(old_pos, (list, tuple)) or not isinstance(new_pos, (list, tuple)) or
            len(old_pos) != 2 or len(new_pos) != 2):
        return None
    dx, dy = new_pos[0] - old_pos[0], new_pos[1] - old_pos[1]
    if math.hypot(dx, dy) < .5:
        return None
    # Save/world Z grows north while the illustrated map's Y grows south, so invert the second save axis before
    # comparing it with map-space compass. A move changing [x,z] by [0,-3] is map south.
    actual, expected = _compass(dx, -dy), hint.get('compass')
    sectors = abs(COMPASS.index(actual) - COMPASS.index(expected))
    sectors = min(sectors, len(COMPASS) - sectors)
    return {'allowed': sectors <= 1, 'expected_compass': expected,
            'actual_compass': actual, 'delta': [round(dx, 3), round(dy, 3)]}


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
    if durable in graph.nodes and proof.get('source') in ('positioned_event', 'transition', 'navigation_step'):
        ancestry = graph.chain(durable)
        if observed is None or observed in ancestry:
            return durable, proof['source']
    position_node = observation.get('position_node')
    position_proof = observation.get('position_node_provenance') or {}
    if position_node in graph.nodes and position_proof.get('source') == 'sleep_spawn':
        ancestry = graph.chain(position_node)
        if observed is None or observed in ancestry:
            return position_node, 'sleep_spawn'
    # A fresh candidate alone is only an appearance hint. Candidate + an affordance that the same unique node
    # offers is local interaction proof (for example Well + fill_can, Bed + sleep), strong enough to start the
    # qualitative route at that nested node without borrowing any last-task state.
    affordances = {str(row.get('kind')) for row in observation.get('visible_affordances', ())
                   if isinstance(row, dict) and row.get('kind')}
    candidate_kinds = {str(row.get('kind')) for row in observation.get('candidates', ())
                       if isinstance(row, dict) and row.get('kind')}
    proved = []
    for node in graph.nodes.values():
        if node.type != 'unique' or str(node.kind) not in candidate_kinds:
            continue
        offers = {str(edge.get('b')) for edge in graph.edges(node.id, 'offers')}
        if offers & affordances:
            proved.append(node.id)
    if len(proved) == 1:
        ancestry = graph.chain(proved[0])
        if observed is None or observed in ancestry:
            return proved[0], 'visible_affordance'
    # A highlighted named affordance can itself localise a unique provider even when its appearance vector misses.
    # Indoors, for example, the sleep bubble beside Tara proves the one Bed that offers sleep more directly than
    # clicking that bubble while a navigate-to-Bed child still owns the turn.
    affordance_providers = []
    for node in graph.nodes.values():
        if node.type != 'unique':
            continue
        offers = {str(edge.get('b')) for edge in graph.edges(node.id, 'offers')}
        if offers & affordances:
            ancestry = graph.chain(node.id)
            if observed is None or observed in ancestry:
                affordance_providers.append(node.id)
    if len(affordance_providers) == 1:
        return affordance_providers[0], 'visible_affordance'
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


def _opposite(compass):
    return COMPASS[(COMPASS.index(compass) + 4) % len(COMPASS)]


def _route_slice(graph, steps):
    nodes = list(steps or ())[:MAX_LOCALIZATION_ROUTE_NODES]
    edges = []
    for source, target in zip(nodes, nodes[1:]):
        edge = next((row for row in graph.edges(source, 'nav') if row.get('b') == target), {})
        edges.append({
            'from': source, 'to': target, 'compass': edge.get('compass'),
            'range': edge.get('range'), 'source': edge.get('source'),
            'transition': edge.get('transition'),
        })
    return {'route_nodes': nodes, 'route_edges': edges}


def _vector_landmarks(graph, observation):
    rows = [row for row in observation.get('candidates', ())
            if isinstance(row, dict) and row.get('source') == 'vector' and
            row.get('kind') != 'Tara' and isinstance(row.get('point'), (list, tuple)) and
            len(row['point']) == 2]
    if not rows:
        rows = [dict(row, id=row.get('id') or f'vector-{index}', source='vector')
                for index, row in enumerate(observation.get('vector_detections', ()))
                if isinstance(row, dict) and row.get('kind') != 'Tara' and
                isinstance(row.get('point'), (list, tuple)) and len(row['point']) == 2]
    strongest = {}
    for index, row in enumerate(rows):
        node_id = _node(graph, row.get('kind'))
        node = graph.nodes.get(node_id) if node_id else None
        if node is None or node.type != 'unique':
            continue
        score = row.get('score')
        rank = float(score) if type(score) in (int, float) else float('-inf')
        if node_id not in strongest or rank > strongest[node_id][0]:
            strongest[node_id] = (rank, index, row, node)
    landmarks = []
    for _rank, _index, row, node in sorted(strongest.values(), key=lambda item: item[1])[
            :MAX_LOCALIZATION_LANDMARKS]:
        point = list(row['point'])
        node_id = node.id
        bearing = _compass(float(point[0]) - 960, float(point[1]) - 540)
        landmarks.append({
            'candidate': row.get('id'), 'kind': row.get('kind'), 'node': node_id,
            'point': point, 'landmark_from_tara': bearing,
            'tara_from_landmark': _opposite(bearing),
            'region': node.region if node else None,
        })
    return landmarks


EXACT_GRAPH_SOURCES = frozenset({'sleep_spawn', 'navigation_step', 'transition', 'positioned_event'})


def _localization(graph, observation, params, current=None, steps=(), current_source=None):
    landmarks = _vector_landmarks(graph, observation)
    belief = params.get('_navigation_belief') or {}
    exact = current is not None and current_source in EXACT_GRAPH_SOURCES
    base = {
        'current': current if exact else 'unknown',
        'likely_region': current,
        'prior_hint': belief.get('current'),
        'landmarks': landmarks,
        'graph_slice': _route_slice(graph, steps),
    }
    if exact:
        return dict(base, stage='graph', next='follow_graph_route')
    if landmarks:
        return dict(base, stage='vectors', next='localize_from_vectors_and_graph')
    return dict(base, stage='vision', next='identify_unique_object_and_create_vector',
                after_vision='map_if_still_unresolved')


def _map_anchor(graph, goal_key):
    """Nearest goal/ancestor explicitly represented on the illustrated map."""
    for node_id in reversed(graph.chain(goal_key)):
        node = graph.nodes[node_id]
        marker = node.extra.get('map')
        if isinstance(marker, dict) and marker.get('kind'):
            return {'node': node_id, 'kind': marker['kind'], 'label': marker.get('label'),
                    'exact': node_id == goal_key}
    return None


def map_target(navigation):
    """Map-bindable node for a navigation receipt; unique unmarked subobjects use their labeled ancestor."""
    goal = (navigation or {}).get('goal') or {}
    anchor = goal.get('map_anchor') or {}
    return anchor.get('node') or goal.get('node')


def receipt(task, observation, graph=None):
    """Expose qualitative graph/map evidence; the model's task-local belief owns route semantics."""
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
    base = {'requested': requested, 'resolved_as': canonical, 'scene': scene,
            'authority': 'advisory', 'belief': params.get('_navigation_belief'),
            'localization': _localization(graph, observation, params)}
    if not goal_key:
        return dict(base, status='unresolved_destination', goal=None, next_edge=None)
    goal = graph.nodes[goal_key]
    goal_receipt = {'node': goal_key, 'scene': scene,
                    'source': goal.extra.get('source'),
                    'enterable': bool(goal.extra.get('enterable'))}
    map_anchor = _map_anchor(graph, goal_key)
    if map_anchor:
        goal_receipt['map_anchor'] = map_anchor
    current, current_source = _observed_current(graph, observation, task)
    if current is None:
        return dict(base, status='unresolved_graph_position', goal=goal_receipt, next_edge=None,
                    graph={'current_node': None, 'destination': goal_key})
    steps = _path(graph, current, goal_key)
    base['localization'] = _localization(graph, observation, params, current, steps, current_source)
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
    hint = params.get('_route_hint') or {}
    if hint and hint.get('region') == scene:
        remaining = hint.get('remaining_steps')
        if remaining is None:  # upgrade a persisted turn-based hint without discarding its captured map proof
            remaining = max(1, int(hint.get('expires_turn') or 0) - int(hint.get('set_turn') or 0))
            hint = dict(hint, remaining_steps=remaining)
        if int(remaining) <= 0:
            return dict(base, status='route_hint_expired', goal=goal_receipt, next_edge=None,
                        graph={'current_node': current, 'destination': goal_key, 'path': steps,
                               'current_source': current_source}, route_hint=dict(hint))
        next_edge.update(compass=hint.get('compass'), range=hint.get('range'), source='model_map')
    current_node = graph.nodes[current]
    return dict(base, status='resolved', goal=goal_receipt, next_edge=next_edge,
                graph={'current_node': current, 'destination': goal_key, 'path': steps,
                       'current_source': current_source,
                       'current_navigation_only': bool(current_node.extra.get('navigation_only')),
                       'current_enterable': bool(current_node.extra.get('enterable'))},
                route_hint=dict(hint) if hint else None)


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
    # Map direction is world/map space, while this point is screen space. The camera projection can vary by scene,
    # so verify the resulting save-position vector after movement instead of comparing unlike coordinates here.
    if edge.get('source') == 'model_map':
        return {'allowed': action.get('walkable') is True, 'alignment': 'map_postcheck',
                'screen_compass': screen_compass, 'range': observed_range,
                'graph_compass': graph_compass, 'graph_range': graph_range}
    alignment = 'unknown'
    allowed = True
    visible_detour = (action.get('visible_detour') is True and action.get('walkable') is True and
                      observed_range in ('near', 'mid'))
    if visible_detour:
        alignment = 'visible_detour'
    elif graph_compass in COMPASS:
        sectors = abs(COMPASS.index(screen_compass) - COMPASS.index(graph_compass))
        sectors = min(sectors, len(COMPASS) - sectors)
        allowed = sectors <= 1
        alignment = 'aligned' if allowed else 'mismatch'
    if not visible_detour and allowed and graph_range in ('near', 'mid', 'far') and observed_range != graph_range:
        ranks = {'near': 0, 'mid': 1, 'far': 2}
        if ranks[observed_range] < ranks[graph_range]:
            # Edge range describes how far away the destination is, not a minimum click length. A shorter
            # compass-aligned visible step is safe incremental progress; only overshooting a nearer edge is unsafe.
            alignment = 'aligned_approach'
        else:
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
    route_hint = owner.params.get('_route_hint')
    if route_hint:
        if after_region != route_hint.get('region'):
            owner.params.pop('_route_hint', None)
        elif experience.evidence.moved is True:
            route_hint['remaining_steps'] = max(0, int(route_hint.get('remaining_steps',
                max(1, int(route_hint.get('expires_turn') or 0) - int(route_hint.get('set_turn') or 0)))) - 1)
    if (proof.get('source') == 'positioned_event' and
            (edge.get('to') == proof.get('node') or edge.get('to') in regions)):
        owner.params['_nav_current'] = edge['to']
        owner.params['_nav_current_proof'] = dict(proof)
    elif edge.get('transition') and after_region == edge['transition'] and after_region != before_region:
        owner.params['_nav_current'] = edge['to']
        owner.params['_nav_current_proof'] = {'source': 'transition', 'experience': experience.id,
                                              'region': after_region}
    elif after_region and after_region != before_region:
        path = ((navigation.get('graph') or {}).get('path') or ())
        graph = _load_graph(after)
        matched = next(((a, b, candidate) for a, b in zip(path, path[1:])
                        for candidate in graph.edges(a, 'nav')
                        if candidate.get('b') == b and candidate.get('transition') == after_region), None)
        if matched:
            owner.params['_nav_current'] = matched[1]
            owner.params['_nav_current_proof'] = {
                'source': 'transition', 'experience': experience.id, 'region': after_region}
    elif (edge.get('navigation_only') and experience.evidence.moved is True and experience.action and
          experience.action.kind == 'click' and experience.action.what == 'step'):
        assessment = assess({'point': list(experience.action.pt or ()), 'walkable': True}, navigation)
        if assessment.get('allowed') and assessment.get('alignment') in ('aligned', 'aligned_approach'):
            owner.params['_nav_current'] = edge['to']
            owner.params['_nav_current_proof'] = {
                'source': 'navigation_step', 'experience': experience.id, 'region': after_region}
