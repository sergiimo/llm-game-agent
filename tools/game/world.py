"""WORLD: the graph built from the save, today's log and click results (spec 2026-11-03 §3, rev. 3).

- Objects of ANY kind: every positioned save object (kind by `kinds.json` `save_has`, or a prefab name learned from a
  log event on it) and every log line `target=<Kind> at (x, y, z)`. Node id `<Kind>#<x>,<z>` (0.1 units).
- Places are grouped ONLY by distance: objects of every kind cluster into area nodes (single linkage, gap from the
  spacing); kind and state are filters (`query`), not nodes.
- State: raw save fields + the one vocabulary (stage/watered/wilted/ready/crop; Tara.can) mapped by `kinds.json`;
  log events newer than the save win, in order (effects from the transition table).
No kind or goal names in code."""
import json
import math
import os
import re
import statistics

from . import plan

KINDS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kinds.json')
NEAR = 0.5             # world units: a position this close to an object of that kind is that object (hives stand 1.25 apart)
GAP_MIN, GAP_MAX = 4.0, 12.0
COMPASS = ((0, 1, 'North'), (0, -1, 'South'), (1, 0, 'East'), (-1, 0, 'West'))
_STAMP = re.compile(r'^\[D(\d+) (\d+):(\d+):(\d+) (AM|PM)\]')
_EVENT = re.compile(r'> (\w+) me=Player target=(\w+)[^\n]*? at \(([-\d.]+), [-\d.]+, ([-\d.]+)\)')
_STATS = re.compile(r'\[STATS\] totalPlanted\.(\S+) =')


def kinds():
    try:
        with open(KINDS) as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith('_')}
    except (OSError, ValueError):
        return {}


# ---- time --------------------------------------------------------------------------------------------------------
def when(stamp):
    """'D185 9:01:00 AM' / '[D185 9:01:00 AM] ...' -> seconds since day 0; None."""
    if stamp is None:
        return None
    m = _STAMP.match(stamp if stamp.startswith('[') else f'[{stamp}]')
    if not m:
        return None
    d, h, mi, s, ap = m.groups()
    h = int(h) % 12 + (12 if ap == 'PM' else 0)
    return int(d) * 86400 + h * 3600 + int(mi) * 60 + int(s)


