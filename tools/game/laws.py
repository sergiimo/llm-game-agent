"""TASKS on the interaction-laws framework (docs/mechanics/interaction-laws.md, user D183-D185, L124-L134).

Framework: OBSERVE (game/observe.py: the frame, never acts) -> ACT (game/act.py: one click + its full record) ->
LEARN (game/learn.py: memory, bubble kinds, actions DB, graph directions) -> NAV (game/nav.py: reach any fitting node).
This module only says what a task is and what each logged event means for it:

1. Tara is always at the frame centre; where she is = the closest node (observe.closest_node).
2. A fitting bubble in reach is clicked (nearest first) until none is left (the bubble loop).
3. None in reach -> nav.seek (graph direction / dry soil / vectors / explore or map; stuck after 3 still clicks).
4. Nothing found -> ONE vision question (a grid cell) with the trace of what was tried; its answer comes back as click=.
5. Done = the save count (replant), or the search finds nothing more (water: no drop bubble, no dry soil after exploring).
6. Stops: late game time (after 23:00 / before 06:00), a UI not in English, LAWS_STUCK after MAX_ASKS questions.

No positions carried between calls; across calls only the vision counter and the last trace (STATE)."""
import json
import os
import re

from . import act as A, core, learn as L, nav as N, observe as O, ui
# re-exports (callers and tests use these names)
from .act import BURST, EVENT_WAIT, Click, click as record_click  # noqa: F401
from .nav import (EXPLORE_R, SEEK_TURNS, STEP_R, STUCK_CLICKS, Target as Task, reach, step as _step)  # noqa: F401
from .observe import CENTRE, HUD, LawsStuck, WrongLanguage, check_language, closest_node, d as _d  # noqa: F401

W_, H_ = O.W_, O.H_
COLS, ROWS = 24, 16                    # the vision grid (same as wf ask_vision 'click': A-X x 1-16)
CELL_W, CELL_H = W_ / COLS, H_ / ROWS  # 80 x 67.5 px
MAX_ASKS = 4                           # vision questions in a row without progress -> LawsStuck
LATE, EARLY = 23.0, 6.0                # game hours: no garden work after LATE / before EARLY (AGENTS rule 0, L27)
WELL_KINDS = ('fill_can', 'full_watering_can')
WORK = ('water', 'grab_item', 'unplant', 'out_of_water', 'fill_watering_can', 'full_watering_can')   # task work = progress
STATE = os.path.join(A.SHOTS, 'laws-state.json')

TASKS = {
    'replant': Task('replant', lambda a: bool(a.drop), 'a WILTED garden bed (grey/brown, drooping, dead-looking plants)',
                    'wilted'),
    'water': Task('water', lambda a: bool(a.drop),
                  'a garden bed that needs water (light-brown dry soil; its bubble has the pale-blue water drop)', 'dry',
                  soil=True),
    'harvest': Task('harvest', lambda a: a.kind == 'pickup', 'a RIPE garden bed (full-grown crop ready to pick)', 'ripe'),
}
DONE_ON = {'replant': ('unplant',), 'water': ('water',), 'harvest': ('grab_item',)}


def harvest_task(ready=False):
    """Harvest fits the pickup bubble; with ready=True also any "!" (ready) bubble. "!" is NOT an order to collect
    (user D185: flowers serve the bees), so the caller decides."""
    t = TASKS['harvest']
    return Task('harvest', (lambda a: a.kind == 'pickup' or a.ready) if ready else t.fits, t.target, 'ripe')


# ---- the vision grid ------------------------------------------------------------------------------------------
FONTS = ('/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/System/Library/Fonts/Helvetica.ttc',
         '/Library/Fonts/Arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')


