"""NAV: get Tara in reach of ANY node of a kind whose bubble fits (framework: observe -> act -> learn -> nav).

Search order when no fitting bubble shows (user D185), one round per call of `seek`:
1. where she is = the CLOSEST NODE (observe.closest_node, fresh each round) -> if it is another node, the graph's
   direction from it to the target node -> a step (a direction that reached the target is learned);
2. soil targets (water): walk to the nearest light-brown (dry) soil of the heat map;
3. the target kind's appearance vectors on screen -> click the nearest;
4. inside the target's region: explore FREE ground (away from bubbles and objects), each direction once per call;
   outside: the map's direction (pin -> region picture -> road route) -> a step.
A seek click is a WALK only when the burst frames show she moved, or its event is on the target node (arrived). An
event on another node (a hive) = blocked. STUCK_CLICKS still clicks in a row = stuck -> stop, vision gets the trace.
Bubbles without the target's sub-icon are never clicked."""
import math
from dataclasses import dataclass

from . import act as A, core, learn as L, observe as O

SEEK_TURNS = 6          # seek rounds before vision is asked
STEP_R = (320, 220)     # px from the centre for a direction step; the second is tried when the first did not move her
STEP_TURN = (0, 35, -35)  # degrees off the direction when a step did not move her
HEADING_MAX = 8         # steps along the last graph direction while the frame shows no node (between two gardens)
WALK_MAX = 16           # seek clicks that walked her and don't use up a search round (a long way, review 2026-11-03)
STUCK_CLICKS = 3        # seek clicks in a row that did not move her = stuck (L75 rule, L132)
EXPLORE = [(1, 0), (0.7, 0.7), (0, 1), (-0.7, 0.7), (-1, 0), (-0.7, -0.7), (0, -1), (0.7, -0.7)]
EXPLORE_R = 300         # px: a free-ground click this far out shows a new part of the region
FREE_GAP = 110          # px: a free-ground point keeps this far from every bubble and object detection
MISS_MAX = 2            # arrival misses in a row: the detections are phantoms here (grass read as beds), map leads
BLIND_MAX = 6           # walk clicks in a row without an event or a bubble of the target kind = lost: stop, ask
MAP_FLAT = 3            # map readings in a row with the pin no closer to the goal = lost (the map's own progress)
MAP_GAIN = 5            # px on the map: closer by at least this = progress
LAST_MAP = {}           # the last map reading: {'pin', 'goal', 'img'} (map_direction)
MAP_STEP_R = 460        # px: a map-led step goes near the frame edge (user D188: "steps are very small")
MAP_STEPS = 3           # long steps per map reading
from objects.graph import COMPASS  # noqa: E402 (N..NW -> screen direction; the graph's ways keep it too)


@dataclass
class Target:
    """What to reach: a node kind whose bubble `fits`. Tasks are Targets plus what to do there (game/laws.TASKS)."""
    name: str
    fits: object                     # Affordance -> bool: this bubble IS a target in reach
    target: str                      # what vision looks for (words)
    save_key: str = None             # save_bed_counts key: how many are left (a hint, law 6)
    kind: str = 'GardenBed'          # appearance vectors (objects/db/<kind>)
    region: str = 'Garden'           # map picture of the region (objects/map_db)
    node: str = 'GardenBed@Garden'   # the graph node: where she must be
    marker: str = None               # a frame marker of the targets nav can walk to ('dry_soil': light-brown soil)


def new_res(name):
    return {'task': name, 'done': [], 'other': [], 'notes': [], 'clicks': 0, 'vision': 0, 'refills': 0,
            'stop': None, 'left_in_save': None, 'surprises': L.SURPRISES}


def log(type_, **kw):
    try:
        core.WF.run_log(type_, **kw)
    except Exception:   # noqa: BLE001
        pass


def trace(res, msg):
    if res is not None:
        res.setdefault('trace', []).append(msg)
        log('seek', what='trace', msg=msg)


def inside(t, here):
    """She is at a node inside the target's region (Garden: its beds, hives, well): the map has nothing finer."""
    if not here:
        return False
    g = L.MEMORY['graph']
    if g is not None and here in g.nodes:
        return g.nodes[here].region == t.region or here == t.region
    return here in (t.node, 'Well', 'BeeHive')


