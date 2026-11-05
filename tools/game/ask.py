"""ASK: the one vision question (spec 2026-11-03 §7) and the state it needs across calls.

Uncertainty -> vision, never a guess. One question at a time, of a kind: `click` (a grid cell: the next node / free
ground), `button` (which on-screen text to press next), `name` (what an unknown icon/card/state change is). Its context
is kept as a PENDING record ({kind, goal, params, row?, step?, bubble?, node?}) so the answer lands where it was asked;
the hint names the goal call (`./wf achieve <goal> k=v answer=...`). LAWS_STUCK after MAX_ASKS without progress.
Also: the A-X x 1-16 grid (draw_grid, parse_point) and the clock stop (late)."""
import json
import os
import re

from . import act as A, core, observe as O
from .observe import CENTRE, LawsStuck

W_, H_ = O.W_, O.H_
COLS, ROWS = 24, 16                    # the vision grid (same as wf ask_vision 'click': A-X x 1-16)
CELL_W, CELL_H = W_ / COLS, H_ / ROWS  # 80 x 67.5 px
MAX_ASKS = 4                           # vision questions in a row without progress -> LawsStuck
STALE_S = 600.0                        # s: question state this old was left by a killed attempt: start fresh
LATE, EARLY = 23.0, 6.0                # game hours: no garden work after LATE / before EARLY (AGENTS rule 0, L27)
STATE = os.path.join(A.SHOTS, 'ask-state.json')


class NeedVision(Exception):
    """ONE question for model vision: the message carries the framed image and the answer call."""


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


# ---- cross-call state ----------------------------------------------------------------------------------------------
def _all(path=None):
    try:
        with open(path or STATE) as fh:
            s = json.load(fh)
    except (OSError, ValueError):
        return {}
    if 'goal' in s or 'task' in s:   # the old single-goal file: one entry
        return {s.get('goal', s.get('task')): s}
    return s


def load_state(goal, path=None):
    """This goal's question state (vision counter, history, trace, pending): kept per goal, so progress on one goal
    never erases another goal's pending question (D188)."""
    import time
    st = _all(path).get(str(goal))
    if st and time.time() - (st.get('t') or 0) > STALE_S:   # live D188: killed attempts left the counter at 3
        st = None
    return st if st else {'goal': goal, 'asks': 0, 'history': []}


def save_state(s, path=None):
    import time
    s = dict(s, t=time.time())   # every save is activity: only a state left alone for STALE_S is stale
    try:
        allst = _all(path)
        allst[str(s.get('goal', s.get('task')))] = s
        os.makedirs(os.path.dirname(path or STATE), exist_ok=True)
        with open(path or STATE, 'w') as fh:
            json.dump(allst, fh)
    except OSError:
        pass


def progress(goal):
    """Progress resets the vision counter (and drops this goal's pending question)."""
    save_state({'goal': goal, 'asks': 0, 'history': []})


def take_answer(goal):
    """The pending question of `goal` (once): the record the answer belongs to, or None."""
    st = load_state(goal)
    p = st.pop('pending', None)
    if p is not None:
        save_state(st)
    return p


def hint(goal, params):
    ps = ' '.join(f'{k}={v}' for k, v in (params or {}).items())
    if isinstance(goal, str) and goal.startswith('forage:'):   # the foraging strategy (game/forage.py)
        return f'./wf forage {goal.split(":", 1)[1]}{" " + ps if ps else ""} answer='

    g = goal if isinstance(goal, str) and re.fullmatch(r'\w+', goal) else f"'{json.dumps(goal)}'"
    return f'./wf achieve {g}{" " + ps if ps else ""} answer='


def ask(kind, question, pending, res, img=None):
    """Raise NeedVision for ONE question (`click` | `button` | `name`) with the frame (or `img`: the map marked up for
    a way question); LawsStuck after MAX_ASKS."""
    if kind == 'decide':
        kind = 'name'   # a free-form answer with a supplied image, using the existing name path
    goal = pending.get('goal')
    st = load_state(goal)
    if st['asks'] >= MAX_ASKS:
        hist = ' | '.join(st['history'][-3:])
        progress(goal)
        raise LawsStuck(f'LAWS_STUCK: {goal} asked vision {MAX_ASKS} times without progress; last: {hist}. '
                        'Stop and report; do not retry blindly.')
    A.gameplay() if kind == 'click' else None
    tr = res.get('trace', [])
    st['asks'] += 1
    st['history'] = (st['history'] + [question[:160]])[-6:]
    st['trace'] = tr[-8:]
    st['pending'] = dict(pending, kind=kind)
    save_state(st)
    how = {'click': 'a grid cell (e.g. Q14), or none', 'button': 'the exact on-screen text to press',
           'name': 'key=value (what changed), or the name'}[kind]
    if pending.get('decide'):
        how = 'click <object id> | walk <cell> | settle <ids>: key=value | done'
    ans = hint(goal, pending.get('params')) + f'<{how}>'
    q = question + (f' The search already tried, in order: {"; ".join(tr[-10:])}.' if tr else '')
    try:
        prompt = core.WF.ask_vision(kind if kind == 'click' else 'game', q, img if img is not None else core.WF.grab(),
                                    answer=ans)
    except Exception:   # noqa: BLE001
        prompt = f'NEED_VISION {kind}: {q} (no frame saved: ./wf look)'
    res['vision'] = res.get('vision', 0) + 1
    _freeze()
    raise NeedVision(f'{prompt}\n  answer: {ans}')


def _freeze():
    """The question's frame is taken: pause the game so thinking costs no game time (live D189: 46 s idle, the clock
    running); only on plain gameplay (Escape on an open card would close it). The next call resumes (screen rules)."""
    try:
        from . import screen
        if screen.read().kind == 'gameplay' and hasattr(core.WF, 'set_paused'):
            core.WF.set_paused(True)
    except Exception:   # noqa: BLE001
        pass


RAIN = ('Raining', 'Rain', 'Storm', 'Thunder')


def rain():
    """Today's forecast from the game log when it is rain/storm ('Raining'), else None (user D187: avoid rain for now)."""
    try:
        lines = core.WF.today_log()[0]
    except Exception:   # noqa: BLE001
        return None
    for line in reversed(lines):
        m = re.search(r'Forecast is (\w+)', line)
        if m:
            return m.group(1) if m.group(1) in RAIN else None
    return None


def late(res):
    """The HUD clock: after LATE or before EARLY -> res['stop']; sets res['light'] for the soil tones."""
    h, light = O.clock()
    if h is None:
        return False
    res['light'] = light
    if h >= LATE or h < EARLY:
        res['stop'] = f'late: game time {int(h):02d}:{int(h % 1 * 60):02d}; no more garden work tonight (ask about bed)'
        return True
    return False
