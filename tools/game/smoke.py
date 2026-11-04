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


def plant_one(seed='Tulip', kind='plant', water=True, tried=()):
    out = []
    try:
        s = screen.require_world()
    except Exception as e:   # noqa: BLE001
        _step(out, 'screen', False, str(e)[:160])
        return out
    _step(out, 'screen', True, s.kind)
    fit = [a for a in O.scan() if a.kind == kind and not a.drop   # a drop = a planted bed asking for water (D186)
           and not any(O.d(a.pt, p) < 60 for p in tried)]
    if not _step(out, 'bubble', bool(fit), str(O.nearest(fit, O.CENTRE)) if fit else
                 f'no {kind} bubble in view: {[str(a) for a in O.scan()] or "none"}'):
        return out
    c = A.click(O.nearest(fit, O.CENTRE).pt, 'bubble')
    s = screen.read()
    if not _step(out, 'click', s.kind == 'picker', f'{s.kind}: {" / ".join(s.texts[:4])}; events {c.events}'):
        out[-1]['pt'] = c.pt   # a wrong bubble (misread kind): the caller skips it
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
    res = {'planted': 0, 'watered': 0, 'stop': None, 'steps': [], 'can': can, 'misses': 0}
    tried = []
    for _ in range(max_beds + 3):
        out = plant_one(seed, kind, water=res['can'] not in ('empty', 'skip'), tried=tried)
        res['steps'].append(out)
        done = {s['step']: s['ok'] for s in out}
        res['planted'] += bool(done.get('confirm'))
        if done.get('confirm'):   # progress: the vision counter starts again
            from . import ask
            ask.progress('plant_garden')
        res['watered'] += bool(done.get('water'))
        failed = next((s for s in out if not s['ok']), None)
        if failed and failed['step'] == 'water':   # an empty can or rain (Space waters nothing): plant on, no watering
            res['can'] = 'empty' if 'out_of_water' in str(failed['proof']) else (res['can'] or 'skip')
            continue
        if failed and failed['step'] == 'click' and failed.get('pt') and res['misses'] < 2:
            res['misses'] += 1     # a misread bubble: its click proved another object (the event relabels it)
            tried.append(failed['pt'])
            continue
        if failed:
            res['stop'] = f"{failed['step']}: {failed['proof']}"
            break
        if res['planted'] >= max_beds:
            res['stop'] = f'max {max_beds} beds'
            break
    else:
        res['stop'] = f'max {max_beds} beds'
    print(f"planted {res['planted']}, watered {res['watered']}, can {res['can'] or '?'}, stop: {res['stop']}")
    return res


def can_from_log():
    """'empty' | 'full' | None: the last can event in today's game log (out_of_water vs a fill)."""
    import re
    try:
        lines = core.WF.today_log()[0]
    except Exception:   # noqa: BLE001
        return None
    for line in reversed(lines):
        if re.search(r'> out_of_water ', line):
            return 'empty'
        if re.search(r'> (?:fill_watering_can|full_watering_can) ', line):
            return 'full'
    return None


AREA_NEAR = 10.0   # world units: within this of the area's centre she is in the area (map pins are coarse)


def calibrate_if_needed():
    """One more map pair while the calibration is missing or narrow (a fresh event position + the pin)."""
    from . import where
    import math
    ps = where.pairs()
    if where.fit() is None or max((math.dist(a[0], b[0]) for a in ps for b in ps), default=0) < 10:
        return where.calibrate_here()
    return False


def _area_pos(region):
    g = core.WF.world_graph() if hasattr(core.WF, 'world_graph') else None
    if g is None or region not in g.nodes:
        return g, None
    return g, tuple(g.nodes[region].extra.get('pos') or ()) or None


