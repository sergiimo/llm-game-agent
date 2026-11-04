"""ENGINE: one loop for every goal (spec 2026-11-03 §6). `achieve(goal, answer=None, **params)`.

stops (language, clock) -> world.refresh (save + today's log) -> targets = the goal's filter (+ objects already being
worked on) -> nearest target -> plan.path (table BFS) -> its first row: needs (an item: stop when missing; Tara's can:
a sub-goal from the table) -> nav.search for a bubble that fits the row in the target's area -> steps.run -> the
events' positions update the world -> repeat. Done = the filter is empty. Nothing found -> ONE vision question
(ask.py). No goal or kind names in code: goals.json, actions.json, kinds.json."""
import json
import math
import os

from . import act as A, ask, core, integrate as I, learn as L, nav as N, observe as O, plan, steps, world

GOALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'goals.json')
MAX_CLICKS = 40
LAST = {}            # the last call's result (also when it ended in a question): for the summary and tests
FAILS = 3            # failed attempts on one target before it is skipped this call


def goals():
    with open(GOALS) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith('_')}


def _goal(goal):
    if isinstance(goal, dict):
        return 'query', goal
    if isinstance(goal, str) and goal.strip().startswith('{'):
        return 'query', json.loads(goal)
    lib = goals()
    if goal not in lib:
        raise core.Failed(f'unknown goal {goal!r}: library has {", ".join(lib)}; or pass a raw query '
                          '{"kind", "where", "make"}')
    return goal, lib[goal]


def _param(name, params):
    """A goal parameter: the call's, else a named list from kinds.json `_lists` (flowers)."""
    if name in params:
        return params[name]
    try:
        with open(os.path.join(os.path.dirname(GOALS), 'kinds.json')) as f:
            return json.load(f).get('_lists', {}).get(name)
    except (OSError, ValueError):
        return None


def _where(spec, params):
    """The goal's filter with $params; a list becomes alternatives ('Carrot|Tulip'); '!$x' = none of them."""
    out = {}
    for k, v in spec.get('where', {}).items():
        neg = isinstance(v, str) and v.startswith('!$')
        if isinstance(v, str) and (v.startswith('$') or neg):
            p = _param(v.lstrip('!$'), params)
            if p is None:
                continue
            v = ('!' if neg else '') + ('|'.join(p) if isinstance(p, (list, tuple)) else p)
        out[k] = v
    return out


def _skip_names(spec, params):
    """Bubble values to leave alone (skip_bubbles: {crop: $flowers}): a set of names, or empty."""
    out = set()
    for v in (spec.get('skip_bubbles') or {}).values():
        p = _param(str(v).lstrip('$'), params) if str(v).startswith('$') else v
        out |= set(p if isinstance(p, (list, tuple)) else [p]) - {None}
    return out


def _passes(g, nid, where):
    """`where` on an object: a state key the object never had passes (memory is a hint, never a gate - law 6)."""
    st = world.state_of(g, nid)
    return plan.holds({k: v for k, v in where.items() if k in st}, st)


def _strict(spec):
    """`where` keys bound from a goal parameter (`crop: $crops`): the user named the value, so it must be KNOWN on
    the object - an unknown one is never assumed (D187: harvest carrots, the save has no crop type)."""
    return {k for k, v in spec.get('where', {}).items() if isinstance(v, str) and v.startswith('$') and k != 'region'}


def _today():
    t = world.when(_stamp())
    return None if t is None else t // 86400


def _stale_keys(g, n, rest, st, today):
    """`fresh: day` goals (user D188): the `where` keys the object fails only by a reading from an earlier game day
    (yesterday's save: not ready; it may have ripened overnight). {} when any failing key is from today."""
    bad = {k: v for k, v in rest.items() if k in st and not plan.holds({k: v}, st)}
    if not bad or today is None:
        return {}
    days = [world.checked_day(g, n, k) for k in bad]
    return bad if all(d is not None and d < today for d in days) else {}


def _stale_path(g, kind, tid, st, want, make, params):
    """A stale object's reading from an earlier day may have changed: each row's `when` over those old keys (plus
    the goal's `where` on them) is a plausible state now; the first one with a path to the goal. (path, state) or
    (None, None)."""
    today = _today()
    old = {k for k in st if today is not None and (world.checked_day(g, tid, k) or today) < today}
    for r in plan.rows(kind):
        if r.get('bubble') is None:
            continue
        guess = dict(st, **want, **{k: v for k, v in r['when'].items()
                                    if k in old and not (isinstance(v, str) and ('|' in v or v.startswith(('$', '!'))))})
        p = plan.path(kind, guess, make, params)
        if p:
            return p, guess
    return None, None


def _targets(g, spec, where, working, unknown=None, stale=None):
    """Objects the goal selects; with `fresh: day`, also those failing it only by an earlier day's reading (they go
    into `stale`: visit and look, the click result stamps them fresh)."""
    base = {'kind': spec['kind']}
    if 'region' in where:
        base['region'] = where['region']
    rest = {k: v for k, v in where.items() if k != 'region'}
    strict = _strict(spec) & set(rest)
    today = _today() if spec.get('fresh') == 'day' else None
    found = []
    for n in world.query(g, base):
        st = world.state_of(g, n)
        if any(k not in st or st[k] is None for k in strict):
            if unknown is not None and _passes(g, n, {k: v for k, v in rest.items() if k not in strict}):
                unknown.add(n)
            continue
        if _passes(g, n, rest):
            found.append(n)
        elif today is not None and _stale_keys(g, n, rest, st, today):
            found.append(n)
            if stale is not None:
                stale[n] = _stale_keys(g, n, rest, st, today)
    return sorted(set(found) | {n for n in working if n in g.nodes})