def walked(c, target=None, res=None):
    """The click got her somewhere: the frames moved, or the event is on the target node (arrived). Counts res['still']."""
    arrived = bool(target and c.node == target)
    if res is not None and A.on_card(c) and res.get('on_card') and res['on_card'](c):
        res.setdefault('surprises', []).append(f'nav click @{c.pt[0]},{c.pt[1]} opened {c.texts[:1]}: finished by '
                                               f'the row')
        return True   # the card the row expects was finished by the row (the walk reached the object)
    if res is not None and (A.on_card(c) or (c.events and not arrived)):
        # a walk click that interacted (a card, an event): an interaction is a step's job, never a walk's (user D188)
        res.setdefault('surprises', []).append(
            f'nav click @{c.pt[0]},{c.pt[1]} interacted: events {c.events or "-"}, screen {c.mode}'
            f'{" (" + " / ".join(c.texts[:2]) + ")" if c.texts else ""}')
        log('seek', what='surprise', msg=res['surprises'][-1])
    if A.on_card(c) or (c.node and not arrived):
        A.gameplay()
    ok = arrived or (not c.node and c.moved is True)
    if ok and c.moved and res is not None and res.get('area'):
        res['area'] = None   # she walked: the area known from the last event may be left behind
    if res is not None:
        if getattr(c, 'exp', None):
            res.setdefault('exps', []).append(c.exp)
            del res['exps'][:-12]
        res['still'] = 0 if (ok or c.moved is True) else res.get('still', 0) + 1
        own = O.NODE_OF.get(target.split('@')[0]) if target else None
        progress = bool(c.events) or (own is not None and any(O.node_of_bubble(a) == own for a in c.after))
        res['blind'] = 0 if progress else res.get('blind', 0) + (1 if c.moved else 0)
    return ok


def lost(res):
    """BLIND_MAX walks in a row without an event or a bubble of the target kind (live D188 12:31: 15+ clicks in the
    wrong part of the farm, nobody noticed): stop clicking, traced once for the question."""
    if res is None or res.get('blind', 0) < BLIND_MAX:
        return False
    if not res.get('lost_traced'):
        trace(res, f'LOST: {res["blind"]} walks without an event or a bubble of the target kind - which way?')
        res['lost_traced'] = True
        _gap(res, f'nav: lost - {res["blind"]} walks without an event or a bubble of the target kind')
    return True


def stuck(res):
    """STUCK_CLICKS seek clicks in a row did not move her, or she is lost (BLIND_MAX walks without progress): stop
    clicking (traced once for vision)."""
    if lost(res):
        return True
    if res is None or res.get('still', 0) < STUCK_CLICKS:
        return False
    if not res.get('stuck_traced'):
        trace(res, f'STUCK: {res["still"]} clicks in a row did not move her')
        res['stuck_traced'] = True
        _gap(res, f'nav: stuck - {res["still"]} clicks in a row did not move her')
    return True


def outcome(c, ok, target=None):
    if target and c.node == target:
        return f'arrived at {target}'
    return 'walked' if ok else f'blocked by {c.node}' if c.node else 'no move'


def step(direction, res=None, label='step', target=None, learn=None, radii=STEP_R):
    """A few steps in `direction` (Tara is at the centre): click `radii[0]` px away; turn a little when she did not
    walk. `learn=(a, b)`: a direction that reached b is learned as the graph's a->b. The Click that walked her, or None."""
    for r in radii:
        for deg in STEP_TURN:
            a = math.radians(deg)
            x = direction[0] * math.cos(a) - direction[1] * math.sin(a)
            y = direction[0] * math.sin(a) + direction[1] * math.cos(a)
            pt = (int(O.CENTRE[0] + x * r), int(O.CENTRE[1] + y * r))
            if O.hud(pt):
                continue
            ctx = {'toward': [learn[0], learn[1], [x, y]], 'target': target} if learn else None
            c = A.click(pt, 'step', context=ctx)   # the boundary learns a direction that reached the target
            if res is not None:
                res['clicks'] = res.get('clicks', 0) + 1
            ok = walked(c, target, res)
            trace(res, f'{label} @{pt[0]},{pt[1]}: ' + outcome(c, ok, target))
            if ok:
                return c
            if stuck(res):
                return None
    return None


def beside(det, affs):
    """A click point on free ground just below a detected object (click-to-move stops her in front of it), at least
    FREE_GAP from every bubble; None when there is none on the frame."""
    box = getattr(det, 'box', None)
    x = det.point[0]
    y = (box[3] if box else det.point[1]) + 40
    for _ in range(4):
        if O.on_frame((x, y)) and all(O.d((x, y), a.pt) >= FREE_GAP for a in affs):
            return (int(x), int(y))
        y += FREE_GAP
    return None


