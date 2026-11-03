"""PLAN: the transition table (`actions.json`, spec 2026-11-03 §4) and paths over it.

A row = one action an object offers: `when` (state it needs), `bubble` (which bubble fits it; null = an event-only
row), `steps` (primitives with expectations), `effect` (state change; `$param`, `$same`), `needs` (an item, Tara's
can). `path` is a BFS over effects from an object's state to the goal's `make`. No kind or goal names in code."""
import copy
import json
import os
import re

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'actions.json')
PRIMITIVES = ('click_bubble', 'click_object', 'press', 'press_space', 'pick_card', 'close', 'read_card')
TRUST = 2            # a learned row is used by `path` after this many agreeing sightings
SAME = '$same'       # keep the object's own value (replant: the same crop)
_PARAM = re.compile(r'\$(\w+)')


def _load():
    with open(DB) as f:
        return json.load(f)


def rows(kind=None):
    return [r for r in _load()['rows'] if kind is None or r['kind'] == kind]


def save_rows(rs):
    d = _load()
    d['rows'] = rs
    with open(DB, 'w') as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
        f.write('\n')


def holds(when, state):
    """`when` ({key: value | "a|b"}) holds for `state` (a missing key is None)."""
    for k, v in (when or {}).items():
        got = state.get(k)
        if isinstance(v, str) and '|' in v:
            if str(got) not in v.split('|'):
                return False
        elif got != v:
            return False
    return True


def fits(row):
    """Affordance -> bool: the bubble fits this row (kind alternatives, drop/ready sub-icons); event-only rows never."""
    b = row.get('bubble')

    def f(a):
        if b is None:
            return False
        if 'kind' in b and a.kind not in b['kind'].split('|'):
            return False
        return all(bool(getattr(a, k)) == v for k, v in b.items() if k in ('drop', 'ready'))
    return f


def match(kind, state, aff):
    return [r for r in rows(kind) if holds(r['when'], state) and fits(r)(aff)]


def _sub(v, params):
    """`$x` -> params[x] (whole value) or inside a string ('$seedSeed' -> 'TulipSeed'); unresolved stays."""
    if not isinstance(v, str) or '$' not in v:
        return v
    m = re.fullmatch(r'\$(\w+)', v)
    if m and m.group(1) in params:
        return params[m.group(1)]
    for name in sorted(_PARAM.findall(v), key=len, reverse=True):
        for k in sorted(params, key=len, reverse=True):
            if name.startswith(k):
                v = v.replace('$' + k, str(params[k]), 1)
                break
    return v


def resolve(row, params):
    r = copy.deepcopy(row)
    r['effect'] = {k: _sub(v, params) for k, v in r['effect'].items()}
    if r.get('needs'):
        r['needs'] = {k: _sub(v, params) for k, v in r['needs'].items()}
    for s in r['steps']:
        if 'arg' in s:
            s['arg'] = _sub(s['arg'], params)
    r['params'] = dict(params)
    return r


def _trusted(r):
    return str(r.get('source', '')).startswith('seed') or r.get('seen', 0) >= TRUST


def goal_values(state, make, params):
    """The goal's `make` with `$same` = the object's current value (kept as '$same' while unknown: the path is planned
    with it and the value is read on the way, e.g. the wilted card names the crop) and `$x` = params."""
    return {k: (state.get(k) if state.get(k) is not None else SAME) if v == SAME else _sub(v, params)
            for k, v in make.items()}


def path(kind, state, make, params, depth=3):
    """Shortest row sequence taking `state` to `make` (BFS, ≤ depth), rows resolved with params; None if none.
    An unresolved `$x` in a row's effect takes the goal's value for that key (planting the crop the goal wants).
    Rows that change `ready` are used only when the goal asks for `ready` ("!" is never a reason to act alone)."""
    want = goal_values(state, make, params)
    if all(state.get(k) == v for k, v in want.items()):
        return []
    cand = [r for r in rows(kind) if r.get('bubble') is not None and _trusted(r)
            and ('ready' in make or not ('ready' in r['effect'] or (r['bubble'] or {}).get('ready')))]
    frontier = [(dict(state), [], dict(params))]
    seen = {json.dumps(state, sort_keys=True, default=str)}
    for _ in range(depth):
        nxt = []
        for st, p, prm in frontier:
            for r in cand:
                if not holds(r['when'], st):
                    continue
                bind = dict(prm)
                for k, v in r['effect'].items():
                    for name in _PARAM.findall(str(v)):
                        if name not in bind and k in want:
                            bind[name] = want[k]
                rr = resolve(r, bind)
                if any(isinstance(v, str) and '$' in v and v != SAME for v in rr['effect'].values()):
                    continue   # a parameter nobody gave
                st2 = dict(st)
                st2.update({k: v for k, v in rr['effect'].items() if not k.startswith('Tara.')})
                key = json.dumps(st2, sort_keys=True, default=str)
                if key in seen:
                    continue
                seen.add(key)
                if all(st2.get(k) == v for k, v in want.items()):
                    return p + [rr]
                nxt.append((st2, p + [rr], bind))
        frontier = nxt
    return None


def _events_of(row):
    """The events that prove a row happened: an event-only row's event, else its last step's expected events."""
    if row.get('event'):
        return [row['event']]
    last = row['steps'][-1] if row['steps'] else {}
    return [e for alt in (last.get('expect') or {}).get('events', []) for e in alt.split('|')]


def effects_of_event(event, params=None):
    """The state change a logged event means (the row it proves); `$x` unresolved -> that key dropped."""
    for r in rows():
        if event in _events_of(r):
            eff = resolve(r, params or {})['effect']
            return {k: v for k, v in eff.items() if not (isinstance(v, str) and '$' in v)}
    return {}


def count(row_id, ok):
    rs = rows()
    for r in rs:
        if r['id'] == row_id:
            r['seen'] = r.get('seen', 0) + 1
            r['ok' if ok else 'surprises'] = r.get('ok' if ok else 'surprises', 0) + 1
    save_rows(rs)
