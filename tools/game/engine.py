"""ENGINE: one loop for every goal (spec 2026-11-03 §6). `achieve(goal, answer=None, **params)`.

stops (language, clock) -> world.refresh (save + today's log) -> targets = the goal's filter (+ objects already being
worked on) -> nearest target -> plan.path (table BFS) -> its first row: needs (an item: stop when missing; Tara's can:
a sub-goal from the table) -> nav.search for a bubble that fits the row in the target's area -> steps.run -> the
events' positions update the world -> repeat. Done = the filter is empty. Nothing found -> ONE vision question
(ask.py). No goal or kind names in code: goals.json, actions.json, kinds.json."""
import json
import math
import os

from . import act as A, ask, core, integrate as I, learn as L, nav as N, observe as O, plan, steps, ui, world

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
        # CLI selectors use a natural plural (`crops=Tulip`) to override a
        # reusable default filter such as `crop: !$flowers`.
        if f'{k}s' in params:
            v = params[f'{k}s']
        neg = isinstance(v, str) and v.startswith('!$')
        if isinstance(v, str) and (v.startswith('$') or neg):
            p = _param(v.lstrip('!$'), params)
            if p is None:
                continue
            v = ('!' if neg else '') + ('|'.join(p) if isinstance(p, (list, tuple)) else p)
        out[k] = v
    # A caller may scope any library goal to a named region even when the
    # reusable goal definition has no region placeholder of its own.
    if params.get('region') is not None and 'region' not in out:
        out['region'] = params['region']
    return out


def _skip_names(spec, params):
    """Bubble values to leave alone (skip_bubbles: {crop: $flowers}): a set of names, or empty."""
    out = set()
    for key, v in (spec.get('skip_bubbles') or {}).items():
        p = _param(str(v).lstrip('$'), params) if str(v).startswith('$') else v
        out |= set(p if isinstance(p, (list, tuple)) else [p]) - {None}
        plural = f'{key}s'
        if plural in params:
            chosen = params[plural]
            out -= set(chosen if isinstance(chosen, (list, tuple)) else [chosen])
            continue
        requested = (spec.get('where') or {}).get(key)
        if isinstance(requested, str) and requested.startswith('$'):
            name = requested.lstrip('$')
            if name in params:  # an explicit request overrides the default preservation policy
                chosen = params[name]
                out -= set(chosen if isinstance(chosen, (list, tuple)) else [chosen])
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


BUBBLE_R = 4.0        # world units: farther shows no bubble (D186 bubbles at 3.75; D189 the far row at ~4.4: none)
PX_PER_UNIT = 57.6     # screen px per world unit at the usual zoom (neighbour bed bubbles 216 px for 3.75 units, D186)
OWN_PX = 140           # px: the bubble this close to a bed's expected screen point is that bed's


def screen_point(tara, obj):
    """Tara is the frame centre; the camera looks north: world +x = right, +z = up."""
    return (round(O.CENTRE[0] + (obj[0] - tara[0]) * PX_PER_UNIT), round(O.CENTRE[1] - (obj[1] - tara[1]) * PX_PER_UNIT))


def world_of(tara, pt):
    """The world point under screen point `pt` (the inverse of screen_point)."""
    return (tara[0] + (pt[0] - O.CENTRE[0]) / PX_PER_UNIT, tara[1] - (pt[1] - O.CENTRE[1]) / PX_PER_UNIT)


def _guard_walk_cells(avoid, toward=None, limit=6):
    """Grid cells that pass the same non-model geometry guard as a `walk:` answer.

    They are only candidates: vision still rejects fences/water/cards.  Ranking near the requested target keeps the
    cheap model from inventing a cell on Tara or a bed when a legal dirt waypoint is already known.
    """
    out = []
    for col in range(ask.COLS):
        for row in range(4, 15):   # world view, excluding HUD and bottom letterbox
            cell = f'{chr(65 + col)}{row + 1}'
            pt = ask.parse_point(cell)
            if O.d(pt, O.CENTRE) < N.SELF_PX:
                continue
            if any(O.d(pt, tuple(p)) < N.FREE_GAP for p in avoid):
                continue
            score = O.d(pt, toward) if toward is not None else O.d(pt, O.CENTRE)
            out.append((score, O.d(pt, O.CENTRE), cell))
    return [cell for _, _, cell in sorted(out)[:limit]]


def _other_kinds(kind, row):
    """Bubble kinds that belong to OTHER rows of `kind` (the planting icon = the plant row): never this row's bubble
    (live D189: the pick clicked the just-harvested bed's planting icon again and again)."""
    if row is None:
        return set()
    bubble = row.get('bubble') or {}
    # A sub-icon is the discriminator even when the main crop icon is also
    # used by another row: `plant_growing +ready` is ripe, and
    # `plant_growing +drop` needs water/wilt handling.
    if 'ready' in bubble or 'drop' in bubble:
        return set()
    out = set()
    for r in plan.rows(kind):
        k = (r.get('bubble') or {}).get('kind')
        if r['id'] != row['id'] and k:
            out |= set(str(k).split('|'))
    return out - set(str((row.get('bubble') or {}).get('kind') or '').split('|'))


def _proven(g, a, res):
    """The bubble sits at the predicted point of a bed already proven this call (picked, or shown not ready)."""
    from . import where
    src, here = where.position(far_ok=False, walk_ok=True)
    if src not in ('event', 'walk'):
        return False
    return any(O.d(a.pt, screen_point(here, tuple(g.nodes[n].extra['pos']))) <= 60
               for n in res.get('tried_nodes', ()) if n in g.nodes)


def _read_bubble(g, tid, a, row, res):
    """The bubble at a bed's point is a fresh reading of that bed (user D189: "the issue is in thinking 'I'm at ready
    beds' or 'I don't know where the ready beds are'"): its crop (wave 2) and, when wave 1 is sure, its badge - none
    or drop = not ready now. True when the reading says the row's bubble is not there (move on, no click)."""
    stamp = _stamp()
    if getattr(a, 'icon', None):
        g.set_state(tid, 'crop', a.icon, stamp, 'bubble')
    badge = getattr(a, 'badge', None)
    if badge in ('none', 'drop') and (row or {}).get('bubble', {}).get('ready'):
        g.set_state(tid, 'ready', False, stamp, 'bubble')
        res.setdefault('tried_nodes', set()).add(tid)
        res.setdefault('notes', []).append(f'{tid}: seen not ready ({badge})')
        return True
    return False


NAVIGATION_EVENTS = {'complete', 'trigger_startday_events'}  # doorway/day-start ambience, not an object action
NEUTRAL_EVENTS = NAVIGATION_EVENTS | {'plant', 'plant_growing'}  # panel opened; a crop's info card


def red_flag(c, res):
    """An event no row of this goal can log (watering during a harvest, live D189): a red flag - the call stops at
    once, a gap bundle for the code factory (user D189: "yes, it's already red flag"). True when raised."""
    red, allowed = res.get('red_events'), res.get('allowed_events')
    if red is None and allowed is None:
        return False
    bad = sorted({e for e in (c.events or ()) if e not in NEUTRAL_EVENTS
                  and (e in red if red is not None else e not in allowed)})
    if not bad:
        return False
    res['stop'] = (f'RED FLAG: the click @{c.pt[0]},{c.pt[1]} ({c.what}) logged {bad}, which no row of '
                   f'{res.get("goal")} logs - stopped')
    res.setdefault('notes', []).append(res['stop'])
    I.gap([getattr(c, 'exp', None)], res['stop'], 'nav' if c.what in ('step', 'explore', 'soil') else 'act')
    return True


def _row_events(r):
    out = set(plan._events_of(r))
    for s in r.get('steps', []):
        ev = (s.get('expect') or {}).get('events')
        if isinstance(ev, list):
            for alt in ev:
                out |= set(alt.split('|'))
    return out


def _red_events(kind, make):
    """A deny list: the events of KNOWN rows outside this goal's path and needs (for harvest: watering, the can,
    removing, planting proof). Unknown events are what exploration learns from - never red."""
    rows = plan.rows()
    path = [r for r in rows if r['kind'] == kind and any(k in (make or {}) for k in r.get('effect', {}))]
    needs = {k for r in path for k in (r.get('needs') or {})}
    ok = path + [r for r in rows if any(k in needs for k in r.get('effect', {}))]
    allowed = set().union(*[_row_events(r) for r in ok]) if ok else set()
    return set().union(*[_row_events(r) for r in rows]) - allowed - NEUTRAL_EVENTS


