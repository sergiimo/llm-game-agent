"""Navigation learning loop (docs/superpowers/specs/2026-10-29-nav-learning-loop-design.md, L62).

Pure functions over the fact log `tools/nav/facts.jsonl` (one JSON line per checkpoint: predicted vs measured world
position). Everything here is derived from the facts on demand: calibration per area, place positions, blocked
spots, edge status, prediction error. No game I/O: tools/wf.py takes the readings and appends the facts.

Storage (L65: every scene has its own world coordinates; buildings share their scene's):
    tools/nav/facts.jsonl          all facts; `scene` = the AREA: 'Farm' outdoors, 'Farm/House' inside
    tools/nav/map.json             L4 map: place pins (map px) + map -> world fit per outdoor scene (cache)
    tools/nav/<Scene>/             one coordinate frame: calib.json (L2 camera fit, cache) + prints.jsonl (L1)
    tools/nav/<Scene>/<Building>/  same coordinates, indoor camera: its own calib.json + prints.jsonl
"""
import json
import math
import os
import re
import statistics

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'nav')
FACTS = os.path.join(ROOT, 'facts.jsonl')
MAP = os.path.join(ROOT, 'map.json')
FRAME_W, FRAME_H = 1920, 1080
BLOCK_HOURS = 1.0          # a NO MOVE target stays blocked this many game hours
PLACE_LAST = 10            # place position = median of the last N arrivals
MIN_SAMPLES = 5


# ---------------------------------------------------------------- fact log
def load(path=FACTS):
    try:
        with open(path) as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except OSError:
        return []


def append(fact, path=FACTS):
    with open(path, 'a') as fh:
        fh.write(json.dumps(fact) + '\n')


def area_dir(area, root=None):
    """Folder of an area ('Farm' -> tools/nav/Farm, 'Farm/House' -> tools/nav/Farm/House)."""
    return os.path.join(root or ROOT, *area.split('/'))


def outdoor(area):
    """Outdoor areas have the map layer (L4); indoors does not (the map won't open there)."""
    return '/' not in (area or '/')


def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(data, fh, indent=1)


def calib_load(area, root=None):
    """The area's camera fit; an outdoor scene without one borrows another outdoor scene's (the outdoor camera is
    the same everywhere: Town = Farm within 0.01 units, L66). The borrowed fit has 'borrowed': <scene>."""
    c = _read_json(os.path.join(area_dir(area, root), 'calib.json'), None)
    if c or not outdoor(area):
        return c
    r = root or ROOT
    for d in sorted(os.listdir(r)) if os.path.isdir(r) else []:
        c = _read_json(os.path.join(r, d, 'calib.json'), None)
        if c and not c.get('borrowed'):
            return dict(c, borrowed=d)
    return None


def calib_save(area, fit, root=None):
    _write_json(os.path.join(area_dir(area, root), 'calib.json'), dict(fit, _doc=(
        'Cache derived from tools/nav/facts.jsonl (every clean one-click checkpoint, L62): H maps normalised screen '
        '((x-960)/500, (y-540)/500) to the world offset (dx, dz) from Tara; tara = her ground point on screen; '
        'err = median residual in world units.')))


def calib_all(facts, root=None):
    """{area: fit} for every area that has facts or a calib.json."""
    areas = {f['scene'] for f in facts if f.get('scene')}
    return {a: c for a in sorted(areas) if (c := calib_load(a, root))}


def map_load(path=None):
    return _read_json(path or MAP, {'places': {}, 'fits': {}})


def map_save(data, path=None):
    data['_doc'] = ('L4 map layer. places: map px (1920x1080 frame, map open with M) of named places, seeded by hand '
                    '+ `wf where --learn`. fits: per outdoor scene, world x = a*mx + b, z = c*my + d (cache, derived '
                    'from pin facts). Indoor areas have no map layer.')
    _write_json(path or MAP, data)


def map_refit(facts, path=None):
    """Recompute the map -> world fit of every outdoor scene with pin facts and cache it in map.json."""
    data = map_load(path)
    data['fits'] = {s: f for s in sorted({f['scene'] for f in facts if f.get('pin') and outdoor(f.get('scene'))})
                    if (f := map_fit(facts, s))}
    map_save(data, path)
    return data['fits']


def game_hours(f):
    """Absolute game time of a fact (or a reading) in hours."""
    return f.get('day', 0) * 24 + f.get('hour', 0)


# ---------------------------------------------------------------- screen <-> ground
def norm(x, y):
    return (x - FRAME_W / 2) / 500.0, (y - FRAME_H / 2) / 500.0


def fit_h(src, dst):
    """Homography (DLT) from normalised screen points to ground (dx, dz)."""
    import numpy as np
    rows = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    h = np.linalg.svd(np.array(rows, float))[2][-1].reshape(3, 3)
    return h / h[2, 2]


def apply_h(h, x, y):
    import numpy as np
    p = np.asarray(h) @ [x, y, 1.0]
    return float(p[0] / p[2]), float(p[1] / p[2])


def screen_to_ground(h, sx, sy):
    """Screen click -> world (dx, dz) offset from Tara."""
    return apply_h(h, *norm(sx, sy))


