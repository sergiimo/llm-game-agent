"""Graph chain strategy (spec 2026-11-02 §10): `run` a garden task over a group chain, bed by bed: the click point comes from
the vision-given layout (frame pixels only, no positions), every move is proved by the camera shift, the log is read for event
TYPE only, every unexpected situation = one vision question (anchor), never a guess. Helpers: chain_step."""
import re
from collections import namedtuple

from game import affordances, core, ui, well

from . import anchor, loop
from .chain_step import (CENTRE, SHIFT, Unexpected, click_target, _implies_bubble, bubble_near, camera_shift, click_tile,  # noqa: F401
                         ensure_gameplay, expected_bubble, layout_point, opened_screen, prove_move)
from .graph import apply_log
from .query import Q


EXPECT = {'replant': {'unplant'}, 'water': {'water', 'out_of_water'}, 'harvest': {'grab_item'}}   # click interactions per task
# What a click's event proves about the bed (L123: events are ground truth; vision misreads wilted vs growing at night)
# plant_growing: no water action happened, so the bed did not need water (a dry one would have been watered)
EVENT_STATE = {'plant_growing': {'phase': 'growing', 'watered_today': True}, 'water': {'phase': 'growing', 'watered_today': True},
               'out_of_water': {'phase': 'growing', 'watered_today': False}, 'unplant': {'phase': 'wilted'},
               'grab_item': {'phase': None}}


class Corrected(Exception):
    """The click's event contradicted the predicted state: the node was corrected from the event; skip to the next."""
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
        self.arrival = None   # the click's log mark when the click itself interacted with the target (ruling 28)
        self.res = None   # the run summary (for the vision prompt)
        self.final = []   # (id, key, value, conf) set after the log replay (apply_log would overwrite them)


def _now():
    return anchor._clock(core)


def _mark(run, aff):
    """Log mark of the act's first click, or the arrival click's mark when that click already did it (consumed once)."""
    m, run.arrival = run.arrival, None
    return m if m is not None else affordances.click(aff)


def _water(run, aff):
    mark = _mark(run, aff)
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
    mark = _mark(run, aff)
    if not event(mark, 'pickup', 2.0):
        raise Unexpected('the pickup bubble produced no grab_item event')
    # the plant regrows into an unknown stage: phase unknown (conf 0) until the next anchor settles it
    run.graph.set_state(nid, 'phase', None, _now(), 'event', 0.0)
    run.graph.set_state(nid, 'watered_today', None, _now(), 'event', 0.0)
    return 'ok'


def _act_replant(run, nid, aff):
    from game.garden import crop_name
    g = run.graph
    mark = _mark(run, aff)   # an arrival by interaction left the Remove card open: use it, do not close it
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


class ChainStuck(Exception):
    """Terminal (ruling 29): the run asked vision too often (4 questions) or the same question again at the same bed. Stop and report."""


MAX_ASKS = 4


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


def _ask(graph, task, why, res=None):
    """One fresh anchor question about the current frame (a stale pending answer is cleared first); raises NeedVision."""
    asks, hist = graph.state_value('Tara', 'asks') or 0, list(graph.state_value('Tara', 'ask_whys') or [])
    at = graph.state_value('Tara', 'at')
    if asks >= MAX_ASKS or (at is not None and [at, why] in hist):
        graph.set_state('Tara', 'asks', 0, _now(), 'event')
        graph.set_state('Tara', 'ask_whys', None, _now(), 'event')
        anchor.clear_pending()
        raise ChainStuck(f'CHAIN_STUCK: {task} stopped after {asks} vision question(s)'
                         f'{" (the same one again at " + at + ")" if at is not None and [at, why] in hist else ""}; last: '
                         + ' | '.join(w[:100] for _, w in hist[-3:] + [[at, why]]) + '. Stop and report; do not retry blindly.')
    graph.set_state('Tara', 'ask_whys', hist + [[at, why]], _now(), 'event')
    why += _summary(res)
    anchor.clear_pending()
    try:
        ensure_gameplay()   # a card/panel left open would hide the beds from vision
    except Exception:   # noqa: BLE001
        pass
    img = core.WF.grab()
    prompt = anchor.question(img, task, graph, why, core=core)
    graph.set_state('Tara', 'asks', asks + 1, _now(), 'event')
    raise _need_vision(prompt)