def _font(px):
    from PIL import ImageFont
    for f in FONTS:
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def draw_grid(img):
    """Copy of img with the A-X x 1-16 grid and Tara's magenta circle at the centre: the `NEED_VISION click` frame."""
    from PIL import Image, ImageDraw
    pic = img.convert('RGBA')
    ov = Image.new('RGBA', pic.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    font = _font(15)
    for c in range(COLS + 1):
        dr.line((c * CELL_W, 0, c * CELL_W, pic.size[1]), fill=(255, 255, 0, 150), width=1)
    for r in range(ROWS + 1):
        dr.line((0, r * CELL_H, pic.size[0], r * CELL_H), fill=(255, 255, 0, 150), width=1)
    for c in range(COLS):
        for r in range(ROWS):
            dr.text((c * CELL_W + 3, r * CELL_H + 2), f'{chr(65 + c)}{r + 1}', fill=(255, 255, 0, 230), font=font)
    out = Image.alpha_composite(pic, ov).convert('RGB')
    x, y = CENTRE
    ImageDraw.Draw(out).ellipse((x - 26, y - 26, x + 26, y + 26), outline=(255, 0, 255), width=5)
    return out


def parse_point(ans):
    """A vision answer -> frame point: a grid cell 'Q14' (its centre) or (x, y). ValueError off the frame or on the HUD."""
    if isinstance(ans, str):
        m = re.fullmatch(r'\s*([A-Xa-x])\s*(\d{1,2})\s*', ans)
        if not m:
            raise ValueError(f'not a grid cell: {ans!r} (expected A1-X16, e.g. Q14)')
        c, r = ord(m.group(1).upper()) - 65, int(m.group(2))
        if not 1 <= r <= ROWS:
            raise ValueError(f'no row {r} (rows 1-{ROWS})')
        x, y = (c + 0.5) * CELL_W, (r - 0.5) * CELL_H
    else:
        x, y = (float(v) for v in ans)
    if not (0 <= x < W_ and 0 <= y < H_):
        raise ValueError(f'({x:.0f}, {y:.0f}) is off the frame')
    if O.hud((x, y)):
        raise ValueError(f'({x:.0f}, {y:.0f}) is on the HUD (clock or buttons), not in the world')
    return round(x), round(y)


# ---- cross-call state (vision counter + last trace) -------------------------------------------------------------
def _load_state(task):
    try:
        with open(STATE) as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        s = {}
    return s if s.get('task') == task else {'task': task, 'asks': 0, 'history': []}


def _save_state(s):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, 'w') as fh:
            json.dump(s, fh)
    except OSError:
        pass


def reset(task=None):
    """Forget the vision counter and trace (a new task or progress)."""
    _save_state({'task': task, 'asks': 0, 'history': []})


def memory_hint():
    return L.memory_hint()


# ---- task steps -------------------------------------------------------------------------------------------------
def _left_in_save(task):
    try:
        return core.WF.save_bed_counts(core.WF.farm_status()['crops'])[task.save_key]
    except Exception:   # noqa: BLE001
        return None


def _fill_can(res, outer=None):
    """Refill at the well by the same navigation (L134): reach the well's bubble, click it, the fill line (1-3 s late)
    proves it. Not found -> the outer task's click question for the well (its answer comes back as click=...)."""
    from . import well
    ui.close()
    wt = Task(outer.name if outer else 'refill', lambda a: a.kind in WELL_KINDS,
              'the WELL (a stone well with a small wooden roof; refills the watering can)', None, 'Well', 'Garden', 'Well')
    a = N.search(wt, res)
    if a is None:
        if outer is None:
            raise core.Failed('the well was not reached; ' + core.ask_vision('where is the well? click point of it'))
        _ask(wt, _load_state(outer.name), res, None)
    c = A.click(a.pt, 'bubble')
    if not (c.has('fill_watering_can', 'full_watering_can') or core.seen(well.FILLED, c.mark, well.FILL_WAIT)):
        raise core.Failed('clicked the well bubble but the game logged no fill; '
                          + core.ask_vision('what happened after clicking the well?'))
    res['refills'] += 1
    res['here'] = 'Well'