def _need_input(g, spec, missing):
    """NEED_INPUT: which params are missing and the values seen for them among the goal's objects."""
    where = spec.get('where', {})
    seen = []
    for p in missing:
        key = next((k for k, v in where.items() if v == f'${p}'), None)
        fixed = {k: v for k, v in where.items() if not (isinstance(v, str) and v.startswith('$'))}
        objs = [n for n in world.query(g, {'kind': spec['kind']}) if _passes(g, n, fixed)]
        if key == 'region':
            vals = sorted({world.area_of(g, n) for n in objs} - {None})
        elif key:
            vals = sorted({str(world.state_of(g, n).get(key)) for n in objs} - {'None'})
        else:
            vals = []
        seen.append(f'{p}? (seen: {", ".join(vals) or "none"})')
    return 'NEED_INPUT ' + '; '.join(seen)


def _marker(spec, where):
    for cond, m in world.kinds().get(spec['kind'], {}).get('markers', {}).items():
        k, v = cond.split('=', 1)
        if str(where.get(k)).lower() == v.lower():
            return m
    return None


def _made(g, nid, make, params, before):
    want = plan.goal_values(dict(before, **{k: v for k, v in world.state_of(g, nid).items() if k == 'crop'}),
                            make, params)
    st = world.state_of(g, nid)
    return all(st.get(k) == v for k, v in want.items() if v != plan.SAME)


def _really_missing(save, item, out):
    """A failed pick is a missing item only when the inventory agrees; else the screen differs (vision asks)."""
    if not out.get('missing'):
        return False
    try:
        return world.inventory(save, core.WF.today_log()[0]).get(item or '', 0) < 1
    except Exception:   # noqa: BLE001
        return True


def _learn(g, out, kind, row, res):
    """A row run's proven facts -> the world, through the improvement loop's boundary (integrate.world_facts: by
    position, card values, Tara's can; the nodes keep the experience ids). The object id or None."""
    from . import integrate as I
    nid, area = I.world_facts(g, out, kind, row, _stamp())
    if out['at']:
        res['area'] = area
    return nid


def _stamp():
    try:
        return core.WF.game_stamp()
    except Exception:   # noqa: BLE001
        return None


def _ambiguous(g, row, kind, area):
    """Objects of `kind` OUTSIDE the target area that the row could act on: their bubbles look the same."""
    return [n for n in world.query(g, {'kind': kind}) if area not in g.chain(n)
            and _passes(g, n, {k: v for k, v in row['when'].items()})]


def _all_need(g, row, kind, area):
    """The world says EVERY object of `kind` in the area needs this row (all south beds empty): any of their bubbles
    in view must fit it - a prediction the frame can refute."""
    objs = world.query(g, {'kind': kind, 'region': area})
    return bool(objs) and all(_passes(g, n, row['when']) for n in objs)


def _bubble_miss(row, area, mine, res):
    """Bubbles of the area's objects in view, none fits the row the world predicts: a recorded miss (evals). Outside
    daylight icons are unreliable (D185 dusk: an empty bed read as `unplant`): stop and suggest sleeping."""
    got = sorted({str(a).split(' @')[0] for a in mine})
    key = (row['id'], tuple(got))
    if key not in res.setdefault('bubble_misses', []):
        res['bubble_misses'].append(key)
        res['surprises'].append(f'{row["id"]}: the world predicts its bubble {row["bubble"]} in {area}; seen {got}')
        try:
            import evals
            evals.record('engine', 'bubble', row['bubble'], got, False, {'row': row['id'], 'area': area,
                                                                       'light': res.get('light')})
        except Exception:   # noqa: BLE001
            pass
        N.log('predict', component='engine', what='bubble', expected=row['bubble'], got=got, hit=False,
              row=row['id'], area=area)
    if res.get('light') not in (None, 'day'):
        res['stop'] = (f'dark ({res["light"]}): the bubbles in {area} ({", ".join(got)}) contradict the world '
                       f'({row["id"]} expected); icons are unreliable outside daylight - suggest sleeping (ask the '
                       f'user), then retry in the morning')
        return True
    return False


PX_PER_UNIT = 57.6     # screen px per world unit at the usual zoom (neighbour bed bubbles 216 px for 3.75 units, D186)
OWN_PX = 140           # px: the bubble this close to a bed's expected screen point is that bed's


def screen_point(tara, obj):
    """Tara is the frame centre; the camera looks north: world +x = right, +z = up."""
    return (round(O.CENTRE[0] + (obj[0] - tara[0]) * PX_PER_UNIT), round(O.CENTRE[1] - (obj[1] - tara[1]) * PX_PER_UNIT))


BELOW_PX = 70          # px below a bed's point: the path between rows, where she stands to work it
HOPS = 2               # short walks per visit before the bed goes back to the search


def world_of(tara, pt):
    """The world point under screen point `pt` (the inverse of screen_point)."""
    return (tara[0] + (pt[0] - O.CENTRE[0]) / PX_PER_UNIT, tara[1] - (pt[1] - O.CENTRE[1]) / PX_PER_UNIT)


