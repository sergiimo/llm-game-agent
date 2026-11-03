"""Interaction laws (docs/mechanics/interaction-laws.md, user D183, L124): one guess per click, confirmed by the game at once.

1. Tara is always at the frame centre (CENTRE): never located, never asked.
2. A click on a visible object is reliable: with no fitting bubble on screen, vision gives ONE click point (a grid cell of
   the gridded frame); the agent passes it back as `click=` on the next call.
3. Every click is recorded (`record_click`): a burst of frames right after it (short-lived text), the new log lines, the
   bubbles before/after, the screen mode and texts. State comes from it: log event > card > bubble change > text > vision.
4. Bubble loop: click every bubble that fits the task (nearest to the centre first) until none is left, then back to 2.

No layouts, grids or positions are carried between clicks. The only cross-call state is the vision-question counter
(STATE), which stops a run that keeps asking without progress (LawsStuck)."""
import json
import os
import re
import time
from dataclasses import dataclass, field

from . import affordances, chains, core, ui

CENTRE = (960, 540)
W_, H_ = 1920, 1080
COLS, ROWS = 24, 16                    # the vision grid (same as wf ask_vision 'click': A-X x 1-16)
CELL_W, CELL_H = W_ / COLS, H_ / ROWS  # 80 x 67.5 px
HUD = ((0, 0, 520, 230), (1440, 0, 1920, 230))   # clock / map-journal-inventory buttons: never a world click
BURST = (0.0, 0.5, 1.5)                # s after the click: frames that catch short-lived text and bubble changes
EVENT_WAIT = 2.5                       # s more for a late log line (D149: `> water` came after ~3 s)
MOVED = 6.0                            # mean abs grey difference (0-255) between first and last burst frame = the view changed
MAX_ASKS = 4                           # vision questions in a row without progress -> LawsStuck
EVENT = re.compile(r'> (\w+)(?:\s|$)')
STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.shots', 'laws-state.json')


class LawsStuck(Exception):
    """Terminal: vision was asked MAX_ASKS times without a single fitting bubble or done bed in between. Stop and report."""


@dataclass
class Click:
    """What one click did (law 3)."""
    pt: tuple
    what: str                                   # 'bubble' | 'point'
    mark: int
    lines: list = field(default_factory=list)   # new game-log lines
    events: list = field(default_factory=list)  # their event types ('unplant', 'water', ...)
    before: list = field(default_factory=list)  # Affordances before
    after: list = field(default_factory=list)   # Affordances after
    mode: str = 'gameplay'                      # the screen after (a card/panel = not 'gameplay')
    texts: list = field(default_factory=list)   # on-screen texts after
    moved: object = None                        # True/False: the view changed during the burst; None = unknown
    frames: list = field(default_factory=list)  # saved burst frame paths
    burst_texts: list = field(default_factory=list)  # short-lived texts OCR'd from the burst frames (outside the HUD)
    surprises: list = field(default_factory=list)    # [(field, expected, got)] vs its chains.json step
    node: str = None                            # the graph node the logged interaction names (target=...): where she is now

    def has(self, *names):
        return any(e in names for e in self.events)

    def nothing(self):
        """No event, no card, no bubble change, no view change: the click did nothing visible."""
        return (not self.events and self.mode == 'gameplay' and _bubble_set(self.before) == _bubble_set(self.after)
                and self.moved is False)

    def describe(self):
        bub = ', '.join(str(a) for a in self.after) or 'none'
        return (f'click {self.what} @{self.pt[0]},{self.pt[1]}: events {self.events or "none"}; screen {self.mode}'
                f'{" (" + " / ".join(self.texts[:3]) + ")" if self.texts else ""}; bubbles after: {bub}; '
                f'view {"changed" if self.moved else "unchanged" if self.moved is False else "?"}'
                f'{"; frames " + ", ".join(self.frames) if self.frames else ""}')


def _bubble_set(affs):
    return sorted((a.kind, a.drop, round(a.pt[0] / 40), round(a.pt[1] / 40)) for a in affs)


def _texts():
    try:
        s = core.WF.state()
        return s.get('mode', 'gameplay'), [t.split(') ', 1)[-1] for t in s.get('text', [])]
    except Exception:   # noqa: BLE001
        return 'gameplay', []


def _view_changed(a, b):
    try:
        import numpy as np
        ga = np.asarray(a.convert('L').resize((240, 135)), dtype=float)
        gb = np.asarray(b.convert('L').resize((240, 135)), dtype=float)
        return float(np.abs(ga - gb).mean()) > MOVED
    except Exception:   # noqa: BLE001 (fakes have no pixels)
        return None


