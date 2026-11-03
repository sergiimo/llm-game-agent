"""ACT: one click and its full record (framework: observe -> act -> learn -> nav; law 3).

`click(pt, what)` clicks, catches a burst of frames (short-lived text, bubble changes, movement), waits for the late log
line, reads the screen, and hands the result to LEARN (bubble kind, memory). State comes from the record:
log event > card > bubble change > text > vision."""
import os
import re
import time
from dataclasses import dataclass, field

from . import core, learn as L, observe as O, ui

BURST = (0.0, 0.5, 1.5)    # s after the click: frames that catch short-lived text and bubble changes
EVENT_WAIT = 2.5           # s more for a late log line (D149: `> water` came after ~3 s)
EVENT = re.compile(r'> (\w+)(?:\s|$)')
SHOTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.shots')


@dataclass
class Click:
    """What one click did."""
    pt: tuple
    what: str                                   # 'bubble' | 'point' | 'step' | 'explore' | 'soil' | 'object' | 'press'
    mark: int
    lines: list = field(default_factory=list)   # new game-log lines
    events: list = field(default_factory=list)  # their event types ('unplant', 'water', ...)
    before: list = field(default_factory=list)  # Affordances before
    after: list = field(default_factory=list)   # Affordances after
    mode: str = 'gameplay'                      # the screen after (a card/panel = not 'gameplay')
    texts: list = field(default_factory=list)   # on-screen texts after
    moved: object = None                        # True/False: the view changed during the burst; None = unknown
    frames: list = field(default_factory=list)  # saved burst frame paths
    burst_texts: list = field(default_factory=list)  # short-lived texts OCR'd from the burst frames
    node: str = None                            # the graph node the logged interaction names (target=...)
    at: tuple = None                            # world (x, z) of the logged interaction (`at (x, y, z)`), if any

    def has(self, *names):
        return any(e in names for e in self.events)

    def nothing(self):
        """No event, no card, no bubble change, no view change: the click did nothing visible."""
        return (not self.events and self.mode == 'gameplay' and O.bubble_set(self.before) == O.bubble_set(self.after)
                and self.moved is False)

    def describe(self):
        bub = ', '.join(str(a) for a in self.after) or 'none'
        return (f'click {self.what} @{self.pt[0]},{self.pt[1]}: events {self.events or "none"}; screen {self.mode}'
                f'{" (" + " / ".join(self.texts[:3]) + ")" if self.texts else ""}; bubbles after: {bub}; '
                f'view {"changed" if self.moved else "unchanged" if self.moved is False else "?"}'
                f'{"; frames " + ", ".join(self.frames) if self.frames else ""}')


def frames_dir():
    try:
        d = core.WF.run_dir()
    except Exception:   # noqa: BLE001
        d = None
    return os.path.join(d or SHOTS, 'clicks')


def save_frames(imgs, tag):
    out = []
    try:
        d = frames_dir()
        os.makedirs(d, exist_ok=True)
        for i, img in enumerate(imgs):
            p = os.path.join(d, f'{tag}-{i}.jpg')
            img.convert('RGB').resize((960, 540)).save(p, quality=70)
            out.append(p)
        for f in sorted(os.listdir(d))[:-90]:   # keep the last 30 clicks' bursts
            os.remove(os.path.join(d, f))
    except Exception:   # noqa: BLE001 (fakes, disk): recording never breaks play
        pass
    return out


AT = re.compile(r' at \(([-\d.]+), [-\d.]+, ([-\d.]+)\)')


def position_of(line):
    m = AT.search(line)
    return (float(m.group(1)), float(m.group(2))) if m else None


def events_of(lines):
    return [m.group(1) for m in map(EVENT.search, lines) if m]


def click(pt, what='point', before=None):
    """Click `pt` and record everything it did; LEARN gets it (bubble kind, memory). Returns a Click."""
    W = core.WF
    before = O.scan() if before is None else before
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
    mode, ts = O.texts()
    c = Click((x, y), what, mark, lines, events_of(lines), before, O.scan(), mode, ts,
              O.view_changed(imgs[0], imgs[-1]) if len(imgs) > 1 else None,
              save_frames(imgs, time.strftime('%H%M%S') + f'-{x}-{y}'), O.burst_texts(imgs) if L.text_gaps() else [])
    from objects import graph as OG
    c.node = next((n for n in map(OG.node_of_line, lines) if n), None)
    c.at = next((p for p in map(position_of, lines) if p), None)
    learned = L.learn_bubble(c, img0)
    L.remember(c.events)
    try:
        W.run_log('click', node=c.node, learned=learned, pt=[x, y], what=what, events=c.events, mode=mode,
                  texts=ts[:4], before=[str(a) for a in before], after=[str(a) for a in c.after], moved=c.moved,
                  frames=c.frames, burst_texts=c.burst_texts[:6])
    except Exception:   # noqa: BLE001
        pass
    return c


def after_press(pt, mark, before, after):
    """A button press (Remove, Select) as a Click record: its log lines, bubbles before/after, the screen after."""
    lines = core.log_text(mark).splitlines()
    mode, ts = O.texts()
    return Click(pt, 'press', mark, lines, events_of(lines), before, after, mode, ts)


def gameplay():
    """Close any card/panel: back to gameplay (failure = reset, law 5)."""
    mode, _ = O.texts()
    if mode != 'gameplay':
        ui.close()