def save_time(save):
    t = save.get('gameState', {}).get('time', {})
    secs = t.get('timeOfDay', {}).get('totalSeconds')
    if t.get('day') is None or secs is None:
        return None
    h, m = divmod(int(secs) // 60, 60)
    return f'D{t["day"]} {h % 12 or 12}:{m:02d}:00 {"PM" if h >= 12 else "AM"}'


def _after(lines, since):
    """(line, stamp seconds) of lines newer than `since` (unstamped lines take the last stamp before them)."""
    t0, cur = when(since), None
    for line in lines:
        w = when(line)
        cur = w if w is not None else cur
        if t0 is None or (cur is not None and cur > t0):
            yield line


# ---- objects ------------------------------------------------------------------------------------------------------
def oid(kind, x, z):
    return f'{kind}#{round(x, 1)},{round(z, 1)}'


def save_objects(save, prefabs=None):
    """Every positioned save object: {'kind' (None = unnamed), 'pos', 'scene', 'prefab', 'raw'}."""
    ks, prefabs, out = kinds(), prefabs or {}, []
    for sc in save.get('scenes', []):
        for o in (sc.get('addedObjects') or []) + (sc.get('updatedObjects') or []):
            p = o.get('position') or {}
            x, z = float(p.get('x', 0)), float(p.get('z', 0))
            if abs(x) + abs(z) < 1e-6:
                continue   # a placeholder position
            raw = {e['name']: e['value'] for e in ((o.get('actorState') or {}).get('userState') or {}).get('entries', [])}
            prefab = (o.get('prefabId') or {}).get('s')
            kind = next((k for k, v in ks.items() if v.get('save_has') and all(f in raw for f in v['save_has'])),
                        prefabs.get(prefab))
            out.append({'kind': kind, 'pos': (round(x, 2), round(z, 2)), 'scene': sc.get('sceneName'),
                        'prefab': prefab, 'raw': raw})
    return out


def _mapped(kind, raw):
    out = {}
    for key, (field, how) in kinds().get(kind, {}).get('state', {}).items():
        if field not in raw:
            continue
        v = raw[field]
        out[key] = (str(v).lower() == 'true') if how == 'bool' else how.get(v, how.get('*', v))
    return out


def _objects(g):
    return [n for n in g.nodes.values() if n.type == 'member' and n.extra.get('pos') and n.extra.get('scene')]


def known_kind(kind):
    """A kind worth keeping in the graph: in kinds.json, in the transition table, or named from the save."""
    return kind in kinds() or any(r['kind'] == kind for r in plan.rows())


def find(g, kind, at, near=NEAR):
    best = None
    for n in _objects(g):
        if kind is not None and n.kind != kind:
            continue
        p = n.extra['pos']
        dd = math.hypot(p[0] - at[0], p[1] - at[1])
        if dd <= near and (best is None or dd < best[0]):
            best = (dd, n.id)
    return best[1] if best else None


def _ensure_object(g, kind, pos, scene, prefab=None, source='save'):
    from objects.graph import Node
    nid = find(g, kind, pos)
    if nid is None:
        nid = oid(kind, *pos)
        g.nodes[nid] = Node(nid, 'member', kind=kind, region=scene, source=source)
        new = True
    else:
        new = False
    n = g.nodes[nid]
    n.extra.update(pos=[round(pos[0], 2), round(pos[1], 2)], scene=scene)
    if prefab:
        n.extra['prefab'] = prefab
    return nid, new


def _set(g, nid, state, stamp, source):
    for k, v in state.items():
        if k.startswith('Tara.'):
            if 'Tara' in g.nodes:
                g.set_state('Tara', k.split('.', 1)[1], v, stamp, source)
        else:
            g.set_state(nid, k, v, stamp, source)


# ---- areas --------------------------------------------------------------------------------------------------------
def _gap(pts):
    ds = sorted({(round(p[0], 1), round(p[1], 1)) for p in pts})
    if len(ds) < 2:
        return GAP_MIN
    nn = [min(math.dist(a, b) for b in ds if b != a) for a in ds]
    return max(GAP_MIN, min(GAP_MAX, 2 * statistics.median(nn)))


def _clusters(items, gap):
    """Single linkage by distance: [[(id, pos, kind)]]."""
    parent = list(range(len(items)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if math.dist(items[i][1], items[j][1]) <= gap:
                parent[root(i)] = root(j)
    groups = {}
    for i, it in enumerate(items):
        groups.setdefault(root(i), []).append(it)
    return list(groups.values())


def _centre(c):
    return (round(sum(p[0] for _, p, _ in c) / len(c), 2), round(sum(p[1] for _, p, _ in c) / len(c), 2))


def _areas(g, scene, changes):
    from objects.graph import Node
    objs = [n for n in _objects(g) if n.extra['scene'] == scene]
    if not objs:
        return
    if scene not in g.nodes:
        g.nodes[scene] = Node(scene, 'region', kind=scene, region=None, source='save')
    items = [(n.id, tuple(n.extra['pos']), n.kind) for n in objs]
    gap = _gap([p for _, p, _ in items])
    clusters = sorted(_clusters(items, gap), key=lambda c: (-_centre(c)[1], _centre(c)[0]))   # north first
    known = {n.id: tuple(n.extra['pos']) for n in g.nodes.values()
             if n.type == 'region' and n.extra.get('area') and n.extra.get('pos') and n.region == scene}
    named, ks = {}, kinds()
    for c in clusters:   # 1) a known area near the cluster keeps its name
        cc = _centre(c)
        hit = min(((math.dist(cc, p), a) for a, p in known.items() if a not in named.values()), default=None)
        if hit and hit[0] <= 2 * gap:
            named[id(c)] = hit[1]
    for c in clusters:   # 2) the main kind's stem, else stem + compass from the nearest named area
        if id(c) in named:
            continue
        main = max({k for _, _, k in c}, key=lambda k: (sum(1 for _, _, kk in c if kk == k), k))
        stem = ks.get(main, {}).get('area', main)
        taken = set(named.values())
        free = stem not in taken and (stem not in g.nodes or (g.nodes[stem].type == 'region'
                                                             and not g.nodes[stem].extra.get('pos')))
        if free:
            named[id(c)] = stem
            continue
        cc = _centre(c)
        ref = [(math.dist(cc, _centre(o)), _centre(o)) for o in clusters if named.get(id(o))]
        base = min(ref)[1] if ref else cc
        dx, dz = cc[0] - base[0], cc[1] - base[1]
        name = stem + max(COMPASS, key=lambda t: t[0] * dx + t[1] * dz)[2]
        k, cand = 2, name
        while cand in taken or (cand in g.nodes and g.nodes[cand].extra.get('pos')):
            cand, k = f'{name}{k}', k + 1
        named[id(c)] = cand
    g._edges = [e for e in g._edges if not (e['rel'] == 'next_to' and e.get('source') == 'cluster'
                                             and g.nodes.get(e['a']) is not None
                                             and g.nodes[e['a']].extra.get('scene') == scene)]
    for c in clusters:
        name = named[id(c)]
        if name not in g.nodes:
            main = max({k for _, _, k in c}, key=lambda k: sum(1 for _, _, kk in c if kk == k))
            g.nodes[name] = Node(name, 'region', kind=ks.get(main, {}).get('area', main), region=scene, source='cluster')
            changes.setdefault(name, []).append(name)
        a = g.nodes[name]
        a.extra.update(area=True, pos=list(_centre(c)))
        if all(g.nodes[nid].extra.get('transient') for nid, _, _ in c):
            a.extra['transient'] = True   # an area of noise objects only: not kept
        else:
            a.extra.pop('transient', None)
        if a.region is None:
            a.region = scene
        for nid, _, _ in c:
            if g.nodes[nid].region != name:
                g.nodes[nid].region = name
        _neighbours(g, c)


def _neighbours(g, c):
    from objects.graph import screen_dir
    for nid, p, _ in c:
        others = [(math.dist(p, q), mid, q) for mid, q, _ in c if mid != nid]
        if not others:
            continue
        d1 = min(others)[0]
        for dd, mid, q in others:
            if dd <= 1.5 * d1 + 1e-6:
                g.add_edge(nid, mid, 'next_to', dir=list(screen_dir(p, q)), source='cluster')


# ---- refresh / place ---------------------------------------------------------------------------------------------
def refresh(graph, save, today_lines, save_time_=None):
    """Save + today's log -> graph (module doc). Idempotent. {area: [new node ids]}."""
    g, changes = graph, {}
    stamp = save_time_ or save_time(save)
    prefabs = g.extra.setdefault('prefabs', {})
    objs = save_objects(save, prefabs)
    g.extra['_unnamed'] = [o for o in objs if o['kind'] is None]   # for place(): a log event names its prefab
    g.extra['unnamed'] = len(g.extra['_unnamed'])
    new_ids = []
    for o in objs:
        if o['kind'] is None:
            continue
        nid, new = _ensure_object(g, o['kind'], o['pos'], o['scene'], o['prefab'])
        if new:
            new_ids.append(nid)
        st = {k: v for k, v in o['raw'].items() if isinstance(v, (str, int, float, bool))}
        st.update(_mapped(o['kind'], o['raw']))
        _set(g, nid, st, stamp, 'save')
    pp = save.get('currentPlayerPosition')
    if pp and 'Tara' in g.nodes and (abs(pp.get('x', 0)) + abs(pp.get('z', 0))) > 1e-6:
        g.nodes['Tara'].extra['pos'] = [round(pp['x'], 2), round(pp['z'], 2)]
    scene = save.get('currentScene') or 'Farm'
    events = [(m.group(1), m.group(2), (float(m.group(3)), float(m.group(4))), line)
              for line in _after(today_lines, stamp) for m in [_EVENT.search(line)] if m]
    for ev, kind, at, line in events:   # a new kind's object first, so areas see it
        if find(g, kind, at) is None:
            nid = place(g, kind, at, [], scene=scene)
            if nid:
                new_ids.append(nid)
    for sc in {n.extra['scene'] for n in _objects(g)}:
        _areas(g, sc, changes)
    for ev, kind, at, line in events:
        place(g, kind, at, [ev], stamp=_stamp_of(line), scene=scene)
    for nid in new_ids:
        n = g.nodes.get(nid)
        if n is not None:
            changes.setdefault(n.region, []).append(nid)
    g.extra.pop('_unnamed', None)
    return changes


def _stamp_of(line):
    m = re.match(r'^\[([^\]]+)\]', line)
    return m.group(1) if m else None


def place(g, kind, at, events, effects=None, frame=None, stamp=None, scene='Farm', params=None):
    """A logged interaction at world `at` -> its object (created when unknown; an unnamed save object there names its
    prefab), its state from the events' effects (+ `frame` sub-icons, source 'frame'), Tara's position. The id."""
    nid = find(g, kind, at)
    if nid is None:
        un = min(((math.dist(o['pos'], at), o) for o in g.extra.get('_unnamed', [])), default=None,
                 key=lambda t: t[0])
        prefab = None
        if un and un[0] <= NEAR:
            prefab = un[1]['prefab']
            g.extra.setdefault('prefabs', {})[prefab] = kind
            scene = un[1]['scene'] or scene
        near = min(((math.dist(tuple(n.extra['pos']), at), n) for n in _objects(g)), default=None, key=lambda t: t[0])
        nid, _ = _ensure_object(g, kind, at, near[1].extra['scene'] if near else scene, prefab, source='event')
        if near and near[0] <= GAP_MAX:
            g.nodes[nid].region = near[1].region
        if not prefab and not known_kind(kind):   # a log-only object of a kind nothing knows (Weed, Stone): this call only
            g.nodes[nid].extra['transient'] = True
    for ev in events:
        eff = plan.effects_of_event(ev, params) if effects is None else effects
        _set(g, nid, eff, stamp, 'event')
    if frame:
        _set(g, nid, frame, stamp, 'frame')
    if 'Tara' in g.nodes and events:
        g.nodes['Tara'].extra['pos'] = [round(at[0], 2), round(at[1], 2)]
    return nid


# ---- queries ------------------------------------------------------------------------------------------------------
def area_of(g, node_or_pos):
    if isinstance(node_or_pos, (tuple, list)):
        best = min(((math.dist(tuple(n.extra['pos']), tuple(node_or_pos)), n.region) for n in _objects(g)),
                   default=None)
        return best[1] if best and best[0] <= GAP_MAX else None
    n = g.nodes.get(node_or_pos)
    while n is not None and not n.extra.get('area'):
        n = g.nodes.get(n.region)
    return n.id if n is not None else None


def state_of(g, nid):
    return {k: (v['value'] if isinstance(v, dict) else v) for k, v in g.nodes[nid].state.items()}


def query(g, flt):
    """Objects passing the filter: {'kind'?, 'region'? (any area/region in its chain), <state key>: value|"a|b"}."""
    flt = dict(flt)
    kind, region = flt.pop('kind', None), flt.pop('region', None)
    out = []
    for n in _objects(g):
        if kind and n.kind not in str(kind).split('|'):
            continue
        if region and region not in g.chain(n.id):
            continue
        if plan.holds(flt, state_of(g, n.id)):
            out.append(n.id)
    return sorted(out)


def count(g, flt):
    return len(query(g, flt))


def tara_pos(g):
    p = g.nodes['Tara'].extra.get('pos') if 'Tara' in g.nodes else None
    return tuple(p) if p else None


def inventory(save, today_lines, save_time_=None):
    """Item counts: the save minus today's `totalPlanted.<item>` increments newer than the save."""
    items = save.get('gameState', {}).get('player', {}).get('inventory', {}).get('items', [])
    inv = {}
    for i in items:
        inv[str(i['nameHash'])] = inv.get(str(i['nameHash']), 0) + int(i['count'])
    for line in _after(today_lines, save_time_ or save_time(save)):
        m = _STATS.search(line)
        if m and m.group(1) in inv:
            inv[m.group(1)] -= 1
    return inv


def nodes(g):
    """One row per area: name, parent, pos, kinds with counts, state values seen with counts."""
    out = []
    for a in sorted((n for n in g.nodes.values() if n.extra.get('area')), key=lambda n: n.id):
        members = [n for n in _objects(g) if n.region == a.id]
        ks, st = {}, {}
        for n in members:
            ks[n.kind] = ks.get(n.kind, 0) + 1
            for k, v in state_of(g, n.id).items():
                if isinstance(v, (str, bool, int, float)):
                    st.setdefault(k, {}).setdefault(str(v), 0)
                    st[k][str(v)] += 1
        out.append({'area': a.id, 'parent': a.region, 'pos': a.extra.get('pos'), 'kinds': ks, 'state': st})
    return out


def catalogue(g):
    lines = []
    for r in nodes(g):
        ks = ', '.join(f'{k} x{v}' for k, v in sorted(r['kinds'].items()))
        voc = {k: v for k, v in r['state'].items() if k in ('stage', 'watered', 'wilted', 'ready', 'crop')}
        lines.append(f'{r["area"]} (in {r["parent"]}, at {r["pos"]}): {ks}'
                     + (f' | {json.dumps(voc, sort_keys=True)}' if voc else ''))
    lines.append('actions per kind (trusted; learning = seen < 2):')
    by = {}
    for row in plan.rows():
        if row.get('bubble') is not None:
            by.setdefault(row['kind'], []).append(row['id'] + ('' if plan._trusted(row) else ' (learning)'))
    lines += [f'  {k}: {", ".join(v)}' for k, v in sorted(by.items())]
    if g.extra.get('unnamed'):
        lines.append(f'unnamed save objects: {g.extra["unnamed"]} (named when a log event lands on one)')
    return '\n'.join(lines)