def _settle_visit(tid, nid, res):
    """A click whose result proved ANOTHER bed (the evidence went to `nid`): the target's visit is off for this call
    and the attempt counts - the next round moves on instead of clicking the same bubble (live D189)."""
    if nid:
        res.setdefault('tried_nodes', set()).add(nid)   # its bubble is known now: never the visit again this call
    if nid and nid != tid:
        res.setdefault('visit_off', set()).add(tid)
        res.setdefault('fails', {})[tid] = res.get('fails', {}).get(tid, 0) + 1
        res.setdefault('surprises', []).append(f'{tid}: the bubble at its point was {nid}\'s - moving on')


def _visit(g, tid, kind, res, row=None):
    """Use a bubble at the target's predicted point; leave every near move to the model."""
    from . import where
    if tid not in g.nodes:
        return None
    src, here = where.position(far_ok=False, walk_ok=True)
    if src not in ('event', 'walk'):
        return None
    pt = screen_point(here, tuple(g.nodes[tid].extra['pos']))
    if not O.on_frame(pt):
        return None
    tried = list(res.get('btried') or []) + [screen_point(here, tuple(g.nodes[n].extra['pos']))
                                           for n in res.get('tried_nodes', ()) if n in g.nodes]
    hive = {O.NODE_OF.get(k) for k in O.NODE_OF if k != kind}
    other = _other_kinds(kind, row)
    near = [a for a in O.scan() if O.d(a.pt, pt) <= OWN_PX and O.node_of_bubble(a) not in hive
            and not any(O.d(a.pt, p) < 60 for p in tried) and a.kind not in other]
    if near:
        a = min(near, key=lambda a: O.d(a.pt, pt))
        if not _read_bubble(g, tid, a, row, res):
            return a
    return None


def _click_bed(g, tid, pt, row, res):
    """Single guarded object click primitive shared by visits and explicit model decisions."""
    c = A.click(pt, 'object', here=res.get('area'), wait_event=True,
                goal={'row': row['id'] if row else None, 'step': 0, 'target': tid})
    res['clicks'] += 1
    return c


def _decision_value(raw):
    value = raw.strip()
    if not value:
        raise core.Failed('answer rejected: settle state needs key=value')
    try:
        return json.loads(value.lower() if value.lower() in ('true', 'false', 'null') else value)
    except (json.JSONDecodeError, TypeError):
        return value.strip('"\'')


def parse_decision(answer, pend):
    """Parse and guard the model's one decision; parsing itself never acts."""
    value = str(answer).strip()
    if value.lower() == 'done':
        return ('done',)
    if value.lower().startswith('click '):
        nid = value[6:].strip()
        if nid not in pend.get('brief_ids', ()):
            raise core.Failed(f'answer rejected: object {nid!r} is not in the brief')
        return 'click', nid
    if value.lower().startswith('walk '):
        try:
            pt = ask.parse_point(value[5:].strip())
        except ValueError as e:
            raise core.Failed(f'answer rejected: {e}') from None
        if O.d(pt, O.CENTRE) < N.SELF_PX:
            raise core.Failed(f'answer rejected: walk point {pt} is on Tara\'s own spot')
        return 'walk', pt
    if value.lower().startswith('settle '):
        named, sep, raw_state = value[7:].partition(':')
        if not sep:
            raise core.Failed('answer rejected: settle syntax is settle <ids>: key=value')
        ids = named.split()
        if not ids:
            raise core.Failed('answer rejected: settle needs at least one object id')
        missing = [nid for nid in ids if nid not in pend.get('brief_ids', ())]
        if missing:
            raise core.Failed(f'answer rejected: object {missing[0]!r} is not in the brief')
        hidden = [nid for nid in ids if nid not in pend.get('in_view', ())]
        if hidden:
            raise core.Failed(f'answer rejected: object {hidden[0]!r} was not shown in view')
        state = {}
        for item in raw_state.split(','):
            key, eq, raw = item.strip().partition('=')
            if not eq or not key:
                raise core.Failed('answer rejected: settle state needs comma-separated key=value entries')
            state[key] = _decision_value(raw)
        return 'settle', ids, state
    raise core.Failed(f'answer rejected: expected click, walk, settle, or done; got {answer!r}')


def decide_q(g, spec, targets, res):
    """Ask one model question with the graph, detections and marked full-scale frame."""
    from . import brief

    goal = res.get('goal')
    question_state = ask.load_state(goal)
    count = question_state.get('decide_asks', 0)
    if count >= 2:   # the initial decision and at most one retry without progress
        N._gap(res, 'decide: one retry exhausted without a click or settle')
        ask.progress(goal)
        raise O.LawsStuck(f'LAWS_STUCK: {goal} exhausted one decide retry without a click or settle. '
                          'Stop and report; do not retry blindly.')
    question_state['decide_asks'] = count + 1
    ask.save_state(question_state)

    res.setdefault('spec', spec)
    res.setdefault('params', {})
    state = brief.build(g, spec['kind'], targets, res)
    ids = [o['id'] for o in state['objects']]
    in_view = [o['id'] for o in state['objects'] if o['screen'] is not None and O.on_frame(o['screen'])]
    screens = {o['id']: list(o['screen']) if o['screen'] is not None else None for o in state['objects']}
    q = (brief.text(state) + '\nDecide exactly one next action: click <object id>; walk <grid cell>; '
         'settle <space-separated object ids>: key=value[, key=value]; or done. A click names an object from the '
         'brief; a walk names free ground, never Tara or a bubble; settle only objects visibly shown in this frame.')
    pending = {'goal': res.get('goal'), 'params': res.get('params') or {}, 'decide': True,
               'brief_ids': ids, 'in_view': in_view, 'screens': screens,
               'bubbles': [dict(b, pt=list(b['pt'])) for b in state['bubbles']],
               'position_source': state.get('tara', {}).get('source'),
               'position': list(state.get('tara', {}).get('pos') or ()), 'targets': list(targets)}
    pending['reasoning_cycle'] = I.reasoning(
        'clues', goal=res.get('goal'), targets=list(targets), objects=len(state['objects']),
        bubbles=[{'kind': b['kind'], 'pt': list(b['pt']), 'owner': b.get('owner')} for b in state['bubbles']],
        heatmap=[{'kind': h['kind'], 'pt': list(h['pt'])} for h in state['heatmap']],
        position=state.get('tara'), decision='need_model_vision', vision_requested=True)
    N.log('decide', what='question', targets=list(targets), brief_ids=ids, in_view=in_view)
    try:
        ask.ask('decide', q, pending, res, img=ask.draw_grid(brief.draw(core.WF.grab(), state)))
    except O.LawsStuck:
        N._gap(res, 'decide: vision questions without a click or settle')
        raise


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


def _blind_near(kind, row, area, res, skip=frozenset()):
    """No exact position, bubbles of `kind` in view, none fits the row: she is near its objects but the readings
    disagree with the world (live D188: a ready bed read as `water`, then a search walk away) - vision's start
    question beats a search walk."""
    from . import where
    if where.position(far_ok=False)[0] == 'event' or res.get('area') not in (None, area):
        return None
    own = O.NODE_OF.get(kind)
    mine = [b for b in O.scan() if O.node_of_bubble(b) == own]

    def wanted(b):   # a fitting bubble the goal does not skip (the ready tulips stay: they don't count, live D189)
        if not plan.fits(row)(b):
            return False
        if not skip:
            return True
        from . import icons
        return icons.name_of(b) not in skip
    return mine if mine and not any(wanted(b) for b in mine) else None


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
    crop = res.get('target_crop') or ((res.get('icon_of') or {}).get(tuple(b.pt)) if b else None)
    if res.get('explicit_click') and b is not None and O.d(b.pt, c.pt) > 30:
        crop = None
    elif res.get('explicit_click') and b is not None and crop is None:
        crop = getattr(b, 'icon', None)
    g = L.MEMORY.get('graph')
    if crop is None and res.get('graph_crop_ok') and g is not None and res.get('tid_now') in g.nodes:
        crop = world.state_of(g, res['tid_now']).get('crop')
    if crop is None and b is not None and res.get('skip_names') and not res.get('explicit_click'):
        from . import icons                                        # name the crop by its icon, don't drop it
        crop = icons.name_of(b)
        if crop is not None:
            res.setdefault('icon_of', {})[tuple(b.pt)] = crop
        else:
            res['icon_unknown'] = b   # asked next (vision names the icon), never a silent close
    if crop is None and g is not None and res.get('tid_now') in g.nodes:
        nid = res['tid_now']
        ask.ask('name', f'Name the crop on the open Collect card clicked for {nid}. Flowers stay; do not confirm yet.',
                {'goal': res['goal'], 'params': res.get('params', {}), 'collect_open': True,
                 'node': nid, 'actual': nid, 'row': row['id'], 'row_spec': row}, res)
    if crop is not None and crop in res.get('skip_names', ()):
        if res.get('tid_now'):
            res.setdefault('skip', []).append(res['tid_now'])
        return False
    if res.get('skip_names') and crop is None:
        return False
    rest = dict(row, steps=row['steps'][1:])
    out = steps.run(rest, row.get('params', {}), b)
    res.setdefault('card_runs', []).append(out)
    return bool(out['ok'])