def _visit(g, tid, kind, res, row=None):
    """Strategy A (user D188): from her position (an event since the last walk, or the end of a short walk to a
    visible point), the target's bubble is the one at its expected screen point - whatever its kind or "!" reading
    says. Its point on screen but no bubble there -> a short walk to the ground just below it (up to HOPS), then look
    again. The bubble, or None (no position / off-screen / not there after the walks: the search takes over)."""
    from . import where
    if tid not in g.nodes:
        return None
    obj = tuple(g.nodes[tid].extra['pos'])
    hive = {O.NODE_OF.get(k) for k in O.NODE_OF if k != kind}
    for hop in range(HOPS + 1):
        src, here = where.position(far_ok=False, walk_ok=True)
        if src not in ('event', 'walk'):
            return None
        pt = screen_point(here, obj)
        if not O.on_frame(pt):
            return None
        affs = O.scan()
        near = [a for a in affs if O.d(a.pt, pt) <= OWN_PX and O.node_of_bubble(a) not in hive]
        if near:
            return min(near, key=lambda a: O.d(a.pt, pt))
        if hop == HOPS or (row is not None and any(plan.fits(row)(a) for a in affs)):
            return None   # a bubble that fits the row is in view: the search takes it, no walk
        ground = (pt[0], min(O.H_ - 60, pt[1] + BELOW_PX))
        if not O.on_frame(ground):
            return None
        c = A.click(ground, 'step')
        res['clicks'] += 1
        if c.events or A.on_card(c) or c.moved is False:   # an interaction, or she didn't move: no reckoning
            A.gameplay()
            return None
        where.walked(to=world_of(here, ground))
    return None


def _evidence(g, nid, kind, row, out, res):
    """A failed step whose card is what ANOTHER row of this kind starts with (a seed panel where Collect was
    expected): that row's `when` is the object's true state. True when applied (no question needed)."""
    screen = str(out.get('screen') or '')
    for r in plan.rows(kind):
        if r['id'] == row['id'] or not r['steps']:
            continue
        want = (r['steps'][0].get('expect') or {}).get('card')
        if want and want.lower() in screen.lower():
            st = {k: v for k, v in r['when'].items() if not (isinstance(v, str) and ('|' in v or '$' in v))}
            if nid and st:
                world._set(g, nid, dict(st, ready=False), _stamp(), 'card')
                res['surprises'].append(f'{row["id"]}: the click showed "{want}" - {nid} is {st}')
                return True
    return False


def _blind_near(kind, row, area, res):
    """No exact position, bubbles of `kind` in view, none fits the row: she is near its objects but the readings
    disagree with the world (live D188: a ready bed read as `water`, then a search walk away) - vision's start
    question beats a search walk."""
    from . import where
    if where.position(far_ok=False)[0] == 'event' or res.get('area') not in (None, area):
        return None
    own = O.NODE_OF.get(kind)
    mine = [b for b in O.scan() if O.node_of_bubble(b) == own]
    return mine if mine and not any(plan.fits(row)(b) for b in mine) else None


def finish_card(c, res):
    """A card opened by a non-step click (a walk) that the current row's first step expects (Collect for pick): the
    row finishes it instead of the walk closing it - when the crop under the click is known and not skipped
    (flowers). True when the row ran its remaining steps."""
    row = res.get('row_now')
    if not row or c.mode == 'gameplay' or not row['steps']:
        return False
    want = (row['steps'][0].get('expect') or {}).get('card')
    if not want or not any(want.lower() in t.lower() for t in c.texts):
        return False
    near = [a for a in c.before if O.d(a.pt, c.pt) <= 160]
    b = min(near, key=lambda a: O.d(a.pt, c.pt)) if near else None
    crop = (res.get('icon_of') or {}).get(tuple(b.pt)) if b else None
    if res.get('skip_names') and (crop is None or crop in res['skip_names']):
        return False
    rest = dict(row, steps=row['steps'][1:])
    out = steps.run(rest, row.get('params', {}), b)
    res.setdefault('card_runs', []).append(out)
    return bool(out['ok'])


