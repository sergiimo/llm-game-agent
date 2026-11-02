"""Graph chain strategy (spec 2026-11-02): locate a neighbour tile on screen by pattern fit (no positions: frame pixels
only), and `run` a garden task over a group chain: tile by tile, the log read for event TYPE only, every unexpected
situation = one vision question (anchor), never a guess. Helpers (pattern fit, expectations, move proof): chain_step."""
import re
from collections import namedtuple

from game import affordances, core, ui, well

from . import anchor, detect as D, loop, store as S
from .chain_step import (CENTRE, SHIFT, Unexpected, _implies_bubble, _lines, _pitch, _prove_shift, bubble_near,  # noqa: F401
                         click_tile, expected_bubble, locate, opened_screen)
from .graph import apply_log
from .query import Q


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
        self.res = None   # the run summary (for the vision prompt)
        self.final = []   # (id, key, value, conf) set after the log replay (apply_log would overwrite them)


def _now():
    return anchor._clock(core)


def _water(run, aff):
    mark = affordances.click(aff)
    line = core.seen(r'> (water|out_of_water) ', mark, wait=2.0)
    if line and '> water ' in line:
        return 'ok'
    if line:
        ui.close()
        well.fill_can(graph=run.graph)   # the chain's graph, so a later save cannot overwrite Well.can
        return 'refill'
    raise Unexpected('the water bubble produced neither a water nor an out_of_water event')


def _act_water(run, nid, aff):
    return _water(run, aff)


def _act_harvest(run, nid, aff):
    mark = affordances.click(aff)
    if not event(mark, 'pickup', 2.0):
        raise Unexpected('the pickup bubble produced no grab_item event')
    # the plant regrows into an unknown stage: phase unknown (conf 0) until the next anchor settles it
    run.graph.set_state(nid, 'phase', None, _now(), 'event', 0.0)
    run.graph.set_state(nid, 'watered_today', None, _now(), 'event', 0.0)
    return 'ok'


def _act_replant(run, nid, aff):
    from game.garden import crop_name
    g = run.graph
    mark = affordances.click(aff)
    if not event(mark, 'unplant', 2.0):
        raise Unexpected('the wilted bubble did not open the Remove card')
    crop = crop_name(' / '.join(ui.texts())) or None
    if not (run.seed or crop):   # nothing to replant with: do not empty the bed first
        ui.close()
        raise Unexpected('card crop unreadable')
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


def _summary(res):
    if not res:
        return ''
    return (f' Run so far: done {len(res["done"])} {[d.split("#")[-1] for d in res["done"]]}, '
            f'skipped {[(i.split("#")[-1], w[:40]) for i, w in res["skipped"]]}, unknown {len(res.get("unknown", []))}.')


def _ask(graph, task, why, detect_fn, res=None):
    """One fresh anchor question about the current frame (a stale pending answer is cleared first); raises NeedVision."""
    why += _summary(res)
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
    if not dets:
        raise Unexpected('no tiles visible on the frame')
    return min(dets, key=lambda d: (d.point[0] - CENTRE[0]) ** 2 + (d.point[1] - CENTRE[1]) ** 2)


def _set_at(g, nid):
    g.set_state('Tara', 'at', nid, _now(), 'event')
    g.set_state('Tara', 'at_scene', anchor._scene(core), _now(), 'event')


def _step(run, cur, nid, detect_fn, last, d=None):
    """Move one chain step onto `nid` (a neighbour of `cur`) and prove it from the frames, then check the bubble above
    Tara's tile against the predicted state. Tara.at is set only after the proof (a click that did not move her, or
    moved her elsewhere, is Unexpected)."""
    g = run.graph
    dets = detect_fn(core.WF.grab())
    if cur != nid:
        pt = click_tile(locate(g, cur, nid, dets), [a.pt for a in affordances.scan()])
        core.WF.run_action(f'click:{pt[0]}:{pt[1]}')
        core.WF.wait_settle()
        scr = opened_screen()
        if scr:   # a click on an adjacent bed can open its panel/card instead of walking
            ui.close()
            raise Unexpected(f'the click opened {scr}')
        dets1 = detect_fn(core.WF.grab())
        _prove_shift(g.nodes[g.nodes[nid].region], dets, dets1, d)
        locate(g, nid, cur, dets1)   # secondary: the previous tile is visible one step back from Tara's tile
        dets = dets1
    run.tile_pt = _centre(dets).point
    _set_at(g, nid)
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
        _ask(g, task, 'the can ran dry; refilled at the well, Tara moved: re-anchor', detect_fn, r.res)
    if out == 'stop':
        return 'stop'
    text = '\n'.join(lines)
    missing = [e for e in t.done_events if not re.search(EVENTS[e], text)]
    if missing:
        raise Unexpected(f'after {task} on {target} the log lacks {missing}')
    return 'ok'