def _far_search(t, res, halt=None):
    """Direct bubbles or far map travel only; a near/unknown tier returns to decide_q."""
    for _ in range(N.WALK_MAX + 1):
        affs = O.scan()
        fit = [a for a in affs if t.fits(a)]
        if fit:
            return O.nearest(fit, O.CENTRE)
        if halt is not None and halt(affs):
            return None
        here = res.get('area') or res.get('here')
        tier = N.tier_of(t, res, here)
        if tier != 'map-far':
            return None
        if N.stuck(res):
            return None
        c = N.map_walk(t, res, read=False)
        N.update_tara(res, tier, here, c, t.node)
        if c is None or res.get('stop'):
            return None
        if c.node:
            res['here'], res['inside'] = c.node, N.inside(t, c.node)
        if c.events or c.mode != 'gameplay':
            A.gameplay()
    return None


def _reach(g, name, params, row, kind, area, res, marker, skip=frozenset()):
    """A bubble that fits the row in the target's area. Her area unknown (she walked) and look-alike objects in
    another area -> ONE question: which area is she in? (answer area=<name>)."""
    tried = res.setdefault('btried', [])
    fits_row, other = plan.fits(row), _other_kinds(kind, row)

    def ok(a):   # another row's icon never fits this row (a planting icon is never a pick, live D189 18:08)
        return fits_row(a) and a.kind not in other and not _proven(g, a, res)
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
    from . import where as WH
    src, here = WH.position(far_ok=False, walk_ok=True)
    tid = res.get('tid_now')
    t = N.Target(name, fits, f'a {kind} in {area} whose bubble fits "{row["id"]}"', None, kind, area, area, marker,
                 pos=tuple(g.nodes[tid].extra['pos']) if tid in g.nodes else None,
                 here=here if src in ('event', 'walk') else None)   # fresh only: the save's position can be an hour old
    res['row_now'], res['skip_names'] = row, set(skip)
    res['graph_crop_ok'] = src in ('event', 'walk')
    res['on_card'] = lambda c: finish_card(c, res)
    res.pop('icon_unknown', None)
    a = _far_search(t, res, halt=halt)
    cache = res.get('icon_cache') or {}
    last = max((k for (_, k) in cache), default=None)   # the latest look's icons
    seen = [n for (pt, k), n in cache.items() if n is not None and k == last]
    res['flowers_only'] = bool(seen) and bool(skip) and all(n in skip for n in seen)   # every fitting icon seen = a flower
    if a is None and res['stop']:
        return None
    if a is None and res.get('icon_unknown') is not None:   # a ready bubble whose crop nobody knows: ask, never guess
        from . import icons
        _ask_bubble(res['icon_unknown'], name, params, res)
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


def _ask_bubble(b, name, params, res):
    """An unknown bubble in the scan (wave 2 can't name the icon, wave 1 may not read the badge): ONE question for
    both, at once (user D189: "ask vision to fill the gaps the moment we run the scan and see unknown bubbles"). The
    answer fills the icon memory and the badge store."""
    from . import icons
    path = icons.save_crop(b)
    p140 = icons.save_bubble(b)
    ask.ask('name', f'The bubble at {b.pt[0]},{b.pt[1]}: what does its icon show, and what is in its top-right corner? '
                    f'Answer "<icon>, <corner>": the icon = the crop name (Green Bean, Carrot, Tulip...) or what it '
                    f'is (Seedling, Honey, Watering Can...); the corner = ready (an orange "!"), drop (a water drop) '
                    f'or none.', {'goal': name, 'params': params, 'crop_icon': path, 'bubble140': p140}, res)


def _ask_click(name, params, what, area, res, row=None, settle=()):
    """The click question; `settle` = the objects the world still lists that a `none` answer settles (not ready,
    source vision): the next call starts from what vision saw, never the same loop (user D189)."""
    listed = (f' The world still lists {len(settle)} of them here; if you see none, answer none (that settles them).'
              if settle else ' Answer none if there is none left.')
    q = (f'Goal {name}: no bubble for {what} is in reach. Tara is the magenta circle (always the frame centre). Give '
         f'the grid cell of the nearest {what} in {area}, on the object (not on a bubble), or of free ground toward '
         f'it if it is off-screen.' + listed)
    ask.ask('click', q, {'goal': name, 'params': params, 'node': area, 'settle': list(settle)}, res)


def _in_view(g, targets):
    """The targets within bubble range of her exact position (the ones a `none` from the frame can speak for)."""
    from . import where as WH
    src, here = WH.position(far_ok=False, walk_ok=True)   # the walk end is close enough to say which beds she sees
    if src not in ('event', 'walk'):
        here = world.tara_pos(g)   # else her last known place in the graph
        if here is None:
            return []
    return [n for n in targets if n in g.nodes and math.dist(here, tuple(g.nodes[n].extra['pos'])) <= BUBBLE_R]


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


def _decision_failed(g, nid, result, res):
    state = ask.load_state(res['goal'])
    state['failed_object'] = {'node': nid, 'state': world.state_of(g, nid), 'result': result}
    ask.save_state(state)


def _decision_card(g, nid, row, params, res, crop=None):
    """The first card is already open: run only the row's remaining steps, preserving their proofs."""
    out = steps.run(dict(row, steps=row['steps'][1:]), params, None)
    res['clicks'] += out['clicks']
    N.trace(res, f'{nid}: {row["id"]} result ok={out["ok"]} events={out["events"]}')
    res.setdefault('exps', []).extend(x for x in out.get('exps', ()) if x)
    if red_flag(A.Click((0, 0), 'press', 0, events=out['events']), res):
        raise O.LawsStuck(res['stop'])
    learned = _learn(g, out, row['kind'], row, res)
    plan.count(row['id'], out['ok'])
    if out['ok']:
        if crop and learned:
            world._set(g, learned, {'crop': crop}, _stamp(), 'vision')
        if learned == nid:
            ask.progress(res['goal'])
        else:
            _decision_failed(g, nid, f'{row["id"]} proved {learned}, expected {nid}', res)
        if learned and _made(g, learned, res['spec'].get('make', {}), params, world.state_of(g, learned)):
            if learned not in res['done']:
                res['done'].append(learned)
    return out['ok']


def _collect_answer(g, pend, answer, params, res):
    """Name an unknown crop while its Collect card remains open; flowers are cancelled."""
    crop = str(answer).strip()
    if not crop or crop.lower() in ('none', 'unknown'):
        ask.ask('name', 'Name the crop on the open Collect card; never confirm an unknown crop.', pend, res)
    nid = pend['node']
    N.trace(res, f'{nid}: Collect crop={crop}')
    if crop in res.get('skip_names', ()):
        A.gameplay()
        if pend.get('actual') == nid:
            res['skip'].append(nid)
            ask.progress(res['goal'])
        else:
            _decision_failed(g, nid, f'clicked {crop}; intended object unproven', res)
        res['notes'].append(f'{nid}: clicked {crop} stays')
        return
    row = pend['row_spec']
    _decision_card(g, nid, row, row.get('params', params), res, crop=crop)
    A.gameplay()