def _goto_garden(g, group):
    """Walk to the group's beds (ruling 27): clears a pending `none` answer's need_goto flag and Tara.at (every walk
    forces a re-anchor)."""
    loop.goto(Q(kind=g.nodes[group].kind), core.WF, graph=g)
    g.set_state('Tara', 'need_goto', None, _now(), 'event')
    _clear_at(g, group)


def _clear_at(g, group):
    """Tara.at forgotten: the group's layout (relative to her bed) goes with it."""
    g.set_state('Tara', 'at', None, _now(), 'event')
    g.nodes[group].extra.pop('layout', None)


def _set_at(g, nid):
    g.set_state('Tara', 'at', nid, _now(), 'event')
    g.set_state('Tara', 'at_scene', anchor._scene(core), _now(), 'event')


def _goto_node(r, at, target, task):
    """Ruling 28: click the target bed's layout point directly. Returns (bubble at target | None, Tara's bed). An in-reach
    bed interacts instead of walking (arrival by interaction: Tara stays at `at`, r.arrival = the click's log mark, no bubble
    check - the event proves the state); a far one is walked to (camera-shift proof, ref_offset re-measured), then the
    bubble above it is checked against the predicted state. Tara.at is set only after the proof."""
    g = r.graph
    ensure_gameplay()
    r.arrival = None
    if at != target:
        kind, val, mark = click_target(g, at, target, [a.pt for a in affordances.scan()])
        if kind == 'event':
            if val not in EXPECT[task]:
                if val not in EVENT_STATE:
                    raise Unexpected(f'clicking {target} logged {val}, {task} expects {sorted(EXPECT[task])}')
                for k, v in EVENT_STATE[val].items():
                    g.set_state(target, k, v, _now(), 'event')
                if val == 'out_of_water':
                    g.set_state('Tara', 'can', 'empty', _now(), 'event')
                ensure_gameplay()   # e.g. the Remove card a misread bed opened: close it, never confirm
                raise Corrected(target)
            r.arrival, r.tile_pt = mark, layout_point(g, at, target)
            return None, at
        g.nodes[g.nodes[target].region].extra['layout']['ref_offset'] = [round(v, 1) for v in val]   # ruling 30
        at = target
    r.tile_pt = layout_point(g, target, target)
    _set_at(g, target)
    b = bubble_near(affordances.scan(), r.tile_pt)
    if b is None:
        raise Unexpected(f'no bubble above {target}, predicted {g.phase(target)}')
    if not expected_bubble(g, target)(b):
        raise Unexpected(f'bubble {b.kind}{" +drop" if b.drop else ""} above {target} does not match predicted {g.phase(target)}')
    return b, at


def _save_stamp():
    try:
        return core.WF.save_stamp()
    except Exception:   # noqa: BLE001
        return None


def _perform(r, t, task, target, b):
    """Act on `target`, replay the log into the graph, check the task's events. 'ok' | 'stop'."""
    g = r.graph
    r.mark = r.arrival if r.arrival is not None else core.WF.log_mark()   # an interaction arrival: its event is in the log
    out = t.act(r, target, b)
    lines = core.log_text(r.mark).splitlines()
    apply_log(g, lines, target)
    for nid, key, val in r.final:
        g.set_state(nid, key, val, _now(), 'event')
    r.final.clear()
    g.set_state('Tara', 'last_action_save', _save_stamp(), _now(), 'event')
    if out == 'refill':
        _goto_garden(g, g.nodes[target].region)   # she stands at the well: back to the beds before vision looks
        _ask(g, task, 'the can ran dry; refilled at the well, Tara moved: re-anchor', r.res)
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


