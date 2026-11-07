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
def scene_lines(lines, scene=None, scope=None, since=None):
    """Each decoded line with its source physical scene and entered-building scope, in chronological order."""
    scope = scope or scene
    saved_scene, cutoff, anchored = scene, when(since), False
    for line in lines:
        stamp = when(line)
        if cutoff is not None and not anchored and stamp is not None and stamp > cutoff:
            if saved_scene is not None and scene != saved_scene:
                scene = scope = saved_scene  # a newer snapshot supersedes an older scene-log reading
            anchored = True
        change = re.search(r'\bChangeScene (\w+)(?:/\w+)?', line)
        entered = re.search(r'\bOnEnterBuilding (\w+)', line)
        exited = re.search(r'\bOnExitBuilding (\w+)', line)
        if change:
            scene = scope = change[1]
        elif entered:
            scope = entered[1]
        elif exited:
            scope = scene
        yield line, scene, scope


def scene_context(lines, scene=None, scope=None, since=None):
    saved_scene, cutoff = scene, when(since)
    for _, scene, scope in scene_lines(lines, scene, scope, since):
        pass
    if (cutoff is not None and saved_scene is not None and scene != saved_scene and
            not any(when(line) is not None and when(line) > cutoff for line in lines)):
        return saved_scene, saved_scene  # no post-snapshot log reading can override the newer physical scene
    return scene, scope or scene


def positioned_sources(lines, scene=None, scope=None):
    return [{'line': line, 'scene': source_scene, 'scope': source_scope}
            for line, source_scene, source_scope in scene_lines(lines, scene, scope) if _EVENT.search(line)]


def event_source(state, line):
    """Immutable per-event context; legacy outcomes may contain only one captured current region."""
    for row in state.get('event_sources', ()):
        if row['line'] == line:
            return row
    region = state.get('region')
    return {'scene': region, 'scope': region, 'line': line, 'legacy': True} if region else None


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
    if not scene:
        raise ValueError('positioned object source scene is unknown')
    if scene not in g.nodes:
        g.nodes[scene] = Node(scene, 'region', source=source)
    candidates = scoped_event_candidates(g, kind, pos, scene, physical_scene=scene)
    if len(candidates) > 1:
        raise ValueError('positioned object identity is ambiguous in source scene')
    nid = candidates[0] if candidates else None
    if nid is None:
        nid = oid(kind, *pos)
        if nid in g.nodes:
            nid = f'{scene}:{nid}'
            if nid in g.nodes:
                raise ValueError('source-scoped object ID conflicts with existing graph identity')
        g.nodes[nid] = Node(nid, 'member', kind=kind, region=scene, source=source)
        new = True
    else:
        new = False
    n = g.nodes[nid]
    n.extra.update(pos=[round(pos[0], 2), round(pos[1], 2)], scene=scene)
    if prefab:
        n.extra['prefab'] = prefab
    return nid, new


def _newer(g, nid, key, stamp):
    """The node already holds `key` from a later game time than `stamp` (a card read at 11:20 vs the 8:00 save)."""
    n = g.nodes.get(nid)
    s = n.state.get(key) if n else None
    old, new = (when(s.get('game_time')) if isinstance(s, dict) else None), when(stamp)
    return old is not None and new is not None and old > new


def _set(g, nid, state, stamp, source):
    """State with its game time; an older reading never overwrites a newer one (user D188: the status must stay
    fresh - a refresh from the morning save must not undo what a click showed at noon)."""
    for k, v in state.items():
        if k.startswith('Tara.'):
            if 'Tara' in g.nodes and not _newer(g, 'Tara', k.split('.', 1)[1], stamp):
                g.set_state('Tara', k.split('.', 1)[1], v, stamp, source)
        elif not _newer(g, nid, k, stamp):
            g.set_state(nid, k, v, stamp, source)


def checked_day(g, nid, key):
    """The game day `key` was last set on the object, or None (no stamp)."""
    s = g.nodes[nid].state.get(key) if nid in g.nodes else None
    t = when(s.get('game_time')) if isinstance(s, dict) else None
    return None if t is None else t // 86400


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
                direction = screen_dir(p, q)
                if direction is not None:  # coincident ambiguous objects have no direction between them
                    g.add_edge(nid, mid, 'next_to', dir=list(direction), source='cluster')