def plant_garden(seed='Tulip', region=None, rounds=12, answer=None):
    """plant_visible; with no seedling bubble in view: away from the area -> walk_to_area (each step closer, map or
    event position); inside it -> click a visible bed not tried yet (its event says where she is). Stops when the
    world has no empty bed in the area left, or a step fails."""
    import math
    from . import where, world
    total = {'planted': 0, 'watered': 0, 'walks': 0, 'stop': None, 'can': can_from_log()}
    tried = []
    if answer is not None:   # vision's cell (an empty bed, or ground toward it): click it first
        from . import ask
        if str(answer).strip().lower() == 'none':
            total['stop'] = 'vision: none'
            return total
        c = A.click(ask.parse_point(answer), 'point')
        print(f'answer: clicked {answer}: {"walked" if c.moved else "no move"}, events {c.events}')
        A.gameplay()
    for _ in range(rounds):
        ok, h, light = daylight()
        if not ok:
            total['stop'] = dark_stop(h, light)
            break
        r = plant_visible(seed, can=total['can'])
        total['can'] = r['can']
        total['planted'] += r['planted']
        total['watered'] += r['watered']
        if r['planted']:
            tried.clear()
            calibrate_if_needed()
        if not str(r['stop']).startswith('bubble'):
            total['stop'] = r['stop']
            break
        g, apos = _area_pos(region)
        if g is not None and not world.query(g, {'kind': 'GardenBed', 'region': region, 'stage': 'empty'}):
            total['stop'] = f'no empty bed left in {region} (world)'
            break
        src, pos = where.position(far_ok=True)
        if src == 'map' and apos and math.dist(pos, apos) <= MAP_FAR:
            src, pos = None, None   # near by the map = unknown: a visible bed first
        if apos and pos is not None and math.dist(pos, apos) > AREA_NEAR:   # unknown: a visible bed first
            walk_to_area(apos, arrive=AREA_NEAR * 0.6)
            total['walks'] += 1
            continue
        dets = [d for d in O.see('GardenBed', tried)]
        if not dets:
            from . import ask
            ask.ask('click', f'Tara (frame centre) must plant the empty beds of {region} but sees no empty-bed bubble '
                             f'and no bed by its look. Give the grid cell of an EMPTY bed (bare soil), or none. '
                             f'Answer: ./wf py "from game import smoke; smoke.plant_garden(\'{seed}\', '
                             f'region=\'{region}\', answer=\'<cell>\')"', {'goal': 'plant_garden',
                                                                         'params': {'region': region}}, total)
        d = dets[0]
        tried.append(d.point)
        from . import nav as N
        c = A.click(N.beside(d, O.scan()) or d.point, 'step')   # beside it, never its bubble (user D188)
        total['walks'] += 1
        print(f'bed: clicked the bed seen @{d.point[0]},{d.point[1]}: {"walked" if c.moved else "no move"}, '
              f'events {c.events}, bubbles {[str(a) for a in c.after] or "-"}')
        if c.at:
            calibrate_if_needed()
        A.gameplay()
    else:
        total['stop'] = f'{rounds} rounds'
    print(f"garden: planted {total['planted']}, watered {total['watered']}, walks {total['walks']}, "
          f"can {total['can'] or '?'}, stop: {total['stop']}")
    return total


STEP_PX = 320   # px from the centre for one step


def walk_until(direction, kind='plant', max_steps=8):
    """Step in a screen direction until a `kind` bubble (without a drop) shows; stops when a step doesn't move her.
    For when her position is unknown (walking logs nothing, D186). {'found', 'steps', 'stop'}."""
    res = {'found': False, 'steps': 0, 'stop': None}
    for _ in range(max_steps):
        if any(a.kind == kind and not a.drop for a in O.scan()):
            res['found'] = True
            break
        pt = (round(O.CENTRE[0] + direction[0] * STEP_PX), round(O.CENTRE[1] + direction[1] * STEP_PX))
        c = A.click(pt, 'step')
        res['steps'] += 1
        print(f'walk_until: step {res["steps"]} @{pt[0]},{pt[1]}: {"walked" if c.moved else "no move"}; '
              f'bubbles {[str(a) for a in c.after] or "-"}')
        if not c.moved:
            res['stop'] = 'no move'
            break
    else:
        res['found'] = any(a.kind == kind and not a.drop for a in O.scan())
        res['stop'] = None if res['found'] else f'{max_steps} steps'
    from . import where
    where.walked()   # her position is unknown until the next positioned event
    return res


MIN_GAIN = 1.5            # world units a step must bring her closer
MAP_FAR = 25.0            # world units: the map steers only while the goal is farther (user D187: it's imprecise)
TURNS = (0, 35, -35)      # degrees off the goal direction after a step without progress