def _reach(g, name, params, row, kind, area, res, marker, skip=frozenset()):
    """A bubble that fits the row in the target's area. Her area unknown (she walked) and look-alike objects in
    another area -> ONE question: which area is she in? (answer area=<name>)."""
    tried = res.setdefault('btried', [])
    ok = plan.fits(row)
    amb = bool(_ambiguous(g, row, kind, area))

    def icon_ok(a):   # skip_bubbles: the crop its icon shows (flowers stay for the bees, user D188)
        if not skip:
            return True
        from . import icons
        key = (a.pt, res['clicks'])
        if key not in res.setdefault('icon_cache', {}):
            res['icon_cache'][key] = icons.name_of(a)
        n = res['icon_cache'][key]
        if n is None:
            res['icon_unknown'] = a
            return False
        res.setdefault('icon_of', {})[tuple(a.pt)] = n
        return n not in skip

    def owned(a):   # the bubble belongs to the target kind when its owner is known (a hive's "!" is not a bed's)
        node = O.node_of_bubble(a)
        return node is None or L.kind_of(node) == kind

    def free(a):
        return ok(a) and owned(a) and not any(O.d(a.pt, p) < 60 for p in tried) and icon_ok(a)

    def fits(a):
        return free(a) and (res.get('area') == area or (res.get('area') is None and not amb))

    expect = _all_need(g, row, kind, area)
    own = O.NODE_OF.get(kind)

    def halt(affs):
        if res.get('area') is None and amb and any(free(a) for a in affs):
            return True
        if skip:   # a fitting bubble whose crop icon is unknown is in view: ask about it now, before any click (D188)
            for a in affs:
                if ok(a) and owned(a) and not any(O.d(a.pt, p) < 60 for p in tried):
                    icon_ok(a)
                    if res.get('icon_unknown') is a:
                        return True
        mine = [a for a in affs if O.node_of_bubble(a) == own]
        if expect and mine and res.get('area') in (None, area) and not any(fits(a) for a in affs):
            return _bubble_miss(row, area, mine, res)
        return False
    t = N.Target(name, fits, f'a {kind} in {area} whose bubble fits "{row["id"]}"', None, kind, area, area, marker)
    res['row_now'], res['skip_names'] = row, set(skip)
    res['on_card'] = lambda c: finish_card(c, res)
    res.pop('icon_unknown', None)
    a = N.search(t, res, halt=halt)
    if a is None and res['stop']:
        return None
    if a is None and res.get('icon_unknown') is not None:   # a ready bubble whose crop nobody knows: ask, never guess
        from . import icons
        b = res['icon_unknown']
        path = icons.save_crop(b)
        ask.ask('name', f'Which crop does the bubble at {b.pt[0]},{b.pt[1]} show (its icon)? Answer the crop name, '
                        f'e.g. Green Bean, Carrot or Tulip.', {'goal': name, 'params': params, 'crop_icon': path}, res)
    if a is not None and expect:
        try:
            import evals
            evals.record('engine', 'bubble', row['bubble'], str(a), True, {'row': row['id'], 'area': area})
        except Exception:   # noqa: BLE001
            pass
        N.log('predict', component='engine', what='bubble', expected=row['bubble'], got=str(a), hit=True,
              row=row['id'], area=area)
    if a is None and res.get('area') is None and amb and any(free(b) for b in O.scan()):
        areas = sorted({world.area_of(g, n) for n in _ambiguous(g, row, kind, area)} | {area})
        ask.ask('name', f'Tara (the frame centre) sees {kind} bubbles that fit "{row["id"]}", but they look the same '
                        f'in {", ".join(areas)}. Which area is she in? Answer area=<one of {", ".join(areas)}>.',
                {'goal': name, 'params': params, 'area_question': True}, res)
    return a


def _ask_click(name, params, what, area, res, row=None):
    q = (f'Goal {name}: no bubble for {what} is in reach. Tara is the magenta circle (always the frame centre). Give '
         f'the grid cell of the nearest {what} in {area}, on the object (not on a bubble), or of free ground toward '
         f'it if it is off-screen. Answer none if there is none left.')
    ask.ask('click', q, {'goal': name, 'params': params, 'node': area}, res)


def _wants(row):
    """What vision looks for to start a row: its bubble's sub-icon (ready = an orange "!") in words."""
    b = row.get('bubble') or {}
    return ' whose bubble shows an orange "!" (not a flower)' if b.get('ready') else (
        ' whose bubble shows a blue water drop' if b.get('drop') else '')


def _ask_start(name, params, kind, row, area, res):
    """No exact position (she walked; no event since): vision's start question (interaction laws: the click point of
    the first node) - its click logs an event, and from that exact position the beds go one by one (strategy A)."""
    q = (f'Goal {name}: Tara is the magenta circle (the frame centre). Give the grid cell ON THE BUBBLE of the nearest '
         f'{kind}{_wants(row)} in {area}; if none is in view, a cell of free ground toward the {area}. Answer none if '
         f'no such {kind} is left.')
    ask.ask('click', q, {'goal': name, 'params': params, 'node': area, 'row': row['id']}, res)


def _subgoal(g, key, value, name, params, res):
    """Restore `key` (e.g. Tara.can = full) with the table's row that makes it: reach its object, run it."""
    row = next((r for r in plan.rows() if r['effect'].get(key) == value and r.get('bubble') is not None), None)
    if row is None:
        res['stop'] = f'needs {key}={value}: no action known to make it'
        return False
    t = N.Target(f'{name}:{row["id"]}', plan.fits(row), f'the {row["kind"]}', None, row['kind'],
                 world.area_of(g, row['kind']) or row['kind'], row['kind'] if row['kind'] in g.nodes else row['kind'])
    a = N.search(t, res)
    if a is None:
        _ask_click(name, params, f'the {row["kind"]} ({row["id"]})', 'view', res)
    out = steps.run(row, {}, a)
    res['clicks'] += out['clicks']
    _learn(g, out, row['kind'], row, res)
    plan.count(row['id'], out['ok'])
    res['subgoals'] += 1
    if out['ok'] and 'Tara' in g.nodes and key.startswith('Tara.'):
        g.set_state('Tara', key.split('.', 1)[1], value, _stamp(), 'event')
    return out['ok']


