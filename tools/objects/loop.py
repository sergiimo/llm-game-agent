"""Goal-driven click loop on detected objects: goto(q, wf). Every action is a click at a frame point (a detection's point,
or a model-answered point); no coordinates are stored. Each frame: region from the log scene + view coverage, detect the
target kind with the target region's thresholds (click it as soon as it is visible, even from outside its region),
else click the next region step (door / exit / the region's own objects). Stuck or lost -> ASK: ask-<n>.png/.json in the
run dir + NeedVision; the agent writes ask-<n>.answer.json ({"point": [x, y]}) with `answer(n, x, y)`
(`./wf py "from objects.loop import answer; answer(1, 900, 500)"`), the next goto() reads it and clicks it once.
A second no-progress ask for the same goal -> Failed."""
import glob
import json
import os
import re
import time
from collections import namedtuple

import numpy as np

from . import detect as D, graph as G, identity as I, regions as R, store as S, views as V
from .bubbles import owner
from .query import Q, path  # noqa: F401

BUBBLE_KEEP = 60     # px: never click this close to a bubble that is not the wanted one
STILL = 0.01         # frame-vector distance below which two frames count as the same
STALL = 3            # clicks without a change = no progress
SCENE_WAIT = 3.0     # s: how long to poll for a scene change after clicking a door / exit
SCENE_POLL = 0.2
NEAR = 300           # px: a wanted bubble this close to the clicked point = arrived

Arrival = namedtuple('Arrival', 'node region point frames')
ACTIVE = frozenset()  # {(node_id, region_id), ...}: every resolved object whose bubble is currently available
OBSERVED_GRAPH = None  # last frame's graph, including transient Tara/bubble/near observations; inspected by available()
STATE = {'goal': None, 'asks': 0}   # no-progress asks for the current goal (reset on arrival)


class NeedVision(Exception):
    def __init__(self, path):
        super().__init__(f'NEED_VISION: look at {path}, answer with answer(n, x, y), then call goto again')
        self.path = path


def available():
    """Active objects in the latest observed frame: graph id/region, direction from Tara, and bubble click data."""
    if OBSERVED_GRAPH is None:
        return []
    directions = {e['b']: e.get('direction') for e in OBSERVED_GRAPH.edges('Tara', 'near')}
    out = []
    for n in OBSERVED_GRAPH.nodes.values():
        bubble = OBSERVED_GRAPH.state_value(n.id, 'bubble')
        if bubble is not None:
            out.append({'id': n.id, 'region': n.region, 'direction': directions.get(n.id),
                        'bubble': bubble.get('kind'), 'point': bubble.get('point')})
    return sorted(out, key=lambda x: x['id'])


try:
    from game.core import Failed
except Exception:   # usable without the game package
    class Failed(Exception):
        pass


def _ask_dir(wf):
    p = wf.run_path()
    if p:
        d = p if os.path.isdir(p) else os.path.dirname(p)
        if d and os.path.isdir(d):
            return d
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.shots')
    os.makedirs(d, exist_ok=True)
    return d


def answer(n, x, y, directory=None):
    """Store the model's answer to ask n: the frame point to click (a walkable point toward the target). The next
    goto() for the same goal clicks it once. Prints and returns what it stored."""
    if directory is None:
        import wf as W   # the wf module (the real tool)
        directory = _ask_dir(W)
    p = os.path.join(directory, f'ask-{n}.answer.json')
    with open(p, 'w') as f:
        json.dump({'point': [int(x), int(y)]}, f)
    msg = f'stored answer for ask {n}: click ({int(x)}, {int(y)}); re-run the call'
    print(msg)
    return msg


def label(n, kind, x0, y0, x1, y1, state=None, directory=None, store=None, wf=None):
    """Teach the store from ask n's clean frame: crop (x0, y0, x1, y1) becomes an example of `kind` (source 'model', light
    from the frame). The target was visible but not detected; re-run the call and it is found. Prints and returns it."""
    from PIL import Image
    if directory is None:
        import wf as W
        directory = _ask_dir(W)
        wf = wf or W
    img = Image.open(os.path.join(directory, f'ask-{n}.frame.png')).convert('RGB')
    W_, H_ = img.size
    if not (0 <= x0 < x1 <= W_ and 0 <= y0 < y1 <= H_):
        raise ValueError(f'box outside the frame ({W_}x{H_})')
    light = None
    try:
        light = wf.light_period(wf.game_hour(img))
    except Exception:   # noqa: BLE001
        pass
    st = store or S.Store()
    crop = img.crop((int(x0), int(y0), int(x1), int(y1)))
    new = not st.count(kind)
    ex = st.add(kind, crop, D.dino.mean_vector(crop), state=state, light=light, source='model', force=True)
    msg = (f'added {kind} (new kind)' if new else f'labelled {kind}') + \
          f' ({int(x0)},{int(y0)},{int(x1)},{int(y1)}) from ask {n}: example {ex.id}; re-run the call'
    print(msg)
    return msg