def walk_to_area(goal, arrive=6.0, kind='plant', max_steps=14):
    """Walk to world `goal` (an area node's position) step by step; each step must bring her closer (position from
    the last event, else the map pin, game/where.py); no progress -> turn; all turns failed -> ONE vision question
    with the trace. Stops when arrived or a `kind` bubble shows. {'stop', 'steps', 'trace'}."""
    import math
    from . import ask, where
    res = {'stop': None, 'steps': 0, 'trace': []}
    src, pos = where.position()
    fails = 0
    for _ in range(max_steps):
        if pos is None:
            break
        d = math.dist(pos, goal)
        if d <= arrive:
            res['stop'] = 'arrived'
            return res
        if src == 'map' and d <= MAP_FAR:   # near: the map can't tell; the caller goes by visible objects / events
            res['stop'] = 'near (map imprecise)'
            return res
        if kind and any(a.kind == kind and not a.drop for a in O.scan()):
            res['stop'] = 'bubble'
            return res
        a = math.radians(TURNS[fails % len(TURNS)])
        dx, dy = (goal[0] - pos[0]) / d, -(goal[1] - pos[1]) / d
        dx, dy = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
        pt = (round(O.CENTRE[0] + dx * STEP_PX), round(O.CENTRE[1] + dy * STEP_PX))
        c = A.click(pt, 'step')
        where.walked()
        res['steps'] += 1
        src, pos2 = where.position()
        gain = d - math.dist(pos2, goal) if pos2 else 0.0
        res['trace'].append(f'step @{pt[0]},{pt[1]} from {tuple(round(v, 1) for v in pos)} ({src}): '
                            f'{"walked" if c.moved else "no move"}, {gain:+.1f} closer')
        print('walk_to_area: ' + res['trace'][-1])
        if gain >= MIN_GAIN:
            fails = 0
        else:
            fails += 1
            if fails >= len(TURNS):
                break
        pos = pos2 or pos
    ask.ask('click', f'Tara (frame centre) must get to the area at world {goal}; the steps got her no closer '
                     f'({"; ".join(res["trace"][-4:]) or "her position is unknown"}). Give the grid cell of free '
                     f'ground toward it (a road, a gap in the fence), or none.',
            {'goal': 'walk', 'params': {'to': list(goal)}}, res)


# ---- the morning chores: plant the rest, refill, water (daylight only; user D186 "run all at morning") ----------
def daylight():
    """(ok, hour, light): bubble icons are read reliably only in daylight (D186: none found at 5:40 pm); no chores in
    the rain for now (user D187): light = 'rain (<forecast>)'."""
    from . import ask
    r = ask.rain()
    if r:
        return False, None, f'rain ({r} today)'
    h, light = O.clock()
    return light in ('day', None), h, light


def dark_stop(h, light):
    if str(light).startswith('rain'):
        return f'{light}: no chores in the rain for now (user D187) - ask the user, try a dry day'
    return (f'dark ({light}, {h if h is None else round(h, 1)} h): bubble icons are unreliable outside daylight - '
            f'suggest sleeping (ask the user), then run in the morning')


def water_visible(max_beds=12):
    """Click every drop bubble in view (dry beds); `> water` proves each. Stops on out_of_water (can empty)."""
    from . import ask
    res = {'watered': 0, 'can': None, 'stop': None}
    tried = []
    for _ in range(max_beds):
        screen.require_world()
        drops = [a for a in O.scan() if a.drop and not any(O.d(a.pt, p) < 60 for p in tried)]
        if not drops:
            res['stop'] = 'no drop bubble in view'
            break
        a = O.nearest(drops, O.CENTRE)
        mark = core.WF.log_mark()
        A.click(a.pt, 'bubble')
        line = core.seen(r'> (?:water|hazel_waterplant|out_of_water) ', mark, WAIT)
        print(f'water: {a} -> {line or "no water line"}')
        if line and 'out_of_water' in line:
            res['can'], res['stop'] = 'empty', 'out_of_water'
            A.gameplay()
            break
        if line:
            res['watered'] += 1
            ask.progress('morning')
        else:   # not a dry bed after all (a wilted card, another object): skip it
            tried.append(a.pt)
            A.gameplay()
    return res


def fill_can(attempts=4):
    """The well's bubble in view -> click -> `fill_watering_can` proves it; else walk to the well's area (each step
    closer) or click the well by its look; else ONE vision question."""
    import math
    from . import ask, where
    res = {'ok': False, 'trace': []}
    for _ in range(attempts):
        screen.require_world()
        wells = [a for a in O.scan() if a.kind in ('fill_can', 'full_watering_can')]
        if wells:
            mark = core.WF.log_mark()
            A.click(O.nearest(wells, O.CENTRE).pt, 'bubble')
            line = core.seen(r'> (?:fill_watering_can|full_watering_can) ', mark, WAIT)
            print(f'fill_can: {line or "no fill line"}')
            res['ok'] = bool(line)
            return res
        g = core.WF.world_graph() if hasattr(core.WF, 'world_graph') else None
        area = g.nodes['Well'].region if g is not None and 'Well' in g.nodes else None
        apos = tuple(g.nodes[area].extra.get('pos') or ()) if area and area in g.nodes else ()
        src, pos = where.position()
        if apos and pos and math.dist(pos, apos) > AREA_NEAR:
            res['trace'].append(f'walk to {area} {apos} from {pos}')
            walk_to_area(apos, arrive=AREA_NEAR * 0.6, kind=None)
            continue
        dets = O.see('Well')
        if dets:
            res['trace'].append(f'well seen @{dets[0].point}')
            from . import nav as N
            A.click(N.beside(dets[0], O.scan()) or dets[0].point, 'step')
            A.gameplay()
            continue
        break
    ask.ask('click', f'Tara (frame centre) must fill her watering can at the Well but sees neither its bubble nor the '
                     f'well ({res["trace"][-3:] or "nothing tried"}). Give the grid cell of the Well, or of free ground '
                     f'toward it. Answer: ./wf py "from game import smoke; smoke.morning(answer=\'<cell>\')"',
            {'goal': 'morning', 'params': {}}, res)