def free(pt, avoid):
    return O.on_frame(pt) and all(O.d(pt, a) >= FREE_GAP for a in avoid)


def explore(t, res):
    """Inside the target's region the map can't help (like inside a house): walk to free ground in a direction not
    tried yet in this call. The Click that walked her, or None (res['explored_all'] when every direction is used)."""
    done = res.setdefault('explored', [])
    avoid = [a.pt for a in O.scan()] + [x.point for x in O.see_all()]
    for dd in EXPLORE:
        if dd in done:
            continue
        done.append(dd)
        pt = (int(O.CENTRE[0] + dd[0] * EXPLORE_R), int(O.CENTRE[1] + dd[1] * EXPLORE_R))
        if not free(pt, avoid):
            trace(res, f'explore {dd}: @{pt[0]},{pt[1]} not free ground')
            continue
        c = A.click(pt, 'explore')
        res['clicks'] += 1
        ok = walked(c, t.node, res)
        trace(res, f'explore @{pt[0]},{pt[1]}: ' + outcome(c, ok, t.node))
        if ok:
            return c
        if stuck(res):
            return None
    res['explored_all'] = True
    return None


def dry_spots(tried=()):
    """The soil heat map's dry spots (observe.soil), nearest first; the soil view goes to memory."""
    spots, _ = O.soil(tried)
    return spots


def map_direction(region):
    """Open the map, find Tara's pin and the region's map picture, take the first stretch of the road route between them.
    A unit (dx, dy) in screen terms (the camera looks north like the map), or None when the map can't tell."""
    from objects import map_vectors as MV
    img = core.WF.map_snapshot()
    if img is None:
        return None
    pin = core.WF.map_pin(img)
    g = L.MEMORY['graph']
    if g is None:
        from objects import graph as OG
        g = OG.Graph()
        g.load(L.graph_path())
    m = MV.locate(g, region, img) if pin else None
    if m is None:
        return None
    route = core.WF.map_route(img, pin, m.point)
    path = route or [m.point]
    ahead = next((q for q in path if math.dist(q, pin) >= 60), path[-1])
    dx, dy = ahead[0] - pin[0], ahead[1] - pin[1]
    n = math.hypot(dx, dy)
    log('seek', what='map', pin=list(pin), goal=list(m.point), score=round(m.score, 2), ahead=list(ahead))
    LAST_MAP.clear()
    LAST_MAP.update(pin=tuple(pin), goal=tuple(m.point), img=img, route_len=_route_len(pin, route, m.point))
    return None if n < 1 else (dx / n, dy / n)


def seek(t, res):
    """One round of the ladder (spec 2026-11-04 nav ladder, user D188): the distance tier first (graph, then one
    map reading); map-far -> the map rung only; near -> the target visible by vectors -> walk beside it; else the
    graph's direction -> a step that way (a blocked step turns: obstacles); else explore inside the region; else the
    map. Tara's place in the graph is updated after the step. The Click that got her somewhere, or None."""
    tried = res.setdefault('tried', [])   # screen points that led nowhere; cleared when she walks
    if stuck(res):
        res['still'] = 0
        return None
    cn = O.closest_node()
    if cn in res.get('lookalike', ()) and not res.get('area'):
        cn = None   # beds look alike in every garden: the frame can't say which one she is at
    here = res.get('area') or cn or res.get('here')
    res['inside'] = inside(t, here) if here else res.get('inside')
    tier = tier_of(t, res, here)
    c = _rung(t, res, tier, cn, here, tried)
    update_tara(res, tier, cn or here, c, t.node)
    return c


