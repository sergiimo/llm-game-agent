"""Game functions (L77): medium-size, self-contained functions (`garden.water_all()`) that agents compose
like code (`./wf py "replant_all()"`). Each one does its inputs, handles its own
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


VISION_ASKS = []   # questions asked of vision (tests read it)


def ask_vision(question):
    """Uncertainty → model vision, always (user, D183): the frame at the innermost failure (before callers close
    menus) as the shared vision ask (`wf.ask_vision`: gridded frame + run-log `vision` event)."""
    from . import ask
    ask.clear_pending()
    question = ('DIAGNOSTIC ONLY — do not issue a gameplay or navigation answer. Inspect this captured frame, then '
                'choose exactly one: update a visual label/embedding; update transition code; or report an '
                f'unresolved game-logic issue to the human. {question}')
    VISION_ASKS.append(question)
    try:
        prompt = WF.ask_vision('game', question, WF.grab())
    except Exception:  # noqa: BLE001 (fakes have no frame)
        return f'NEED_VISION game: {question} (no frame saved: ./wf look)'
    try:
        ask._freeze()
    except Exception:
        pass  # A pause failure must not discard the captured evidence or its question.
    return prompt


def bind(wf):
    global WF
    WF = wf


def log_text(mark):
    return WF._unhash(WF.log_since(mark))


def seen(pattern, mark, wait=LOG_WAIT):
    """The regex `pattern` in the game log since `mark` (waiting up to `wait` s); the line, or None."""
    end = time.time() + wait
    while True:
        for line in log_text(mark).splitlines():
            if re.search(pattern, line):
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
            if 'NEED_VISION' in why:  # an inner action already saved the frame of the failure
                raise
            why = f'{why}; ' + ask_vision(f'{name}({args}) is unsure: what is on screen, what should be clicked?')
            raise Failed(why) from e
        except Exception as e:  # noqa: BLE001
            ok, why = False, f'{type(e).__name__}: {e}'
            if type(e).__name__ in ('Stuck', 'NeedVision', 'LawsStuck'):  # a vision question goes to the agent as it is
                raise
            raise Failed(f'{name}({args}): {why}') from e
        finally:
            _DEPTH[0] -= 1
            if depth == 0:  # one screen read per top-level action (≈0.5 s each)
                _SCREEN[0] = screen()
            track.action_event(name, args, t0, time.time(), depth, ok, why, before, _SCREEN[0])
            if depth == 0:  # eval (M0): a top-level action proved itself or not
                try:
                    import evals
                    evals.record('skills', name, args, 'ok' if ok else why, ok, {'action': name, 'args': args})
                except Exception:  # noqa: BLE001 (scoring never breaks play)
                    pass
    return run


def prove(what, pattern, mark, wait=LOG_WAIT):
    """Raise Failed unless `pattern` shows in the game log since `mark`."""
    line = seen(pattern, mark, wait)
    if not line:
        raise Failed(f'{what}: no `{pattern}` in the game log (screen: {screen()})')
    return line