def _answer(g, name, params, answer, res):
    pend = ask.take_answer(name) or {'kind': 'click'}
    if str(answer).strip().lower() == 'none':
        res['stop'] = 'vision: none left'
        return
    if pend['kind'] == 'click':
        try:
            pt = ask.parse_point(answer)
        except ValueError as e:
            raise core.Failed(f'answer rejected: {e}. Answer a grid cell A1-X16, or none') from None
        c = A.click(pt, 'point', here=res.get('area'))
        res['clicks'] += 1
        if c.at:
            world.place(g, c.node.split('@')[0] if c.node else 'Object', c.at, c.events, stamp=_stamp())
            res['area'] = world.area_of(g, c.at)
        row = next((r for r in plan.rows() if r['id'] == pend.get('row')), None)
        want = ((row or {}).get('steps') or [{}])[0].get('expect', {}).get('card') if row else None
        if want and c.mode != 'gameplay' and any(want.lower() in t.lower() for t in c.texts):
            out = steps.run(dict(row, steps=row['steps'][1:]), row.get('params', {}), None)   # vision chose the bed
            res['clicks'] += out['clicks']
            nid = _learn(g, out, row['kind'], row, res)
            plan.count(row['id'], out['ok'])
            if out['ok'] and nid:
                res['done'].append(nid)
                ask.progress(name)
        A.gameplay()
    elif pend['kind'] == 'button':
        rs = plan.rows()
        for r in rs:
            if r['id'] == pend.get('row') and pend.get('step') is not None:
                r['steps'][pend['step']] = button_step(answer, r['steps'][pend['step']])
                r['source'] = f'{r["source"]}; step {pend["step"]} from vision ({answer})'
        plan.save_rows(rs)
        res['learned'].append(f'{pend.get("row")}[{pend.get("step")}] press {answer}')
    else:
        _answer_name(g, pend, answer, res)


def button_step(answer, old):
    """Vision's `button` answer -> the step that replaces the failed one (its expectation kept): `space`, a grid
    cell (a card or a button without text) or the exact on-screen text."""
    a = str(answer).strip()
    if a.lower() in ('space', 'key:space'):
        step = {'do': 'press_space'}
    else:
        try:
            ask.parse_point(a)
            step = {'do': 'click_cell', 'arg': a.upper()}
        except ValueError:
            step = {'do': 'press', 'arg': a}
    if old.get('expect'):
        step['expect'] = old['expect']
    return step


def _answer_name(g, pend, answer, res):
    """Vision named what an explored click changed ('key=value'): a learned row, applied to the clicked object; or
    which area she is in ('area=<name>')."""
    from .affordances import Affordance
    if pend.get('crop_icon'):   # vision named a crop icon: store it, the next bubble like it is known
        from . import icons
        if icons.learn_file(pend['crop_icon'], str(answer).strip()):
            res['learned'].append(f'crop icon: {answer}')
        return
    if pend.get('area_question') or str(answer).strip().startswith('area='):
        a = str(answer).split('=', 1)[-1].strip()
        if a in g.nodes:
            res['area'] = a
        else:
            res['notes'].append(f'area answer unknown: {answer}')
        return
    lr = pend.get('learn') or {}
    b = lr.get('bubble') or ['?', False, False, [0, 0]]
    row = L.new_row(lr.get('kind'), {}, Affordance(b[0], None, tuple(b[3]), False, 0.0, b[1], b[2]),
                    {'events': lr.get('events', [])}, answer=answer)
    if row is None:
        res['notes'].append(f'name answer not a key=value: {answer}')
        return
    row = L.add_row(row)
    res['learned'].append(row['id'])
    if lr.get('nid') in g.nodes:
        world._set(g, lr['nid'], row['effect'], _stamp(), 'vision')


def _assumed(st, where):
    """The goal's literal `where` values for keys the object never had (it was selected as maybe having them)."""
    return {k: v for k, v in where.items()
            if k not in st and k != 'region'
            and (not (isinstance(v, str) and ('|' in v or v.startswith('$'))) or str(v).startswith('!'))}


def _only_maybes(g, targets, where, res):
    """Every target left was selected only because its state is unknown (or from an earlier day), and no fitting
    bubble shows: done."""
    stale = res.get('stale') or {}
    from . import where as WH
    src, here = WH.position(far_ok=False)
    if src != 'event' or not all(O.on_frame(screen_point(here, tuple(g.nodes[n].extra['pos']))) for n in targets):
        return False   # she can't see where they are: no conclusion (live D188: 'done' with 7 ready beds away)
    if targets and all(_assumed(world.state_of(g, n), where) or n in stale for n in targets):
        res['stop'] = f'done: no fitting bubble left in view ({len(targets)} with unknown state)'
        return True
    return False