def _frames_dir():
    try:
        d = core.WF.run_dir()
    except Exception:   # noqa: BLE001
        d = None
    return os.path.join(d or os.path.dirname(STATE), 'clicks')


def _save_frames(imgs, tag):
    out = []
    try:
        d = _frames_dir()
        os.makedirs(d, exist_ok=True)
        for i, img in enumerate(imgs):
            p = os.path.join(d, f'{tag}-{i}.jpg')
            img.convert('RGB').resize((960, 540)).save(p, quality=70)
            out.append(p)
        old = sorted(os.listdir(d))
        for f in old[:-90]:   # keep the last 30 clicks' bursts
            os.remove(os.path.join(d, f))
    except Exception:   # noqa: BLE001 (fakes, disk): recording never breaks play
        pass
    return out


def _burst_texts(imgs):
    out = []
    for img in imgs[1:]:
        try:
            items = core.WF.ocr_image(img)
        except Exception:   # noqa: BLE001
            return out
        for it in items:
            x, y = it.get('cx', 0), it.get('cy', 0)
            t = (it.get('text') or '').strip()
            if t and t not in out and not any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in HUD):
                out.append(t)
    return out


def _text_gaps():
    """OCR the burst only while some step's short-lived text is still a gap or expected (costly, ~0.5 s a frame)."""
    try:
        db = chains.load()
    except (OSError, ValueError):
        return False
    return any(s['expect'].get('text', '?') is not None for k, v in db.items() if not k.startswith('_') for s in v)


SURPRISES = []   # this run's mismatches vs chains.json (reset by run)
STEP_OF = {'unplant': ('replant', 0), 'water': ('water', 0), 'out_of_water': ('water', 1), 'grab_item': ('harvest', 0),
           'plant_growing': ('bed', 0)}   # a bubble-loop click's chain step, known only from its event


def check(c, chain=None, idx=None):
    """Check a click against its chains.json step (by event when not given); surprises go on the click."""
    if chain is None:
        hit = next((STEP_OF[e] for e in c.events if e in STEP_OF), None)
        if hit is None:
            return c
        chain, idx = hit
    try:
        c.surprises = chains.observe(chain, idx, c)
    except Exception:   # noqa: BLE001 (the DB never breaks play)
        pass
    SURPRISES.extend(f'{chain}[{idx}] {f}: expected {w!r}, got {g!r}' for f, w, g in c.surprises)
    return c


def record_click(pt, what='point', before=None, chain=None, idx=None):
    """Law 3: click `pt` and record everything it did (and check it against its chains.json step). Returns a Click."""
    W = core.WF
    before = affordances.scan() if before is None else before
    x, y = round(pt[0]), round(pt[1])
    img0 = W.grab() if what == 'bubble' else None   # the clicked bubble's crop, to learn its kind from the event
    mark = W.log_mark()
    W.run_action(f'click:{x}:{y}')
    t0, imgs = time.monotonic(), []
    for t in BURST:
        time.sleep(max(0.0, t0 + t - time.monotonic()))
        imgs.append(W.grab())
    W.wait_settle()
    if not core.seen(EVENT.pattern, mark, 0):
        core.seen(EVENT.pattern, mark, EVENT_WAIT)
    lines = core.log_text(mark).splitlines()
    mode, texts = _texts()
    c = Click((x, y), what, mark, lines, [m.group(1) for m in map(EVENT.search, lines) if m], before,
              affordances.scan(), mode, texts, _view_changed(imgs[0], imgs[-1]) if len(imgs) > 1 else None,
              _save_frames(imgs, time.strftime('%H%M%S') + f'-{x}-{y}'), _burst_texts(imgs) if _text_gaps() else [])
    from objects import graph as OG
    c.node = next((n for n in map(OG.node_of_line, lines) if n), None)
    learned = _learn_bubble(c, img0)
    check(c, chain, idx)
    remember(c.events)
    try:
        W.run_log('click', node=c.node, learned=learned, pt=[x, y], what=what, events=c.events, mode=mode, texts=texts[:4],
                  before=[str(a) for a in before], after=[str(a) for a in c.after], moved=c.moved, frames=c.frames,
                  burst_texts=c.burst_texts[:6], surprises=[list(x) for x in c.surprises])
    except Exception:   # noqa: BLE001
        pass
    return c