def _rung(t, res, tier, cn, here, tried):
    if tier == 'map-far':
        return map_walk(t, res, read=False)
    if t.marker == 'dry_soil' and res.get('light') in ('day', None):   # a visible marker of the targets
        for x, y, n in dry_spots(tried)[:2]:
            c = A.click((x, y), 'soil')
            res['clicks'] += 1
            tried.append((x, y))
            ok = walked(c, t.node, res)
            trace(res, f'dry soil @{x},{y} ({n} cells): ' + outcome(c, ok, t.node))
            if ok:
                return c
            if stuck(res):
                return None
    if t.marker and res.get('inside'):   # inside the region the targets are marked (drop, dry soil), not just beds
        return explore(t, res)
    c = _visible(t, res, tried)   # rung 1: the target visible by vectors (screen-far)
    if c is not None or stuck(res):
        return c
    at = cn or here
    if at and at != t.node:   # rung 2: the graph says close and knows the direction
        dd = L.toward(at, t.node)
        if dd:
            log('seek', what='graph', here=at, to=t.node, dir=list(dd))
            c = step(dd, res, f'graph {at}->{t.node}', t.node, learn=(at, t.node))
            if c is not None:
                res['here'], res['heading'], res['heading_n'] = c.node, dd, 0
                return c
    if not at and res.get('heading') and res.get('heading_n', 0) < HEADING_MAX:   # between nodes: keep going
        res['heading_n'] = res.get('heading_n', 0) + 1
        c = step(res['heading'], res, f'heading {res["heading_n"]}/{HEADING_MAX}', t.node)
        if c is not None:
            res['here'] = c.node
            return c
    if (res.get('inside') or inside(t, here)) and not res.get('no_detect'):
        res['inside'] = True
        return explore(t, res)
    return map_walk(t, res, read=not res.get('map_fresh'))   # rung 3: the map


def _visible(t, res, tried):
    """The target kind seen by its vectors: free ground just below it (never its bubble, user D188)."""
    for det in ([] if res.get('no_detect') else O.see(t.kind, tried)[:2]):
        pt = beside(det, O.scan())
        if pt is None:
            tried.append(det.point)
            trace(res, f'{t.kind} seen @{det.point[0]},{det.point[1]}: no free ground beside it')
            continue
        box = getattr(det, 'box', None)
        c = A.click(pt, 'step', context={'det_box': list(box) if box else None, 'det_kind': t.kind, 'target': t.node})
        res['clicks'] += 1
        tried.append(det.point)
        res['tier_now'] = 'screen-far'
        res['misses'] = 0 if _predicted_arrival(t, c) else res.get('misses', 0) + 1
        if res['misses'] >= MISS_MAX and not res.get('no_detect'):
            res['no_detect'] = True
            trace(res, f'{MISS_MAX} arrival misses: the {t.kind} detections here are not {t.kind}s; the map leads')
            _gap(res, f'nav: {MISS_MAX} arrival misses on {t.kind} detections (phantoms)')
        ok = walked(c, t.node, res)
        trace(res, f'{t.kind} seen @{det.point[0]},{det.point[1]}: ' + outcome(c, ok, t.node))
        if c.node == t.node and not any(t.fits(a) for a in c.after):   # a bed, but not one this target needs
            res['still'] = res.get('still', 0) + 1
            trace(res, f'  that {t.kind} does not need it (no fitting bubble)')
            A.gameplay()
            if stuck(res):
                return None
            continue
        if c.node and c.node != t.node and str(c.learned or '').startswith('look:'):   # the boundary relabelled it
            trace(res, f'learned: the look @{det.point[0]},{det.point[1]} is a {c.learned[5:]}')
        if ok or c.node:
            return c
        if stuck(res):
            return None
    return None


NEAR_MAP_PX = 60    # map px from the target's map point: nearer = near (the mine -> garden is ~100)
PIN_JUMP = 150      # map px between two readings in one call: more = a misread pin (D188: 598,461 -> 1320,419)


def tier_of(t, res, here):
    """The distance tier, cheapest evidence first: a bubble of the target kind in view = steps-far; inside the
    target's region (graph) = near; else one map reading: far from the target's map point = map-far, else near;
    no reading = unknown."""
    own = O.NODE_OF.get(t.kind)
    if own and any(O.node_of_bubble(a) == own for a in O.scan()):
        return 'steps-far'
    if res.get('inside') or (here and inside(t, here)):
        return 'near'
    dd = read_map(t, res)
    if dd is None or not LAST_MAP.get('pin') or not LAST_MAP.get('goal'):
        return 'unknown'
    d = math.dist(LAST_MAP['pin'], LAST_MAP['goal'])
    return 'map-far' if d > NEAR_MAP_PX else 'near'