def chains_observe_remove(c):
    """Step 'press Remove': from the card click's mark (its unplant_impl), bubbles before = the card click's before."""
    rec = A.after_press(c.pt, c.mark, c.before, O.scan())
    rec.events = [e for e in rec.events if e != 'unplant']
    L.remember(rec.events)
    L.check(rec, 'replant', 1)


def _replant(c, res, seed):
    """The Remove card is open (event `unplant`): Remove -> the same crop -> Select -> water. 'done' | 'stop'."""
    from .garden import crop_name
    crop = crop_name(' / '.join(ui.texts())) or None
    want = seed or crop
    L.remember([], crop=crop)
    if not want:
        ui.close()
        raise core.Failed('the Remove card names no crop; ' + core.ask_vision('which crop is on this bed card?'))
    for _ in range(3):   # wilted card (no Remove text, a ⃠ icon) -Space-> "remove …?" confirmation -> Remove button
        if core.seen(r'> unplant_impl ', c.mark, 0):
            break
        if ui.shows('remove', wait=0.5):
            ui.press('Remove')
        else:
            ui.press_bubble()
        if core.seen(r'> unplant_impl ', c.mark, 1.5):
            break
    else:
        raise core.Failed('Remove was pressed but the game logged no unplant_impl; '
                          + core.ask_vision('what is on screen after pressing Remove?'))
    plant = O.nearest(O.scan(), c.pt, lambda a: a.kind == 'plant')
    if plant is None:
        raise core.Failed('no seedling bubble after the bed was cleared; '
                          + core.ask_vision('the bed was just cleared: where is its planting bubble?'))
    chains_observe_remove(c)
    pc = A.click(plant.pt, 'bubble', chain='replant', idx=2)
    try:
        ui.pick_card(want)
    except core.Failed as e:
        ui.close()
        ui.close()
        res['stop'] = f'no seeds for {want}: {str(e)[:120]}'
        return 'stop'
    mark, before = core.WF.log_mark(), O.scan()
    ui.press('Select')
    if not core.seen(r'totalPlanted\.', mark, 3.0):
        raise core.Failed(f'Select was pressed but {want} was not planted; '
                          + core.ask_vision(f'is {want} planted on the bed?'))
    after = O.scan()
    sel = A.after_press(pc.pt, mark, before, after)
    L.remember(sel.events)
    L.check(sel, 'replant', 3)
    drop = O.nearest(after, pc.pt, lambda a: a.drop, max_d=250)
    if drop is None:
        res['notes'].append(f'{want} planted; no water bubble seen: water it later (water_all)')
        return 'done'
    w = A.click(drop.pt, 'bubble', chain='replant', idx=4)
    if w.has('out_of_water'):
        _fill_can(res, TASKS['replant'])
        res['notes'].append(f'{want} planted; can was empty, refilled: the bed still needs water (water_all)')
    return 'done'


def _handle(task, c, res, seed):
    """What one click's record means for the task. 'done' | 'progress' | 'none' | 'stop'."""
    if c.node:
        res['here'] = c.node   # the logged interaction says which node she is at (fallback for closest_node)
        res['inside'] = N.inside(task, c.node)
    elif c.moved:
        res['here'] = None     # she walked: the old node is stale
    if c.moved:                # screen points remembered as tried mean nothing after a walk
        res.get('tried', []).clear()
        res.get('btried', []).clear()
    if c.has(*WORK):
        res['still'], res['stuck_traced'] = 0, False   # task work is progress, wherever she stands
    if c.has('fill_watering_can', 'full_watering_can'):   # a vision cell on the well
        res['refills'] += 1
        res['here'] = 'Well'
        return 'progress'
    if task.name == 'replant' and c.has('unplant'):
        out = _replant(c, res, seed)
        if out == 'done':
            res['done'].append(c.pt)
        return out
    if c.has('out_of_water'):
        _fill_can(res, task)
        return 'progress'
    if c.has(*DONE_ON.get(task.name, ())):
        res['done'].append(c.pt)
        return 'done'
    if c.has('water'):   # another task's work on the way (a dry bed while replanting)
        res['other'].append(f'@{c.pt[0]},{c.pt[1]} was dry, not {task.save_key}: watered')
        return 'progress'
    if c.has('grab_item'):
        res['other'].append(f'@{c.pt[0]},{c.pt[1]} was ripe: picked')
        return 'progress'
    if c.events or c.mode != 'gameplay':   # e.g. plant_growing, a wilted bed's card in the water task
        res['other'].append(f'@{c.pt[0]},{c.pt[1]}: {c.events or c.mode}')
        A.gameplay()
        return 'none'
    return 'progress' if c.moved else 'none'   # a bubble set changing while she stands still is flicker (L132)


