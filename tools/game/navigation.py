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


def _position(task, observation, scene, graph):
    params = _field(task, 'params', {}) or {}
    estimate = params.get('_nav_estimate') or {}
    if estimate.get('scene') == scene and estimate.get('position'):
        value = list(estimate['position'])
        if graph is not None and 'Tara' in graph.nodes:
            graph.nodes['Tara'].extra['pos'] = value
            graph.nodes['Tara'].region = scene
        return {'value': value, 'source': estimate.get('source', 'estimate'),
                'experience': estimate.get('experience')}
    tara = graph.nodes.get('Tara') if graph is not None else None
    value = observation.get('position') or (tara.extra.get('pos') if tara is not None else None)
    if not value:
        return None
    source = ((observation.get('state_provenance') or {}).get('position') or {}).get('source', 'observation')
    return {'value': list(value), 'source': source}


def _load_graph(observation):
    from . import engine, world
    graph = engine._open_graph()
    world.landmarks(graph)
    scene = observation.get('region') or observation.get('scene')
    if scene and 'Tara' in graph.nodes:
        graph.nodes['Tara'].region = scene
        if observation.get('position'):
            graph.nodes['Tara'].extra['pos'] = list(observation['position'])
    return graph


def _node(graph, name):
    folded = str(name).casefold()
    return next((node.id for node in graph.nodes.values()
                 if node.id.casefold() == folded or str(node.kind).casefold() == folded), None)


def _nearest_nav_node(graph, scene, point):
    endpoints = {edge[key] for edge in graph.edges(rel='nav') for key in ('a', 'b')}
    candidates = []
    for node_id in endpoints:
        node = graph.nodes.get(node_id)
        pos = node.extra.get('pos') if node else None
        if not pos or scene not in graph.chain(node_id):
            continue
        candidates.append((math.dist(point, pos), node_id))
    return min(candidates)[1] if candidates else None


def _map_pin_node(graph, scene, pin):
    if not pin:
        return None
    candidates = []
    nav_nodes = {edge[key] for edge in graph.edges(rel='nav') for key in ('a', 'b')}
    for node_id in nav_nodes:
        node = graph.nodes.get(node_id)
        map_info = node.extra.get('map') if node else None
        point = map_info.get('point') if isinstance(map_info, dict) and map_info.get('scene') == scene else None
        if point:
            candidates.append((math.dist(pin, point), node_id))
    if not candidates:
        return None
    candidates.sort()
    from .world import LANDMARK_PX
    if candidates[0][0] > LANDMARK_PX:
        return None
    if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 10.0:
        return None
    return candidates[0][1]


def _newer_position_proof(observed, durable):
    if not observed or not durable:
        return bool(observed) and not durable
    if observed.get('path') and durable.get('path') and observed['path'] != durable['path']:
        return True
    if (type(observed.get('save_count')) is int and type(durable.get('save_count')) is int and
            observed['save_count'] > durable['save_count']):
        return True
    from .world import when
    observed_time, durable_time = when(observed.get('game_time')), when(durable.get('game_time'))
    return observed_time is not None and durable_time is not None and observed_time > durable_time