def ground_to_screen(h, dx, dz):
    """World offset from Tara -> screen point to click."""
    import numpy as np
    nx, ny = apply_h(np.linalg.inv(np.asarray(h)), dx, dz)
    return round(nx * 500 + FRAME_W / 2), round(ny * 500 + FRAME_H / 2)


def predict(h, start, clicks):
    """Dead reckoning: each click moves her by its ground offset (the camera follows her, so offsets add up)."""
    x, z = start
    for sx, sy in clicks:
        dx, dz = screen_to_ground(h, sx, sy)
        x, z = x + dx, z + dz
    return x, z


# ---------------------------------------------------------------- calibration
def calib_samples(facts, scene):
    """Clean single-click segments: (click, measured world offset)."""
    out = []
    for f in facts:
        if (f.get('scene') == scene and f.get('from') and f.get('to') and len(f.get('clicks') or []) == 1
                and not f.get('dirty') and not f.get('stale') and f.get('result') in ('arrived', 'short', 'moved')):
            out.append((tuple(f['clicks'][0]), (f['to'][0] - f['from'][0], f['to'][1] - f['from'][1])))
    return out


def _residuals(h, samples):
    res = []
    for c, d in samples:
        a = screen_to_ground(h, *c)
        res.append(math.hypot(a[0] - d[0], a[1] - d[1]))
    return res


def fit_robust(samples):
    """Fit, drop samples with residual > 3x median (at least 0.3 units: walks that stopped short), refit; repeat
    until stable (outliers pull the first fit, hiding each other). Returns {'H', 'n', 'kept', 'err', 'tara'} or None
    when there are too few samples."""
    if len(samples) < MIN_SAMPLES:
        return None
    kept = samples
    h = fit_h([norm(*c) for c, _ in kept], [d for _, d in kept])
    for _ in range(5):
        res = _residuals(h, samples)
        cut = max(0.3, 3 * statistics.median(_residuals(h, kept)))
        nxt = [s for s, r in zip(samples, res) if r <= cut]
        if len(nxt) < MIN_SAMPLES or nxt == kept:
            break
        kept = nxt
        h = fit_h([norm(*c) for c, _ in kept], [d for _, d in kept])
    err = statistics.median(_residuals(h, kept))
    return {'H': h.tolist(), 'n': len(samples), 'kept': len(kept), 'err': round(err, 3),
            'tara': ground_to_screen(h, 0, 0)}


# ---------------------------------------------------------------- derived views
def places(facts):
    """{scene: {name: (x, z, n, spread)}} from the last arrivals with that goal."""
    by = {}
    for f in facts:
        if f.get('result') == 'arrived' and f.get('goal') and f.get('to'):
            by.setdefault((f['scene'], f['goal']), []).append(f['to'])
    out = {}
    for (scene, name), pts in by.items():
        pts = pts[-PLACE_LAST:]
        x, z = statistics.median(p[0] for p in pts), statistics.median(p[1] for p in pts)
        spread = max(math.hypot(p[0] - x, p[1] - z) for p in pts)
        out.setdefault(scene, {})[name] = (x, z, len(pts), round(spread, 2))
    return out


def blocks(facts, scene, now):
    """World points that refused a click (NO MOVE) within BLOCK_HOURS game hours of `now` (a reading)."""
    t = game_hours(now)
    return [tuple(f['target']) for f in facts
            if f.get('result') == 'no_move' and f.get('scene') == scene and f.get('target')
            and 0 <= t - game_hours(f) <= BLOCK_HOURS]


def edge_status(facts, now):
    """{edge: {'status', 'ok', 'fail', 'rate'}}; recent attempts weigh more (half-life 7 game days)."""
    t = game_hours(now)
    by = {}
    for f in facts:
        if f.get('edge'):
            by.setdefault(f['edge'], []).append(f)
    out = {}
    for e, fs in by.items():
        okw = failw = 0.0
        for f in fs:
            w = 0.5 ** (max(0, t - game_hours(f)) / (24 * 7))
            if f['result'] in ('arrived', 'scene'):
                okw += w
            else:
                failw += w
        rate = (okw + 1) / (okw + failw + 2)
        fails = [f for f in fs if f['result'] not in ('arrived', 'scene')]
        last3 = fs[-3:]
        if len({f.get('day') for f in fails}) >= 3 and not any(f['result'] in ('arrived', 'scene') for f in last3):
            status = 'suspect-wall'
        elif fs[-1]['result'] not in ('arrived', 'scene') and t - game_hours(fs[-1]) <= BLOCK_HOURS:
            status = 'blocked-now'
        elif fails and rate < 0.7:
            status = 'flaky'
        else:
            status = 'ok'
        out[e] = {'status': status, 'ok': len(fs) - len(fails), 'fail': len(fails), 'rate': round(rate, 2)}
    return out