def _answer_decision(g, pend, answer, params, res):
    """Execute the model's guarded decision once, with persisted view and failure evidence."""
    N.trace(res, f'decision: {answer}')
    if not str(answer).strip():   # Task 2's one no-progress retry, without an input action
        return
    decision = parse_decision(answer, pend)
    action = decision[0]
    cycle = pend.get('reasoning_cycle') or I.reasoning('clues', goal=res.get('goal'), decision='model_answered')
    I.reasoning('final_decision', cycle, model_answer=str(answer), action=action,
                reason='model selected one guarded action from deterministic clues and optional frame vision')
    if action == 'done':
        res['stop'] = 'done: vision decision'
        I.reasoning('outcome', cycle, verdict='done', outcome=res['stop'])
        return
    if action == 'settle':
        if any(k.startswith('Tara.') for k in decision[2]):
            raise core.Failed('answer rejected: redirected Tara state is not a visible-object settlement')
        for nid in decision[1]:
            world._set(g, nid, decision[2], _stamp(), 'vision')
        N.trace(res, f'settle {decision[1]}: {decision[2]} (vision)')
        I.reasoning('outcome', cycle, action='settle', targets=decision[1], verdict='applied')
        ask.progress(res['goal'])
        return
    nid = decision[1] if action == 'click' else None
    if nid:
        if pend.get('position'):
            from . import brief
            current_source, current_pos = brief._position(g)
            old_pos = tuple(pend['position'])
            stale = (current_pos is None or current_source != pend.get('position_source') and
                     current_source not in ('event', 'walk') or
                     math.dist(old_pos, tuple(current_pos)) > 0.5)
            if stale:
                N.trace(res, f'decision point stale: {pend.get("position_source")} {old_pos} -> '
                             f'{current_source} {current_pos}; re-asking before click')
                targets = [n for n in pend.get('targets', ()) if n in g.nodes]
                return decide_q(g, res['spec'], targets, res)
        pt = (pend.get('screens') or {}).get(nid)
        if nid not in g.nodes or pt is None or not O.on_frame(pt):
            raise core.Failed(f'answer rejected: {nid} has no visible screen point')
        spec = res['spec']
        before = world.state_of(g, nid)
        path = plan.path(g.nodes[nid].kind, dict(before, **_assumed(before, _where(spec, params))),
                         spec.get('make', {}), params)
        row = path[0] if path else None
        state = ask.load_state(res['goal'])
        failed = state.get('failed_object')
        if failed and failed['node'] == nid and failed['state'] == world.state_of(g, nid):
            N._gap(res, f'decide: repeated failed object click {nid}: {failed["result"]}')
            raise O.LawsStuck(f'LAWS_STUCK: repeated failed object click {nid}; stop and report')
    else:
        from .affordances import Affordance
        pt = decision[1]
        visible = [Affordance(b.get('kind', '?'), None, tuple(b['pt']), False, 0.0)
                   for b in pend.get('bubbles', ())]
        if not N.walkable(pt, visible + list(O.scan())):
            raise core.Failed(f'answer rejected: {pt} is not walkable free ground')
    c = _click_bed(g, nid, pt, row, res) if nid else A.click(pt, 'point', here=res.get('area'), wait_event=True)
    if not nid:
        res['clicks'] += 1
    N.trace(res, f'{action} {nid or pt}: {c.describe()}')
    I.reasoning('outcome', cycle, action=action, target=nid, point=list(pt), experience=c.exp,
                events=c.events, moved=c.moved, verdict='observed', outcome=c.describe())
    if c.exp:
        res.setdefault('exps', []).append(c.exp)
    if red_flag(c, res):
        raise O.LawsStuck(res['stop'])
    actual = None
    if c.at:
        actual = world.place(g, c.node.split('@')[0] if c.node else 'Object', c.at, c.events, stamp=_stamp())
        res['area'] = world.area_of(g, c.at)
    if nid and actual and actual != nid:
        N.trace(res, f'wrong object: expected {nid}, proved {actual}')
        _decision_failed(g, nid, c.describe(), res)
        res['stop'] = f'wrong object: expected {nid}, proved {actual}'
        A.gameplay()
        return
    if A.on_card(c) and nid:
        want = ((row or {}).get('steps') or [{}])[0].get('expect', {}).get('card')
        if not want or not any(want.lower() in t.lower() for t in c.texts):
            _decision_failed(g, nid, c.describe(), res)
            ask.ask('name', f'Unexpected card {c.texts} for {nid}; expected {want}. What state does this show?',
                    {'goal': res['goal'], 'params': params,
                     'learn': {'kind': g.nodes[nid].kind, 'nid': actual, 'events': c.events}}, res)
        if want.lower() == 'collect':
            res['tid_now'], res['row_now'] = nid, row
            res['skip_names'] = _skip_names(res['spec'], params)
            res['params'] = params
            res['explicit_click'] = True
            res['graph_crop_ok'] = pend.get('position_source') in ('event', 'walk') and actual in (None, nid)
            finish_card(c, res)
            runs = res.pop('card_runs', [])
            if runs:
                out = runs[0]
                learned = _learn(g, out, row['kind'], row, res)
                plan.count(row['id'], out['ok'])
                if out['ok'] and learned == nid and _made(g, nid, res['spec'].get('make', {}), params, world.state_of(g, nid)):
                    if nid not in res['done']: res['done'].append(nid)
                    ask.progress(res['goal'])
                elif not out['ok']:
                    _decision_failed(g, nid, f'Collect did not finish: {c.describe()}', res)
                A.gameplay()
                return
            if nid in res.get('skip', ()):
                A.gameplay()
                return
        else:
            crop = world.state_of(g, actual or nid).get('crop') if actual or nid else None
            if _decision_card(g, nid, row, row.get('params', params), res, crop=crop):
                A.gameplay()
                return
    elif (nid and actual == nid) or (not c.events and c.moved):
        ask.progress(res['goal'])
        A.gameplay()
        return
    if nid:
        _decision_failed(g, nid, c.describe(), res)
        I.reasoning('gap', cycle, target=nid, code_fix='candidate', invariant='model action did not prove its target',
                    experience=c.exp)
    A.gameplay()