def _ask(task, st, res, last):
    """ONE vision question: the click cell of the next node, with the trace of what the search tried (vision debugs it).
    Raises NeedVision (or LawsStuck after MAX_ASKS)."""
    from objects.loop import NeedVision
    if st['asks'] >= MAX_ASKS:
        hist = ' | '.join(st['history'][-3:])
        reset(task.name)
        raise LawsStuck(f'LAWS_STUCK: {task.name} asked vision {MAX_ASKS} times without progress; last: {hist}. '
                        'Stop and report; do not retry blindly.')
    A.gameplay()
    left = res['left_in_save']
    tr = res.get('trace', [])
    q = (f'Task: {task.name}. Tara is the magenta circle (always the frame centre). No fitting bubble is on screen. '
         f'Give the grid cell of {task.target} nearest to Tara: a cell on the object itself (not on a bubble). '
         f'If none is visible but it may be off-screen, give a cell of free ground toward it. '
         f'If there is none left anywhere, answer none.'
         + (f' The save says {left} left (may be stale).' if left is not None else '')
         + f' This call: done {len(res["done"])}, other {res["other"][-3:]}.'
         + (f' Memory: {L.memory_hint()}.' if L.memory_hint() else '')
         + (f' Your last answer led to: {last.describe()}.' if last is not None else '')
         + (f' The search (closest node -> graph / dry soil / vectors / explore free ground or map) already tried, in '
            f'order: {"; ".join(tr[-10:])}. Debug it: if a step was blocked, say by what in your report and answer a '
            f'cell of FREE ground (no object, no fence) she can walk to that gets her around it or shows more nodes; '
            f'if the target is visible, its cell.' if tr else ''))
    st['asks'] += 1
    st['history'] = (st['history'] + [last.describe()[:160] if last is not None else 'no fitting bubble'])[-6:]
    st['trace'] = tr[-8:]   # the next call (vision's answer) starts with what was tried
    _save_state(st)
    ans = f"./wf py \"{task.name}_all(click='Q14')\""
    try:
        prompt = core.WF.ask_vision('click', q, core.WF.grab(), answer=ans)
    except Exception:   # noqa: BLE001
        prompt = f'NEED_VISION click: {q} (no frame saved: ./wf look)'
    res['vision'] += 1
    e = NeedVision(prompt)
    e.args = (prompt + f'\n  run so far: {summary(res)}',)
    raise e


def summary(res):
    return (f"{res['task']}: done {len(res['done'])}, other {len(res['other'])}, clicks {res['clicks']}, "
            f"vision {res['vision']}, refills {res['refills']}"
            + (f", stop: {res['stop']}" if res['stop'] else '')
            + (f", surprises: {res['surprises']}" if res.get('surprises') else '')
            + (f", notes: {res['notes']}" if res['notes'] else ''))


def _late(res):
    """The HUD clock: after LATE or before EARLY -> res['stop']; sets res['light'] for the soil tones."""
    h, light = O.clock()
    if h is None:
        return False
    res['light'] = light
    if h >= LATE or h < EARLY:
        res['stop'] = f'late: game time {int(h):02d}:{int(h % 1 * 60):02d}; no more garden work tonight (ask about bed)'
        return True
    return False