def _num(p):
    s = os.path.basename(p)[4:].split('.')[0]
    return int(s) if s.isdigit() else 0


def _pending_answer(d, goal):
    """(n, point) of the newest ask for `goal` with an unused answer, else None; marks it used. An answer belongs to
    the goal stored in its ask-<n>.json; answers to other goals are left alone."""
    for p in sorted(glob.glob(os.path.join(d, 'ask-*.answer.json')), key=_num, reverse=True):
        try:
            data = json.load(open(p))
            pt = (int(data['point'][0]), int(data['point'][1]))
            asked = json.load(open(os.path.join(d, f'ask-{_num(p)}.json')))['goal']
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
        if asked != goal:
            continue
        os.replace(p, p.replace('.answer.json', '.answer.used.json'))
        return _num(p), pt
    return None


def _write_ask(wf, img, goal, step, dets):
    from PIL import ImageDraw
    d = _ask_dir(wf)
    n = max([_num(p) for p in glob.glob(os.path.join(d, 'ask-*.json'))], default=0) + 1
    im = img.convert('RGB').copy()
    dr = ImageDraw.Draw(im)
    for x in dets:
        dr.rectangle(x.box, outline=(255, 0, 0), width=3)
        dr.text((x.box[0], max(0, x.box[1] - 12)), f'{x.kind} {x.dist:.1f}', fill=(255, 255, 0))
    png = os.path.join(d, f'ask-{n}.png')
    img.convert('RGB').save(os.path.join(d, f'ask-{n}.frame.png'))   # clean frame for label()
    im.save(png)
    with open(os.path.join(d, f'ask-{n}.json'), 'w') as f:
        json.dump({'goal': goal, 'step': step, 'n': n,
                   'detections': [{'kind': x.kind, 'point': list(x.point), 'z': round(x.dist, 2)} for x in dets]}, f)
    return png


ASKS = 'asks.json'
MAX_ASKS = 2         # questions per goal; the next no-progress / not-detected -> Failed (escalate)


def goal_key(q):
    return repr((q.kind, q.offers, sorted(q.state.items())))


def _asks_path(wf):
    return os.path.join(_ask_dir(wf), ASKS)


def _asks(wf):
    try:
        return json.load(open(_asks_path(wf)))
    except (OSError, ValueError):
        return {}


def _set_asks(wf, goal, n):
    a = _asks(wf)
    if n:
        a[goal] = n
    else:
        a.pop(goal, None)
    with open(_asks_path(wf), 'w') as f:
        json.dump(a, f)


def _ask(wf, img, goal, step, dets):
    """The one way to NeedVision: counted per goal (kept across goal changes, cleared on arrival); the third ask for a
    goal is Failed instead."""
    n = _asks(wf).get(goal, 0)
    if n >= MAX_ASKS:
        raise Failed(f'{goal}: {MAX_ASKS} answers didn\'t help, escalate ({step})')
    _set_asks(wf, goal, n + 1)
    raise NeedVision(_write_ask(wf, img, goal, step, dets))


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** .5


def click_point(det, bubbles, keep=BUBBLE_KEEP):
    """The detection's point, or the nearest point of its box that is >= keep px from every unwanted bubble (best effort:
    the farthest box point when none is)."""
    p = det.point
    if all(_dist(p, b) >= keep for b in bubbles):
        return p
    x0, y0, x1, y1 = det.box
    cs = [(int(x0 + (x1 - x0) * k / 20), int(y0 + (y1 - y0) * j / 20)) for k in range(21) for j in range(21)]
    ok = [c for c in cs if min(_dist(c, b) for b in bubbles) >= keep]
    if ok:
        return min(ok, key=lambda c: _dist(c, p))
    return max(cs, key=lambda c: min(_dist(c, b) for b in bubbles))


def _offers(graph, n):
    """Bubble kinds that offer an action of the node: the graph's action names mapped through game.affordances.KINDS
    (fill_can <- full_watering_can, harvest <- pickup ...); names without an entry stand for themselves."""
    try:
        from game.affordances import KINDS
    except Exception:   # noqa: BLE001 (usable without the game package)
        KINDS = {}
    out = set()
    for id in (n.id, n.region, n.kind):
        for e in graph.edges(id, 'offers'):
            out |= set(KINDS.get(e['b'], ())) | {e['b']}
    return out


