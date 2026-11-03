"""SMOKE: one bed, one primitive at a time, each with its own proof (design review D186: the engine layered guesses
over primitives that were never proven live). `./wf py "from game import smoke; smoke.plant_one('Tulip')"` prints
one line per step and stops at the first that fails:

  screen   gameplay (screen.require_world)
  bubble   a `plant` bubble in view (affordances.scan) - nearest to Tara
  click    click it -> the screen is the picker (its text says Inventory / Seeds)
  pick     ui.pick_card(seed) -> the card's name on screen
  confirm  Space -> `[STATS] totalPlanted` in the game log (the only proof of a planting)
  water    Space -> `> water` (or `> out_of_water`) in the game log

No navigation, no world graph, no table: if this fails, the failing primitive is named with its evidence."""
from . import act as A, core, observe as O, screen, ui

WAIT = 3.0   # s for a proving log line


def _step(out, name, ok, proof):
    out.append({'step': name, 'ok': bool(ok), 'proof': proof})
    try:
        core.WF.run_log('smoke', step=name, ok=bool(ok), proof=str(proof)[:200])
    except Exception:   # noqa: BLE001
        pass
    print(f'{name}: {"ok" if ok else "FAIL"} - {proof}')
    return ok


def _space(pattern):
    mark = core.WF.log_mark()
    ui.press_bubble()
    return core.seen(pattern, mark, WAIT)


def plant_one(seed='Tulip', kind='plant', water=True):
    out = []
    try:
        s = screen.require_world()
    except Exception as e:   # noqa: BLE001
        _step(out, 'screen', False, str(e)[:160])
        return out
    _step(out, 'screen', True, s.kind)
    fit = [a for a in O.scan() if a.kind == kind]
    if not _step(out, 'bubble', bool(fit), str(O.nearest(fit, O.CENTRE)) if fit else
                 f'no {kind} bubble in view: {[str(a) for a in O.scan()] or "none"}'):
        return out
    c = A.click(O.nearest(fit, O.CENTRE).pt, 'bubble')
    s = screen.read()
    if not _step(out, 'click', s.kind == 'picker', f'{s.kind}: {" / ".join(s.texts[:4])}; events {c.events}'):
        ui.close()
        return out
    try:
        title = ui.pick_card(seed)
        _step(out, 'pick', True, title)
    except core.Failed as e:
        _step(out, 'pick', False, str(e)[:160])
        ui.close()
        return out
    line = _space(r'totalPlanted\.')
    if not _step(out, 'confirm', line, line or f'no totalPlanted within {WAIT} s; screen {screen.read().kind}'):
        ui.close()
        return out
    if not water:   # the can ran dry earlier: plant only (the beds are listed for water_all after a refill)
        return out
    line = _space(r'> (?:water|out_of_water) ')
    _step(out, 'water', line and 'out_of_water' not in line, line or f'no water line within {WAIT} s')
    return out


def plant_visible(seed='Tulip', kind='plant', max_beds=12, can=None):
    """plant_one while a `kind` bubble is in view (the bubble loop on proven primitives); stops at the first step that
    fails. {'planted', 'watered', 'stop', 'steps'}."""
    res = {'planted': 0, 'watered': 0, 'stop': None, 'steps': [], 'can': can}
    for _ in range(max_beds):
        out = plant_one(seed, kind, water=res['can'] != 'empty')
        res['steps'].append(out)
        done = {s['step']: s['ok'] for s in out}
        res['planted'] += bool(done.get('confirm'))
        res['watered'] += bool(done.get('water'))
        failed = next((s for s in out if not s['ok']), None)
        if failed and failed['step'] == 'water' and 'out_of_water' in str(failed['proof']):
            res['can'] = 'empty'   # an empty can stops watering, not planting
            continue
        if failed:
            res['stop'] = f"{failed['step']}: {failed['proof']}"
            break
    else:
        res['stop'] = f'max {max_beds} beds'
    print(f"planted {res['planted']}, watered {res['watered']}, can {res['can'] or '?'}, stop: {res['stop']}")
    return res


# ---- one walk toward the nearest object the world says needs it -----------------------------------------------------
PX_PER_UNIT = 57.6   # screen px per world unit at the usual zoom (D186: neighbour bed bubbles 216 px apart, 3.75 units)


def px_per_unit(affs, pitch):
    """From the two closest bubbles on one row (neighbour objects `pitch` world units apart); else the default."""
    pts = sorted(a.pt for a in affs)
    best = None
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            if abs(p[1] - q[1]) < 30 and abs(q[0] - p[0]) > 40 and (best is None or abs(q[0] - p[0]) < best):
                best = abs(q[0] - p[0])
    return best / pitch if best and pitch else PX_PER_UNIT


def screen_point(tara, obj, k):
    """Tara is the frame centre; the camera looks north: world +x = right, +z = up."""
    return (round(O.CENTRE[0] + (obj[0] - tara[0]) * k), round(O.CENTRE[1] - (obj[1] - tara[1]) * k))


def walk_to_need(where, kind='GardenBed', region=None):
    """Refresh the world (save + today's log), take the nearest object that matches, click the ground below it (she
    walks there). The Click, or None when nothing matches / her position is unknown."""
    from . import world
    g = core.WF.world_graph() if hasattr(core.WF, 'world_graph') else None
    if g is None:
        return None
    tara = world.tara_pos(g)
    flt = dict(where, kind=kind, **({'region': region} if region else {}))
    objs = world.query(g, flt)
    if not tara or not objs:
        print(f'walk: nothing to walk to (tara {tara}, {len(objs)} matching)')
        return None
    import math
    nid = min(objs, key=lambda n: math.dist(tara, tuple(g.nodes[n].extra['pos'])))
    pos = tuple(g.nodes[nid].extra['pos'])
    ns = sorted(math.dist(pos, tuple(g.nodes[m].extra['pos'])) for m in world.query(g, {'kind': kind}) if m != nid)
    k = px_per_unit(O.scan(), ns[0] if ns else 0)
    x, y = screen_point(tara, (pos[0], pos[1] - 1.2), k)   # just south of it: she stands in front, its bubble shows
    x, y = min(max(x, 60), 1860), min(max(y, 260), 1020)
    c = A.click((x, y), 'step')
    print(f'walk: to {nid} at {pos} from {tara} (k {k:.1f} px/unit) -> click {x},{y}: '
          f'{"walked" if c.moved else "no move"}, events {c.events}')
    return c


def plant_garden(seed='Tulip', region=None, rounds=8):
    """plant_visible, then walk to the nearest empty bed the world knows, until none is left or a walk fails."""
    total = {'planted': 0, 'watered': 0, 'walks': 0, 'stop': None, 'can': None}
    for _ in range(rounds):
        r = plant_visible(seed, can=total['can'])
        total['can'] = r['can']
        total['planted'] += r['planted']
        total['watered'] += r['watered']
        if not str(r['stop']).startswith('bubble'):
            total['stop'] = r['stop']
            break
        c = walk_to_need({'stage': 'empty'}, region=region)
        if c is None:
            total['stop'] = 'no empty bed left (world)'
            break
        total['walks'] += 1
        if not c.moved:
            total['stop'] = 'walk: no move'
            break
    else:
        total['stop'] = f'{rounds} rounds'
    print(f"garden: planted {total['planted']}, watered {total['watered']}, walks {total['walks']}, "
          f"can {total['can'] or '?'}, stop: {total['stop']}")
    return total