def _learn_bubble(c, img0):
    """Gap filling for bubble kinds (D185: the honey bubble stayed 'unknown'): a clicked bubble is labelled by the
    interaction the game logged next; a wrong/unknown kind is stored as a new reference (wf.learn_bubble). The label or None."""
    W = core.WF
    if c.what != 'bubble' or not hasattr(W, 'event_kind') or not hasattr(W, 'learn_bubble'):
        return None
    b = _nearest(c.before, c.pt, max_d=60)
    label = W.event_kind(c.lines)
    if b is None or not label or b.kind == label:
        return None
    try:
        return label if W.learn_bubble(W.bubble_crop(img0, b.pt), label, b.kind) else None
    except Exception:   # noqa: BLE001
        return None


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
    """Copy of img with the A-X x 1-16 grid (thin lines, the cell name in each cell) and Tara's magenta circle at the
    centre: the frame of a `NEED_VISION click` question."""
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
    """A vision answer -> frame point: a grid cell 'Q14' (its centre) or (x, y). ValueError on a point off the frame or on the HUD."""
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
    if any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in HUD):
        raise ValueError(f'({x:.0f}, {y:.0f}) is on the HUD (clock or buttons), not in the world')
    return round(x), round(y)


# ---- graph memory (law 6: hints, never a gate) -------------------------------------------------------------------
GRAPH = None        # Farm.json path (None = objects/graph/Farm.json)
GROUP = 'GardenBed@Garden'
MEMORY = {'graph': None}


def _graph_path():
    if GRAPH:
        return GRAPH
    from objects import graph as OG
    return os.path.join(OG.DEFAULT_DIR, 'Farm.json')


def _open_memory():
    from objects import graph as OG
    g = OG.Graph()
    try:
        g.load(_graph_path())
    except (OSError, ValueError):
        g = None
    MEMORY['graph'] = g if g is not None and GROUP in g.nodes else None


def _close_memory():
    g, MEMORY['graph'] = MEMORY['graph'], None
    if g is not None:
        try:
            g.save(_graph_path())
        except OSError:
            pass


def _stamp():
    try:
        return core.WF.game_stamp()
    except Exception:   # noqa: BLE001
        return None


def remember(events, crop=None):
    """A click's events (and a crop read from a card) -> the group's memory (objects/graph.note_click)."""
    g = MEMORY['graph']
    if g is None or not (events or crop):
        return
    from objects import graph as OG
    OG.note_click(g, GROUP, list(events), _stamp(), crop=crop)


def memory_hint():
    g = MEMORY['graph']
    if g is None:
        return ''
    from objects import graph as OG
    return OG.hint(g, GROUP)


# ---- cross-call vision counter ---------------------------------------------------------------------------------
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
    """Forget the vision counter (a new task or progress)."""
    _save_state({'task': task, 'asks': 0, 'history': []})


# ---- tasks -----------------------------------------------------------------------------------------------------
@dataclass
class Task:
    name: str
    fits: object        # Affordance -> bool
    target: str         # what vision looks for
    save_key: str       # save_bed_counts key: how many are left (a hint, law 6)
    kind: str = 'GardenBed'   # the graph node kind to reach (its appearance vectors: objects/db/<kind>)
    region: str = 'Garden'    # the node whose map picture gives the direction (objects/map_db)
    node: str = 'GardenBed@Garden'   # the graph node of the target: where she must be (graph navigation)


TASKS = {
    'replant': Task('replant', lambda a: bool(a.drop), 'a WILTED garden bed (grey/brown, drooping, dead-looking plants)', 'wilted'),
    'water': Task('water', lambda a: bool(a.drop), 'a garden bed whose crop needs water (dry soil, a water-drop bubble)', 'dry'),
    'harvest': Task('harvest', lambda a: a.kind == 'pickup', 'a RIPE garden bed (full-grown crop ready to pick)', 'ripe'),
}


def _left_in_save(task):
    try:
        return core.WF.save_bed_counts(core.WF.farm_status()['crops'])[task.save_key]
    except Exception:   # noqa: BLE001
        return None


def _gameplay():
    mode, _ = _texts()
    if mode != 'gameplay':
        ui.close()


def _nearest(affs, pt, pred=lambda a: True, max_d=None):
    best = None
    for a in affs:
        if not pred(a):
            continue
        d = (a.pt[0] - pt[0]) ** 2 + (a.pt[1] - pt[1]) ** 2
        if (max_d is None or d <= max_d ** 2) and (best is None or d < best[0]):
            best = (d, a)
    return best[1] if best else None