def _known_kinds():
    """Bubble kinds the game's affordances know (a bubble of another kind is 'unknown': e.g. a growing bed's tulip)."""
    try:
        from game.affordances import KINDS
    except Exception:   # noqa: BLE001
        return set()
    return set().union(*KINDS.values())


def _active_candidates(graph, candidates, q, vis, bubs, frame, target=None, last=None):
    """{node_id: (node, bubble_point, bubble_kind)} for every contextual candidate with an available interaction bubble.

    A bubble means Tara is in interaction range of its object. Several objects can therefore be active at once (for
    example six adjacent garden beds). Ownership selects the candidate; it does not have to be the member the movement
    loop would otherwise choose first. The old near-click fallback remains only for an unowned bubble after targeting a
    particular object, and still requires a bubble kind that object can offer (or an as-yet unknown kind).
    """
    nodes = {n.id: n for n in candidates}
    for n in nodes.values():
        graph.set_state(n.id, 'bubble', None, frame, 'frame')
    by_det = {id(d): nodes[node_id] for node_id, d in vis.items() if node_id in nodes}
    dets = list(vis.values())
    known = _known_kinds()
    out = {}
    unowned = []
    for bp, kind in bubs:
        d = owner(bp, dets)
        n = by_det.get(id(d)) if d is not None else None
        compatible = n is not None and (kind in _offers(graph, n) or kind not in known)
        if compatible:
            out.setdefault(n.id, (n, bp, kind))
        elif n is None:
            unowned.append((bp, kind))
    if target is not None and target.id not in out:
        tdet = vis[target.id]
        offers = _offers(graph, target)
        for bp, kind in unowned:
            near = (last is not None and _dist(bp, last) < NEAR) or _dist(bp, tdet.point) < NEAR
            if near and (kind in offers or (q.offers is None and kind not in known)):
                out[target.id] = (target, bp, kind)
                break
    for n, bp, kind in out.values():
        graph.set_state(n.id, 'bubble', {'kind': kind, 'point': [bp[0], bp[1]]}, frame, 'frame')
    return out


def _direction(a, b, dead=40):
    """Screen-relative cardinal direction from point a to b (y decreases north)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ns = 'north' if dy < -dead else 'south' if dy > dead else ''
    ew = 'west' if dx < -dead else 'east' if dx > dead else ''
    return '-'.join(x for x in (ns, ew) if x) or 'overlapping'


def _interaction_proof(wf, mark, target):
    """A post-click game-log action on the selected kind proves reach even when bubble ownership was unresolved."""
    if mark is None or target is None or not hasattr(wf, 'log_since'):
        return None
    try:
        lines = wf.log_since(mark).splitlines()
    except Exception:  # noqa: BLE001 (optional evidence must not break navigation)
        return None
    for line in lines:
        m = re.search(r'>\s*\w+\b.*?target=(\w+)', line)
        if m and m.group(1) == target.kind:
            return line
    return None


def _observe_tara(graph, fr, cur, vis, active, frame):
    """Add the Tara node (transient when the graph has none) + screen-relative `near` edges to every bubble-active object in this frame."""
    tara = next((d for d in fr.dets(cur, ('Tara',)) if d.kind == 'Tara'), None)
    if tara is None:
        return None
    if 'Tara' not in graph.nodes:   # the stored Tara node (the chain cursor) stays; only its frame states / edges are transient
        graph.nodes['Tara'] = G.Node('Tara', 'unique', 'Tara', cur, transient=True)
    graph.nodes['Tara'].region = cur
    graph.set_state('Tara', 'screen', {'point': list(tara.point), 'box': list(tara.box), 'z': round(tara.dist, 2)},
                    frame, 'frame')
    for node_id, (n, _, kind) in active.items():
        d = vis.get(node_id)
        if d is None:
            continue
        graph.add_edge('Tara', n.id, 'near', direction=_direction(tara.point, d.point), basis='screen',
                       bubble=kind, source='frame', frame=frame)
    return graph.nodes['Tara']


def _region_of(graph, n):
    for c in reversed(graph.chain(n.id)):
        if graph.nodes[c].type == 'region' and c != n.id:
            return c
    return None


def _context_candidates(graph, cur, query_candidates):
    """Query candidates plus every unique/member object in the current region, deduped in graph order.

    Bubble ownership must see neighbouring object kinds before the query filters them: a beehive bubble above a bed
    must belong to the hive, then fail a GardenBed query, rather than being assigned to the only kind we searched.
    """
    ids = {n.id for n in query_candidates}
    out = list(query_candidates)
    for n in graph.nodes.values():
        if n.type in ('unique', 'member') and n.id not in ids and _region_of(graph, n) == cur:
            out.append(n)
            ids.add(n.id)
    return out


class _Frame:
    """One frame's evidence (detections cached per region)."""

    def __init__(self, wf, graph, store, detect_fn):
        self.graph, self.store, self.fn = graph, store, detect_fn
        self.img = wf.grab()
        self._d = {}

    def dets(self, region, extra=()):
        kinds = list(dict.fromkeys(list(R.scope(self.graph, region)) + list(extra) + ['Tara']))
        key = (region, tuple(kinds))
        if key not in self._d:
            self._d[key] = self.fn(self.img, self.store, kinds=kinds, region=region, exclude=self.containers(region))
        return self._d[key]

    def containers(self, region):
        """Kinds of the region itself and its ancestor regions: they stay out of the per-patch competition."""
        return tuple(dict.fromkeys(self.graph.nodes[c].kind for c in self.graph.chain(region)
                                   if c in self.graph.nodes and self.graph.nodes[c].type == 'region'))


