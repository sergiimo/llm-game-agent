"""walk(target) on the world model (M3, spec 2026-10-30 §5): the mode follows the evidence.
in reach → nothing · on screen → one click on the (uncovered) target, the game pathfinds · same area off screen →
costmap waypoints, one click per hop · other area → the old graph route (until world.graph walks, ledgered).
A save reading only when the belief needs one (u > 3) or to confirm arrival when the estimate is too loose."""
import math

from . import core
from .core import Failed, action

REACH = 2.5          # world units: close enough to use an object
SURE = 0.3           # belief std (units) below which an arrival needs no reading (day-walk: a loose "arrived" cost a
                     # wrong Space on a hive; a reading costs 2.5 s)
PRECISE = 0.5        # belief std above which a reading comes before clicking the target itself
MAX_HOPS = 8
BUBBLE_CLEAR = 80    # px: walking clicks keep this far from any bubble
NO_PROGRESS = 2      # clicks in a row that move her < 0.5 units: stop and ask (world-walk: 8 clicks on hives)


def _read(W):
    W.checkpoint(fill=False)


def _goal(target):
    area = getattr(target, 'scene', None) or getattr(target, 'area', None) or 'Farm'
    return area, float(target.x), float(target.z)


def click_object(target):
    """Click the object itself if it's on screen (the game pathfinds to it and turns her to it: the well, D150).
    True if clicked."""
    from world import view
    W = core.WF
    w = W.world()
    area, _, _ = _goal(target)
    c = W.calib_load(area)
    if not c:
        return False
    if w.belief.u() > PRECISE:
        W.checkpoint(fill=False)
        c = W.calib_load(area)
    pt = view.click_point(c['H'], w.belief, target)
    if not pt:
        return False
    msg = W.go_to(*pt)
    return not (msg and msg.startswith(('MENU OPEN', 'NO MOVE')))


def _screen_point(W, w, H, target, area, tx, tz, reach):
    from world import view
    from . import affordances
    zones = affordances.no_click_zones()  # a click on a bubble is an action, not a step
    pt = view.click_point(H, w.belief, target)
    if pt and not any(math.dist(pt, p) < BUBBLE_CLEAR for p in zones):
        if w.belief.u() > PRECISE:  # the target's screen point is only as good as her position: read it exactly first
            W.checkpoint(fill=False)
            pt = view.click_point(W.calib_load(area)['H'], w.belief, target)
        return pt  # the target itself: the game pathfinds round the hives (D148 well click)
    status, wps = w.route_status((area, tx, tz), reach=reach)
    if status != 'way':
        return None
    for x, z in reversed(wps):  # the farthest waypoint on screen and not on a bubble
        if view.on_screen(H, w.belief, x, z):
            sx, sy = view._scr(H, w.belief, x, z)
            if any(math.dist((sx, sy), p) < BUBBLE_CLEAR for p in zones):
                continue
            return int(sx), int(sy)
    return None


def _learn_click(W, w, H, target, pt, frm):
    """A click that brought up the object's own bubble shows where its sprite is: store that ground point as the
    object's click spot (the well's roof, D150), so the next walk clicks the object you see, not its use point."""
    try:
        if hasattr(target, 'state') and _bubble_up(target):
            import nav
            dx, dz = nav.screen_to_ground(H, *pt)
            target.state['click_xz'] = [round(frm[0] + dx, 2), round(frm[1] + dz, 2)]
            w.save()
    except Exception:  # noqa: BLE001
        pass


def _ask(W, target, d, why):
    """The vision question. No Escape to clear cards: in rain `state` reads "overlay" during gameplay, and that Escape
    paused the game mid-walk (obj-walk-2); hover cards are avoided by parking the mouse instead."""
    if not hasattr(W, 'stuck_vision'):
        return ''
    return W.stuck_vision(str(target), d, why)


def _bubble_up(target):
    """The target's bubble shows: a kind only its kind of object offers (the well's can), or a bubble matched to it."""
    from . import affordances
    kind = getattr(target, 'kind', None)
    for a in affordances.scan():
        if a.kind == 'unknown':  # an unrecognised icon proves nothing (obj-walk-2: hive honey bubbles "were" the well)
            continue
        if kind and affordances.OWNER.get(a.kind) == kind:
            return True
        if a.entity is not None and math.dist((a.entity.x, a.entity.z), (target.x, target.z)) <= affordances.SAME:
            return True
    return False


@action
def walk(target, reach=REACH):
    """Walk to an object/point with x, z (same area) or a place name (other area via the graph)."""
    W = core.WF
    if not hasattr(target, 'x'):
        msg = W.goto(str(target))
        if not msg.startswith(('ARRIVED', 'NEAR')):
            raise Failed(f'walk {target}: {msg.splitlines()[0][:200]}')
        return msg
    w = W.world()
    area, tx, tz = _goal(target)
    still, last = 0, None
    for hop in range(MAX_HOPS + 1):
        W.world_sync()
        if w.needs_fix():
            _read(W)
        if _bubble_up(target):  # the target's own bubble is on screen: it's in reach (zoom-walk-2)
            return f'ARRIVED {target}: its bubble is up'
        a, x, z, u = w.tara()
        if a != area:  # another area: the graph route of the old code (ruling until world.graph walks)
            return W.goto_point(area, tx, tz, r=reach)
        d = math.dist((x, z), (tx, tz))
        if last is not None:
            still = still + 1 if math.dist(last, (x, z)) < 0.5 else 0
            if still >= NO_PROGRESS:
                why = f'no progress: {still} clicks without moving at ({x:.1f}, {z:.1f})'
                q = _ask(W, target, (tx - x, tz - z), why)
                raise Failed(f'walk {target}: {why}' + (f'\n{q}' if q else ''))
        if d <= reach:
            if u > SURE:  # close by the estimate, but the estimate is loose: confirm once
                _read(W)
                a, x, z, u = w.tara()
                d = math.dist((x, z), (tx, tz))
                if d > reach:
                    continue
            return f'ARRIVED {target}: {d:.1f} units off (±{u:.1f}), {hop} click(s)'
        if hop == MAX_HOPS:
            break
        c = W.calib_load(area)
        if not c:
            return W.goto_point(area, tx, tz, r=reach)
        pt = _screen_point(W, w, c['H'], target, area, tx, tz, reach)
        if pt is None:  # no point we can compute: ask the model for the next step (goal + annotated image, L74)
            why = f'no clickable point toward it from ({x:.1f}, {z:.1f}) ±{u:.1f}'
            q = _ask(W, target, (tx - x, tz - z), why)
            raise Failed(f'walk {target}: {why}' + (f'\n{q}' if q else ''))
        last = (x, z)
        msg = W.go_to(*pt)
        if msg and msg.startswith('MENU OPEN'):
            raise Failed(f'walk {target}: {msg}')
        _learn_click(W, w, c['H'], target, pt, (x, z))
    raise Failed(f'walk {target}: not within {reach} units after {MAX_HOPS} clicks')