def _fill_can(res):
    from . import well
    ui.close()
    well.fill_can()
    res['refills'] += 1
    res['here'] = 'Well'   # graph navigation: after the refill she stands at the well, next to the hives


def _after_press(pt, mark, before, after):
    """A button press (Remove, Select) as a Click record: its log lines, bubbles before/after, the screen after."""
    lines = core.log_text(mark).splitlines()
    mode, texts = _texts()
    return Click(pt, 'press', mark, lines, [m.group(1) for m in map(EVENT.search, lines) if m], before, after, mode, texts)


def chains_observe_remove(c):
    """Step 'press Remove': from the card click's mark (its unplant_impl), bubbles before = the card click's before."""
    rec = _after_press(c.pt, c.mark, c.before, affordances.scan())
    rec.events = [e for e in rec.events if e != 'unplant']
    remember(rec.events)
    check(rec, 'replant', 1)


def _replant(c, res, seed):
    """The Remove card is open (event `unplant`): Remove -> the same crop -> Select -> water. 'done' | 'stop'."""
    from .garden import crop_name
    crop = crop_name(' / '.join(ui.texts())) or None
    want = seed or crop
    remember([], crop=crop)
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
    plant = _nearest(affordances.scan(), c.pt, lambda a: a.kind == 'plant')
    if plant is None:
        raise core.Failed('no seedling bubble after the bed was cleared; '
                          + core.ask_vision('the bed was just cleared: where is its planting bubble?'))
    chains_observe_remove(c)
    pc = record_click(plant.pt, 'bubble', chain='replant', idx=2)
    try:
        ui.pick_card(want)
    except core.Failed as e:
        ui.close()
        ui.close()
        res['stop'] = f'no seeds for {want}: {str(e)[:120]}'
        return 'stop'
    mark, before = core.WF.log_mark(), affordances.scan()
    ui.press('Select')
    if not core.seen(r'totalPlanted\.', mark, 3.0):
        raise core.Failed(f'Select was pressed but {want} was not planted; '
                          + core.ask_vision(f'is {want} planted on the bed?'))
    after = affordances.scan()
    sel = _after_press(pc.pt, mark, before, after)
    remember(sel.events)
    check(sel, 'replant', 3)
    drop = _nearest(after, pc.pt, lambda a: a.drop, max_d=250)
    if drop is None:
        res['notes'].append(f'{want} planted; no water bubble seen: water it later (water_all)')
        return 'done'
    w = record_click(drop.pt, 'bubble', chain='replant', idx=4)
    if w.has('out_of_water'):
        _fill_can(res)
        res['notes'].append(f'{want} planted; can was empty, refilled: the bed still needs water (water_all)')
    return 'done'


def _handle(task, c, res, seed):
    """Update the run from one click's result. 'done' | 'progress' | 'none' | 'stop'."""
    if c.node:
        res['here'] = c.node   # the logged interaction says which node she is at
    if task.name == 'replant' and c.has('unplant'):
        out = _replant(c, res, seed)
        if out == 'done':
            res['done'].append(c.pt)
        return out
    if c.has('out_of_water'):
        _fill_can(res)
        return 'progress'
    if c.has('water'):
        if task.name == 'water':
            res['done'].append(c.pt)
            return 'done'
        res['other'].append(f'@{c.pt[0]},{c.pt[1]} was dry, not wilted: watered')
        return 'progress'
    if c.has('grab_item'):
        if task.name == 'harvest':
            res['done'].append(c.pt)
            return 'done'
        res['other'].append(f'@{c.pt[0]},{c.pt[1]} was ripe: picked')
        return 'progress'
    if c.events or c.mode != 'gameplay':   # e.g. plant_growing, a wilted bed's card in the water task: not this task's node
        res['other'].append(f'@{c.pt[0]},{c.pt[1]}: {c.events or c.mode}')
        _gameplay()
        return 'none'
    return 'progress' if (c.moved or _bubble_set(c.before) != _bubble_set(c.after)) else 'none'


SEEK_TURNS = 6          # see -> map -> step rounds before vision is asked (user D185: limited turns, straightforward)
SEE_NEAR = 160          # px: a detection this close to Tara is where she already is (its bubble would show)
STEP_R = (320, 220)     # px from the centre for a map step; the second is tried when the first did not move her
STEP_TURN = (0, 35, -35)  # degrees off the map direction when a step did not move her