def water_garden(region, rounds=10):
    """water_visible; can empty -> fill_can; no drop in view and the world still has dry beds in the area -> click a
    visible bed not tried yet. Stops when the world says no dry bed is left."""
    from . import ask, world
    total = {'watered': 0, 'fills': 0, 'stop': None}
    tried = []
    for _ in range(rounds):
        ok, h, light = daylight()
        if not ok:
            total['stop'] = dark_stop(h, light)
            break
        r = water_visible()
        total['watered'] += r['watered']
        if r['can'] == 'empty':
            if not fill_can()['ok']:
                total['stop'] = 'fill_can failed'
                break
            total['fills'] += 1
            continue
        g, _ = _area_pos(region)
        dry = world.query(g, {'kind': 'GardenBed', 'region': region, 'stage': 'growing|producing', 'watered': False}) \
            if g is not None else []
        if not dry:
            total['stop'] = 'no dry bed left (world)'
            break
        dets = O.see('GardenBed', tried)
        if not dets:
            ask.ask('click', f'Tara (frame centre) must water the dry beds of {region} ({len(dry)} left) but sees no '
                             f'drop bubble and no bed by its look. Give the grid cell of a dry bed (light-brown soil), '
                             f'or none. Answer: ./wf py "from game import smoke; smoke.morning(answer=\'<cell>\')"',
                    {'goal': 'morning', 'params': {'region': region}}, total)
        tried.append(dets[0].point)
        from . import nav as N
        A.click(N.beside(dets[0], O.scan()) or dets[0].point, 'step')
        A.gameplay()
    else:
        total['stop'] = f'{rounds} rounds'
    return total


def morning(seed='Tulip', region='GardenSouth', answer=None):
    """Plant the empty beds of `region`, refill the can if it ran dry, water every dry bed - daylight only, every
    step with its log proof. {'planted', 'watered', 'fills', 'stop'}."""
    ok, h, light = daylight()
    if not ok:
        res = {'planted': 0, 'watered': 0, 'fills': 0, 'stop': dark_stop(h, light)}
        print(f"morning: {res['stop']}")
        return res
    if answer is not None:   # vision's cell from a morning question: click it first
        from . import ask
        A.click(ask.parse_point(answer), 'point')
        A.gameplay()
    p = plant_garden(seed, region=region)
    res = {'planted': p['planted'], 'watered': p['watered'], 'fills': 0, 'stop': None}
    if not str(p['stop']).startswith('no empty bed left'):
        res['stop'] = f'plant: {p["stop"]}'
    else:
        if can_from_log() == 'empty':
            f = fill_can()
            if not f['ok']:
                res['stop'] = 'fill_can failed'
            res['fills'] += 1
        if res['stop'] is None:
            w = water_garden(region)
            res['watered'] += w['watered']
            res['fills'] += w['fills']
            res['stop'] = 'done' if w['stop'] == 'no dry bed left (world)' else f'water: {w["stop"]}'
    print(f"morning: planted {res['planted']}, watered {res['watered']}, fills {res['fills']}, stop: {res['stop']}")
    return res


def vision_click(answer, here=None):
    """A click that answers a vision question (a grid cell 'Q14' or (x, y)): through act.click(..., 'point') so what
    it proves is learned (the look as its kind, the direction toward the area reached, an eval). Use it for every
    supervisor / vision click instead of a raw click."""
    from . import ask
    pt = ask.parse_point(answer) if isinstance(answer, str) else tuple(answer)
    c = A.click(pt, 'point', here=here)
    print(f'vision_click {answer}: {"walked" if c.moved else "no move"}, events {c.events}, '
          f'triggers {[l.split("] ", 1)[-1] for l in c.lines if "[TRIGGER]" in l][:3]}, bubbles {[str(a) for a in c.after][:3]}')
    return c