_DAY = re.compile(r'D(\d+)')


def _at_stale(g):
    """Tara.at is stale when set on another game day or in another scene than now (she walked, slept or left meanwhile)."""
    st = g.nodes['Tara'].state.get('at')
    if not st:
        return False
    then, now = _DAY.match(str(st.get('game_time'))), _DAY.match(_now())
    if then and now and then.group(1) != now.group(1):
        return True
    was, cur = g.state_value('Tara', 'at_scene'), anchor._scene(core)
    return bool(was and cur and was != cur)


def run(task, group, graph, seed=None, max_steps=40, detect_fn=None, wf=None):
    """Do `task` on every needing member of `group`, nearest first (a pending water from an interrupted replant first).
    Returns {'done','skipped','unknown','vision','steps','count_check'}; raises loop.NeedVision (an anchor question) when
    Tara.at is unknown or anything is unexpected - answer with ./wf anchor and call again: the run continues from the graph."""
    t, g = TASKS[task], graph
    detect_fn = detect_fn or _default_detect(g, group)
    r = _Run(g, seed)
    res = r.res = {'done': [], 'skipped': r.skipped, 'unknown': [], 'vision': 0, 'steps': 0}
    at = g.state_value('Tara', 'at')
    if at in g.nodes and g.nodes[at].region != group:
        loop.goto(Q(kind=g.nodes[group].kind), core.WF, graph=g)
        g.set_state('Tara', 'at', None, _now(), 'event')
        at = None
    elif at in g.nodes and _at_stale(g):
        g.set_state('Tara', 'at', None, _now(), 'event')
        at = None
    if at not in g.nodes:
        if not detect_fn(core.WF.grab()):   # outside the garden (or nothing seen): walk there first, then ask
            loop.goto(Q(kind=g.nodes[group].kind), core.WF, graph=g)
        _ask(g, task, 'Tara.at is unknown', detect_fn, res)
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
        _ask(g, task, e.why, detect_fn, res)
    except core.Failed as e:   # fill_can / Remove / Select failed: close any menu, then exactly one question
        try:
            ui.close()
        except Exception:   # noqa: BLE001
            pass
        _ask(g, task, str(e).split('NEED_VISION')[0].rstrip('; ') or 'an action failed', detect_fn, res)
    res['unknown'] = [m.id for m in g.members(group) if g.phase(m.id) is None]
    _count_check(g, res, task, detect_fn)
    res['vision'] = g.state_value('Tara', 'asks') or 0
    g.set_state('Tara', 'asks', 0, _now(), 'event')
    return res


def _count_check(g, res, task, detect_fn):
    """Graph vs save counts, only on a save newer than the run's last action, at most once per save stamp, and only when the
    graph covers every bed (a group without members/pattern or an unknown phase makes the farm-wide sums meaningless)."""
    why = anchor.incomplete(g)
    if why:
        res['count_check'] = 'skipped (graph incomplete)'
        return
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
        _ask(g, task, 'graph vs save counts differ (graph, save): ' + ', '.join(f'{k}={v}' for k, v in mm.items()), detect_fn, res)


def _save_mismatch(graph):
    try:
        counts = core.WF.save_bed_counts(core.WF.farm_status()['crops'])
    except Exception:   # noqa: BLE001 (no save: nothing to compare)
        return {}
    return anchor.count_mismatch(graph, None, counts)