def _done_looking(task, res):
    """Soil tasks (water) are done when the search found nothing more: every explore direction used, not stuck, no dry
    soil in view (daylight). The run ends with a summary instead of a vision question."""
    if not (task.soil and res.get('explored_all') and res.get('light') in ('day', None)):
        return False
    if res.get('still', 0) >= STUCK_CLICKS or res.get('stuck_traced'):
        return False
    if N.dry_spots([]):
        return False
    res['stop'] = 'no water-drop bubble and no dry soil left in view after exploring the Garden'
    return True


def run(task_name, click=None, seed=None, max_clicks=30, task=None):
    """Do `task_name` ('replant' | 'water' | 'harvest') on every fitting node. `click` = vision's answer to the last
    question: a grid cell ('Q14'), (x, y), or 'none'. Returns the summary dict; raises NeedVision when nothing fitting
    is found (answer by calling again with click=...)."""
    L.open_memory()
    try:
        return _run(task or TASKS[task_name], click, seed, max_clicks)
    finally:
        L.close_memory()
        L.settle_db()


def _run(task, click, seed, max_clicks):
    st = _load_state(task.name)
    res = N.new_res(task.name)
    res['left_in_save'] = _left_in_save(task)
    L.SURPRISES.clear()
    O.check_language()
    A.gameplay()
    last = None
    if _late(res):
        return res
    if click is not None and st.get('trace'):
        res['trace'] = [f'(before the answer) {t}' for t in st['trace']]
    if isinstance(click, str) and click.strip().lower() == 'none':
        reset(task.name)
        res['stop'] = 'vision: none left'
        return res
    if click is None and res['left_in_save'] == 0:
        res['stop'] = f'save: no {task.save_key} beds'
        return res
    if click is not None:
        try:
            pt = parse_point(click)
        except ValueError as e:
            raise core.Failed(f'click answer rejected: {e}. Answer a grid cell A1-X16 on the target, or none') from None
        last = A.click(pt, 'point')
        res['clicks'] += 1
        out = _handle(task, last, res, seed)
        if out == 'stop':
            return res
        if out in ('done', 'progress'):
            reset(task.name)
            st = _load_state(task.name)
    seeks = 0                              # seek rounds since the last fitting bubble
    tried = res.setdefault('btried', [])   # bubble points that did not progress: not clicked again until she walks
    while res['clicks'] < max_clicks and not res['stop']:
        if res['clicks'] and res['clicks'] % 5 == 0 and _late(res):
            break
        if res['left_in_save'] is not None and len(res['done']) >= res['left_in_save'] > 0:
            res['stop'] = f"save: all {res['left_in_save']} {task.save_key} beds done"   # the save only over-counts
            break   # (written earlier; beds only get done since), so done >= its count = all of them
        affs = O.scan()
        fit = [a for a in affs if task.fits(a) and not any(O.d(a.pt, p) < 60 for p in tried)]
        if not fit:
            seeks += 1
            c = N.seek(task, res) if seeks <= SEEK_TURNS else None
            if c is not None and c.what == 'explore':
                seeks -= 1   # exploring is bounded by its directions (each once per call), not by the round count
            if c is None and _done_looking(task, res):
                break
            if c is None:
                _ask(task, st, res, last)
            last = c
            if _handle(task, c, res, seed) == 'stop':
                break
            continue
        seeks = 0
        a = O.nearest(fit, CENTRE)
        last = A.click(a.pt, 'bubble', before=affs)   # checked by its event (learn.STEP_OF)
        res['clicks'] += 1
        out = _handle(task, last, res, seed)
        if out == 'stop':
            break
        if out == 'none':
            tried.append(a.pt)
        else:   # progress resets the vision counter
            tried.clear()
            reset(task.name)
            st = _load_state(task.name)
    return res