def _near_current(graph, node_id, scene, point, max_distance=3.0):
    """A current nav node must belong to this scene and be within 3 world units of Tara's observed position."""
    if node_id not in graph.nodes or scene not in graph.chain(node_id):
        return False
    node_pos = graph.nodes[node_id].extra.get('pos')
    return bool(point and node_pos and math.dist(point, node_pos) <= max_distance)


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
    """Resolve one graph-native step. Legacy navigation data is used only for aliases and click calibration."""
    import nav as learned
    from objects import graph as OG

    params = _field(task, 'params', {}) or {}
    requested = params.get('destination') or params.get('where') or params.get('region')
    scene = observation.get('region') or observation.get('scene')
    graph = graph or _load_graph(observation)
    position = _position(task, observation, scene, graph)
    data = learned.map_load(learned.MAP)
    aliases = {str(key).casefold(): value for key, value in (data.get('aliases') or {}).items()}
    aliases.setdefault('supermarket', 'DahlGeneralStore')
    canonical = aliases.get(str(requested).casefold(), requested) if requested else None
    goal_key = _node(graph, canonical) if canonical else None
    if goal_key is None and canonical:
        goal_key = next((node.id for node in graph.nodes.values()
                         if str(node.kind).casefold() == str(canonical).casefold()), None)
    calibration = learned.calib_load(scene, learned.ROOT) if scene else None
    calibration_receipt = ({'available': True, 'H': calibration['H'], 'samples': calibration.get('kept'),
                            'error': calibration.get('err'), 'source': calibration.get('borrowed', scene)}
                           if calibration and calibration.get('H') else {'available': False})
    base = {'requested': requested, 'resolved_as': canonical, 'scene': scene, 'position': position,
            'calibration': calibration_receipt}
    if not goal_key:
        return dict(base, status='unresolved_destination', goal=None, next_edge=None)
    goal = graph.nodes[goal_key]
    goal_pos = OG.pos_of(graph, goal_key)
    goal_receipt = {'node': goal_key, 'scene': scene, 'position': list(goal_pos) if goal_pos else None,
                    'source': goal.extra.get('position_source') or goal.extra.get('source'),
                    'enterable': bool(goal.extra.get('enterable'))}
    if not position:
        return dict(base, status='unresolved_position', goal=goal_receipt, next_edge=None)
    nav_nodes = {edge[key] for edge in graph.edges(rel='nav') for key in ('a', 'b')}
    map_frame = (observation.get('screen') or {}).get('kind') == 'map'
    map_pin = observation.get('map_pin') if map_frame else None
    current = _map_pin_node(graph, scene, map_pin) if map_pin else None
    current_source = 'map_pin' if current else None
    durable = params.get('_nav_current')
    observed_proof = (observation.get('state_provenance') or {}).get('position') or {}
    durable_proof = params.get('_nav_current_proof') or {}
    durable_fresh = not _newer_position_proof(observed_proof, durable_proof)
    if current is None and not map_frame and durable_fresh and durable_proof and \
            durable in nav_nodes and scene in graph.chain(durable):
        current, current_source = durable, 'task_state'
    fresh_position = observation.get('position')
    if fresh_position is None and 'Tara' in graph.nodes:
        fresh_position = graph.nodes['Tara'].extra.get('pos')
    if current is None and not map_frame:
        current = _nearest_nav_node(graph, scene, fresh_position)
        current_source = 'observed_position' if current else None
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
    target_pos = OG.pos_of(graph, next_key)
    distance = round(math.dist(position['value'], target_pos), 2) if position and target_pos else None
    next_edge = {'from': current, 'to': next_key, 'relation': 'nav', 'target': list(target_pos) if target_pos else None,
             'source': edge.get('source'), 'compass': edge.get('compass'), 'distance': distance,
             'walkable': True, 'navigation_only': bool(target.extra.get('navigation_only')),
             'enterable': bool(target.extra.get('enterable'))}
    current_node = graph.nodes[current]
    return dict(base, status='resolved', goal=goal_receipt, next_edge=next_edge,
                graph={'current_node': current, 'destination': goal_key, 'path': steps,
                       'current_source': current_source,
                       'current_navigation_only': bool(current_node.extra.get('navigation_only')),
                       'current_enterable': bool(current_node.extra.get('enterable'))})