def _see(kind, tried=()):
    """The node's appearance vectors on the current frame: detections of `kind`, nearest to Tara first, without the
    one she stands at and points already tried. [Detection]"""
    from objects import detect as D, store as S
    img = core.WF.grab()
    dets = [d for d in D.detect(img, S.Store(), kinds=[kind])
            if _d(d.point, CENTRE) > SEE_NEAR and not _hud(d.point)
            and not any(_d(d.point, p) < 80 for p in tried)]
    return sorted(dets, key=lambda d: _d(d.point, CENTRE))


def _map_direction(node):
    """Open the map, find Tara's pin and `node`'s map picture, take the first stretch of the road route between them.
    A unit (dx, dy) in screen terms (the camera looks north like the map), or None when the map can't tell."""
    import math
    from objects import map_vectors as MV
    img = core.WF.map_snapshot()
    if img is None:
        return None
    pin = core.WF.map_pin(img)
    g = MEMORY['graph']
    if g is None:
        from objects import graph as OG
        g = OG.Graph()
        g.load(_graph_path())
    m = MV.locate(g, node, img) if pin else None
    if m is None:
        return None
    path = core.WF.map_route(img, pin, m.point) or [m.point]
    ahead = next((q for q in path if math.dist(q, pin) >= 60), path[-1])
    dx, dy = ahead[0] - pin[0], ahead[1] - pin[1]
    n = math.hypot(dx, dy)
    _log('seek', what='map', pin=list(pin), goal=list(m.point), score=round(m.score, 2), ahead=list(ahead))
    return None if n < 1 else (dx / n, dy / n)


def _step(d):
    """A few steps on the ground in direction `d` (Tara is at the centre): click a point STEP_R px away; turn a little
    when she did not move. The Click that moved her, or None."""
    import math
    for r in STEP_R:
        for deg in STEP_TURN:
            a = math.radians(deg)
            x = d[0] * math.cos(a) - d[1] * math.sin(a)
            y = d[0] * math.sin(a) + d[1] * math.cos(a)
            pt = (int(CENTRE[0] + x * r), int(CENTRE[1] + y * r))
            if _hud(pt):
                continue
            c = record_click(pt, 'step')
            if _changed(c):
                return c
    return None


def _seek(task, res):
    """One round when no fitting bubble shows (user D185). In order: (0) an unknown bubble not tried yet -> click it once
    (its event teaches its kind: gap filling); (1) she is at another node (the last event's target, e.g. the Well after a
    refill) -> the graph's direction from there to the target node -> a few steps; (2) the target's vectors on screen ->
    click the nearest (a click that lands on another node, e.g. a hive, is never repeated and tells where she is);
    (3) the map's direction -> a few steps. The Click that changed something, or None (then vision)."""
    from objects import graph as OG
    tried = res.setdefault('tried', [])   # points that led elsewhere: never clicked again this call

    def fresh(pt):
        return not any(_d(pt, p) < 80 for p in tried)

    unk = [a for a in affordances.scan() if a.kind == 'unknown' and fresh(a.pt)]
    if unk:
        a = _nearest(unk, CENTRE)
        tried.append(a.pt)
        c = record_click(a.pt, 'bubble')
        res['clicks'] += 1
        if _changed(c):
            return c
    here = res.get('here')
    if here and here != task.node:
        d = OG.toward(MEMORY['graph'], here, task.node)
        if d:
            _log('seek', what='graph', here=here, to=task.node, dir=list(d))
            c = _step(d)
            res['clicks'] += 1
            if c is not None:
                res['here'] = c.node   # she left that node: unknown until the next event names one
                return c
    for det in _see(task.kind, tried)[:2]:
        c = record_click(det.point, 'object')
        res['clicks'] += 1
        tried.append(det.point)
        if c.node and c.node != task.node:   # a hive seen as a bed: she is there now; the graph leads on
            return c
        if _changed(c):
            return c
    d = _map_direction(task.region)
    if d is None:
        return None
    c = _step(d)
    res['clicks'] += 1
    return c


def _changed(c):
    """The click did something: Tara moved (view changed), an event, a card, or the bubbles changed."""
    return bool(c.moved or c.events or c.mode != 'gameplay' or _bubble_set(c.before) != _bubble_set(c.after))


def _log(type_, **kw):
    try:
        core.WF.run_log(type_, **kw)
    except Exception:   # noqa: BLE001
        pass