def read_map(t, res):
    """One map reading for this round (direction, pin, goal), checked: a pin that jumped more than PIN_JUMP from the
    last good one is a misread - rejected, a gap, and vision is asked the way from the last good pin."""
    LAST_MAP.clear()
    res['map_fresh'] = False
    dd = map_direction(t.region)
    res['map_dd'] = dd
    pin, ok = LAST_MAP.get('pin'), res.get('pin_ok')
    if dd is not None and pin and ok and math.dist(pin, ok) > PIN_JUMP:
        trace(res, f'map: the pin read at {list(pin)} jumped {math.dist(pin, ok):.0f} px from {list(ok)}: rejected')
        _gap(res, f'nav: map pin jumped {math.dist(pin, ok):.0f} px in one call ({list(ok)} -> {list(pin)})')
        LAST_MAP['pin'] = tuple(ok)
        ask_way(t, res, None, why=f'the map pin was misread (it jumped to {list(pin)})')
    if dd is not None and pin:
        res['pin_ok'] = tuple(pin)
        res['goal_ok'] = tuple(LAST_MAP['goal']) if LAST_MAP.get('goal') else None
        res['route_ok'] = LAST_MAP.get('route_len')
    res['map_fresh'] = dd is not None
    return dd


DIST_STALE = 600.0   # s: a distance edge older than this is not a baseline (another trip)


def update_tara(res, tier, near, c, target=None):
    """After each step: Tara's place in the graph - her node (last good pin, the node she is at, exact pos, time)
    and the Tara -> target `distance` edge (user D188: tier map-far / screen-far / steps-far, map px, route px)."""
    g = L.MEMORY['graph']
    if g is None or 'Tara' not in g.nodes:
        return
    import time as _t
    from objects import graph as OG
    tier = res.pop('tier_now', None) or tier
    ex = g.nodes['Tara'].extra
    ex.update(near=near, t=round(_t.time(), 1))
    ex.pop('tier', None)   # the tier lives on the distance edge
    if res.get('pin_ok'):
        ex['pin'] = list(res['pin_ok'])
    if c is not None and getattr(c, 'at', None):
        ex['pos'] = [round(c.at[0], 2), round(c.at[1], 2)]
    if target:
        old = distance(g, target) or {}
        pin, goal = res.get('pin_ok'), res.get('goal_ok')
        attrs = {'tier': tier, 't': ex['t'], 'source': 'map' if pin and goal else 'graph'}
        if pin and goal:
            attrs['map_px'] = round(math.dist(pin, goal), 1)
        if res.get('route_ok') is not None:
            attrs['route_px'] = round(res['route_ok'], 1)
        for k in ('map_px', 'route_px'):   # a step without a reading keeps the last one
            if k not in attrs and k in old:
                attrs[k] = old[k]
        OG.set_edge(g, 'Tara', target, 'distance', **attrs)
    log('seek', what='tara', tier=tier, near=near, pin=ex.get('pin'), target=target)


def distance(g, target):
    """The Tara -> target distance edge (fresh: younger than DIST_STALE), or None."""
    import time as _t
    for e in (g.edges('Tara', 'distance') if g is not None else []):
        if e['b'] == target and _t.time() - (e.get('t') or 0) <= DIST_STALE:
            return e
    return None


def _gap(res, invariant):
    """A navigation failure for the code factory: the experiences of this call's clicks."""
    try:
        from . import integrate as I
        I.gap(res.get('exps') or [], invariant, 'nav')
    except Exception:   # noqa: BLE001
        pass


def _route_len(pin, route, goal):
    """Map px from the pin to the goal along the road route (its last point to the goal straight); None without one."""
    if not route:
        return None
    pts = [tuple(pin)] + [tuple(p) for p in route] + [tuple(goal)]
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _way_learned(g, a, b):
    for e in (g.edges(a, 'toward') if g is not None else []):
        if e['b'] == b and e.get('dir') and e.get('source') == 'learned':
            return tuple(e['dir'])
    return None


def map_walk(t, res, read=True):
    """The map rung: this round's reading (`read` = take one now), then MAP_STEPS long steps along the way. At a
    dead-end landmark that isn't the goal (the mine, user D188) the route is not followed: a learned way from there,
    else vision reads the marked-up map for the road direction (raises NeedVision). The Click that walked her, or None."""
    from . import world
    dd = read_map(t, res) if read else res.get('map_dd')
    res['map_fresh'] = False   # one reading, one walk
    if dd is None:
        trace(res, 'map: no direction')
        return None
    if not _map_progress(res, t.node):
        return None
    g = L.MEMORY['graph']
    mark = world.landmark_at(g, LAST_MAP.get('pin')) if g is not None else None
    if mark and mark not in (t.region, t.node) and g.nodes[mark].extra.get('dead_end'):
        way = _way_learned(g, mark, t.node)
        if way is None:
            ask_way(t, res, mark)
        trace(res, f'map: at the {mark} (a dead end): the learned way {way}')
        dd = way
    c = None
    for i in range(MAP_STEPS):
        ci = path_step(dd, res, f'map {i + 1}/{MAP_STEPS}', t.node)
        if ci is None:
            break
        c = ci
        if ci.node or any(t.fits(a) for a in ci.after):
            break
    return c