def _explore(g, tid, kind, area, where, name, params, res, working, make):
    """No row takes the target where the goal wants: click one bubble that agrees with the goal's sub-icons (ready)
    in the target's area and learn the row from the game's answer (frame change / event); vision names a change the
    frame doesn't show. 'stop' | None."""
    tried = res.setdefault('btried', [])

    def fits(a):
        return ((where.get('ready') is not True or a.ready) and res.get('area') in (None, area)
                and not any(O.d(a.pt, p) < 60 for p in tried))
    t = N.Target(f'{name}:explore', fits, f'a {kind} in {area}', None, kind, area, area, None)
    a = N.search(t, res)
    if a is None:
        if res['stop'] or _only_maybes(g, [n for n in _targets(g, {'kind': kind}, where, working)
                                           if n not in res['skip']], where, res):
            return 'stop'
        _ask_click(name, params, f'a {kind} (no known action yet)', area, res)
    row = {'id': 'explore', 'kind': kind, 'when': {}, 'bubble': {}, 'steps': [{'do': 'click_bubble'}], 'effect': {}}
    out = steps.run(row, {}, a)
    res['clicks'] += out['clicks']
    nid = _learn(g, out, kind, row, res)
    A.gameplay()
    if nid is None or g.nodes[nid].kind != kind:
        tried.append(a.pt)
        res['notes'].append(f'explored @{a.pt}: {out["events"] or "no event"} (not a {kind})')
        return None
    new = L.new_row(kind, world.state_of(g, nid), a, out)
    if new is None:
        ask.ask('name', f'Tara clicked a {kind} bubble ({a.kind}{" +ready" if a.ready else ""}'
                        f'{" +drop" if a.drop else ""}); the game logged {out["events"] or "nothing"}. What changed on '
                        f'the {kind}? Answer key=value (e.g. ready=false), or none.',
                {'goal': name, 'params': params,
                 'learn': {'kind': kind, 'nid': nid, 'events': out['events'],
                           'bubble': [a.kind, bool(a.drop), bool(a.ready), list(a.pt)]}}, res)
    row = L.add_row(new)
    res['learned'].append(row['id'])
    world._set(g, nid, row['effect'], _stamp(), 'event')
    ask.progress(name)
    res['btried'].clear()
    if nid not in working:
        working.append(nid)
    if _made(g, nid, make, params, world.state_of(g, nid)) and nid not in res['done']:
        res['done'].append(nid)
    return None


def _lookalikes(g):
    """Frame node names (kinds.json `node`) of kinds whose objects stand in more than one area: the frame can't tell
    which one she is at."""
    out = set()
    for k, v in world.kinds().items():
        if v.get('node') and len({world.area_of(g, n) for n in world.query(g, {'kind': k})}) > 1:
            out.add(v['node'])
    return out


def _open_graph():
    from objects import graph as OG
    g = OG.Graph()
    g.load(L.graph_path())
    L.MEMORY['graph'] = g
    return g


def achieve(goal, answer=None, max_clicks=MAX_CLICKS, **params):
    """Reach the goal (a library name or a raw {kind, where, make} query) on every object its filter selects.
    Returns {'goal', 'done', 'left', 'clicks', 'vision', 'subgoals', 'surprises', 'learned', 'stop', ...};
    raises NeedVision with ONE question (answer by calling again with answer=...)."""
    name, spec = _goal(goal)
    W = core.WF
    res = N.new_res(name)
    res.update(goal=name, subgoals=0, learned=[], surprises=[], area=None, skip=[], fails={}, btried=[])
    g = _open_graph()
    try:
        O.check_language()
        A.gameplay()
        if ask.late(res):
            return res
        r = ask.rain()
        if r:
            res['stop'] = f'rain ({r} today): no chores in the rain for now (user D187) - ask the user, try a dry day'
            return res
        if spec.get('light') and res.get('light') and res['light'] != spec['light']:
            res['stop'] = (f'dark ({res["light"]}): {name} reads bubble icons, reliable only in daylight - suggest '
                           f'sleeping (ask the user), then retry in the morning')
            return res
        _, save = W.read_save()
        world.refresh(g, save, W.today_log()[0])
        tp = world.tara_pos(g)
        res['area'] = world.area_of(g, tp) if tp else None
        missing = [p for p in spec.get('required', []) if p not in params]
        if missing:
            res['stop'] = f'NEED_INPUT {name}: ' + _need_input(g, spec, missing)[len('NEED_INPUT '):]
            return res
        region = _where(spec, params).get('region')
        if region and not (region in g.nodes and g.nodes[region].type == 'region'):
            res['stop'] = (f'NEED_INPUT {name}: ' + _need_input(g, spec, ['region'])[len('NEED_INPUT '):]
                           + f' - {region!r} is not an area')
            return res
        res['lookalike'] = _lookalikes(g)
        from . import where as WH
        if len(WH.pairs()) >= 2 and WH.fit() is None:   # the map can't place her: say so, never a silent fallback
            res['notes'].append(f'map calibration unusable ({len(WH.pairs())} pairs disagree > {WH.MAX_ERR} units): '
                                f'far navigation has only the map compass')
        if answer is not None:
            _answer(g, name, params, answer, res)
        _loop(g, name, spec, params, save, max_clicks, res)
        return res
    finally:
        res['left'] = len(_targets(g, spec, _where(spec, params), [])) if 'kind' in spec else None
        n = max(1, len(res['done']))
        res['clicks_per_target'] = round(res['clicks'] / n, 2)
        res['vision_per_target'] = round(res['vision'] / n, 2)
        res['surprises'] = res['surprises'] + list(L.SURPRISES)
        try:
            res['learned'] += [f'{c[0]} {c[1]}[{c[2]}] {c[3]}' for c in L.settle_rows()]
        except Exception:   # noqa: BLE001 (the table never breaks play)
            pass
        try:
            res['gaps'] = I.settle()   # repeated unresolved misses -> gap bundles (offline code factory)
        except Exception:   # noqa: BLE001
            res['gaps'] = []
        try:
            g.save(L.graph_path())
        except OSError:
            pass
        L.MEMORY['graph'] = None
        LAST.clear()
        LAST.update(res)
        _log(res)