def pred_error(facts):
    """{scene: (early median, late median, n)} of |pred - to|: should shrink as the loop learns."""
    by = {}
    for f in facts:
        if (f.get('pred') and f.get('to') and not f.get('dirty') and not f.get('stale')
                and f.get('result') != 'stuck'):  # a wall stop is not a prediction error
            by.setdefault(f['scene'], []).append(math.hypot(f['pred'][0] - f['to'][0], f['pred'][1] - f['to'][1]))
    out = {}
    for s, es in by.items():
        half = max(1, len(es) // 2)
        out[s] = (round(statistics.median(es[:half]), 2), round(statistics.median(es[half:] or es), 2), len(es))
    return out


def report(facts, calib, now):
    """Text for `wf learn nav`. `calib` = {scene: fit} as stored in tools/calib.json."""
    lines = [f'nav facts: {len(facts)} ({FACTS})']
    scenes = sorted({f['scene'] for f in facts if f.get('scene')} | {k for k in calib if not k.startswith('_')})
    for s in scenes:
        c = calib.get(s) or {}
        n = len(calib_samples(facts, s))
        lines.append(f'calib {s}: {n} samples' + (f', fit kept {c.get("kept", c.get("hops"))}/{c.get("n", c.get("hops"))}'
                                                  f', err {c.get("err", c.get("loo_err"))}, Tara at {c.get("tara")}'
                                                  if c else ' (no fit yet: need 5)'))
    for s, (a, b, n) in pred_error(facts).items():
        lines.append(f'prediction error {s}: {a} -> {b} units (n {n}, early -> late)')
    for s, pl in places(facts).items():
        lines.append(f'places {s}: ' + ', '.join(f'{k} ({x:.1f}, {z:.1f}) n{n} ±{sp}' for k, (x, z, n, sp) in pl.items()))
    es = edge_status(facts, now)
    for e, v in es.items():
        flag = '  ← REVIEW: remove edge or fix its clicks?' if v['status'] == 'suspect-wall' else ''
        lines.append(f'edge {e}: {v["status"]} ({v["ok"]} ok / {v["fail"]} fail, rate {v["rate"]}){flag}')
    for s in scenes:
        b = blocks(facts, s, now)
        if b:
            lines.append(f'blocked now {s}: ' + ', '.join(f'({x:.1f}, {z:.1f})' for x, z in b))
    for s in scenes:
        mf = map_fit(facts, s)
        if mf:
            lines.append(f'map->world {s}: {mf["n"]} pin pairs, err {mf["err"]} units')
        n, share, cut = img_accuracy(facts, s)
        if n:
            lines.append(f'image localisation {s}: {n} evaluated, {share:.0%} within {IMG_OK} units (d <= {cut})'
                         f' -> {"TRUSTED" if img_trusted(facts, s, cut or 0) else "not trusted yet"}')
    lines.append('last facts (t: delete the line in the file to undo):')
    for f in facts[-8:]:
        lines.append(f"  {f.get('t')} D{f.get('day')} {f.get('hour', 0):.1f}h {f.get('scene')} {f.get('result')}"
                     f" to {f.get('to')} pred {f.get('pred')} goal {f.get('goal')} edge {f.get('edge')}")
    return '\n'.join(lines)


# ---------------------------------------------------------------- 1. units: map pixels -> world (phase 2)
MAP_NEAR = 150             # map px: a map place belongs to the scene with pin pairs this close
MAP_RADIUS = 2.0           # world units: least arrival radius of a coarse map node (pins snap to roads, L64)


# Map pixels as a compass (L72): the map is stylised, so a per-scene fit from a few road-snapped pins is unreliable
# (D148: 0.16-0.67 world units per map px between pin pairs), but its directions agree with the world (x right,
# map y down = world -z; ±20°). So the map gives direction and distance only; every hop ends in a reading.
MAP_SCALE = 0.3            # world units per map px: median over pin pairs (±50 %)
MAP_HOP = 8.0              # world units per coarse map hop


def path_ahead(path, m, px):
    """The point on a map route `px` map px along it past the route point nearest map position `m`."""
    if not path:
        return None
    i = min(range(len(path)), key=lambda k: math.dist(path[k], m))
    done, prev = 0.0, path[i]
    for q in path[i + 1:]:
        done += math.dist(prev, q)
        prev = q
        if done >= px:
            break
    return prev


def map_heading(m, tgt, units=MAP_HOP):
    """World (dx, dz) of a hop `units` long toward map point `tgt` from map position `m`; None if already there."""
    dx, dy = tgt[0] - m[0], tgt[1] - m[1]
    d = math.hypot(dx, dy)
    if d < 1:
        return None
    k = min(units, d * MAP_SCALE) / d
    return dx * k, -dy * k


def map_dead_reckon(m, dx, dz):
    """New map position after a measured world move (dx, dz)."""
    return m[0] + dx / MAP_SCALE, m[1] - dz / MAP_SCALE


def map_pairs(facts, scene):
    if not outdoor(scene):
        return []
    return [(f['pin'], f['to']) for f in facts if f.get('scene') == scene and f.get('pin') and f.get('to')
            and not f.get('stale')]


def map_fit(facts, scene):
    """Axis-aligned map -> world fit for a scene: x = a*mx + b, z = c*my + d (north-up map, fixed camera).
    Returns {'a','b','c','d','n','err'} or None (needs 2+ pairs differing on both axes)."""
    import numpy as np
    pairs = map_pairs(facts, scene)
    if len(pairs) < 2:
        return None
    m = np.array([p for p, _ in pairs], float)
    w = np.array([t for _, t in pairs], float)
    if np.ptp(m[:, 0]) < 5 or np.ptp(m[:, 1]) < 5:
        return None
    a, b = np.polyfit(m[:, 0], w[:, 0], 1)
    c, d = np.polyfit(m[:, 1], w[:, 1], 1)
    err = float(np.median(np.hypot(a * m[:, 0] + b - w[:, 0], c * m[:, 1] + d - w[:, 1])))
    return {'a': float(a), 'b': float(b), 'c': float(c), 'd': float(d), 'n': len(pairs), 'err': round(err, 2)}


def map_to_world(fit, mx, my):
    return fit['a'] * mx + fit['b'], fit['c'] * my + fit['d']


def map_places_world(facts, map_places):
    """map.json places (map px) -> {scene: {name: (x, z, r)}} for outdoor scenes with a map fit and pin pairs
    nearby; r = arrival radius (the map is coarse: 2x the fit error, at least MAP_RADIUS)."""
    scenes = {f['scene'] for f in facts if f.get('pin') and f.get('scene')}
    fits = {s: map_fit(facts, s) for s in scenes}
    out = {}
    for name, (mx, my) in map_places.items():
        best = None
        for s in scenes:
            if not fits[s]:
                continue
            d = min(math.hypot(p[0] - mx, p[1] - my) for p, _ in map_pairs(facts, s))
            if d <= MAP_NEAR and (best is None or d < best[0]):
                best = (d, s)
        if best:
            fit = fits[best[1]]
            out.setdefault(best[1], {})[name] = (*map_to_world(fit, mx, my), max(MAP_RADIUS, 2 * fit['err']))
    return out


# ---------------------------------------------------------------- 2. graph in world units
def nodes(facts, map_places=None):
    """{'<area>:<name>': {'scene','name','x','z','src'}} from arrivals, map places, anchors and exits. Map nodes
    (src 'map', coarse) also carry 'r', their arrival radius; an arrival overrides them."""
    out = {}
    for s, pl in map_places_world(facts, map_places or {}).items():
        for n, (x, z, r) in pl.items():
            out[f'{s}:{n}'] = {'scene': s, 'name': n, 'x': x, 'z': z, 'src': 'map', 'r': r}
    for s, pl in places(facts).items():  # arrivals (incl. anchors: scene facts carry the anchor as goal)
        for n, (x, z, k, _) in pl.items():
            out[f'{s}:{n}'] = {'scene': s, 'name': n, 'x': x, 'z': z, 'src': 'arrived'}
    for f in facts:  # detour points: walkable ground beside a wall, found by go_world (L67)
        if f.get('result') == 'via' and f.get('to') and not f.get('stale'):
            x, z = f['to']
            out[f'{f["scene"]}:via({x:.0f},{z:.0f})'] = {'scene': f['scene'], 'name': f'via({x:.0f},{z:.0f})',
                                                         'x': x, 'z': z, 'src': 'via'}
    anchors = {}
    for f in facts:
        if f.get('result') == 'scene' and f.get('goal') and f.get('to'):
            anchors.setdefault((f['scene'], f['goal']), []).append(f['to'])
    for (s, n), pts in anchors.items():
        pts = pts[-PLACE_LAST:]
        out[f'{s}:{n}'] = {'scene': s, 'name': n, 'x': statistics.median(p[0] for p in pts),
                           'z': statistics.median(p[1] for p in pts), 'src': 'anchor'}
    exits = {}
    for f in facts:  # an exit is only stored when traced from a reading; untraced crossings keep the link only
        if f.get('result') == 'scene' and f.get('from_scene') and f.get('goal'):
            e = exits.setdefault(f'{f["from_scene"]}:exit>{f["goal"]}', {
                'scene': f['from_scene'], 'name': f'exit>{f["goal"]}', 'src': 'exit', 'to': f'{f["scene"]}:{f["goal"]}',
                'pts': []})
            if f.get('exit'):
                e['pts'].append(f['exit'])
    for k, e in exits.items():
        pts = e.pop('pts')[-PLACE_LAST:]
        e['x'] = statistics.median(p[0] for p in pts) if pts else None
        e['z'] = statistics.median(p[1] for p in pts) if pts else None
        t = out.get(e['to'])
        if e['x'] is None and t and t['scene'].split('/')[0] == e['scene'].split('/')[0]:
            e['aim'] = (t['x'], t['z'])  # a building door: walk toward the other side (same coordinates, L64)
        out[k] = e
    out.update(back_links(facts, out))
    for (s, x, z), _ in trail(facts).items():
        out.setdefault(trail_key(s, x, z), {'scene': s, 'name': trail_key(s, x, z).split(':', 1)[1],
                                            'x': x, 'z': z, 'src': 'trail'})
    return out


# ---------------------------------------------------------------- trail: where she has really walked (L73)
# Two readings in a row in one area with a real move between them = a proven walk (the game's pathfinding found a
# way), usable both ways. The graph prefers proven walks over straight lines, so a plan back out of a dead end
# (a porch, someone's yard) follows the way in.
TRAIL_GRID = 2.0           # world units: trail points this close are one node
TRAIL_MIN = 1.0            # world units: a shorter move proves nothing
STEP_COST = 5.0            # a never-walked straight line costs its length + this (its own reading; unknown ground)
STRAIGHT_OK = 8.0          # world units: about one screen hop; a never-walked line beyond this crosses ground we
LONG_FACTOR = 2.0          # haven't seen (fences, hedges): each unit beyond costs this much more (L73)
TRAIL_FACTOR = 0.5         # a proven walk costs this x its length (she got through there; readings can be skipped)


def trail_key(scene, x, z):
    g = TRAIL_GRID
    return f'{scene}:trail({round(x / g) * g:.0f},{round(z / g) * g:.0f})'


def trail(facts):
    """{(scene, x, z): [(x, z) of the other end]} of proven walks (both directions; first point per grid cell)."""
    pts, out = {}, {}

    def node(s, p):
        return pts.setdefault(trail_key(s, *p), (s, float(p[0]), float(p[1])))
    for f in facts:
        a, b = f.get('from'), f.get('to')
        if (not a or not b or f.get('stale') or f.get('result') in ('scene', 'no_move', 'blocked')
                or math.dist(a, b) < TRAIL_MIN):
            continue
        na, nb = node(f['scene'], a), node(f['scene'], b)
        if na != nb:
            out.setdefault(na, []).append(nb[1:])
            out.setdefault(nb, []).append(na[1:])
    return out


STUCK_MOVES = 3            # moves: her position barely changing over this many moves = stuck (user rule, L75)
STUCK_SPREAD = 2.0         # world units: "barely changing"


def no_progress(track):
    """track = [(area, x, z)] her position after each move (reading or estimate) of one trip. True when the last
    STUCK_MOVES moves stayed within STUCK_SPREAD of each other in one area (the trip isn't at its goal yet)."""
    last = track[-(STUCK_MOVES + 1):]
    if len(last) < STUCK_MOVES + 1 or len({a for a, _, _ in last}) > 1:
        return False
    return max(math.dist(p[1:], q[1:]) for p in last for q in last) < STUCK_SPREAD


BACK_PUSH = 3.0            # world units past the arrival point, against the first move after arriving
BACK_COST = 15.0           # an untraced way back across a border (the next crossing traces it)


def back_links(facts, ns):
    """Reverse of each traced scene crossing F -> S that has no exit S -> F yet: walk from S's arrival point against
    the first move she made after arriving (that's where the border is), arriving at F's traced exit point."""
    out = {}
    have = {(n['scene'], n['to'].split(':')[0].split('/')[0]) for n in ns.values() if n['src'] == 'exit'}
    for k, a in ns.items():
        if a['src'] != 'exit' or a.get('x') is None or a.get('to') not in ns:
            continue
        anc = ns[a['to']]
        s, f = anc['scene'], a['scene']
        if '/' in s or '/' in f or (s, f) in have:  # buildings have their doors; only scene borders
            continue
        first = next((g['to'] for g in facts if g.get('scene') == s and g.get('from') and g.get('to')
                      and math.dist(g['from'], (anc['x'], anc['z'])) < TRAIL_GRID
                      and math.dist(g['to'], g['from']) >= TRAIL_MIN), None)
        if not first:
            continue
        dx, dz = anc['x'] - first[0], anc['z'] - first[1]
        L = math.hypot(dx, dz)
        back = f'{f}:back<{s}'
        out[back] = {'scene': f, 'name': f'back<{s}', 'x': a['x'], 'z': a['z'], 'src': 'anchor'}
        out[f'{s}:exit>{back}'] = {'scene': s, 'name': f'exit>{back}', 'src': 'exit', 'to': back, 'back': True,
                                   'x': anc['x'] + dx / L * BACK_PUSH, 'z': anc['z'] + dz / L * BACK_PUSH,
                                   'cost': BACK_COST}
    return out


NO_COORDS_COST = 30.0      # a link whose exit position is unknown and has no direction: explore


def target_of(n):
    """Where to walk for a node: its coordinates, else its aim (the other side of a door), else None (explore)."""
    if n.get('x') is not None:
        return n['x'], n['z']
    return n.get('aim')


WALL_NEAR = 1.0            # world units: a straight walk passing this close to a wall stop is blocked
WALL_COST = 50.0


EVENTS = os.path.join(ROOT, 'events.jsonl')
STUCK_AT = (r'Player locomotion failed at (\w+) \((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)'
            r'|Path blocked timeout exceeded at \((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)')


def event(what, **kw):
    """Every nav event and every skip with its reason, whether or not a run is open (retro 2026-10-29)."""
    import time
    os.makedirs(ROOT, exist_ok=True)
    with open(EVENTS, 'a') as fh:
        fh.write(json.dumps({'t': round(time.time(), 1), 'what': what, **kw}) + '\n')


def log_position(txt):
    """Last exact position the game logged when a walk failed (free reading, L67): (scene or None, x, z) or None.
    txt = decoded log text."""
    import re
    m = None
    for m in re.finditer(STUCK_AT, txt):
        pass
    if not m:
        return None
    if m.group(1):
        return m.group(1), float(m.group(2)), float(m.group(4))
    return None, float(m.group(5)), float(m.group(7))


PATH_FAIL = (r'Player failed to pathfind from\s+\((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\) to\s+at '
             r'\((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)')


def log_pathfail(txt):
    """Last 'failed to pathfind' line (a click on ground she can't reach): ((x, z) where she is, (x, z) clicked)."""
    import re
    m = None
    for m in re.finditer(PATH_FAIL, txt):
        pass
    if not m:
        return None
    v = [float(g) for g in m.groups()]
    return (v[0], v[2]), (v[3], v[5])


OBJECTS = os.path.join(ROOT, 'objects.json')
OBJ_AT = re.compile(r'(?:target=|to )([A-Za-z]\w*?)(?:\(Clone\))?(?: \(\d+\))? at \((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)')
WALKABLE = {'GardenBed'}   # objects she stands on to use (not obstacles)
OBJ_NEAR = 0.7             # world units: a line this close to an object's centre hits it (hives 1.25 apart, D149)


def objects_from_log(txt):
    """[(name, x, z)] of objects the game log names with a position (`target=BeeHive(Clone) at (2.72, 0.10, -23.46)`,
    `failed to pathfind … to BeeHive(Clone) at …`), walkable ones excluded (L79)."""
    return [(m.group(1), float(m.group(2)), float(m.group(4))) for m in OBJ_AT.finditer(txt)
            if m.group(1) not in WALKABLE]


def objects_load(path=None):
    return _read_json(path or OBJECTS, {})


def objects_learn(area, objs, path=None):
    """Add objects seen in `area` (deduped to 0.1 units). Returns how many were new."""
    if not area or not objs:
        return 0
    data = objects_load(path)
    have = {(o[0], round(o[1], 1), round(o[2], 1)) for o in data.get(area, [])}
    new = []
    for n, x, z in objs:
        k = (n, round(x, 1), round(z, 1))
        if k not in have:
            have.add(k)
            new.append([n, round(x, 2), round(z, 2)])
    if new:
        data.setdefault(area, []).extend(new)
        _write_json(path or OBJECTS, data)
    return len(new)


def walls(facts, objects=None):
    """{area: [(x, z, dx, dz)]}: where walks stopped against a barrier (exact, from the game log, L67), with the
    direction she was walking (from -> to; 0, 0 unknown): the barrier lies that way (L73); plus objects the log named
    with a position (hives, the well…: obstacles, no direction, L79)."""
    out = {}
    for f in facts:
        if f.get('result') in ('stuck', 'blocked') and f.get('to'):
            d = (f['to'][0] - f['from'][0], f['to'][1] - f['from'][1]) if f.get('from') else (0.0, 0.0)
            out.setdefault(f['scene'], []).append((*f['to'], *d))
    for area, objs in (objects_load() if objects is None else objects).items():
        for _, x, z in objs:
            out.setdefault(area, []).append((x, z, None, None))  # None = a solid object (blocks from any side)
    return out


WALL_ANGLE = 60            # degrees: a walk starting at a wall point this close to the stuck direction is blocked


def _seg_dist(p, a, b):
    ax, az, bx, bz = *a, *b
    L2 = (bx - ax) ** 2 + (bz - az) ** 2
    t = 0 if not L2 else max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - az) * (bz - az)) / L2))
    return math.hypot(p[0] - ax - t * (bx - ax), p[1] - az - t * (bz - az))


