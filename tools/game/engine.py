"""ENGINE: one loop for every goal (spec 2026-11-03 §6). `achieve(goal, answer=None, **params)`.

stops (language, clock) -> world.refresh (save + today's log) -> targets = the goal's filter (+ objects already being
worked on) -> nearest target -> plan.path (table BFS) -> its first row: needs (an item: stop when missing; Tara's can:
a sub-goal from the table) -> nav.search for a bubble that fits the row in the target's area -> steps.run -> the
events' positions update the world -> repeat. Done = the filter is empty. Nothing found -> ONE vision question
(ask.py). No goal or kind names in code: goals.json, actions.json, kinds.json."""
import json
import math
import os

from . import act as A, ask, core, learn as L, nav as N, observe as O, plan, steps, world

GOALS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'goals.json')
MAX_CLICKS = 40
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


def _where(spec, params):
    """The goal's filter with $params; a list param becomes alternatives ('Carrot|Tulip')."""
    out = {}
    for k, v in spec.get('where', {}).items():
        if isinstance(v, str) and v.startswith('$'):
            p = params.get(v[1:])
            if p is None:
                continue
            v = '|'.join(p) if isinstance(p, (list, tuple)) else p
        out[k] = v
    return out


def _passes(g, nid, where):
    """`where` on an object: a state key the object never had passes (memory is a hint, never a gate - law 6)."""
    st = world.state_of(g, nid)
    return plan.holds({k: v for k, v in where.items() if k in st}, st)


def _strict(spec):
    """`where` keys bound from a goal parameter (`crop: $crops`): the user named the value, so it must be KNOWN on
    the object - an unknown one is never assumed (D187: harvest carrots, the save has no crop type)."""
    return {k for k, v in spec.get('where', {}).items() if isinstance(v, str) and v.startswith('$') and k != 'region'}


def _targets(g, spec, where, working, unknown=None):
    base = {'kind': spec['kind']}
    if 'region' in where:
        base['region'] = where['region']
    rest = {k: v for k, v in where.items() if k != 'region'}
    strict = _strict(spec) & set(rest)
    found = []
    for n in world.query(g, base):
        st = world.state_of(g, n)
        if any(k not in st or st[k] is None for k in strict):
            if unknown is not None and _passes(g, n, {k: v for k, v in rest.items() if k not in strict}):
                unknown.add(n)
            continue
        if _passes(g, n, rest):
            found.append(n)
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
    """A run's events -> the world (by position); stored card values; where she is now. The object id or None."""
    nid = None
    if out['at']:
        nid = world.place(g, out['kind'] or kind, out['at'], out['events'], stamp=_stamp(),
                          params=row.get('params'), lines=out['lines'])
        res['area'] = world.area_of(g, nid)
    for k, v in out['stored'].items():
        if nid and v:
            g.set_state(nid, k, v, _stamp(), 'card')
    if not out['at']:   # an event without a position (Tara's can): its effects still count
        for ev in out['events']:
            for k, v in plan.effects_of_event(ev).items():
                if k.startswith('Tara.') and 'Tara' in g.nodes:
                    g.set_state('Tara', k.split('.', 1)[1], v, _stamp(), 'event')
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


def _reach(g, name, params, row, kind, area, res, marker):
    """A bubble that fits the row in the target's area. Her area unknown (she walked) and look-alike objects in
    another area -> ONE question: which area is she in? (answer area=<name>)."""
    tried = res.setdefault('btried', [])
    ok = plan.fits(row)
    amb = bool(_ambiguous(g, row, kind, area))

    def free(a):
        return ok(a) and not any(O.d(a.pt, p) < 60 for p in tried)

    def fits(a):
        return free(a) and (res.get('area') == area or (res.get('area') is None and not amb))

    expect = _all_need(g, row, kind, area)
    own = O.NODE_OF.get(kind)

    def halt(affs):
        if res.get('area') is None and amb and any(free(a) for a in affs):
            return True
        mine = [a for a in affs if O.node_of_bubble(a) == own]
        if expect and mine and res.get('area') in (None, area) and not any(fits(a) for a in affs):
            return _bubble_miss(row, area, mine, res)
        return False
    t = N.Target(name, fits, f'a {kind} in {area} whose bubble fits "{row["id"]}"', None, kind, area, area, marker)
    a = N.search(t, res, halt=halt)
    if a is None and res['stop']:
        return None
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


def _ask_click(name, params, what, area, res):
    q = (f'Goal {name}: no bubble for {what} is in reach. Tara is the magenta circle (always the frame centre). Give '
         f'the grid cell of the nearest {what} in {area}, on the object (not on a bubble), or of free ground toward '
         f'it if it is off-screen. Answer none if there is none left.')
    ask.ask('click', q, {'goal': name, 'params': params, 'node': area}, res)


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
        c = A.click(pt, 'point')
        res['clicks'] += 1
        if c.at:
            world.place(g, c.node.split('@')[0] if c.node else 'Object', c.at, c.events, stamp=_stamp())
            res['area'] = world.area_of(g, c.at)
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
            if k not in st and k != 'region' and not (isinstance(v, str) and ('|' in v or v.startswith('$')))}


def _only_maybes(g, targets, where, res):
    """Every target left was selected only because its state is unknown, and no fitting bubble shows: done."""
    if targets and all(_assumed(world.state_of(g, n), where) for n in targets):
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
    res.update(goal=name, subgoals=0, learned=[], surprises=[], area=None, skip=[], fails={})
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
            g.save(L.graph_path())
        except OSError:
            pass
        L.MEMORY['graph'] = None
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
        unknown = set()
        targets = [n for n in _targets(g, spec, where, working, unknown) if n not in res['skip']]
        if unknown and not any('unknown' in n_ for n_ in res['notes']):
            res['notes'].append(f'{len(unknown)} matching objects have an unknown {", ".join(sorted(_strict(spec)))} '
                                f'(unknown crop/value: not acted on): {sorted(unknown)[:4]}')
        working = [n for n in working if not _made(g, n, make, params, world.state_of(g, n))]
        targets = [n for n in targets if n in working or not _made(g, n, make, params, world.state_of(g, n))]
        if not targets:
            res['stop'] = 'done: query empty' if not res['skip'] else f'left: {len(res["skip"])} skipped ({res["notes"][-3:]})'
            break
        here = world.tara_pos(g)
        tid = min(targets, key=lambda n: math.dist(here, tuple(g.nodes[n].extra['pos'])) if here else 0)
        st, area = world.state_of(g, tid), world.area_of(g, tid)
        assumed = _assumed(st, where)
        p = plan.path(kind, dict(st, **assumed), make, params)
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
        a = _reach(g, name, params, t, kind, area, res, _marker(spec, where))
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
        plan.count(t['id'], out['ok'])
        if not out['ok'] and (out.get('why') or out.get('screen')) and not _really_missing(save, item, out):
            st = t['steps'][out['failed_step']]
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