# ---- refresh / place ---------------------------------------------------------------------------------------------
LANDMARK_PX = 45   # map px: the pin this close to a landmark's map point = she is at it (80 held her "at the Mine" past it, D188)


def landmarks(g):
    """kinds.json `_landmarks` -> unique graph nodes (fixed places that aren't save objects: the mine)."""
    from objects import graph as OG
    try:
        with open(KINDS) as f:
            config = json.load(f)
            marks = config.get('_landmarks', {})
    except (OSError, ValueError):
        marks, config = {}, {}
    for name, v in marks.items():
        if name.startswith('_') or not isinstance(v, dict):
            continue
        region = v.get('region', 'Farm')
        if region not in g.nodes:
            g.nodes[region] = OG.Node(region, 'region', region)
        extra = {k: v[k] for k in ('pos', 'dead_end', 'map', 'source', 'navigation_only', 'enterable') if k in v}
        point = (v.get('map') or {}).get('point')
        scene = (v.get('map') or {}).get('scene')
        if point and scene:
            try:
                import nav as learned_map
                fit = (learned_map.map_load(learned_map.MAP).get('fits') or {}).get(scene)
                if fit:
                    extra['pos'] = [round(fit['a'] * point[0] + fit['b'], 3),
                                    round(fit['c'] * point[1] + fit['d'], 3)]
                    extra['position_source'] = 'map_calibration'
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if name in g.nodes:
            g.nodes[name].extra.update(extra)
        else:
            g.nodes[name] = OG.Node(name, v.get('type', 'unique'), v.get('kind', name), region, **extra)
    for edge in config.get('_nav_edges', ()):
        if edge.get('a') in g.nodes and edge.get('b') in g.nodes:
            g.add_edge(edge['a'], edge['b'], 'nav', compass=edge.get('compass'),
                       source=edge.get('source', 'map_graph'))
def landmark_at(g, pin):
    """The landmark whose map point is nearest the map pin (within LANDMARK_PX), or None."""
    best = None
    for n in g.nodes.values():
        pt = (n.extra.get('map') or {}).get('point') if isinstance(n.extra.get('map'), dict) else None
        if pt and pin:
            dd = math.dist(tuple(pt), tuple(pin))
            if dd <= LANDMARK_PX and (best is None or dd < best[0]):
                best = (dd, n.id)
    return best[1] if best else None


def refresh(graph, save, today_lines, save_time_=None):
    """Save + today's log -> graph (module doc). Idempotent. {area: [new node ids]}."""
    g, changes = graph, {}
    conflicts = g.extra['_refresh_conflicts'] = []
    landmarks(g)
    stamp = save_time_ or save_time(save)
    prefabs = g.extra.setdefault('prefabs', {})
    objs = save_objects(save, prefabs)
    g.extra['_unnamed'] = [o for o in objs if o['kind'] is None]   # for place(): a log event names its prefab
    g.extra['unnamed'] = len(g.extra['_unnamed'])
    new_ids = []
    for o in objs:
        if o['kind'] is None:
            continue
        try:
            nid, new = _ensure_object(g, o['kind'], o['pos'], o['scene'], o['prefab'])
        except ValueError as error:
            conflicts.append(dict(source='save', scene=o['scene'], kind=o['kind'], at=list(o['pos']), reason=str(error)))
            continue
        if new:
            new_ids.append(nid)
        st = {k: v for k, v in o['raw'].items() if isinstance(v, (str, int, float, bool))}
        st.update(_mapped(o['kind'], o['raw']))
        _set(g, nid, st, stamp, 'save')
    _new_day(g, stamp, today_lines)
    pp = save.get('currentPlayerPosition')
    if pp and 'Tara' in g.nodes and (abs(pp.get('x', 0)) + abs(pp.get('z', 0))) > 1e-6:
        g.nodes['Tara'].extra['pos'] = [round(pp['x'], 2), round(pp['z'], 2)]
    scene = save.get('currentScene')
    if scene and 'Tara' in g.nodes:
        if scene not in g.nodes:
            g.nodes[scene] = Node(scene, 'region', scene)
        g.nodes['Tara'].region = scene
    events, since = [], []
    cutoff, current = when(stamp), None
    for line, source_scene, source_scope in scene_lines(today_lines, scene, since=stamp):
        current = when(line) if when(line) is not None else current
        if cutoff is not None and (current is None or current <= cutoff):
            continue
        m = _EVENT.search(line)               # `> plant` is logged when the panel opens, totalPlanted after, D186)
        since.append(line)
        if m:
            if events:
                events[-1][4].extend(since[:-1])
            events.append((m.group(1), m.group(2), (float(m.group(3)), float(m.group(4))), line, list(since),
                           {'scene': source_scene, 'scope': source_scope, 'line': line}))
            since = []
    if events:
        events[-1][4].extend(since)
    resolved = []
    for ev, kind, at, line, ctx, source in events:
        before_ids = set(g.nodes)
        try:
            nid = place(g, kind, at, [], scene=source['scene'], source=source)
        except ValueError as error:
            conflicts.append(dict(source, kind=kind, at=list(at), reason=str(error)))
            continue
        if nid not in before_ids:
            new_ids.append(nid)
        resolved.append((ev, kind, at, line, ctx, source, nid))
    for sc in {n.extra['scene'] for n in _objects(g)}:
        _areas(g, sc, changes)
    for ev, kind, at, line, ctx, source, nid in resolved:
        place(g, kind, at, [ev], stamp=_stamp_of(line), scene=source['scene'], lines=ctx, node_id=nid, source=source)
    for nid in new_ids:
        n = g.nodes.get(nid)
        if n is not None:
            changes.setdefault(n.region, []).append(nid)
    g.extra.pop('_unnamed', None)
    return changes