def walk_cost(a, b, ws=()):
    """Straight-walk cost a -> b: distance, + WALL_COST if the line passes a wall stop (not at its very start: a
    walk away from a wall is fine)."""
    d = math.hypot(b[0] - a[0], b[1] - a[1])

    def hit(w):
        wx, wz, *wd = w
        if wd and wd[0] is None:  # a solid object: blocks any line passing within reach, even from right beside it
            return _seg_dist((wx, wz), a, b) < OBJ_NEAR
        if math.dist((wx, wz), a) > WALL_NEAR:
            return _seg_dist((wx, wz), a, b) < WALL_NEAR
        if not wd or not any(wd) or not d:  # starting at the wall: blocked only straight into it again
            return False
        cos = ((b[0] - a[0]) * wd[0] + (b[1] - a[1]) * wd[1]) / (d * math.hypot(*wd))
        return cos > math.cos(math.radians(WALL_ANGLE))
    blocked = any(hit(w) for w in ws)
    return d + (WALL_COST if blocked else 0)


def straight_cost(a, b, ws=()):
    """Cost of a never-walked straight line a -> b: length, walls, one reading, and unseen ground beyond one hop."""
    return walk_cost(a, b, ws) + STEP_COST + max(0.0, math.dist(a, b) - STRAIGHT_OK) * LONG_FACTOR