def summary(res):
    """One line for the agent: done/left, clicks, vision, sub-goals, learned rows, surprises, stop."""
    return (f"{res['goal']}: done {len(res['done'])}, left {res.get('left')}, clicks {res['clicks']}, "
            f"vision {res['vision']}, sub-goals {res['subgoals']}, per target: clicks {res.get('clicks_per_target')} "
            f"vision {res.get('vision_per_target')}"
            + (f", learned {res['learned']}" if res['learned'] else '')
            + (f", surprises {res['surprises'][:4]}" if res['surprises'] else '')
            + (f", notes {res['notes'][-3:]}" if res['notes'] else '')
            + f", stop: {res['stop']}")


def _log(res):
    try:
        core.WF.run_log('engine', goal=res['goal'], done=len(res['done']), left=res.get('left'), clicks=res['clicks'],
                        vision=res['vision'], subgoals=res['subgoals'], stop=res['stop'],
                        clicks_per_target=res.get('clicks_per_target'), vision_per_target=res.get('vision_per_target'),
                        surprises=[str(s) for s in res['surprises']][:6], learned=res['learned'])
    except Exception:   # noqa: BLE001
        pass


def _loop(g, name, spec, params, save, max_clicks, res):
    W, kind, make = core.WF, spec['kind'], spec.get('make', {})
    where = _where(spec, params)
    working = []
    while not res['stop']:
        if res['clicks'] >= max_clicks:
            res['stop'] = f'click cap {max_clicks}'
            break
        if res['clicks'] and ask.late(res):
            break
        unknown, stale = set(), {}
        targets = [n for n in _targets(g, spec, where, working, unknown, stale) if n not in res['skip']]
        res['stale'] = stale
        if unknown and not any('unknown' in n_ for n_ in res['notes']):
            res['notes'].append(f'{len(unknown)} matching objects have an unknown {", ".join(sorted(_strict(spec)))} '
                                f'(unknown crop/value: not acted on): {sorted(unknown)[:4]}')
        working = [n for n in working if not _made(g, n, make, params, world.state_of(g, n))]
        targets = [n for n in targets if n in working or n in stale
                   or not _made(g, n, make, params, world.state_of(g, n))]
        if not targets:
            res['stop'] = 'done: query empty' if not res['skip'] else f'left: {len(res["skip"])} skipped ({res["notes"][-3:]})'
            break
        here = world.tara_pos(g)
        tid = min(targets, key=lambda n: math.dist(here, tuple(g.nodes[n].extra['pos'])) if here else 0)
        st, area = world.state_of(g, tid), world.area_of(g, tid)
        assumed = _assumed(st, where)
        p = plan.path(kind, dict(st, **assumed), make, params)
        if tid in stale:   # an earlier day's reading (user D188): visit and look, as if it were what the goal wants
            p, _ = _stale_path(g, kind, tid, dict(st, **assumed), stale[tid], make, params)
            if not p:
                res['skip'].append(tid)
                res['notes'].append(f'{tid}: stale {stale[tid]}, no row reaches {make} from it')
                continue
        if p is None:   # no known action: explore one fitting bubble, learn the row from what the game shows
            if _explore(g, tid, kind, area, where, name, params, res, working, make) == 'stop':
                break
            continue
        if not p:
            res['skip'].append(tid)
            res['notes'].append(f'{tid}: already {make} but still selected by {where}')
            continue
        t = p[0]
        if any(isinstance(s.get('arg'), str) and '$' in s['arg'] for s in t['steps']):
            res['skip'].append(tid)
            res['notes'].append(f'{tid}: {t["id"]} needs a value nobody gave ({t["steps"]})')
            continue
        need = t.get('needs') or {}
        item = need.get('item')
        if item and world.inventory(save, W.today_log()[0]).get(item, 0) < 1:
            res['stop'] = f'missing {item}'
            break
        for k, v in need.items():
            if k.startswith('Tara.') and g.state_value('Tara', k.split('.', 1)[1]) not in (None, v):
                if not _subgoal(g, k, v, name, params, res):
                    res['stop'] = res['stop'] or f'sub-goal {k}={v} failed'
        if res['stop']:
            break
        skip_names = _skip_names(spec, params)
        a = None if tid in res.setdefault('visit_off', set()) else _visit(g, tid, kind, res, t)
        visited = a is not None
        if a is not None and skip_names:   # the crop its icon shows: flowers stay; an unknown icon is asked now
            from . import icons
            crop = icons.name_of(a)
            if crop is None:
                path = icons.save_crop(a)
                ask.ask('name', f'Which crop does the bubble at {a.pt[0]},{a.pt[1]} show (its icon)? Answer the crop '
                                f'name, e.g. Green Bean, Carrot or Tulip.',
                        {'goal': name, 'params': params, 'crop_icon': path}, res)
            res.setdefault('icon_of', {})[tuple(a.pt)] = crop
            if crop in skip_names:
                g.set_state(tid, 'crop', crop, _stamp(), 'icon')
                res['skip'].append(tid)
                res['notes'].append(f'{tid}: {crop} stays (flower)')
                continue
        blind = None if a is not None or res.get('asked_start') else _blind_near(kind, t, area, res)
        if blind:
            res['asked_start'] = True
            if _bubble_miss(t, area, blind, res):   # recorded; at dusk it stops (icons unreliable)
                break
            _ask_start(name, params, kind, t, area, res)
        if a is None:
            a = _reach(g, name, params, t, kind, area, res, _marker(spec, where), skip_names)
        runs = res.pop('card_runs', [])
        for out in runs:   # a card the row finished during a walk: its events update the world like a step's
            res['clicks'] += out['clicks']
            nid = _learn(g, out, kind, t, res)
            plan.count(t['id'], out['ok'])
            if nid and out['ok'] and nid not in working:
                working.append(nid)
            if nid and out['ok'] and _made(g, nid, make, params, world.state_of(g, nid)) and nid not in res['done']:
                res['done'].append(nid)
        if runs and a is None:
            continue
        if a is None:
            if res['stop'] or _only_maybes(g, targets, where, res):
                break
            _ask_click(name, params, f'a {kind} that needs "{t["id"]}"', area, res)
        out = steps.run(t, t['params'], a)
        res['clicks'] += out['clicks']
        if out['ok'] and not out['at'] and out['events']:   # the event names no position: it was the target (surprise)
            out['at'], out['kind'] = tuple(g.nodes[tid].extra['pos']), kind
            res['surprises'].append(f'{t["id"]}: no position in the event lines {out["events"]}; counted on {tid}')
        nid = _learn(g, out, kind, t, res)
        crop = (res.get('icon_of') or {}).get(tuple(a.pt))
        if nid and crop:   # the icon said which crop this bed holds (the save never does)
            g.set_state(nid, 'crop', crop, _stamp(), 'icon')
        plan.count(t['id'], out['ok'])
        if (t.get('bubble') or {}).get('ready') and out.get('img0') is not None:   # label the bubble's truth
            if out['ok'] or out.get('failed_step') not in (None, 0):
                L.save_truth(out['img0'], out.get('bubble_pt'), f'{t["id"]}: {out["events"]}', ready=True)
            elif L.card_state(str(out.get('screen') or '').split(' / ')):
                L.save_truth(out['img0'], out.get('bubble_pt'), f'{t["id"]}: {out.get("screen")}', ready=False)
        if not out['ok'] and _evidence(g, nid or tid, kind, t, out, res):
            for x in out.get('exps') or ():
                I.resolved(x)   # another row's card explained the miss: no gap
            A.gameplay()
            res['btried'].append(a.pt)
            continue
        info = L.card_state(str(out.get('screen') or '').split(' / ')) if not out['ok'] else {}
        if info:   # the click showed the object's info card (2 days remaining): evidence, not a prompt - no question
            for x in out.get('exps') or ():
                I.resolved(x)
            res['surprises'].append(f'{t["id"]}: the bubble led to its info card {info} (not what the row expects)')
            A.gameplay()
            res['btried'].append(a.pt)
            continue
        if not out['ok'] and (out.get('why') or out.get('screen')) and not _really_missing(save, item, out):
            st = t['steps'][out['failed_step']]
            I.gap(out.get('exps') or [], f'row {t["id"]} step {out["failed_step"]} ({st["do"]} {st.get("arg", "")}): '
                                        f'no step the table knows moves this screen on ({out.get("screen") or "?"})',
                  'table')   # the table can't represent the next step: a capability gap for the code factory
            ask.ask('button', f'Goal {name}: step {out["failed_step"]} of "{t["id"]}" ({st["do"]} {st.get("arg", "")}) '
                              f'did not work ({str(out.get("why") or out["surprises"])[:120]}). On screen: '
                              f'{out.get("screen") or "?"}. '
                              f'What does Tara do next on this screen? Answer the exact on-screen text to press, '
                              f'space, or the grid cell of the card/button.',
                    {'goal': name, 'params': params, 'row': t['id'], 'step': out['failed_step']}, res)
        if nid and nid not in working and nid in g.nodes and g.nodes[nid].kind == kind:
            working.append(nid)
        if out['ok']:
            res['btried'].clear()
            ask.progress(name)
            if nid and _made(g, nid, make, params, world.state_of(g, nid)) and nid not in res['done']:
                res['done'].append(nid)
            continue
        if out['missing']:   # the item is really gone (the inventory agrees)
            res['stop'] = f'missing {item or out["missing"]}'
            break
        res['surprises'] += [f'{t["id"]}[{s[0]}] {s[1]}: expected {s[2]!r}, got {str(s[3])[:80]!r}' for s in out['surprises']]
        A.gameplay()
        if not out['events']:
            res['btried'].append(a.pt)
        if visited:   # the bubble at the bed's point was not its bubble (zoom, geometry): search normally for it now
            res['visit_off'].add(tid)
        res['fails'][tid] = res['fails'].get(tid, 0) + 1
        if res['fails'][tid] >= FAILS:
            res['skip'].append(tid)
            res['notes'].append(f'{tid}: {FAILS} failed attempts')


def parse_cli(args):
    """`./wf achieve <goal|json> [k=v ...] [answer=X]` -> (goal, params, answer); `a,b` values become lists."""
    goal = args[0]
    if goal.strip().startswith('{'):
        goal = json.loads(goal)
    params, answer = {}, None
    for a in args[1:]:
        k, _, v = a.partition('=')
        if k == 'answer':
            answer = v
        else:
            params[k] = v.split(',') if ',' in v else v
    return goal, params, answer