def _new_day(g, save_stamp, lines):
    """Today's log is a newer game day than the save: each kind's `daily` state resets (D188: the save was from the
    rainy day before, every bed 'watered'; a new day dries them)."""
    sd = when(save_stamp)
    days = [int(m.group(1)) for m in (re.match(r'^\[D(\d+) ', l) for l in lines) if m]
    if sd is None or not days or max(days) <= sd // 86400:
        return
    today = f'D{max(days)} 7:00:00 AM'
    for kind, v in kinds().items():
        if v.get('daily'):
            for n in _objects(g):
                if n.kind == kind:
                    _set(g, n.id, v['daily'], today, 'day')


def _stamp_of(line):
    m = re.match(r'^\[([^\]]+)\]', line)
    return m.group(1) if m else None


def place(g, kind, at, events, effects=None, frame=None, stamp=None, scene='Farm', params=None, lines=None,
          node_id=None, source=None):
    """A logged interaction at world `at` -> its object (created when unknown; an unnamed save object there names its
    prefab), its state from the events' effects (+ `frame` sub-icons, source 'frame'), Tara's position. The id."""
    candidates = scoped_event_candidates(g, kind, at, scene, physical_scene=scene) if node_id is None else []
    if node_id is None and len(candidates) > 1:
        raise ValueError('positioned object identity is ambiguous in source scene')
    nid = node_id if node_id is not None else candidates[0] if candidates else None
    if node_id is not None and (node_id not in g.nodes or g.nodes[node_id].kind != kind or
                                math.dist(g.nodes[node_id].extra.get('pos', ()), at) > NEAR):
        raise ValueError('resolved event node conflicts with positioned kind/coordinates')
    if nid is None:
        un = min(((math.dist(o['pos'], at), o) for o in g.extra.get('_unnamed', []) if o['scene'] == scene), default=None,
                 key=lambda t: t[0])
        prefab = None
        if un and un[0] <= NEAR:
            prefab = un[1]['prefab']
            g.extra.setdefault('prefabs', {})[prefab] = kind
            scene = un[1]['scene'] or scene
        near = min(((math.dist(tuple(n.extra['pos']), at), n) for n in _objects(g) if n.extra['scene'] == scene),
                   default=None, key=lambda t: t[0])
        nid, _ = _ensure_object(g, kind, at, scene, prefab, source='event')
        if near and near[0] <= GAP_MAX:
            g.nodes[nid].region = near[1].region
        if not prefab and not known_kind(kind):   # a log-only object of a kind nothing knows (Weed, Stone): this call only
            g.nodes[nid].extra['transient'] = True
    for ev in events:
        eff = plan.effects_of_event(ev, params, lines) if effects is None else effects
        _set(g, nid, eff, stamp, 'event')
        if kind == 'GardenBed' and ev in ('water', 'hazel_waterplant') and state_of(g, nid).get('stage') == 'empty':
            # Empty beds cannot be watered. A water proof after an older empty save means planting completed just
            # before it (some picker flows emit only ``complete`` + ``water``, without totalPlanted in the log).
            _set(g, nid, {'stage': 'growing', 'ready': False}, stamp, 'event')
    if frame:
        _set(g, nid, frame, stamp, 'frame')
    if events:
        g.nodes[nid].extra['event_provenance'] = dict(source or {'scene': g.nodes[nid].extra['scene']}, game_time=stamp)
    if 'Tara' in g.nodes and events:
        g.nodes['Tara'].extra['pos'] = [round(at[0], 2), round(at[1], 2)]
    return nid