def edges_graph(facts, ns, recipes=None, now=None):
    """[(a, b, cost, kind)] over node keys. recipes = edges.json keys 'A>B' (anchor names)."""
    fails = {}
    for f in facts:
        if f.get('goal') and f.get('result') in ('short', 'still'):
            fails[f'{f.get("scene")}:{f["goal"]}'] = fails.get(f'{f.get("scene")}:{f["goal"]}', 0) + 1
    ws = walls(facts)
    out = []
    by_scene = {}
    for k, n in ns.items():
        by_scene.setdefault(n['scene'], []).append(k)
    for keys in by_scene.values():
        for a in keys:
            if ns[a].get('x') is None:
                continue
            for b in keys:
                if a != b:
                    tb = target_of(ns[b])
                    c = straight_cost((ns[a]['x'], ns[a]['z']), tb, ws.get(ns[a]['scene'], ())) if tb else NO_COORDS_COST
                    out.append((a, b, c + 5 * fails.get(b, 0), 'walk'))
    for (s, x, z), ends in trail(facts).items():  # proven walks: their length, walls don't count (she got through)
        for ex, ez in ends:
            out.append((trail_key(s, x, z), trail_key(s, ex, ez), math.dist((x, z), (ex, ez)) * TRAIL_FACTOR, 'walk'))
    for k, n in ns.items():
        if n['src'] == 'exit' and n.get('to') in ns:
            out.append((k, n['to'], n.get('cost', 5.0), 'link'))
    status = edge_status(facts, now or {})
    by_name = {}
    for k, n in ns.items():
        by_name.setdefault(n['name'], k)
    for r in recipes or []:
        a, _, b = r.partition('>')
        if a in by_name and b in by_name and status.get(r, {}).get('status') != 'suspect-wall':
            out.append((by_name[a], by_name[b], 3.0, 'replay'))
    return out


