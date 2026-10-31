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


@action
def fill_can():
    """Fill the watering can at the well (an already full can counts as done); sets the graph's Well can=full."""
    g = G.Graph()
    g.load(GRAPH)
    pt = _can_bubble()
    if pt is None:
        pt = loop.goto(Q(kind='Well'), core.WF, graph=g).point
    mark = core.WF.log_mark()
    _click(pt)
    line = prove('fill the can', PROOF, mark)
    changes = G.apply_log(g, [line], [])
    if not changes and 'already full' in line:
        g.set_state('Well', 'can', 'full', line.split(']')[0].lstrip('[') if line.startswith('[') else None, 'log')
    g.save(GRAPH)
    return line