def _bubbles(wf, img):
    out = []
    for b in wf.find_bubbles(img) or []:
        try:
            kind = wf.bubble_kind(img, b)[0]
        except Exception:
            kind = None
        out.append(((int(b[0]), int(b[1])), kind))
    return out


def _visible(fr, cands):
    """{node_id: Detection} of candidates in the frame (target region's thresholds; group members deduped + assigned)."""
    g = fr.graph
    unit = lambda n: g.nodes[n.region] if n.type == 'member' else n   # noqa: E731
    by_region = {}
    for n in cands:
        by_region.setdefault(_region_of(g, unit(n)), set()).add(unit(n).kind)
    vis = {}
    for reg, kinds in by_region.items():
        dets = fr.dets(reg, kinds)
        done = set()
        for n in cands:
            grp = unit(n)
            if _region_of(g, grp) != reg:
                continue
            mine = [d for d in dets if d.kind == grp.kind]
            if n.type == 'unique':
                if mine:
                    vis[n.id] = mine[0]
            elif grp.id not in done and mine:
                done.add(grp.id)
                if grp.extra.get('pattern'):
                    mine = I.dedupe_for(grp, mine)
                    hives = sorted(d.point[1] for d in dets if d.kind == 'BeeHive')
                    anchor = hives[len(hives) // 2] if hives and grp.kind == 'GardenBed' else None
                    got, _ = I.assign(grp, g.members(grp.id), mine, anchor)
                    vis.update(got)
    return vis


def _step_target(fr, cur, step, target=None):
    """Detection to click for a region step, or None. `enter` a view region: the best detected member of it (children
    kinds, its own thresholds; the target's own kind first, else the highest z); the region's own peak only when no
    member is detected."""
    g, dets = fr.graph, fr.dets(cur)
    if step.action == 'exit':
        return next((d for d in dets if d.kind == step.node.kind), None)
    r = step.node
    if r.extra.get('signal') == 'view':
        inner = [d for d in fr.dets(r.id) if d.kind != r.kind]   # its members, seen from outside with its thresholds
        if inner:
            grp = fr.graph.nodes[target.region] if target is not None and target.type == 'member' else target
            same = [d for d in inner if grp is not None and d.kind == grp.kind]
            return (same or inner)[0]
        return next((d for d in dets if d.kind == r.kind), None)
    door = next((e['a'] for e in g.edges(None, 'leads_to') if e['b'] == r.id), None)
    kind = g.nodes[door].kind if door in g.nodes else r.kind
    return next((d for d in dets if d.kind == kind), None)


def goto(q, wf, max_clicks=8, graph=None, store=None, detect_fn=None):
    """Click until `q` is reached: any matching node has a compatible owned bubble (or the targeted node has one near
    its last click). Every showing bubble is transient graph state, so several nodes can be active simultaneously.
    Returns Arrival(node, region, point, frames); raises NeedVision (a question was written) or Failed."""
    global ACTIVE, OBSERVED_GRAPH
    graph = graph or _default_graph()
    store = store or S.Store()
    fn = detect_fn or D.detect
    goal = goal_key(q)
    STATE['goal'] = goal
    clicks, frames, vecs, last = 0, 0, [], None   # last = point of the last target click
    pend = _pending_answer(_ask_dir(wf), goal)
    if pend:
        wf.run_action(f'click:{pend[1][0]}:{pend[1][1]}')
        wf.wait_settle()
        clicks += 1
    while True:
        graph.clear_frame()
        fr = _Frame(wf, graph, store, fn)
        frames += 1
        cur, _ = R.current_region(graph, wf.current_scene(), lambda r: fr.dets(r))
        cands = q.run(graph, cur)
        context = _context_candidates(graph, cur, cands)
        all_vis = _visible(fr, context)
        vis = {n.id: all_vis[n.id] for n in cands if n.id in all_vis}
        order = q.run(graph, cur, visible=set(vis))
        target = next((n for n in order if n.id in vis), None)
        bubs = _bubbles(wf, fr.img)
        active = _active_candidates(graph, context, q, all_vis, bubs, frames, target, last)
        _observe_tara(graph, fr, cur, all_vis, active, frames)
        OBSERVED_GRAPH = graph
        ACTIVE = frozenset((n.id, cur) for n, _, _ in active.values())
        arrived = next((n for n in order if n.id in active), None)
        if arrived is not None:
            _set_asks(wf, goal, 0)
            return Arrival(arrived, cur, active[arrived.id][1], frames)
        if clicks >= max_clicks:
            raise Failed(f'goto: not reached after {max_clicks} clicks')
        if clicks:
            vecs.append(V.frame_vector(fr.img))
            tail = vecs[-(STALL + 1):]
            if len(tail) > STALL and all(1 - float(np.dot(a, b)) < STILL for a, b in zip(tail, tail[1:])):
                _stuck(wf, fr, goal, 'the frame does not change', fr.dets(cur))
        others = [bp for bp, _ in bubs]
        dest = None
        if target is not None:
            dest = _dest_scene(graph, target)
            pt = click_point(vis[target.id], others)
            last = vis[target.id].point
        else:
            steps = path(graph, cur, order[0]) if order else []
            step = steps[0] if steps else None
            det = _step_target(fr, cur, step, order[0] if order else None) if step and step.action != 'reach' else None
            if det is None:
                what = f'{step.action} {step.node.id}: not detected' if step else 'no target in the graph'
                _ask(wf, fr.img, goal, what, fr.dets(cur))
            dest = _dest_scene(graph, None, step)
            pt = click_point(det, others)
            last = None
        before = wf.current_scene()
        mark = wf.log_mark() if hasattr(wf, 'log_mark') else None
        wf.run_action(f'click:{pt[0]}:{pt[1]}')
        wf.wait_settle()
        clicks += 1
        proof = _interaction_proof(wf, mark, target)
        if proof is not None:
            graph.clear_frame()
            graph.set_state(target.id, 'interaction', {'line': proof}, frames, 'frame')
            ACTIVE = frozenset()
            OBSERVED_GRAPH = graph
            _set_asks(wf, goal, 0)
            return Arrival(target, cur, pt, frames)
        if dest and before != dest and _wait_scene(wf, dest):   # a door / exit is reached by the scene change (no bubble)
            if target is not None:
                ACTIVE = frozenset()
                graph.clear_frame()                              # the old frame's bubbles/near edges are invalid now
                _set_asks(wf, goal, 0)
                return Arrival(target, dest, pt, frames)
            vecs.clear()


def _dest_scene(graph, node, step=None):
    """The scene region a click on `node` (a door / exit) leads to, or a scene region step's own id; else None."""
    dest = None
    if node is not None:
        dest = next((e['b'] for e in graph.edges(node.id, 'leads_to')), None)
    if dest is None and step is not None:
        if step.action == 'enter':
            dest = step.node.id
        elif step.action == 'exit':
            dest = next((e['b'] for e in graph.edges(step.node.id, 'leads_to')), None)
    n = graph.nodes.get(dest)
    return dest if n is not None and n.type == 'region' and n.extra.get('signal') == 'scene' else None


def _wait_scene(wf, scene):
    """Poll the log scene for up to SCENE_WAIT s; True when it becomes `scene`."""
    end = time.time() + SCENE_WAIT
    while True:
        if wf.current_scene() == scene:
            return True
        if time.time() >= end:
            return False
        time.sleep(SCENE_POLL)


def _stuck(wf, fr, goal, why, dets):
    _ask(wf, fr.img, goal, 'stuck: ' + why, dets)


def _default_graph():
    g = G.Graph()
    g.load(os.path.join(G.DEFAULT_DIR, 'Farm.json'))
    return g