def marked_map(mark=None):
    """The last map with the pin (magenta), the goal (yellow) and dead ends (red X) drawn: the way question's image."""
    img = LAST_MAP.get('img')
    if img is None:
        return None
    from PIL import ImageDraw
    from . import world
    pic = img.convert('RGB').copy()
    dr = ImageDraw.Draw(pic)
    for pt, col in ((LAST_MAP.get('pin'), (255, 0, 255)), (LAST_MAP.get('goal'), (255, 220, 0))):
        if pt:
            dr.ellipse((pt[0] - 18, pt[1] - 18, pt[0] + 18, pt[1] + 18), outline=col, width=5)
    g = L.MEMORY['graph']
    for n in (g.nodes.values() if g is not None else []):
        p = (n.extra.get('map') or {}).get('point') if isinstance(n.extra.get('map'), dict) else None
        if p and n.extra.get('dead_end'):
            dr.line((p[0] - 14, p[1] - 14, p[0] + 14, p[1] + 14), fill=(255, 0, 0), width=5)
            dr.line((p[0] - 14, p[1] + 14, p[0] + 14, p[1] - 14), fill=(255, 0, 0), width=5)
    return pic


WAY_MARGIN = 140    # map px around the pin and the goal in the zoomed map


def way_box():
    """The map crop (x0, y0, x1, y1) around the pin and the goal: 16:9, WAY_MARGIN around both, inside the frame."""
    pin, goal = LAST_MAP.get('pin'), LAST_MAP.get('goal')
    pts = [p for p in (pin, goal) if p] or [(960, 540)]
    x0, x1 = min(p[0] for p in pts) - WAY_MARGIN, max(p[0] for p in pts) + WAY_MARGIN
    y0, y1 = min(p[1] for p in pts) - WAY_MARGIN, max(p[1] for p in pts) + WAY_MARGIN
    w, h = x1 - x0, y1 - y0
    if w / h < 16 / 9:   # widen to 16:9 around the centre
        cx, w = (x0 + x1) / 2, h * 16 / 9
        x0, x1 = cx - w / 2, cx + w / 2
    else:
        cy, h = (y0 + y1) / 2, w * 9 / 16
        y0, y1 = cy - h / 2, cy + h / 2
    dx = max(0, -x0) - max(0, x1 - 1920)
    dy = max(0, -y0) - max(0, y1 - 1080)
    return (round(x0 + dx), round(y0 + dy), round(x1 + dx), round(y1 + dy))


def way_image(mark=None):
    """The way question's picture at FULL scale (user D188: "Scale was a major cause - let's always screenshot full
    scale"): the marked-up map zoomed to the box around her pin and the goal (top, 1920x1080), the game view now
    (bottom, 1920x1080, Tara at its centre)."""
    from PIL import Image, ImageDraw
    m = marked_map(mark)
    if m is None:
        return None
    try:
        frame = core.WF.grab().convert('RGB')
    except Exception:   # noqa: BLE001
        frame = Image.new('RGB', (1920, 1080), (0, 0, 0))
    pic = Image.new('RGB', (1920, 2160), (0, 0, 0))
    pic.paste(m.crop(way_box()).resize((1920, 1080)), (0, 0))
    pic.paste(frame.resize((1920, 1080)), (0, 1080))
    dr = ImageDraw.Draw(pic)
    dr.ellipse((960 - 28, 1620 - 28, 960 + 28, 1620 + 28), outline=(255, 0, 255), width=6)   # Tara in the view
    dr.line((0, 1080, 1920, 1080), fill=(255, 255, 255), width=6)
    return pic