def plan(ns, es, start, goal, ws=None):
    """Dijkstra from start = (scene, x, z) to the node named `goal` (or a node key). Returns
    [(kind, node_key)] steps, or None. The start connects to every node of its scene by a walk edge."""
    import heapq
    targets = [k for k, n in ns.items() if k == goal or n['name'] == goal]
    if not targets:
        return None
    adj = {}
    for a, b, c, kind in es:
        adj.setdefault(a, []).append((b, c, kind))
    s, x, z = start
    adj['@start'] = [(k, straight_cost((x, z), target_of(n), (ws or {}).get(s, ())) if target_of(n) else NO_COORDS_COST,
                      'walk') for k, n in ns.items() if n['scene'] == s]
    dist, prev = {'@start': 0.0}, {}
    q = [(0.0, '@start')]
    while q:
        d, u = heapq.heappop(q)
        if u in targets:
            steps = []
            while u != '@start':
                p, kind = prev[u]
                steps.append((kind, u))
                u = p
            return steps[::-1]
        if d > dist.get(u, float('inf')):
            continue
        for v, c, kind in adj.get(u, []):
            if d + c < dist.get(v, float('inf')):
                dist[v], prev[v] = d + c, (u, kind)
                heapq.heappush(q, (d + c, v))
    return None


