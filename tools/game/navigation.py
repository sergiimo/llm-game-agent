"""Bounded graph/compass receipts for model-owned waypoint decisions."""
import math


COMPASS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')


def _field(value, name, default=None):
    return value.get(name, default) if hasattr(value, 'get') else getattr(value, name, default)


def _compass(dx, screen_dy):
    angle = math.degrees(math.atan2(dx, -screen_dy)) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


def _position(task, observation, scene):
    params = _field(task, 'params', {}) or {}
    estimate = params.get('_nav_estimate') or {}
    if estimate.get('scene') == scene and estimate.get('position'):
        return {'value': list(estimate['position']), 'source': estimate.get('source', 'estimate'),
                'experience': estimate.get('experience')}
    value = observation.get('position')
    if not value:
        return None
    source = ((observation.get('state_provenance') or {}).get('position') or {}).get('source', 'observation')
    return {'value': list(value), 'source': source}


def receipt(task, observation):
    """Resolve a navigate task into one bounded current-position -> next graph-node receipt."""
    import nav as learned

    params = _field(task, 'params', {}) or {}
    requested = params.get('destination') or params.get('where') or params.get('region')
    scene = observation.get('region') or observation.get('scene')
    position = _position(task, observation, scene)
    data = learned.map_load(learned.MAP)
    aliases = {str(key).casefold(): value for key, value in (data.get('aliases') or {}).items()}
    canonical = aliases.get(str(requested).casefold(), requested) if requested else None
    facts = learned.load(learned.FACTS)
    nodes = learned.nodes(facts, data.get('places') or {})
    matches = [(key, node) for key, node in nodes.items()
               if canonical is not None and (key == canonical or node.get('name') == canonical)]
    if scene:
        matches.sort(key=lambda row: row[1].get('scene') != scene)
    calibration = learned.calib_load(scene, learned.ROOT) if scene else None
    calibration_receipt = ({'available': True, 'H': calibration['H'], 'samples': calibration.get('kept'),
                            'error': calibration.get('err'), 'source': calibration.get('borrowed', scene)}
                           if calibration and calibration.get('H') else {'available': False})
    base = {'requested': requested, 'resolved_as': canonical, 'scene': scene, 'position': position,
            'calibration': calibration_receipt}
    if not matches:
        return dict(base, status='unresolved_destination', goal=None, route=None)
    goal_key, goal = matches[0]
    goal_receipt = {'node': goal_key, 'scene': goal.get('scene'), 'position': [goal.get('x'), goal.get('z')],
                    'source': goal.get('src')}
    if not position:
        return dict(base, status='unresolved_position', goal=goal_receipt, route=None)
    start = (scene, *position['value'])
    steps = learned.plan(nodes, learned.edges_graph(facts, nodes), start, goal_key, learned.walls(facts))
    if not steps:
        return dict(base, status='unresolved_route', goal=goal_receipt, route=None)
    edge, next_key = steps[0]
    target = nodes[next_key]
    dx, dz = target['x'] - start[1], target['z'] - start[2]
    route = {'next_node': next_key, 'edge': edge, 'target': [target['x'], target['z']],
             'source': target.get('src'), 'compass': _compass(dx, -dz),
             'distance': round(math.hypot(dx, dz), 2)}
    return dict(base, status='resolved', goal=goal_receipt, route=route)


def assess(action, navigation):
    """Describe a waypoint's calibrated compass and whether it agrees with the graph receipt."""
    import nav as learned

    point = action.get('point') or ()
    if len(point) != 2:
        return {'allowed': False, 'alignment': 'invalid', 'reason': 'waypoint needs a two-coordinate point'}
    sx, sy = point
    screen_compass = _compass(sx - 960, sy - 540)
    graph_compass = ((navigation or {}).get('route') or {}).get('compass')
    calibration = (navigation or {}).get('calibration') or {}
    world = None
    alignment = 'unknown'
    allowed = True
    if calibration.get('available') and calibration.get('H'):
        dx, dz = learned.screen_to_ground(calibration['H'], sx, sy)
        waypoint_compass = _compass(dx, -dz)
        world = {'delta': [round(dx, 2), round(dz, 2)], 'compass': waypoint_compass}
        if graph_compass in COMPASS:
            sectors = abs(COMPASS.index(waypoint_compass) - COMPASS.index(graph_compass))
            sectors = min(sectors, len(COMPASS) - sectors)
            allowed = sectors <= 1
            alignment = 'aligned' if allowed else 'mismatch'
    return {'allowed': allowed, 'alignment': alignment, 'screen_compass': screen_compass,
            'world': world, 'graph_compass': graph_compass}


def advance(task, experience):
    """Fold one proved waypoint endpoint into the durable task estimate without claiming an exact reading."""
    if (not experience.action or experience.action.kind != 'click' or experience.action.what != 'step' or
            experience.verdict.value != 'hit' or experience.evidence.moved is not True or not experience.action.pt):
        return
    before = dict(experience.before.state)
    after = dict(experience.evidence.state)
    scene = before.get('scene') or before.get('region')
    after_scene = after.get('scene') or after.get('region')
    if after_scene and scene and after_scene != scene:
        task.params.pop('_nav_estimate', None)
        return
    navigation = before.get('navigation') or {}
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