def ask_way(t, res, mark, why=None):
    """Vision reads the map's roads for the first direction: from a dead end, after a misread map pin (`why`), or
    between two distant places."""
    from . import ask
    pin, goal = LAST_MAP.get('pin'), LAST_MAP.get('goal')
    where_ = (f'She is at the {mark}, a dead end: the straight line to the goal is blocked (rocks, cliffs, water).'
              if mark else f'The map reading is unsure: {why}; the magenta circle is her last good map pin.')
    q = (f'TOP: the world map, zoomed around her - Tara = the magenta circle at the pin, the goal = the yellow circle '
         f'(the {t.region}), red X = a dead end. BOTTOM: the game view now, Tara = the magenta circle at its centre. '
         f'{where_} Trace on the TOP the road from her pin to the goal (never the straight line), then on the BOTTOM '
         f'the path she stands on that starts that road. Which way '
         f'must she walk first along that path? Answer one of N, NE, E, SE, S, SW, W, NW (north = up, as on the '
         f'screen; the camera and the map both look north).')
    ask.ask('name', q, {'goal': res.get('goal'), 'params': res.get('params') or {}, 'map_dir': True, 'from': mark,
                        'to': t.node, 'pin': list(pin) if pin else None, 'map_goal': list(goal) if goal else None},
            res, img=way_image(mark))


def walk_way(answer, pend, res):
    """Vision's compass answer: MAP_STEPS long steps that way; the next map reading that is closer learns the way
    (graph: from -> to). The last Click or None."""
    d = COMPASS.get(str(answer).strip().upper())
    if d is None:
        raise core.Failed(f'answer rejected: {answer!r} is not one of {", ".join(COMPASS)}')
    if pend.get('pin') and pend.get('map_goal'):
        res['map_best'] = math.dist(pend['pin'], pend['map_goal'])
    res['way'] = (pend['from'], pend['to'], d)
    res['map_first'] = True
    c = None
    for i in range(MAP_STEPS):
        ci = path_step(d, res, f'way {answer} {i + 1}/{MAP_STEPS}', pend['to'])
        if ci is None:
            if c is None:   # blocked every way from the start: vision names a cell ON the path (its look is learned)
                ask_path(answer, d, pend, res)
            break
        c = ci
    return c


PATH_KIND = 'Path'        # the objects db kind of walkable path patches (learned from vision answers, D188)
PATH_R = (200, 560)       # px from her: a path patch for the next step
PATH_COS = 0.5            # within 60 degrees of the wanted direction


def path_step(d, res, label, target):
    """A long step that follows the path: the seen Path patch (embeddings) nearest the wanted direction, else the
    plain direction step (turns when blocked). The Click that walked her, or None."""
    try:
        dets = O.see(PATH_KIND)
    except Exception:   # noqa: BLE001 (no Path examples yet)
        dets = []
    best = None
    for det in dets:
        vx, vy = det.point[0] - O.CENTRE[0], det.point[1] - O.CENTRE[1]
        r = math.hypot(vx, vy)
        if not PATH_R[0] <= r <= PATH_R[1] or O.hud(det.point):
            continue
        cos = (vx * d[0] + vy * d[1]) / r
        if cos >= PATH_COS and (best is None or cos + r / 2000 > best[0]):
            best = (cos + r / 2000, det)
    if best is not None:
        pt = (int(best[1].point[0]), int(best[1].point[1]))
        c = A.click(pt, 'step')
        if res is not None:
            res['clicks'] = res.get('clicks', 0) + 1
        ok = walked(c, target, res)
        trace(res, f'{label} path @{pt[0]},{pt[1]}: ' + outcome(c, ok, target))
        if ok:
            return c
    return step(d, res, label, target, radii=(MAP_STEP_R, STEP_R[0]))


def ask_path(answer, d, pend, res):
    """Every step toward the answered way was blocked: vision gives a cell ON THE PATH she should follow; the
    click that walks her there proves it, and its look becomes a Path example (gap filling)."""
    from . import ask
    q = (f'Tara (the magenta circle, frame centre) must go {answer} toward the {pend.get("to")}, but every step that '
         f'way was blocked (rocks, water, cliffs). Give the grid cell ON THE PATH (the dirt road she should follow '
         f'out of here), a few steps from her - never rocks, water, grass behind rocks, or a building.')
    ask.ask('click', q, {'goal': res.get('goal'), 'params': res.get('params') or {}, 'path_cell': True,
                         'from': pend.get('from'), 'to': pend.get('to'), 'dir': list(d),
                         'pin': pend.get('pin'), 'map_goal': pend.get('map_goal')}, res)


