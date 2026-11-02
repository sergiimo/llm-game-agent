"""Graph chain strategy (spec 2026-11-02): locate a neighbour tile on screen by pattern fit (no positions: frame pixels
only), and `run` a garden task over a group chain: tile by tile, the log read for event TYPE only, every unexpected
situation = one vision question (anchor), never a guess."""
import re
from collections import namedtuple

from game import affordances, core, ui, well

from . import anchor, detect as D, identity, loop, store as S
from .graph import apply_log, cell
from .query import Q

CENTRE = (960, 540)   # frame centre in the 1920x1080 virtual frame: the camera follows Tara, so the `at` tile is nearest it


class Unexpected(Exception):
    def __init__(self, why):
        super().__init__(why)
        self.why = why


def _lines(vals, sizes):
    """Cluster index per value (input order): split sorted values only at gaps > half the median tile size, so pixel
    jitter never makes phantom rows/columns even when fewer lines than the pattern has are visible."""
    lim = .5 * sorted(sizes)[len(sizes) // 2]
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    lab, c = [0] * len(vals), 0
    for k, i in enumerate(order):
        if k and vals[i] - vals[order[k - 1]] > lim:
            c += 1
        lab[i] = c
    return lab


def locate(graph, at, target, dets):
    """The detection of `target`, fitted to the group grid relative to `at` (the tile nearest the frame centre)."""
    group = graph.nodes[graph.nodes[at].region]
    dets = identity.dedupe_for(group, list(dets))
    if len(dets) < 2:
        raise Unexpected(f'pattern fit: only {len(dets)} tile(s) visible')
    ry = _lines([d.point[1] for d in dets], [d.box[3] - d.box[1] for d in dets])
    cx = _lines([d.point[0] for d in dets], [d.box[2] - d.box[0] for d in dets])
    cells = list(zip(ry, cx))
    if len(set(cells)) < len(cells):
        raise Unexpected('pattern fit: ambiguous (two tiles in one grid cell)')
    i0 = min(range(len(dets)), key=lambda i: (dets[i].point[0] - CENTRE[0]) ** 2 + (dets[i].point[1] - CENTRE[1]) ** 2)
    (ar, ac), (tr, tc) = cell(at), cell(target)
    want = (ry[i0] + tr - ar, cx[i0] + tc - ac)
    for d, rc in zip(dets, cells):
        if rc == want:
            return d
    raise Unexpected(f'pattern fit: target not visible (offset {tr - ar},{tc - ac} from {at})')


def click_tile(det, bubbles):
    """Pixel to click on a tile, kept away from unwanted bubbles."""
    return loop.click_point(det, bubbles)


def expected_bubble(graph, node_id):
    """Predicate on an Affordance: does it look like what the predicted state of the node shows?"""
    ph = graph.phase(node_id)
    if ph == 'wilted' or (ph == 'growing' and not graph.state_value(node_id, 'watered_today')):
        return lambda a: bool(a.drop)
    if ph == 'growing':   # watered: the crop icon, no water drop
        return lambda a: not a.drop
    if ph == 'empty':
        return lambda a: a.kind == 'plant'
    if ph == 'ripe':
        return lambda a: a.kind == 'pickup'
    return lambda a: True


def bubble_near(affs, tile_pt, max_dx=110, max_up=(40, 260)):
    """The bubble above the clicked tile (screen-relative), closest one; None if none qualifies."""
    best, bd = None, None
    for a in affs:
        dx, up = abs(a.pt[0] - tile_pt[0]), tile_pt[1] - a.pt[1]
        if dx <= max_dx and max_up[0] <= up <= max_up[1]:
            d = dx * dx + up * up
            if bd is None or d < bd:
                best, bd = a, d
    return best


EVENTS = {'unplant': r'> unplant ', 'removed': r'> unplant_impl ', 'plant': r'> plant ', 'planted': r'totalPlanted\.',
          'water': r'> water ', 'dry_can': r'> out_of_water ', 'pickup': r'> grab_item '}


def event(mark, name, wait):
    """The log line of event `name` since `mark` (no position check: the click already pinned the target)."""
    return core.seen(EVENTS[name], mark, wait)


# ---- the runner -------------------------------------------------------------------------------------------------
Task = namedtuple('Task', 'needs act done_events')   # needs(graph, id) -> bool; act(run, id, aff) -> 'ok'|'refill'


class _Run:
    """One run() call: what the acts need (seed, skip list, current log mark)."""

    def __init__(self, graph, seed):
        self.graph, self.seed, self.mark, self.stop, self.skipped = graph, seed, 0, False, []
        self.tile_pt = CENTRE
        self.final = []   # (id, key, value, conf) set after the log replay (apply_log would overwrite them)


def _now():
    try:
        return core.WF.game_stamp() or 'vision'
    except Exception:   # noqa: BLE001
        return 'vision'


def _water(run, aff):
    mark = affordances.click(aff)
    line = core.seen(r'> (water|out_of_water) ', mark, wait=2.0)
    if line and '> water ' in line:
        return 'ok'
    if line:
        ui.close()
        well.fill_can()
        return 'refill'
    raise Unexpected('the water bubble produced neither a water nor an out_of_water event')


def _act_water(run, nid, aff):
    return _water(run, aff)


def _act_harvest(run, nid, aff):
    mark = affordances.click(aff)
    if not event(mark, 'pickup', 2.0):
        raise Unexpected('the pickup bubble produced no grab_item event')
    # the plant stays and regrows: hint only (conf .5), the next anchor settles it
    run.graph.set_state(nid, 'phase', 'growing', _now(), 'event', 0.5)
    run.graph.set_state(nid, 'watered_today', False, _now(), 'event', 0.5)
    return 'ok'


def _act_replant(run, nid, aff):
    from game.garden import crop_name
    g = run.graph
    mark = affordances.click(aff)
    if not event(mark, 'unplant', 2.0):
        raise Unexpected('the wilted bubble did not open the Remove card')
    crop = crop_name(' / '.join(ui.texts())) or None
    for _ in range(2):   # card -> (confirmation) -> exact Remove button, as garden._finish_unplant but position-free
        if ui.shows('remove', wait=0.5) and not event(mark, 'removed', 0):
            ui.press('Remove')
        if event(mark, 'removed', 1.5):
            break
    else:
        raise Unexpected('Remove was pressed but the game logged no unplant_impl')
    g.set_state(nid, 'phase', 'empty', _now(), 'event')
    g.set_state(nid, 'crop', None, _now(), 'event')
    plant = bubble_near(affordances.scan(), run.tile_pt)
    if plant is None or plant.kind != 'plant':
        raise Unexpected('no plant bubble after the bed was cleared')
    pmark = affordances.click(plant)
    want = run.seed or crop
    try:
        ui.pick_card(want)
    except core.Failed as e:
        ui.close()
        ui.close()
        run.skipped.append((nid, f'no seeds for {want}: {e}'))
        run.stop = True
        return 'stop'
    ui.press('Select')
    if not event(pmark, 'planted', 3.0):
        raise Unexpected(f'Select was pressed but {want} was not planted')
    g.set_state(nid, 'phase', 'growing', _now(), 'event')
    g.set_state(nid, 'watered_today', False, _now(), 'event')
    run.final.append((nid, 'crop', want))
    drop = bubble_near(affordances.scan(), run.tile_pt)
    if drop is None or not drop.drop:
        raise Unexpected('no water bubble on the freshly planted bed')
    out = _water(run, drop)
    if out == 'refill':
        g.set_state('Tara', 'pending_water', nid, _now(), 'event')
    return out


TASKS = {
    'replant': Task(lambda g, i: g.phase(i) == 'wilted', _act_replant, ('unplant', 'removed', 'planted', 'water')),
    'water': Task(lambda g, i: g.phase(i) == 'growing' and g.state_value(i, 'watered_today') is not True,
                  _act_water, ('water',)),
    'harvest': Task(lambda g, i: g.phase(i) == 'ripe', _act_harvest, ('pickup',)),
}


def _need_vision(prompt):
    e = loop.NeedVision(prompt)
    e.args = (prompt,)
    e.prompt = prompt
    return e


def _ask(graph, task, why, detect_fn):
    """One fresh anchor question about the current frame (a stale pending answer is cleared first); raises NeedVision."""
    anchor.clear_pending()
    img = core.WF.grab()
    prompt, _ = anchor.question(img, detect_fn(img), task, graph, why, core=core)
    graph.set_state('Tara', 'asks', (graph.state_value('Tara', 'asks') or 0) + 1, _now(), 'event')
    raise _need_vision(prompt)


def _default_detect(graph, group):
    node = graph.nodes[group]
    store = S.Store()
    return lambda img: D.detect(img, store, kinds=[node.kind], region=node.region)


def _centre(dets):
    return min(dets, key=lambda d: (d.point[0] - CENTRE[0]) ** 2 + (d.point[1] - CENTRE[1]) ** 2)


def _pitch(dets, axis):
    """Tile pitch along axis 0 (x) / 1 (y): median gap between adjacent tile lines; one line -> the tile's own size."""
    sizes = [d.box[axis + 2] - d.box[axis] for d in dets]
    lab = _lines([d.point[axis] for d in dets], sizes)
    by = {}
    for l, d in zip(lab, dets):
        by.setdefault(l, []).append(d.point[axis])
    ms = sorted(sum(v) / len(v) for v in by.values())
    gaps = sorted(b - a for a, b in zip(ms, ms[1:]))
    return gaps[len(gaps) // 2] if gaps else sorted(sizes)[len(sizes) // 2]


SHIFT = {'E': (-1, 0), 'W': (1, 0), 'S': (0, -1), 'N': (0, 1)}   # grid shift (in pitches) after Tara moves one tile that way


def _prove_shift(group, dets0, dets1, d):
    """Screen geometry (frame pixels only): after a one-tile move toward `d` the camera follows, so the whole visible grid
    shifts by one pitch the opposite way. The shift is the whole-pitch displacement k that best maps the tiles seen
    before onto the tiles seen after; it must be exactly the expected one (a tie or any other k = not proved)."""
    d0, d1 = identity.dedupe_for(group, list(dets0)), identity.dedupe_for(group, list(dets1))
    px, py = _pitch(d0, 0), _pitch(d0, 1)
    scores = {}
    for kx in range(-3, 4):
        for ky in range(-3, 4):
            scores[(kx, ky)] = sum(1 for p in d0 if any(abs(p.point[0] + kx * px - q.point[0]) < .3 * px and
                                                        abs(p.point[1] + ky * py - q.point[1]) < .3 * py for q in d1))
    top = max(scores.values())
    best = [k for k, v in scores.items() if v == top]
    if top < 1 or len(best) != 1 or best[0] != SHIFT[d]:
        raise Unexpected(f'move not proved: grid shifted {best[0] if len(best) == 1 else "ambiguously"} pitches '
                         f'(expected {SHIFT[d]} for {d})')


def _implies_bubble(g, nid):
    ph = g.phase(nid)
    return ph in ('wilted', 'empty', 'ripe') or (ph == 'growing' and g.state_value(nid, 'watered_today') is not True)


def _step(run, cur, nid, detect_fn, last, d=None):
    """Move one chain step onto `nid` (a neighbour of `cur`) and prove it from the frames, then check the bubble above
    Tara's tile against the predicted state. Tara.at is set only after the proof (a click that did not move her, or
    moved her elsewhere, is Unexpected)."""
    g = run.graph
    img, dets = core.WF.grab(), None
    dets = detect_fn(img)
    if cur != nid:
        det, prev = locate(g, cur, nid, dets), locate(g, cur, cur, dets)
        pt = click_tile(det, [a.pt for a in affordances.scan()])
        core.WF.run_action(f'click:{pt[0]}:{pt[1]}')
        core.WF.wait_settle()
        img1 = core.WF.grab()
        dets1 = detect_fn(img1)
        _prove_shift(g.nodes[nid].region and g.nodes[g.nodes[nid].region], dets, dets1, d)
        locate(g, nid, cur, dets1)   # secondary: the previous tile is visible one step back from Tara's tile
        img, dets = img1, dets1
    run.tile_pt = _centre(dets).point
    g.set_state('Tara', 'at', nid, _now(), 'event')
    b = bubble_near(affordances.scan(), run.tile_pt)
    if b is None:
        if last or _implies_bubble(g, nid):
            raise Unexpected(f'no bubble above {nid}, predicted {g.phase(nid)}')
        return None
    if not expected_bubble(g, nid)(b):
        raise Unexpected(f'bubble {b.kind}{" +drop" if b.drop else ""} above {nid} does not match predicted {g.phase(nid)}')
    return b


def _goto_node(r, at, target, detect_fn):
    """Walk the chain from `at` to `target`; returns (bubble at target, new at)."""
    b = None
    for d, nid in r.graph.hops(at, target) + [(None, target)] * (at == target):
        b = _step(r, at, nid, detect_fn, nid == target, d)
        at = nid
    return b, at


def _save_stamp():
    try:
        return core.WF.save_stamp()
    except Exception:   # noqa: BLE001
        return None


def _perform(r, t, task, target, b, detect_fn):
    """Act on `target`, replay the log into the graph, check the task's events. 'ok' | 'stop'."""
    g = r.graph
    r.mark = core.WF.log_mark()
    out = t.act(r, target, b)
    lines = core.log_text(r.mark).splitlines()
    apply_log(g, lines, target)
    for nid, key, val in r.final:
        g.set_state(nid, key, val, _now(), 'event')
    r.final.clear()
    g.set_state('Tara', 'last_action_save', _save_stamp(), _now(), 'event')
    if out == 'refill':
        g.set_state('Tara', 'at', None, _now(), 'event')
        _ask(g, task, 'the can ran dry; refilled at the well, Tara moved: re-anchor', detect_fn)
    if out == 'stop':
        return 'stop'
    text = '\n'.join(lines)
    missing = [e for e in t.done_events if not re.search(EVENTS[e], text)]
    if missing:
        raise Unexpected(f'after {task} on {target} the log lacks {missing}')
    return 'ok'


def run(task, group, graph, seed=None, max_steps=40, detect_fn=None, wf=None):
    """Do `task` on every needing member of `group`, nearest first (a pending water from an interrupted replant first).
    Returns {'done','skipped','vision','steps','count_check'}; raises loop.NeedVision (an anchor question) when Tara.at
    is unknown or anything is unexpected - answer with ./wf anchor and call again: the run continues from the graph."""
    t, g = TASKS[task], graph
    detect_fn = detect_fn or _default_detect(g, group)
    r = _Run(g, seed)
    res = {'done': [], 'skipped': r.skipped, 'vision': 0, 'steps': 0}
    at = g.state_value('Tara', 'at')
    if at in g.nodes and g.nodes[at].region != group:
        loop.goto(Q(kind=g.nodes[group].kind), core.WF, graph=g)
        g.set_state('Tara', 'at', None, _now(), 'event')
        at = None
    if at not in g.nodes:
        _ask(g, task, 'Tara.at is unknown', detect_fn)
    try:
        pw = g.state_value('Tara', 'pending_water')
        if pw:
            if pw in g.nodes and g.phase(pw) == 'growing' and g.state_value(pw, 'watered_today') is not True:
                b, at = _goto_node(r, at, pw, detect_fn)
                _perform(r, TASKS['water'], 'water', pw, b, detect_fn)
                res['done'].append(pw)
            g.set_state('Tara', 'pending_water', None, _now(), 'event')
        while not r.stop and res['steps'] < max_steps:
            todo = [(len(h), i) for i in g.needs(group, lambda n: t.needs(g, n.id))
                    if (h := g.hops(at, i)) is not None]
            if not todo:
                break
            res['steps'] += 1
            target = min(todo)[1]
            b, at = _goto_node(r, at, target, detect_fn)
            if _perform(r, t, task, target, b, detect_fn) == 'stop':
                break
            res['done'].append(target)
    except Unexpected as e:
        _ask(g, task, e.why, detect_fn)
    _count_check(g, res, task, detect_fn)
    res['vision'] = g.state_value('Tara', 'asks') or 0
    g.set_state('Tara', 'asks', 0, _now(), 'event')
    return res


def _count_check(g, res, task, detect_fn):
    """Graph vs save counts, only on a save newer than the run's last action and at most once per save stamp."""
    stamp = _save_stamp()
    if stamp is None:
        res['count_check'] = 'skipped (no save)'
        return
    if stamp <= (g.state_value('Tara', 'last_action_save') or 0):
        res['count_check'] = 'skipped (save older than run)'
        return
    if stamp == g.state_value('Tara', 'count_checked'):
        res['count_check'] = 'skipped (this save already checked)'
        return
    g.set_state('Tara', 'count_checked', stamp, _now(), 'event')
    mm = _save_mismatch(g)
    res['count_check'] = 'ok' if not mm else 'mismatch'
    if mm:
        _ask(g, task, 'graph vs save counts differ (graph, save): ' + ', '.join(f'{k}={v}' for k, v in mm.items()), detect_fn)


def _save_mismatch(graph):
    try:
        counts = core.WF.save_bed_counts(core.WF.farm_status()['crops'])
    except Exception:   # noqa: BLE001 (no save: nothing to compare)
        return {}
    return anchor.count_mismatch(graph, None, counts)