def _answer(g, name, params, answer, res):
    pend = ask.take_answer(name) or {'kind': 'click'}
    if pend.get('decide'):
        try:
            return _answer_decision(g, pend, answer, params, res)
        except core.Failed:
            # Validation can reject an answer before input (for example, a walk onto Tara's spot). Keep the
            # decision attached to the question so the next call can supply a corrected answer.
            state = ask.load_state(name)
            state['pending'] = pend
            ask.save_state(state)
            raise
    if pend.get('collect_open'):
        return _collect_answer(g, pend, answer, params, res)
    entry_words = [w for w in str(answer).strip().lower().split()
                   if w.partition('=')[0] not in ('relative', 'distance')]
    if pend.get('garden_entry_only') and entry_words == ['inside']:
        from . import brief
        region = (pend.get('params') or {}).get('region')
        state = brief.build(g, ('GardenBed', 'BeeHive'),
                            world.query(g, {'kind': 'GardenBed|BeeHive', 'region': region}),
                            dict(res, inside_region=None))
        if state['region_conflicts']:
            # Reject before persisting relative=... distance=inside, and retain all task/coverage fields.
            checkpoint = ask.load_state(name)
            checkpoint['pending'] = pend
            ask.save_state(checkpoint)
            ask.ask('click', brief.entry_text(state, region) + '\nInside answer rejected. '
                    'Choose target <cell> or walk <cell> toward the requested region and report '
                    'relative=<compass> distance=<near|far>.', pend, res,
                    img=ask.draw_grid(brief.draw(core.WF.grab(), state)))
    answer = _record_relative_answer(g, pend, answer, res)
    if pend.get('garden_entry_only') and str(answer).strip().lower() == 'inside':
        res['inside_region'] = (pend.get('params') or {}).get('region')
        ask.progress(name)
        return
    if str(answer).strip().lower() == 'none':
        settled = [n for n in pend.get('settle') or () if n in g.nodes]
        for n in settled:   # vision's "none" is the proof: the world stops listing them (user D189: never stuck)
            g.set_state(n, 'ready', False, _stamp(), 'vision')
        res['stop'] = 'done: vision sees none left' + (f' ({len(settled)} settled)' if settled else '')
        return
    if pend['kind'] == 'click':
        raw_answer = str(answer).strip()
        click_mode = 'walk'
        target_crop = None
        if raw_answer.lower().startswith('target '):
            click_mode, raw_answer = 'target', raw_answer[7:].strip()
            cell, sep, crop = raw_answer.partition(' crop=')
            if sep:
                raw_answer, target_crop = cell.strip(), crop.strip() or None
        elif raw_answer.lower().startswith('walk '):
            raw_answer = raw_answer[5:].strip()
        try:
            pt = ask.parse_point(raw_answer)
        except ValueError as e:
            raise core.Failed(f'answer rejected: {e}. Answer target <cell>, walk <cell>, or none') from None
        if (pend.get('navigation_only') and click_mode == 'walk'
                and any(O.d(pt, tuple(p)) < N.FREE_GAP for p in pend.get('avoid') or ())):
            raise core.Failed(f'answer rejected: navigation point {pt} is inside a garden object hitbox')
        what = 'object' if click_mode == 'target' else 'point'
        cycle = pend.get('reasoning_cycle') or I.reasoning(
            'clues', goal=name, avoid=pend.get('avoid') or [], covered=pend.get('covered') or [],
            decision='model_answered', vision_requested=True)
        I.reasoning('final_decision', cycle, model_answer=str(answer), action=click_mode, point=list(pt),
                    reason=('target and its full road are visible' if click_mode == 'target'
                            else 'visible free-ground waypoint toward remaining targets'))
        c = A.click(pt, what, here=res.get('area'), wait_event=True)   # the event says what was actually hit
        res['clicks'] += 1
        I.reasoning('outcome', cycle, action=click_mode, point=list(pt), experience=c.exp, events=c.events,
                    moved=c.moved, verdict='observed', outcome=c.describe())
        if pend.get('path_cell') and c.moved and not c.events and c.exp:   # she walked onto it: a Path look
            hx, hy = L.ANSWER_BOX
            I.prove(c.exp, 'proven_look', img0=c.img0, box=[max(0, pt[0] - hx), max(0, pt[1] - hy), pt[0] + hx,
                                                           pt[1] + hy], kind=N.PATH_KIND)
            res['learned'].append('look: Path')
            if pend.get('from') and pend.get('dir'):
                res['way'] = (pend['from'], pend['to'], tuple(pend['dir']))
        if c.at:
            world.place(g, c.node.split('@')[0] if c.node else 'Object', c.at, c.events, stamp=_stamp())
            res['area'] = world.area_of(g, c.at)
        if pend.get('navigation_only'):
            collect_open = (click_mode == 'target' and name == 'garden'
                            and ((target_crop is not None and c.mode != 'gameplay')
                                 or any('collect' in t.lower() for t in c.texts)
                                 or ui.shows('Collect', wait=3.0)))
            if collect_open:
                if not c.texts:
                    c.texts = ui.texts()
                if target_crop is not None and not any('collect' in t.lower() for t in c.texts):
                    c.texts = list(c.texts) + ['Collect']   # the model named the visible ready crop; OCR may miss UI
                row = _garden_row('pick')
                res.update(row_now=row, target_crop=target_crop, skip_names=set(res.get('flower_names') or ()),
                           explicit_click=True, graph_crop_ok=False, params=params)
                if finish_card(c, res):
                    out = res.pop('card_runs')[-1]
                    actual = _learn(g, out, 'GardenBed', row, res)
                    plan.count(row['id'], out['ok'])
                    if out['ok'] and actual:
                        res['harvested'] = res.get('harvested', 0) + 1
                        if actual not in res.setdefault('acted', []):
                            res['acted'].append(actual)
                        ask.progress(name)
                    I.reasoning('outcome', cycle, action='collect', target=actual, events=out.get('events'),
                                experience=(out.get('exps') or [None])[-1],
                                verdict='hit' if out['ok'] else 'miss',
                                code_fix=None if out['ok'] else 'evaluate_gap')
                    A.gameplay()
                    return
            # `complete` is emitted when a doorway/scene transition finishes;
            # that is navigation progress even when the frame-diff heuristic
            # cannot call it movement. Object-action events are still a miss.
            interaction_events = [e for e in c.events if e not in NAVIGATION_EVENTS]
            if click_mode == 'walk' and interaction_events:
                raise core.Failed(f'navigation click triggered interaction {c.events}; it was not navigation progress')
            if c.moved or (click_mode == 'target' and (c.events or A.on_card(c))):
                ask.progress(name)
            A.gameplay()   # close any inspection card; its event already identified the actual node
            return
        row = next((r for r in plan.rows() if r['id'] == pend.get('row')), None)
        if row is None and A.on_card(c) and res.get('spec'):   # any card the goal's rows start with (live D189:
            kind = res['spec'].get('kind')                    # a generic answer click opened Collect - closed)
            row = next((r for r in plan.rows(kind) if r['steps'] and (r['steps'][0].get('expect') or {}).get('card')
                        and any(r['steps'][0]['expect']['card'].lower() in t.lower() for t in c.texts)), None)
            if row is not None and res.get('skip_names'):   # never a flower: the crop of the bubble by the click
                res['row_now'] = dict(row, params={})
                if finish_card(c, res):
                    res['done'].append(f'answer@{pt[0]},{pt[1]}')
                    ask.progress(name)
                A.gameplay()
                return
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
                i, old = pend['step'], r['steps'][pend['step']]
                if old['do'] in ('click_bubble', 'click_object'):   # the click happened: the button comes after it
                    new = button_step(answer, {})
                    r['steps'].insert(i + 1, new)   # (live D189: never rewrite the click step itself)
                    r['source'] = f'{r["source"]}; step {i + 1} inserted from vision ({answer})'
                else:
                    r['steps'][i] = button_step(answer, old)
                    r['source'] = f'{r["source"]}; step {i} from vision ({answer})'
        plan.save_rows(rs)
        res['learned'].append(f'{pend.get("row")}[{pend.get("step")}] press {answer}')
    else:
        _answer_name(g, pend, answer, res)


_RELATIVE_ALIASES = {
    'NORTH': 'N', 'NORTHEAST': 'NE', 'NORTH-EAST': 'NE', 'EAST': 'E',
    'SOUTHEAST': 'SE', 'SOUTH-EAST': 'SE', 'SOUTH': 'S',
    'SOUTHWEST': 'SW', 'SOUTH-WEST': 'SW', 'WEST': 'W',
    'NORTHWEST': 'NW', 'NORTH-WEST': 'NW',
}


def _record_relative_answer(g, pend, answer, res):
    """Strip and persist optional model localization metadata before the answer causes input."""
    from objects import graph as OG
    words, clean, meta = str(answer).strip().split(), [], {}
    for word in words:
        key, sep, value = word.partition('=')
        if sep and key.lower() in ('relative', 'distance'):
            meta[key.lower()] = value
        else:
            clean.append(word)
    if not meta:
        return answer
    if set(meta) != {'relative', 'distance'}:
        raise core.Failed('answer rejected: localization requires both relative=<compass> and distance=<inside|near|far>')
    region = (pend.get('params') or {}).get('region')
    if not region:
        raise core.Failed('answer rejected: relative localization has no target region')
    point = _RELATIVE_ALIASES.get(meta['relative'].strip().upper(), meta['relative'].strip().upper())
    try:
        edge = OG.observe_relative(g, 'Tara', region, point, meta['distance'], _stamp())
    except ValueError as e:
        raise core.Failed(f'answer rejected: {e}') from None
    res['relative_location'] = {k: edge[k] for k in ('b', 'compass', 'distance', 'game_time', 'source')}
    I.reasoning('model_vision', goal=pend.get('goal'), question='relative_localization', region=region,
                relative=edge['compass'], distance=edge['distance'], source=edge['source'], model_answer=str(answer))
    return ' '.join(clean)


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
    if pend.get('map_dir'):   # vision read the map's roads: walk that way (the graph learns it when it gets closer)
        N.walk_way(answer, pend, res)
        return
    if pend.get('crop_icon'):   # vision named the bubble: its icon (wave 2) and its corner (wave 1) are stored
        from . import badges, icons
        icon, _, corner = str(answer).partition(',')
        icon, corner = icon.strip(), corner.strip().lower()
        if icon and icons.learn_file(pend['crop_icon'], icon):
            res['learned'].append(f'icon: {icon}')
        if corner in badges.LABELS and pend.get('bubble140') and os.path.exists(pend['bubble140']):
            from PIL import Image
            badges.add(corner, Image.open(pend['bubble140']).convert('RGB'), f'vision: {answer}')
            res['learned'].append(f'badge: {corner}')
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
    if src != 'event' or not all(math.dist(here, tuple(g.nodes[n].extra['pos'])) <= BUBBLE_R for n in targets):
        return False   # a bed beyond bubble range shows no bubble at all: no conclusion (live D188 7 beds away;
        # D189 1:28 PM the far row on screen, 4.5 units off, ready by the save)
    def maybe(n):   # selected only because a POSITIVE condition is unknown (ready unknown): no "!" in range = not ready.
        # A bed known ready whose only unknown is "not a flower": a maybe only when every fitting bubble in view was
        # a skipped flower (the evidence); else no bubble contradicts the world -> vision confirms
        a = _assumed(world.state_of(g, n), where)
        return n in stale or any(not str(v).startswith('!') for v in a.values()) or (bool(a) and res.get('flowers_only'))
    if targets and all(maybe(n) for n in targets):
        res['stop'] = f'done: no fitting bubble left in view ({len(targets)} with unknown state, in bubble range)'
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
    a = _far_search(t, res)
    if a is None:
        listed = [n for n in _targets(g, {'kind': kind}, where, working) if n not in res['skip']]
        if res['stop']:
            return 'stop'
        decide_q(g, res['spec'], listed, res)
    row = {'id': 'explore', 'kind': kind, 'when': {}, 'bubble': {}, 'effect': {},   # a hard case: wait for its line
           'steps': [{'do': 'click_bubble', 'expect': {'events': '?'}}]}         # ('?' = observe what comes)
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
    res.update(goal=name, subgoals=0, learned=[], surprises=[], area=None, skip=[], fails={}, btried=[], params=params)
    g = _open_graph()
    try:
        O.check_language()
        pending = ask.load_state(name).get('pending') or {}
        if not (answer is not None and pending.get('collect_open')):
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
            res['red_events'] = _red_events(spec['kind'], spec.get('make', {}))
            A.ON_EVENT = lambda c: red_flag(c, res)
            res['spec'], res['skip_names'] = spec, _skip_names(spec, params)
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
        A.ON_EVENT = None
        LAST.clear()
        LAST.update(res)
        _log(res)