def layers(facts, calib, ns, prints_n):
    """One line per area: what each layer knows there. L4 map (outdoors only) -> L3 graph -> L2 calib -> L1 prints.
    prints_n = {area: number of stored prints}."""
    areas = sorted({f['scene'] for f in facts if f.get('scene')} | set(calib) | {n['scene'] for n in ns.values()})
    out = []
    for a in areas:
        if outdoor(a):
            mf = map_fit(facts, a)
            l4 = f'map {mf["n"]} pins ±{mf["err"]}' if mf else f'map {len(map_pairs(facts, a))} pins (no fit: need 2 apart)'
        else:
            l4 = 'map — (indoor)'
        kinds = {}
        for n in ns.values():
            if n['scene'] == a:
                kinds[n['src']] = kinds.get(n['src'], 0) + 1
        l3 = 'graph ' + (', '.join(f'{v} {k}' for k, v in sorted(kinds.items())) or 'empty')
        c = calib.get(a)
        l2 = f'calib {c["kept"]}/{c["n"]} ±{c["err"]}' if c else f'calib none ({len(calib_samples(facts, a))}/{MIN_SAMPLES} samples)'
        n, share, cut = img_accuracy(facts, a)
        l1 = f'prints {prints_n.get(a, 0)}' + (f', {share:.0%} ok of {n}' + (' TRUSTED' if img_trusted(facts, a, cut or 0) else '')
                                                 if n else '')
        out.append(f'{a}: L4 {l4} | L3 {l3} | L2 {l2} | L1 {l1}')
    return out


# ---------------------------------------------------------------- coverage matrix (L67)
# Outdoors: one grid over the map picture (all outdoor scenes share it), COVER_CELL map px per cell; facts are placed
# by their pin, or by world -> map through their scene's fit. Indoors: a world grid per area. A cell is covered
# when it has every layer: L4 a map pin (outdoors only), L3 an exact reading, L2 a confirmed prediction (a calibrated
# walk landed < 1 unit from where it was predicted), L1 an image print.
COVER_CELL = 40            # map px
INDOOR_CELL = 3.0          # world units
PRED_OK = 1.0


def world_to_map(fit, x, z):
    return (x - fit['b']) / fit['a'], (z - fit['d']) / fit['c']


