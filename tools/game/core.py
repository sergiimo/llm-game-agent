"""Game functions (L77): medium-size, self-contained functions (`garden.plant(bed, 'Tulip')`) that agents compose
like code (`./wf py "for b in beds(wilted=True): replant(b)"`). Each one does its inputs, handles its own
confirmations, and checks the game log for the line that proves it happened; `@action` logs every call (args,
time, screen, result) as a tree into the run log. All game access goes through `WF` (the wf module, bound by
wf.py; tests bind a fake)."""
import functools
import re
import time

WF = None
_DEPTH = [0]
_SCREEN = ['?']        # the screen after the last action = the screen before the next one
LOG_WAIT = 6.0         # seconds to wait for a proving log line (D149: a `> water` line came after 3 s)


class Failed(Exception):
    """An action could not prove it happened; the message says which and why."""


def bind(wf):
    global WF
    WF = wf


def log_text(mark):
    return WF._unhash(WF.log_since(mark))


def seen(pattern, mark, wait=LOG_WAIT, at=None):
    """The regex `pattern` in the game log since `mark` (waiting up to `wait` s). at=(x, z): the line's position
    must be within 0.5 of it (`… at (x, y, z)`), so the proof is for this target, not a neighbour."""
    end = time.time() + wait
    while True:
        for line in log_text(mark).splitlines():
            if re.search(pattern, line):
                if at is None:
                    return line
                m = re.search(r' at \((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)', line)
                if m and abs(float(m.group(1)) - at[0]) < 0.5 and abs(float(m.group(3)) - at[1]) < 0.5:
                    return line
        if time.time() >= end:
            return None
        time.sleep(0.3)


def screen():
    """Short label of what's on screen: mode + first texts (for the action log)."""
    try:
        s = WF.state()
        txt = ' / '.join(t.split(') ', 1)[-1] for t in s.get('text', [])[:3])
        return f"{s['mode']}" + (f': {txt[:80]}' if txt else '')
    except Exception as e:  # noqa: BLE001 (a label must never break an action)
        return f'? ({type(e).__name__})'


def _fmt(a, kw):
    return ', '.join([str(x) for x in a] + [f'{k}={v!r}' for k, v in kw.items()])


def action(fn):
    """Log the call as one node of the action tree (start, end, depth, screen before/after, ok/why) and turn any
    error into Failed naming the action. Proving log lines are checked inside the function with `prove()`."""
    from . import track

    @functools.wraps(fn)
    def run(*a, **kw):
        name = f'{fn.__module__.rsplit(".", 1)[-1]}.{fn.__name__}'
        args = _fmt(a, kw)
        t0, before = time.time(), _SCREEN[0]
        depth = _DEPTH[0]
        _DEPTH[0] += 1
        ok, why = True, None
        try:
            return fn(*a, **kw)
        except Failed as e:
            ok, why = False, str(e)
            raise
        except Exception as e:  # noqa: BLE001
            ok, why = False, f'{type(e).__name__}: {e}'
            raise Failed(f'{name}({args}): {why}') from e
        finally:
            _DEPTH[0] -= 1
            if depth == 0:  # one screen read per top-level action (≈0.5 s each)
                _SCREEN[0] = screen()
            track.action_event(name, args, t0, time.time(), depth, ok, why, before, _SCREEN[0])
    return run


def prove(what, pattern, mark, at=None, wait=LOG_WAIT):
    """Raise Failed unless `pattern` shows in the game log since `mark` (for target position `at`)."""
    line = seen(pattern, mark, wait, at)
    if not line:
        raise Failed(f'{what}: no `{pattern}` in the game log' + (f' at {at}' if at else '') +
                     f' (screen: {screen()})')
    return line