def _d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _hud(pt):
    return any(x0 <= pt[0] < x1 and y0 <= pt[1] < y1 for x0, y0, x1, y1 in HUD)


def _ask(task, st, res, last):
    """Law 2: one vision question, the click point of the next node. Raises NeedVision (or LawsStuck after MAX_ASKS)."""
    from objects.loop import NeedVision
    if st['asks'] >= MAX_ASKS:
        hist = ' | '.join(st['history'][-3:])
        reset(task.name)
        raise LawsStuck(f'LAWS_STUCK: {task.name} asked vision {MAX_ASKS} times without progress; last: {hist}. '
                        'Stop and report; do not retry blindly.')
    _gameplay()
    left = res['left_in_save']
    q = (f'Task: {task.name}. Tara is the magenta circle (always the frame centre). No fitting bubble is on screen. '
         f'Give the grid cell of {task.target} nearest to Tara: a cell on the bed itself (its soil/plants, not on a bubble). '
         f'If no such bed is visible but the garden may be off-screen, give a cell of open ground toward the garden. '
         f'If there is none left anywhere, answer none.'
         + (f' The save says {left} left (may be stale).' if left is not None else '')
         + f' This call: done {len(res["done"])}, other {res["other"][-3:]}.'
         + (f' Memory: {memory_hint()}.' if memory_hint() else '')
         + (f' Your last answer led to: {last.describe()}.' if last is not None else ''))
    st['asks'] += 1
    st['history'] = (st['history'] + [last.describe()[:160] if last is not None else 'no fitting bubble'])[-6:]
    _save_state(st)
    ans = f"./wf py \"{'replant' if task.name == 'replant' else task.name}_all(click='Q14')\""
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
            + (f", surprises: {res['surprises']}" if res.get('surprises') else '') + (f", notes: {res['notes']}" if res['notes'] else ''))


def run(task_name, click=None, seed=None, max_clicks=30):
    """Do `task_name` ('replant' | 'water' | 'harvest') on every fitting garden bed by the four laws. `click` = vision's
    answer to the last question: a grid cell ('Q14'), (x, y), or 'none' (nothing left: the run ends). Returns the summary
    dict; raises NeedVision when no fitting bubble is on screen (answer by calling again with click=...)."""
    _open_memory()
    try:
        return _run(TASKS[task_name], click, seed, max_clicks)
    finally:
        _close_memory()


def _run(task, click, seed, max_clicks):
    st = _load_state(task.name)
    res = {'task': task.name, 'done': [], 'other': [], 'notes': [], 'clicks': 0, 'vision': 0, 'refills': 0,
           'stop': None, 'left_in_save': _left_in_save(task), 'surprises': SURPRISES}
    SURPRISES.clear()
    _gameplay()
    last = None
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
            raise core.Failed(f'click answer rejected: {e}. Answer a grid cell A1-X16 on the bed, or none') from None
        last = record_click(pt, 'point')
        res['clicks'] += 1
        out = _handle(task, last, res, seed)
        if out == 'stop':
            return res
        if out in ('done', 'progress'):
            reset(task.name)
            st = _load_state(task.name)
    seeks = 0    # seek rounds since the last fitting bubble
    tried = []   # bubble points that did not progress (a growing bed's drop misread, ...): never clicked again this call
    while res['clicks'] < max_clicks and not res['stop']:
        if res['left_in_save'] is not None and len(res['done']) >= res['left_in_save'] > 0 and task.name == 'replant':
            break   # every wilted bed the save knows of is replanted
        affs = affordances.scan()
        fit = [a for a in affs if task.fits(a) and not any(abs(a.pt[0] - p[0]) < 60 and abs(a.pt[1] - p[1]) < 60 for p in tried)]
        if not fit:
            seeks += 1   # the node's vector on screen, else the map's direction; vision only after SEEK_TURNS
            c = _seek(task, res) if seeks <= SEEK_TURNS else None
            if c is None:
                _ask(task, st, res, last)
            last = c
            out = _handle(task, c, res, seed)
            if out == 'stop':
                break
            continue
        seeks = 0
        a = _nearest(fit, CENTRE)
        last = record_click(a.pt, 'bubble', before=affs)   # checked by its event (STEP_OF)
        res['clicks'] += 1
        out = _handle(task, last, res, seed)
        if out == 'stop':
            break
        if out == 'none':
            tried.append(a.pt)
        else:   # something changed (bubbles moved): progress resets the vision counter
            tried = []
            reset(task.name)
            st = _load_state(task.name)
    return res