def cell_of(area, x, z, fits):
    """Coverage cell of a world point: ('map', cx, cy) outdoors (None without a map fit), (area, cx, cz) indoors."""
    if outdoor(area):
        fit = fits.get(area)
        if not fit:
            return None
        mx, my = world_to_map(fit, x, z)
        return ('map', int(mx // COVER_CELL), int(my // COVER_CELL))
    return (area, math.floor(x / INDOOR_CELL), math.floor(z / INDOOR_CELL))


def light(hour):
    """Lighting period of a game hour (same bands as wf.light_period): prints look different in each."""
    return 'day' if 7 <= hour < 17 else 'dusk' if 17 <= hour < 20 else 'night'


def coverage(facts, fits, printed, period=None):
    """{cell: set of layers present}; printed = set of fact t that have a stored print. period ('day'/'dusk'/'night'):
    L1 counts only prints taken in that light (a place looks different at night)."""
    out = {}
    for f in facts:
        a, to = f.get('scene'), f.get('to')
        if not a or f.get('stale'):
            continue
        if f.get('pin') and outdoor(a):
            out.setdefault(('map', f['pin'][0] // COVER_CELL, f['pin'][1] // COVER_CELL), set()).add('L4')
        if not to:
            continue
        c = cell_of(a, to[0], to[1], fits)
        if c is None:
            continue
        s = out.setdefault(c, set())
        s.add('L3')
        if f.get('pred') and f.get('result') in ('arrived', 'short', 'moved', 'near') and not f.get('dirty') \
                and math.dist(f['pred'], to) < PRED_OK:
            s.add('L2')
        if f.get('t') in printed and (period is None or light(f.get('hour', 12)) == period):
            s.add('L1')
    return out


def missing(cell, cov):
    need = ('L4', 'L3', 'L2', 'L1') if cell and cell[0] == 'map' else ('L3', 'L2', 'L1')
    return [l for l in need if l not in cov.get(cell, set())]


def coverage_matrix(cov, key='map', roads=None, here=None):
    """Text grid of one coverage key ('map' or an indoor area): digit = layers present, '·' road (from the last map
    picture) with no data, '@' = Tara's cell. roads = set of (cx, cy) cells that have road."""
    cells = {(c[1], c[2]): v for c, v in cov.items() if c[0] == key}
    pts = set(cells) | (roads or set())
    if not pts:
        return '(no data)'
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    rows = [f'     x {x0}..{x1} (cells of {COVER_CELL} map px)' if key == 'map' else
            f'     x {x0}..{x1}, rows = z (cells of {INDOOR_CELL} units)']
    for y in range(y0, y1 + 1) if key == 'map' else range(y1, y0 - 1, -1):  # world z grows north (screen up)
        row = ''
        for x in range(x0, x1 + 1):
            if here and (x, y) == here:
                row += '@'
            elif (x, y) in cells:
                row += str(len(cells[(x, y)]))
            elif roads and (x, y) in roads:
                row += '·'
            else:
                row += ' '
        rows.append(f'{y:4d} {row}')
    return '\n'.join(rows)


# ---------------------------------------------------------------- 3. vectors: place fingerprints
IMG_K = 3
IMG_MIN = 5                # prints needed in a scene before predicting
IMG_OK = 1.5               # world units: a correct image localisation
IMG_GATE = (20, 0.8)       # last N evaluated facts with d under the cut, share that must be correct


def prints_load(area, root=None):
    """{fact t: print vector} of one area (tools/nav/<area>/prints.jsonl)."""
    import base64
    import numpy as np
    path = os.path.join(area_dir(area, root), 'prints.jsonl')
    out = {}
    try:
        with open(path) as fh:
            for l in fh:
                if l.strip():
                    r = json.loads(l)
                    out[r['t']] = np.frombuffer(base64.b64decode(r['v']), dtype=np.float32)
    except OSError:
        pass
    return out


def print_append(area, t, v, root=None):
    import base64
    import numpy as np
    path = os.path.join(area_dir(area, root), 'prints.jsonl')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as fh:
        fh.write(json.dumps({'t': t, 'v': base64.b64encode(np.asarray(v, np.float32).tobytes()).decode()}) + '\n')


def img_predict(facts, prints, scene, v, exclude=None):
    """World point from the nearest stored prints of this scene: ({'pred': [x, z], 'd': nearest distance}) or None."""
    import numpy as np
    refs = [(f['to'], prints[f['t']]) for f in facts
            if f.get('scene') == scene and f.get('to') and f.get('t') in prints and f.get('t') != exclude
            and not f.get('stale')]
    if len(refs) < IMG_MIN:
        return None
    ds = sorted(((float(np.linalg.norm(w - v)), to) for to, w in refs if len(w) == len(v)), key=lambda r: r[0])[:IMG_K]
    if not ds:
        return None
    ws = [1 / max(d, 1e-6) for d, _ in ds]
    x = sum(w * to[0] for w, (_, to) in zip(ws, ds)) / sum(ws)
    z = sum(w * to[1] for w, (_, to) in zip(ws, ds)) / sum(ws)
    return {'pred': [round(x, 3), round(z, 3)], 'd': round(ds[0][0], 4)}


def img_accuracy(facts, scene):
    """(evaluated, correct share, distance cut) over the scene's facts that recorded an image prediction.
    The cut = the 75th percentile of d among correct ones (looser matches are not trusted)."""
    ev = [(f['img']['d'], math.hypot(f['img']['pred'][0] - f['to'][0], f['img']['pred'][1] - f['to'][1]))
          for f in facts if f.get('scene') == scene and f.get('img') and f.get('to') and not f.get('stale')]
    if not ev:
        return 0, 0.0, None
    good = sorted(d for d, e in ev if e <= IMG_OK)
    cut = good[int(0.75 * (len(good) - 1))] if good else None
    recent = [e for d, e in ev if cut is not None and d <= cut][-IMG_GATE[0]:]
    share = sum(e <= IMG_OK for e in recent) / len(recent) if recent else 0.0
    return len(ev), round(share, 2), cut


def img_trusted(facts, scene, d):
    """May an image prediction with nearest distance d replace a reading in this scene? (derived gate)"""
    n, share, cut = img_accuracy(facts, scene)
    return n >= IMG_GATE[0] and share >= IMG_GATE[1] and cut is not None and d <= cut