def run(task, group, graph, seed=None, max_steps=40, wf=None):
    """Do `task` on every needing member of `group`, nearest first (a pending water from an interrupted replant first).
    Returns {'done','skipped','unknown','vision','steps','count_check'}; raises loop.NeedVision (an anchor question) when
    Tara.at is unknown or anything is unexpected - answer with ./wf anchor and call again: the run continues from the graph."""
    t, g = TASKS[task], graph
    r = _Run(g, seed)
    res = r.res = {'done': [], 'skipped': r.skipped, 'unknown': [], 'corrected': [], 'vision': 0, 'steps': 0}
    blocked = None
    try:
        ensure_gameplay()
    except core.Failed as e:
        blocked = str(e).split('NEED_VISION')[0].rstrip('; ') or 'could not close the open screen'
    at = g.state_value('Tara', 'at')
    went = False
    if at in g.nodes and g.nodes[at].region != group:
        went = True
        _goto_garden(g, group)
        at = None
    elif at in g.nodes and _at_stale(g):
        _clear_at(g, group)
        at = None
    if g.state_value('Tara', 'need_goto') and not went:   # the last anchor answer was `none`
        went = True
        _goto_garden(g, group)
        at = None
    if at not in g.nodes:
        if not went:
            _goto_garden(g, group)
        _ask(g, task, blocked or 'Tara.at is unknown', res=res)
    if blocked:   # Tara.at is known, but a card/panel would not close
        _ask(g, task, blocked, res=res)
    try:
        pw = g.state_value('Tara', 'pending_water')
        if pw:
            if pw in g.nodes and g.phase(pw) == 'growing' and g.state_value(pw, 'watered_today') is not True:
                try:
                    b, at = _goto_node(r, at, pw, 'water')
                    _perform(r, TASKS['water'], 'water', pw, b)
                    res['done'].append(pw)
                except Corrected:
                    res['corrected'].append(pw)
            g.set_state('Tara', 'pending_water', None, _now(), 'event')
        while not r.stop and res['steps'] < max_steps:
            todo = [(len(h), i) for i in g.needs(group, lambda n: t.needs(g, n.id))
                    if i not in res['corrected'] and (h := g.hops(at, i)) is not None]   # never re-target a corrected bed
            if not todo:
                break
            res['steps'] += 1
            target = min(todo)[1]
            try:
                b, at = _goto_node(r, at, target, task)
            except Corrected:
                res['corrected'].append(target)
                continue
            if _perform(r, t, task, target, b) == 'stop':
                break
            res['done'].append(target)
    except Unexpected as e:
        _ask(g, task, e.why, res=res)
    except core.Failed as e:   # fill_can / Remove / Select failed: close any menu, then exactly one question
        try:
            ui.close()
        except Exception:   # noqa: BLE001
            pass
        _ask(g, task, str(e).split('NEED_VISION')[0].rstrip('; ') or 'an action failed', res=res)
    res['unknown'] = [m.id for m in g.members(group) if g.phase(m.id) is None]
    _count_check(g, res, task)
    res['vision'] = g.state_value('Tara', 'asks') or 0
    g.set_state('Tara', 'asks', 0, _now(), 'event')
    g.set_state('Tara', 'ask_whys', None, _now(), 'event')
    return res


def _count_check(g, res, task):
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
        _ask(g, task, 'graph vs save counts differ (graph, save): ' + ', '.join(f'{k}={v}' for k, v in mm.items()), res=res)


def _save_mismatch(graph):
    try:
        counts = core.WF.save_bed_counts(core.WF.farm_status()['crops'])
    except Exception:   # noqa: BLE001 (no save: nothing to compare)
        return {}
    return anchor.count_mismatch(graph, None, counts)
