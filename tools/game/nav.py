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
    if res is not None and c.mode != 'gameplay' and res.get('on_card') and res['on_card'](c):
        res.setdefault('surprises', []).append(f'nav click @{c.pt[0]},{c.pt[1]} opened {c.texts[:1]}: finished by '
                                               f'the row')
        return True   # the card the row expects was finished by the row (the walk reached the object)
    if res is not None and (c.mode != 'gameplay' or (c.events and not arrived)):
        # a walk click that interacted (a card, an event): an interaction is a step's job, never a walk's (user D188)
        res.setdefault('surprises', []).append(
            f'nav click @{c.pt[0]},{c.pt[1]} interacted: events {c.events or "-"}, screen {c.mode}'
            f'{" (" + " / ".join(c.texts[:2]) + ")" if c.texts else ""}')
        log('seek', what='surprise', msg=res['surprises'][-1])
    if c.mode != 'gameplay' or (c.node and not arrived):
        A.gameplay()
    ok = arrived or (not c.node and c.moved is True)
    if ok and c.moved and res is not None and res.get('area'):
        res['area'] = None   # she walked: the area known from the last event may be left behind
    if res is not None:
        res['still'] = 0 if (ok or c.moved is True) else res.get('still', 0) + 1
    return ok


def stuck(res):
    """STUCK_CLICKS seek clicks in a row did not move her: stop clicking (traced once for vision)."""
    if res is None or res.get('still', 0) < STUCK_CLICKS:
        return False
    if not res.get('stuck_traced'):
        trace(res, f'STUCK: {res["still"]} clicks in a row did not move her')
        res['stuck_traced'] = True
    return True


def outcome(c, ok, target=None):
    if target and c.node == target:
        return f'arrived at {target}'
    return 'walked' if ok else f'blocked by {c.node}' if c.node else 'no move'


def step(direction, res=None, label='step', target=None, learn=None):
    """A few steps in `direction` (Tara is at the centre): click STEP_R px away; turn a little when she did not walk.
    `learn=(a, b)`: a direction that reached b is learned as the graph's a->b. The Click that walked her, or None."""
    for r in STEP_R:
        for deg in STEP_TURN:
            a = math.radians(deg)
            x = direction[0] * math.cos(a) - direction[1] * math.sin(a)
            y = direction[0] * math.sin(a) + direction[1] * math.cos(a)
            pt = (int(O.CENTRE[0] + x * r), int(O.CENTRE[1] + y * r))
            if O.hud(pt):
                continue
            c = A.click(pt, 'step')
            if res is not None:
                res['clicks'] = res.get('clicks', 0) + 1
            ok = walked(c, target, res)
            trace(res, f'{label} @{pt[0]},{pt[1]}: ' + outcome(c, ok, target))
            if ok:
                if learn and (c.node == target or O.closest_node(c.after) == target):
                    L.learn_toward(learn[0], learn[1], (x, y))
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
    path = core.WF.map_route(img, pin, m.point) or [m.point]
    ahead = next((q for q in path if math.dist(q, pin) >= 60), path[-1])
    dx, dy = ahead[0] - pin[0], ahead[1] - pin[1]
    n = math.hypot(dx, dy)
    log('seek', what='map', pin=list(pin), goal=list(m.point), score=round(m.score, 2), ahead=list(ahead))
    return None if n < 1 else (dx / n, dy / n)


def seek(t, res):
    """One search round (module doc). The Click that got her somewhere, or None (stuck / nothing more: then vision)."""
    tried = res.setdefault('tried', [])   # screen points that led nowhere; cleared when she walks
    if stuck(res):
        res['still'] = 0
        return None
    # the area known from the last event (engine) first: look-alike bubbles (beds in two gardens) can't tell; then the
    # frame; the last event only when the frame shows no node
    cn = O.closest_node()
    if cn in res.get('lookalike', ()) and not res.get('area'):
        cn = None   # beds look alike in every garden: the frame can't say which one she is at
    here = res.get('area') or cn or res.get('here')
    res['inside'] = inside(t, here) if here else res.get('inside')
    if here and here != t.node:
        dd = L.toward(here, t.node)
        if dd:
            log('seek', what='graph', here=here, to=t.node, dir=list(dd))
            c = step(dd, res, f'graph {here}->{t.node}', t.node, learn=(here, t.node))
            if c is not None:
                res['here'], res['heading'], res['heading_n'] = c.node, dd, 0
                return c
    if not here and res.get('heading') and res.get('heading_n', 0) < HEADING_MAX:   # between nodes: keep going
        res['heading_n'] = res.get('heading_n', 0) + 1
        c = step(res['heading'], res, f'heading {res["heading_n"]}/{HEADING_MAX}', t.node)
        if c is not None:
            res['here'] = c.node
            return c
    if t.marker == 'dry_soil' and res.get('light') in ('day', None):
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
    for det in O.see(t.kind, tried)[:2]:
        img = core.WF.grab()
        pt = beside(det, O.scan())   # free ground just below the object, never its bubble (user D188)
        if pt is None:
            tried.append(det.point)
            trace(res, f'{t.kind} seen @{det.point[0]},{det.point[1]}: no free ground beside it')
            continue
        c = A.click(pt, 'step')
        res['clicks'] += 1
        tried.append(det.point)
        _predicted_arrival(t, c)
        ok = walked(c, t.node, res)
        trace(res, f'{t.kind} seen @{det.point[0]},{det.point[1]}: ' + outcome(c, ok, t.node))
        if c.node == t.node and not any(t.fits(a) for a in c.after):   # a bed, but not one this target needs
            res['still'] = res.get('still', 0) + 1
            trace(res, f'  that {t.kind} does not need it (no fitting bubble)')
            A.gameplay()
            if stuck(res):
                return None
            continue
        if c.node and c.node != t.node:   # the game proved it is another object: learn its look as that kind
            if L.relabel(img, getattr(det, 'box', None), L.kind_of(c.node)):
                trace(res, f'learned: the look @{det.point[0]},{det.point[1]} is a {L.kind_of(c.node)}')
        if ok or c.node:   # walked / arrived, or another node took it: the event tells where she is
            return c
        if stuck(res):
            return None
    if res.get('inside') or inside(t, here):
        res['inside'] = True
        return explore(t, res)
    dd = map_direction(t.region)
    if dd is None:
        trace(res, 'map: no direction')
        return None
    return step(dd, res, 'map', t.node)


def _predicted_arrival(t, c):
    """A click on a seen object of the target kind predicts she arrives at one: its bubble shows (or its event)."""
    own = O.NODE_OF.get(t.kind)
    hit = (c.node == t.node or (bool(c.node) and L.kind_of(c.node) == t.kind)   # an event on any object of the kind
           or any(O.node_of_bubble(a) == own for a in c.after))
    got = c.node or [str(a) for a in c.after][:4]
    try:
        import evals
        evals.record('nav', 'arrive', t.kind, got, hit, {'pt': list(c.pt), 'target': t.node})
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
