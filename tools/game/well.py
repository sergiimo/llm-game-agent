"""The well on the object loop: click the can bubble if it shows, else `loop.goto(Q(kind='Well'))` clicks the well as soon
as it is visible (else the next region step) and returns when its bubble is up. The log line proves it and updates the
graph's Well state. NeedVision propagates: the agent answers (`loop.answer(n, X, Y)`) and runs `fill_can()` again."""
import os

from objects import graph as G, loop
from objects.query import Q

from . import core
from .core import action, prove

GRAPH = os.path.join(G.DEFAULT_DIR, 'Farm.json')
PROOF = r'target=Well|My watering can is already full'


def _can_bubble():
    img = core.WF.grab()
    for b in core.WF.find_bubbles(img) or []:
        try:
            kind = core.WF.bubble_kind(img, b)[0]
        except Exception:  # noqa: BLE001
            continue
        if kind in ('fill_can', 'full_watering_can'):
            return (int(b[0]), int(b[1]))
    return None


def _click(pt):
    core.WF.run_action(f'click:{pt[0]}:{pt[1]}')
    try:
        core.WF.wait_settle()
    except AttributeError:
        pass


FILLED = r'> (?:fill_watering_can|full_watering_can) '
FILL_WAIT = 3.0   # s: the fill line is written ~1-3 s after the click (D185: a 0.5 s wait missed it -> a 2nd click, "already full")


def _filled(mark):
    """The log line proving the can is full since `mark` (filled now, or already full), else None."""
    return core.seen(FILLED, mark, FILL_WAIT) or None


@action
def fill_can(graph=None):
    """Fill the watering can at the well (an already full can counts as done); sets the graph's Well can=full. With `graph`
    (the chain's) the state goes into that graph and the caller saves it; without, Farm.json is loaded and saved here."""
    g = graph
    if g is None:
        g = G.Graph()
        g.load(GRAPH)
    start = core.WF.log_mark()
    line = None
    pt = _can_bubble()
    if pt is None:
        # Law 2/3 (L126): a click on the visible well walks there AND fills the can, so the log may prove success while
        # goto still waits for the well's bubble; the log event wins over goto's own arrival check.
        try:
            pt = loop.goto(Q(kind='Well'), core.WF, graph=g).point
        except (loop.NeedVision, core.Failed):
            line = _filled(start)
            if line is None:
                raise
        else:
            line = _filled(start)
    if line is None:
        mark = core.WF.log_mark()
        _click(pt)
        line = prove('fill the can', PROOF, mark)
    changes = G.apply_log(g, [line], at=None)
    if not changes and 'already full' in line:
        g.set_state('Well', 'can', 'full', line.split(']')[0].lstrip('[') if line.startswith('[') else None, 'event')
    if graph is None:
        g.save(GRAPH)
    return line