def _map_progress(res, target=None):
    """A map-led walk is measured on the map: the pin closer to the goal (MAP_GAIN px) = progress (the blind count
    resets); MAP_FLAT readings without a gain = lost. The baseline is this call's best, else the Tara -> target
    distance edge (a fresh one from the last call). No reading (a fake, no pin) = trusted."""
    if not LAST_MAP:
        res['blind'] = 0
        return True
    d = LAST_MAP.get('route_len') or math.dist(LAST_MAP['pin'], LAST_MAP['goal'])   # by road (live D188: a pocket
    # by the river was closer in a straight line and taught a wrong way)
    best = res.get('map_best')
    if best is None and target:
        e = distance(L.MEMORY['graph'], target)
        best = (e.get('route_px') if LAST_MAP.get('route_len') else e.get('map_px')) if e else None
        if best is not None:
            res['map_best'] = best
    if best is None or d < best - MAP_GAIN:
        if best is not None and res.get('way'):   # the answered/learned way brought her closer: the graph keeps it
            from . import integrate as I
            a, b, way = res.pop('way')
            I.relation(a, b, way, f'map pin {best:.0f} -> {d:.0f} px from the goal', route_px=round(best, 1))
        res['map_best'], res['map_flat'], res['blind'] = d, 0, 0
        return True
    res['map_flat'] = res.get('map_flat', 0) + 1
    if res['map_flat'] >= MAP_FLAT:
        trace(res, f'LOST: the map pin is no closer to the goal after {MAP_FLAT} readings ({d:.0f} px) - which way?')
        res['lost_traced'] = True
        return False
    return True


def _predicted_arrival(t, c):
    """A click on a seen object of the target kind predicts she arrives at one: its bubble shows (or its event)."""
    own = O.NODE_OF.get(t.kind)
    hit = (c.node == t.node or (bool(c.node) and L.kind_of(c.node) == t.kind)   # an event on any object of the kind
           or any(O.node_of_bubble(a) == own for a in c.after))
    got = c.node or [str(a) for a in c.after][:4]
    try:
        import evals
        evals.record('nav', 'arrive', t.kind, got, hit, {'pt': list(c.pt), 'target': t.node, 'exp': c.exp})
    except Exception:   # noqa: BLE001 (scoring never breaks play)
        pass
    log('predict', component='nav', what='arrive', expected=t.kind, got=got, hit=hit, pt=list(c.pt))
    return hit


def search(t, res, rounds=SEEK_TURNS, halt=None):
    """Seek rounds until a fitting bubble shows: the nearest fitting Affordance, or None (stuck / nothing found /
    `halt(bubbles)` says stop). A seek click that walked her does not use up a round (up to WALK_MAX)."""
    r, walks = 0, 0
    while r <= rounds:
        affs = O.scan()
        fit = [a for a in affs if t.fits(a)]
        if fit:
            return O.nearest(fit, O.CENTRE)
        if halt is not None and halt(affs):
            return None
        c = seek(t, res)
        if c is None:
            return None
        if c.moved and walks < WALK_MAX:
            walks += 1
        else:
            r += 1
        if c.node:
            res['here'], res['inside'] = c.node, inside(t, c.node)
        if c.moved:
            res.get('tried', []).clear()
        if c.events or c.mode != 'gameplay':
            A.gameplay()
    return None


def reach(fits=lambda a: True, kind='GardenBed', node=None, region='Garden', marker=None, target=None,
          rounds=SEEK_TURNS):
    """The low-level navigation (L133): get Tara in reach of ANY node of `kind` whose bubble `fits`. Returns the nearest
    fitting Affordance (not clicked: the caller acts). Raises Failed with NEED_VISION (the trace) when the search gives
    nothing. E.g. `reach(lambda a: a.kind == 'plant')` = an empty bed; `reach(lambda a: a.kind == 'fill_can',
    kind='Well', node='Well')` = the well."""
    t = Target('reach', fits, target or f'a {kind}', None, kind, region, node or f'{kind}@{region}', marker)
    res = new_res('reach')
    L.open_memory()
    try:
        O.check_language()
        A.gameplay()
        res['light'] = O.clock()[1]
        a = search(t, res, rounds)
        if a is not None:
            return a
        tr = '; '.join(res.get('trace', [])[-10:]) or 'nothing tried'
        raise core.Failed(f'reach {t.node}: no fitting bubble after the search ({tr}); '
                          + core.ask_vision(f'Tara (frame centre) must reach {t.target}. The search tried: {tr}. '
                                            f'What blocks it? Give the click point of {t.target}, or of free ground '
                                            f'toward it.'))
    finally:
        L.close_memory()