# ---- queries ------------------------------------------------------------------------------------------------------
def scoped_event_candidates(g, kind, at, scene, physical_scene=None):
    """Compatible candidates after source-scene filtering; callers never select among ambiguous identities."""
    if g is None or not scene:
        return []
    scope_chain = g.chain(scene)
    candidates = []
    for node in _objects(g):
        if physical_scene is not None and node.extra['scene'] != physical_scene:
            continue
        chain = [key for key in g.chain(node.id) if g.nodes[key].type == 'region']
        physical_scope = physical_scene is not None and scene == physical_scene
        if not physical_scope and (scene not in chain or node.extra['scene'] not in scope_chain):
            continue
        if node.kind == kind and math.dist(node.extra['pos'], at) <= NEAR:
            candidates.append(node.id)
    return candidates


def scoped_event_node(g, kind, at, scene, physical_scene=None):
    """Resolve exactly one kind/position candidate after filtering current scene and coherent ancestry."""
    candidates = scoped_event_candidates(g, kind, at, scene, physical_scene)
    return candidates[0] if len(candidates) == 1 else None


def region_proof(g, lines, scene, sources=()):
    """Fresh positioned interaction -> known object ancestry. A stored player position alone proves no arrival."""
    if g is None or not scene:
        return None
    found = None
    for line in lines:
        match = _EVENT.search(line)
        if not match:
            continue
        found = None  # the latest positioned event supersedes an earlier object's location
        at = (float(match[3]), float(match[4]))
        source = next((row for row in sources if row['line'] == line), None)
        if source and source.get('scope') not in g.chain(scene):
            continue  # a later transition left this event's source; it cannot prove arrival in the final view
        nid = scoped_event_node(g, match[2], at, scene, source.get('scene') if source else None)
        if nid is not None:
            chain = [key for key in g.chain(nid) if g.nodes[key].type == 'region']
            found = {'source': 'positioned_event', 'node': nid, 'line': line, 'regions': chain}
    return found


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


STATUS_KEYS = ('stage', 'ready', 'crop', 'days_left', 'watered', 'wilted')


CHANGING = ('stage', 'ready')   # readings that change from day to day (a crop's name does not)


def status(g, kind, today=None, keys=STATUS_KEYS, changing=CHANGING):
    """One line per object of `kind`, by area: each reading with its source and game time; CHECK = no reading that
    changes from day to day (stage, ready) is from `today` (user D188: see which status is fresh and
    where to look)."""
    lines = []
    for n in sorted((n for n in _objects(g) if n.kind == kind), key=lambda n: (str(n.region), n.extra['pos'])):
        parts, days = [], []
        for k in keys:
            s = n.state.get(k)
            if not isinstance(s, dict):
                continue
            parts.append(f'{k}={s.get("value")} ({s.get("source")} {s.get("game_time") or "?"})')
            if k in changing and checked_day(g, n.id, k) is not None:
                days.append(checked_day(g, n.id, k))
        old = today is not None and bool(days) and max(days) < today   # nothing that changes was read today
        lines.append(f'{n.id} [{n.region}] at {n.extra["pos"]}: ' + ', '.join(parts) + ('  CHECK' if old else ''))
    return lines


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