def _garden_row(row_id):
    return next(r for r in plan.rows() if r['id'] == row_id)


def _garden_log(nid, status, actions, reason=None):
    """One compact coverage record per bed, separate from the transition experiences."""
    try:
        core.WF.run_log('garden_visit', node=nid, status=status, actions=list(actions), reason=reason)
    except Exception:   # noqa: BLE001
        pass


def _garden_inspected(g, targets, lines):
    """Garden nodes whose harmless info bubble or collection was already opened today.

    `plant_growing` is the proof emitted by that inspection.  It carries the actual bed position, so it is stronger
    than screen projection and remains usable after a save refresh or a new garden command.
    """
    out = set()
    for line in lines or ():
        event_kind = next((event for event in ('plant_growing', 'beehive_progress', 'beehive_collect')
                           if f'> {event} ' in line), None)
        kind = 'GardenBed' if event_kind == 'plant_growing' else 'BeeHive' if event_kind else None
        if kind is None or f'target={kind}' not in line:
            continue
        at = A.position_of(line)
        nid = world.find(g, kind, at) if at is not None else None
        if nid in targets:
            out.add(nid)
    return out


def tend_garden(region='Garden', chores=('replant', 'harvest', 'water'), answer=None, max_clicks=MAX_CLICKS,
                crops=None):
    """Inspect and immediately tend each garden bed before advancing to the next one.

    The graph is only the coverage list.  A live bubble chooses the action; cards and events prove its result.
    Empty beds are planted with an available seed.  A bed made empty by removing a wilted crop prefers that crop,
    then falls back to any available seed; every planted bed is watered before the traversal advances.
    """
    enabled = set(chores or ())
    unknown = enabled - {'plant', 'replant', 'harvest', 'water'}
    if unknown:
        raise core.Failed(f'unknown garden chores: {", ".join(sorted(unknown))}')
    W = core.WF
    res = N.new_res('garden')
    authorized = set(crops if isinstance(crops, (list, tuple, set)) else
                     [x.strip() for x in str(crops).split('|') if x.strip()] if crops else ())
    task_params = {'region': region, **({'crops': '|'.join(sorted(authorized))} if authorized else {})}
    res.update(goal='garden', region=region, chores=sorted(enabled), visited=[], acted=[], flowers=[], unresolved=[],
               harvested=0, watered=0, replanted=0, clicks=0, vision=0, subgoals=0, learned=[], surprises=[],
               notes=[], area=None, skip=[], fails={}, btried=[], params=task_params,
               authorized_crops=sorted(authorized))
    g = _open_graph()
    try:
        O.check_language()
        A.gameplay()
        rain = ask.rain()
        hour, light = O.clock()
        res.update(hour=hour, light=light)
        if rain:
            res['stop'] = (f'SLEEP_REQUIRED: rain ({rain}); run ./wf sleep, advance to gameplay, '
                           'then retry garden')
            return res
        if light not in (None, 'day'):
            res['stop'] = (f'SLEEP_REQUIRED: dark ({light}); run ./wf sleep, advance to gameplay, '
                           'then retry garden')
            return res
        if ask.late(res):
            return res
        pending_before = ask.load_state('garden').get('pending') or {}
        continuing = (pending_before.get('streaming') is True
                      and pending_before.get('params') == task_params)
        covered_before = set(pending_before.get('covered') or ()) if continuing else set()
        seen_before = {tuple(p) for p in pending_before.get('seen_bubbles') or ()} if continuing else set()
        res['inside_region'] = pending_before.get('inside_region') if continuing else None
        _, save = W.read_save()
        today_lines = W.today_log()[0]
        world.refresh(g, save, today_lines)
        beds = list(world.query(g, {'kind': 'GardenBed', 'region': region}))
        hives = list(world.query(g, {'kind': 'BeeHive', 'region': region}))
        if not beds:
            res['stop'] = f'no GardenBed nodes in {region}'
            return res
        flowers = set(_param('flowers', {}) or ())
        res['flower_names'] = flowers
        targets = set(beds + hives)
        inspected_before = _garden_inspected(g, targets, today_lines)
        covered = covered_before | inspected_before
        remaining, replanting, seen_bubbles = targets - covered, {}, set(seen_before)
        res['btried'].extend(p for p in seen_before if p not in res['btried'])
        res['visited'].extend(n for n in beds if n in covered)
        res['hives_visited'] = [n for n in hives if n in covered]
        res['honey'] = sum(1 for line in today_lines if '> beehive_collect ' in line and 'target=BeeHive' in line)
        res['spec'] = {'kind': 'GardenBed', 'where': {'region': region}, 'make': {}}
        res['coverage_targets'] = True
        res['allowed_events'] = set().union(*[_row_events(r) for r in plan.rows()]) | NEUTRAL_EVENTS
        A.ON_EVENT = lambda c: red_flag(c, res)
        # A persisted entry claim may predate landmark validation. Check it before consuming an old bed answer
        # or performing any subgoal/action; contradictory appearance must return to model localization.
        if res.get('inside_region') == region:
            from . import brief
            state = brief.build(g, ('GardenBed', 'BeeHive'), list(remaining), dict(res, inside_region=None))
            if state['region_conflicts']:
                res['inside_region'] = None
                pending = {k: v for k, v in pending_before.items()
                           if k not in ('inside_region', 'node', 'walk_cells')}
                pending.update(garden_entry_only=True, covered=sorted(covered),
                               avoid=[list(b['pt']) for b in state['bubbles']])
                checkpoint = ask.load_state('garden')
                checkpoint['pending'] = pending
                ask.save_state(checkpoint)
                ask.ask('click', brief.entry_text(state, region) + '\nStored entry claim invalidated; '
                        'the previous bed answer is not executed. Choose target <cell> or walk <cell> '
                        'toward the requested region and report relative=<compass> distance=<near|far>.',
                        pending, res, img=ask.draw_grid(brief.draw(W.grab(), state)))
        if answer is not None:
            _answer(g, 'garden', task_params, answer, res)
            if pending_before.get('garden_entry_only') and res.get('inside_region') != region:
                res['stop'] = 'entry step completed; re-evaluate Garden region before tending'
                return res
            if str(res.get('stop')).startswith('done: vision sees none'):
                res['unresolved'].extend(beds)
                res['stop'] = f'unresolved: model sees no route to {len(beds)} beds'
                return res
            ask.progress('garden')

        # A refill interrupted by vision may resume in a later process while Tara is already at the Well. Honor the
        # proven empty-can state before sending her back through the garden entrance, or the routine loops away from
        # the refill and immediately needs the same round trip again.
        if 'water' in enabled and g.state_value('Tara', 'can') == 'empty':
            if not _subgoal(g, 'Tara.can', 'full', 'garden', task_params, res):
                res['stop'] = res.get('stop') or 'unresolved: fill watering can before garden entry'
                return res

        # A garden pass is only valid from inside the named region. If Tara's position is unknown or
        # resolves to another area, ask for a visible entrance waypoint before inspecting any beds.
        from . import brief
        source, pos = brief._position(g)
        current_area = world.area_of(g, pos) if pos is not None else None
        if current_area != region and res.get('inside_region') != region:
            state = brief.build(g, ('GardenBed', 'BeeHive'), list(remaining), res)
            avoid = [list(o['screen']) for o in state['objects'] if o.get('screen') is not None]
            avoid += [list(b['pt']) for b in state['bubbles']]
            q = (brief.entry_text(state, region) + f'\nTara is outside or not yet located in {region}. Find its visible entrance. '
                 f'When a real bed or hive and its full walkable road from Tara are visible, prefer target <cell> on '
                 f'that object so game pathfinding takes the whole road. Otherwise give one short cell of clear dirt '
                 f'path toward the entrance; do not click bubbles, rocks, or fence. Treat detector points only as clues: '
                 f'visually reject them when the frame does not actually show beds or hives. '
                 f'Also report Tara relative to {region} using relative=N|NE|E|SE|S|SW|W|NW and '
                 f'distance=inside|near|far. If Tara is visibly inside {region}, answer '
                 f'inside relative=<compass> distance=inside; otherwise answer '
                 f'target <cell> or walk <cell> relative=<compass> distance=<near|far>. Shell-safe calls: '
                 f'./wf garden region={region} answer=target:<cell> relative=<compass> distance=<near|far> or '
                 f'./wf garden region={region} answer=walk:<cell> relative=<compass> distance=<near|far>.')
            ask.ask('click', q, {'goal': 'garden', 'params': task_params, 'navigation_only': True,
                                 'garden_entry_only': True, 'avoid': avoid, 'covered': sorted(covered),
                                 'seen_bubbles': [list(p) for p in sorted(seen_bubbles)],
                                 'streaming': True}, res,
                    img=ask.draw_grid(brief.draw(W.grab(), state)))

        while remaining and not res['stop']:
            if res['clicks'] >= max_clicks:
                res['stop'] = f'click cap {max_clicks}'
                break
            here = world.tara_pos(g)
            # Any owned bed bubble is directly actionable now; do not let nearest-bed ordering
            # force a navigation question while another bed already has a visible action.
            from . import brief
            visible_state = brief.build(g, ('GardenBed', 'BeeHive'), list(remaining), res)
            visible_nodes = [b for b in visible_state['bubbles'] if b.get('owner') in remaining]
            visible_actions = []
            affordances = {tuple(x.pt): x for x in O.scan()}
            for bubble in visible_state['bubbles']:
                # Projection may nominate an unvisited candidate, but it must never revive an already covered node.
                if bubble.get('owner') is not None and bubble['owner'] not in remaining:
                    continue
                a = affordances.get(tuple(bubble['pt']))
                if a is None or tuple(a.pt) in seen_bubbles:
                    continue
                owner_kind = O.node_of_bubble(a) if a is not None else None
                row_id = ('hive_collect' if owner_kind == 'BeeHive' and (a.ready or a.kind == 'honey') else
                          'hive_inspect' if owner_kind == 'BeeHive' else
                          'info_growing' if a is not None and a.kind == 'plant_growing'
                          and not a.ready and not a.drop else
                          'water' if a is not None and a.kind == 'water' and 'water' in enabled else
                          'remove_wilted' if a is not None and a.kind == 'unplant' and 'replant' in enabled else
                          'pick' if a is not None and a.ready and a.icon is not None
                          and (a.icon not in flowers or a.icon in authorized)
                          and 'harvest' in enabled else None)
                if row_id:
                    visible_actions.append((a, _garden_row(row_id)))

            # A visible action is stronger evidence than a stale/missing Tara coordinate. Act first; its log event
            # carries the bed's world position, which identifies the node without a navigation detour.
            if visible_actions:
                a, row = visible_actions[0]
                need = row.get('needs') or {}
                for key, value in need.items():
                    if key.startswith('Tara.') and g.state_value('Tara', key.split('.', 1)[1]) not in (None, value):
                        if not _subgoal(g, key, value, 'garden', task_params, res):
                            res['stop'] = f'unresolved: sub-goal {key}={value} failed for visible {row["id"]} bubble'
                            break
                if res['stop']:
                    break
                out = steps.run(row, {}, a, {})
                seen_bubbles.add(tuple(a.pt))
                res['clicks'] += out['clicks']
                tid = _learn(g, out, row['kind'], row, res)
                plan.count(row['id'], out['ok'])
                if not out['ok']:
                    res['stop'] = out.get('why') or f'visible {row["id"]} action failed'
                    break
                if tid not in remaining:
                    # An ambiguous projected owner pointed at a bubble already
                    # proved to belong to a covered bed. Remember the exact
                    # point and keep scheduling; do not restart and click it.
                    if tuple(a.pt) not in res['btried']:
                        res['btried'].append(tuple(a.pt))
                    res['notes'].append(f'skipped covered bubble {a.pt}: event proved {tid}')
                    A.gameplay()   # close the covered bed's info card before observing another target
                    continue
                actions = [row['id']]
                if tid not in res['acted']:
                    res['acted'].append(tid)
                if row['kind'] == 'BeeHive':
                    if row['id'] == 'hive_collect':
                        res['honey'] += 1
                    remaining.remove(tid)
                    if tuple(a.pt) not in res['btried']:
                        res['btried'].append(tuple(a.pt))
                    res['hives_visited'].append(tid)
                    _garden_log(tid, 'visited', [row['id']])
                    ask.progress('garden')
                    A.gameplay()
                    continue
                if row['id'] == 'water':
                    res['watered'] += 1
                    remaining.remove(tid)
                    if tuple(a.pt) not in res['btried']:
                        res['btried'].append(tuple(a.pt))
                    res['visited'].append(tid)
                    _garden_log(tid, 'visited', actions)
                    ask.progress('garden')
                    continue
                if row['id'] == 'info_growing':
                    remaining.remove(tid)
                    if tuple(a.pt) not in res['btried']:
                        res['btried'].append(tuple(a.pt))
                    res['visited'].append(tid)
                    _garden_log(tid, 'visited', actions)
                    ask.progress('garden')
                    A.gameplay()   # close the info card before the next frame/vision question
                    continue
                if row['id'] == 'pick':
                    res['harvested'] += 1
                    if 'replant' in enabled and getattr(a, 'icon', None):
                        replanting[tid] = a.icon
                elif row['id'] == 'remove_wilted':
                    seed = out.get('stored', {}).get('crop') or getattr(a, 'icon', None)
                    if seed:
                        replanting[tid] = seed
                ask.progress('garden')
            elif visible_nodes:
                tid = visible_nodes[0]['owner']
                actions = []
            else:
                tid = min(remaining, key=lambda n: math.dist(here, tuple(g.nodes[n].extra['pos'])) if here else 0)
                actions = []
            while tid in remaining and not res['stop']:
                if res['clicks'] >= max_clicks:
                    res['stop'] = f'click cap {max_clicks}'
                    break
                target_kind = g.nodes[tid].kind
                a = _visit(g, tid, target_kind, res)
                if a is None and tid in res['acted']:
                    # Harvest/remove animations can briefly hide the replacement bubble. The bed is already in
                    # reach and proven, so settle and inspect it again in place instead of asking the model to walk.
                    W.wait_settle()
                    a = _visit(g, tid, target_kind, res)
                if a is None:
                    # Coverage cannot be inferred from appearance. Ask only for navigation; the next call consumes
                    # the cell and resumes bubble-first inspection, never settling a bed from appearance.
                    state = brief.build(g, ('GardenBed', 'BeeHive'), list(remaining), res)
                    q = (brief.text(state) + f'\nNo bubble for {tid} is in reach. If a garden target and its full '
                         f'walkable road are visible, answer target <cell>; add crop=<name> for a visible ready crop '
                         f'(flowers stay unless explicitly authorized by crops={"|".join(sorted(authorized)) or "none"}). '
                         f'Otherwise answer walk <cell> on visible '
                         f'free ground toward the unvisited beds and hives in {region}. In either answer also report '
                         f'Tara relative to {region} with relative=N|NE|E|SE|S|SW|W|NW and '
                         f'distance=inside|near|far. Shell-safe calls use answer=walk:<cell> or '
                         f'answer=target:<cell> with relative=<compass> distance=<inside|near|far>. '
                         f'Answer none only if no route exists.')
                    avoid = [list(o['screen']) for o in state['objects'] if o.get('screen') is not None]
                    avoid += [list(b['pt']) for b in state['bubbles']]
                    target_screen = next((o['screen'] for o in state['objects'] if o['id'] == tid), None)
                    walk_cells = _guard_walk_cells(avoid, target_screen)
                    if walk_cells:
                        q += (f' Guard-valid walk cells near the target: {", ".join(walk_cells)}. Choose among these '
                              f'only when the frame visibly shows dirt/path there; otherwise use target or none.')
                    ask.ask('click', q, {'goal': 'garden', 'params': task_params, 'node': tid,
                                         'covered': sorted(targets - remaining), 'navigation_only': True,
                                         'avoid': avoid, 'inside_region': res.get('inside_region'),
                                         'walk_cells': walk_cells,
                                         'seen_bubbles': [list(p) for p in sorted(seen_bubbles)],
                                         'streaming': True}, res,
                            img=ask.draw_grid(brief.draw(W.grab(), state)))

                if target_kind == 'BeeHive':
                    row = _garden_row('hive_collect' if a.ready or a.kind == 'honey' else 'hive_inspect')
                    out = steps.run(row, {}, a, world.state_of(g, tid))
                    seen_bubbles.add(tuple(a.pt))
                    if tuple(a.pt) not in res['btried']:
                        res['btried'].append(tuple(a.pt))
                    res['clicks'] += out['clicks']
                    actual = _learn(g, out, 'BeeHive', row, res)
                    plan.count(row['id'], out['ok'])
                    if not out['ok'] or actual != tid:
                        res['unresolved'].append(tid)
                        remaining.remove(tid)
                        _garden_log(tid, 'unresolved', [row['id']], out.get('why') or f'action proved {actual}')
                        break
                    if row['id'] == 'hive_collect':
                        res['honey'] += 1
                    if tid not in res['acted']:
                        res['acted'].append(tid)
                    res['hives_visited'].append(tid)
                    res['visited'].append(tid)
                    remaining.remove(tid)
                    _garden_log(tid, 'visited', [row['id']])
                    ask.progress('garden')
                    break

                crop = getattr(a, 'icon', None) or world.state_of(g, tid).get('crop')
                if crop:
                    g.set_state(tid, 'crop', crop, _stamp(), 'bubble')
                state = world.state_of(g, tid)
                row = row_params = None
                if a.kind == 'plant_growing' and not a.ready and not a.drop:
                    row = _garden_row('info_growing')
                elif a.kind == 'plant':
                    if 'plant' not in enabled and tid not in replanting:
                        remaining.remove(tid)
                        res['visited'].append(tid)
                        _garden_log(tid, 'visited', actions, 'pre-existing empty bed')
                        break
                    inventory = world.inventory(save, W.today_log()[0])
                    preferred = replanting.get(tid) or state.get('crop')
                    available = sorted(name[:-4] for name, count in inventory.items()
                                       if name.endswith('Seed') and count > 0)
                    seed = preferred if preferred in available else (available[0] if available else None)
                    if seed is None:
                        res['unresolved'].append(tid)
                        remaining.remove(tid)
                        detail = f'missing {preferred}Seed' if preferred else 'missing any crop seed'
                        _garden_log(tid, 'unresolved', actions, detail)
                        break
                    row, row_params = _garden_row('plant'), {'seed': seed}
                elif a.ready:
                    if crop in flowers and crop not in authorized:
                        res['flowers'].append(tid)
                        remaining.remove(tid)
                        res['visited'].append(tid)
                        _garden_log(tid, 'flower', actions, crop)
                        break
                    if 'harvest' in enabled:
                        row = _garden_row('pick')
                elif a.drop:
                    if 'replant' in enabled and (a.kind == 'unplant' or state.get('wilted') is True):
                        row = _garden_row('remove_wilted')
                    elif 'water' in enabled and state.get('wilted') is not True:
                        row = _garden_row('water')

                if row is None:
                    remaining.remove(tid)
                    res['visited'].append(tid)
                    _garden_log(tid, 'visited', actions)
                    break

                need = row.get('needs') or {}
                for key, value in need.items():
                    if key.startswith('Tara.') and g.state_value('Tara', key.split('.', 1)[1]) not in (None, value):
                        if not _subgoal(g, key, value, 'garden', task_params, res):
                            res['unresolved'].append(tid)
                            remaining.remove(tid)
                            _garden_log(tid, 'unresolved', actions, f'sub-goal {key}={value} failed')
                            break
                if tid not in remaining:
                    break
                out = steps.run(row, row_params or {}, a, state)
                res['clicks'] += out['clicks']
                nid = _learn(g, out, 'GardenBed', row, res)
                plan.count(row['id'], out['ok'])
                if not out['ok']:
                    res['unresolved'].append(tid)
                    remaining.remove(tid)
                    _garden_log(tid, 'unresolved', actions, out.get('why') or str(out.get('surprises')))
                    A.gameplay()
                    break
                actual = nid or tid
                if actual != tid:
                    nominated = tid
                    if actual not in remaining or g.nodes.get(actual) is None or g.nodes[actual].kind != target_kind:
                        res['stop'] = core.ask_vision(
                            f'Garden interaction near projected {nominated} proved {actual}, which is not an '
                            f'unvisited {target_kind}. Decide whether the graph, transition, or visual label is wrong.')
                        break
                    # Screen projection nominated a candidate only. The event's world coordinates own the result.
                    tid = actual
                    state = world.state_of(g, tid)
                    crop = out.get('stored', {}).get('crop') or getattr(a, 'icon', None) or state.get('crop')
                    try:
                        W.run_log('garden_identity', nominated=nominated, actual=actual, source='event_position')
                    except (AttributeError, TypeError):
                        pass
                actions.append(row['id'])
                if tid not in res['acted']:
                    res['acted'].append(tid)
                if row['id'] == 'pick':
                    res['harvested'] += 1
                    if 'replant' in enabled and crop:
                        replanting[tid] = crop
                elif row['id'] == 'water':
                    res['watered'] += 1
                    remaining.remove(tid)
                    res['visited'].append(tid)
                    _garden_log(tid, 'visited', actions)
                    ask.progress('garden')
                    break
                elif row['id'] == 'info_growing':
                    remaining.remove(tid)
                    res['visited'].append(tid)
                    _garden_log(tid, 'visited', actions)
                    ask.progress('garden')
                    A.gameplay()   # the next brief must not be captured behind this card
                    break
                elif row['id'] == 'remove_wilted':
                    seed = out.get('stored', {}).get('crop') or crop
                    if seed:
                        replanting[tid] = seed
                elif row['id'] == 'plant':
                    res['replanted'] += 1
                    # Plant's final Space may water immediately; count the proven event and otherwise rescan.
                    if any(e in ('water', 'hazel_waterplant') for e in out.get('events', ())):
                        res['watered'] += 1
                ask.progress('garden')

        if not res['stop']:
            res['stop'] = (('done: all garden nodes visited' if hives else 'done: all beds visited')
                           if not res['unresolved'] else
                           (f'unresolved: {len(res["unresolved"])} of {len(targets)} garden nodes' if hives else
                            f'unresolved: {len(res["unresolved"])} of {len(beds)} beds'))
        return res
    finally:
        res['left'] = len(remaining) if 'remaining' in locals() else None
        if 'targets' in locals():
            try:
                core.WF.run_log('garden_summary', region=region, targets=sorted(targets),
                                covered=sorted(set(res.get('visited', ())) |
                                               set(res.get('hives_visited', ()))),
                                unresolved=sorted(set(res.get('unresolved', ()))), stop=res.get('stop'))
            except (AttributeError, TypeError):
                pass
        try:
            g.save(L.graph_path())
        except OSError:
            pass
        L.MEMORY['graph'] = None
        A.ON_EVENT = None
        LAST.clear()
        LAST.update(res)


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
    res['spec'] = spec
    res['red_events'] = _red_events(kind, make)
    A.ON_EVENT = lambda c: red_flag(c, res)   # every click's events are checked against the goal (red flags)
    where = _where(spec, params)
    working = []
    while not res['stop']:
        if res['clicks'] >= max_clicks:
            res['stop'] = f'click cap {max_clicks}'
            break
        if res['clicks'] and ask.late(res):
            break
        unknown, stale = set(), {}
        targets = [n for n in _targets(g, spec, where, working, unknown, stale)
                   if n not in res['skip'] and n not in res.get('seen', ())]
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
        N.log('decide', target=tid, dist=round(math.dist(here, tuple(g.nodes[tid].extra['pos'])), 1) if here else None,
              why=f'nearest of {len(targets)} listed ({", ".join(sorted(targets))[:120]})',
              state={k: v for k, v in world.state_of(g, tid).items() if k in ('stage', 'ready', 'crop')})
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
        if a is None and tid in res.get('tried_nodes', ()) and not _passes(g, tid, where):
            res.setdefault('seen', []).append(tid)   # she saw it: not ready now (a fresh reading) - the next bed
            continue
        visited = a is not None
        if a is not None and skip_names:   # the crop its icon shows: flowers stay; an unknown icon is asked now
            from . import icons
            crop = icons.name_of(a)
            if crop is None:
                _ask_bubble(a, name, params, res)
            res.setdefault('icon_of', {})[tuple(a.pt)] = crop
            if crop in skip_names:
                g.set_state(tid, 'crop', crop, _stamp(), 'icon')
                res['skip'].append(tid)
                res['notes'].append(f'{tid}: {crop} stays (flower)')
                continue
        if a is None:
            res['tid_now'] = tid   # nav walks toward THIS bed (user D189), not whichever bed the vectors see
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
            if res['stop']:
                break
            decide_q(g, spec, targets, res)
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
            _settle_visit(tid, nid, res)
            if res['fails'].get(tid, 0) >= FAILS:
                res['skip'].append(tid)
            continue
        info = L.card_state(str(out.get('screen') or '').split(' / ')) if not out['ok'] else {}
        if info:   # the click showed the object's info card (2 days remaining): evidence, not a prompt - no question
            for x in out.get('exps') or ():
                I.resolved(x)
            res['surprises'].append(f'{t["id"]}: the bubble led to its info card {info} (not what the row expects)')
            A.gameplay()
            res['btried'].append(a.pt)
            _settle_visit(tid, nid, res)
            if res['fails'].get(tid, 0) >= FAILS:
                res['skip'].append(tid)
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
            if nid and _made(g, nid, make, params, world.state_of(g, nid)):   # done with this bed: its new bubble
                res.setdefault('tried_nodes', set()).add(nid)   # (a planting icon) is never the next bed's (D189)
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