def assess(action, navigation):
    """Guard with fixed-camera screen/map compass; retain homography output as diagnostic only."""
    import nav as learned

    point = action.get('point') or ()
    if not point and action.get('cell'):
        match = re.fullmatch(r'([A-Xa-x])(1[0-6]|[1-9])', action['cell'])
        if match:
            point = ((ord(match[1].upper()) - 65 + .5) * 80, (int(match[2]) - .5) * 67.5)
    if len(point) != 2:
        return {'allowed': False, 'alignment': 'invalid', 'reason': 'waypoint needs a two-coordinate point'}
    sx, sy = point
    screen_compass = _compass(sx - 960, sy - 540)
    graph_compass = ((navigation or {}).get('next_edge') or {}).get('compass')
    calibration = (navigation or {}).get('calibration') or {}
    world = None
    alignment = 'unknown'
    allowed = True
    if calibration.get('available') and calibration.get('H'):
        dx, dz = learned.screen_to_ground(calibration['H'], sx, sy)
        waypoint_compass = _compass(dx, -dz)
        world = {'delta': [round(dx, 2), round(dz, 2)], 'compass': waypoint_compass}
    if graph_compass in COMPASS:
        sectors = abs(COMPASS.index(screen_compass) - COMPASS.index(graph_compass))
        sectors = min(sectors, len(COMPASS) - sectors)
        allowed = sectors <= 1
        alignment = 'aligned' if allowed else 'mismatch'
    return {'allowed': allowed, 'alignment': alignment, 'screen_compass': screen_compass,
            'world': world, 'graph_compass': graph_compass}


def advance(task, experience):
    """Fold one proved waypoint endpoint into the durable task estimate without claiming an exact reading."""
    if experience.verdict.value != 'hit':
        return
    before = dict(experience.before.state)
    after = dict(experience.evidence.state)
    navigation = before.get('navigation') or {}
    graph = navigation.get('graph') or {}
    current_node = graph.get('current_node')
    if current_node:
        task.params['_nav_current'] = current_node
        before_proof = (before.get('state_provenance') or {}).get('position') or {}
        after_proof = (after.get('state_provenance') or {}).get('position') or {}
        proof = after_proof or before_proof
        if proof:
            task.params['_nav_current_proof'] = dict(proof)
        else:
            task.params.pop('_nav_current_proof', None)
    if (not experience.action or experience.action.kind != 'click' or experience.action.what != 'step' or
            experience.evidence.moved is not True or not experience.action.pt):
        return
    scene = before.get('scene') or before.get('region')
    after_scene = after.get('scene') or after.get('region')
    if after_scene and scene and after_scene != scene:
        task.params.pop('_nav_estimate', None)
        return
    observed_position = after.get('position')
    before_proof = (before.get('state_provenance') or {}).get('position') or {}
    after_proof = (after.get('state_provenance') or {}).get('position') or {}
    from . import world
    fresh_saved_position = (after_proof.get('source') == 'save' and
                            (after_proof.get('path') != before_proof.get('path') or
                             (type(after_proof.get('save_count')) is int and
                              type(before_proof.get('save_count')) is int and
                              after_proof['save_count'] > before_proof['save_count']) or
                             (world.when(after_proof.get('game_time')) is not None and
                              world.when(before_proof.get('game_time')) is not None and
                              world.when(after_proof['game_time']) > world.when(before_proof['game_time']))))
    direct_position = isinstance(observed_position, (list, tuple)) and len(observed_position) == 2
    if direct_position and (after_proof.get('source') not in ('save', None) or fresh_saved_position):
        task.params['_nav_estimate'] = {'scene': scene, 'position': [round(float(observed_position[0]), 3),
                                                                     round(float(observed_position[1]), 3)],
                                        'source': 'observed_position', 'experience': experience.id}
        return
    position = navigation.get('position') or {}
    calibration = navigation.get('calibration') or {}
    if not position.get('value') or not calibration.get('available') or not calibration.get('H'):
        return
    import nav as learned
    dx, dz = learned.screen_to_ground(calibration['H'], *experience.action.pt)
    x, z = position['value']
    task.params['_nav_estimate'] = {'scene': scene, 'position': [round(x + dx, 3), round(z + dz, 3)],
                                    'source': 'calibrated_waypoint', 'experience': experience.id,
                                    'error': calibration.get('error')}
