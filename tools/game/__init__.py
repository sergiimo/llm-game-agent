"""Game functions for agents (L77). `./wf py "<code>"` runs code with these names in scope; `./wf call garden.water 3`
runs one. Add behaviour by adding a function to the module of its area."""
from . import affordances, core, garden, move, track, ui, walk, well  # noqa: F401
from .core import Failed, bind  # noqa: F401
from .garden import Bed, bed, beds, goto_bed, harvest, plant, replant, unplant, water  # noqa: F401
from .move import goto  # noqa: F401
from .ui import close, press, press_bubble, shows  # noqa: F401
from .well import fill_can  # noqa: F401
from objects import loop  # noqa: F401
from objects.loop import answer, label  # noqa: F401  (answer an ask: `answer(n, X, Y)` / `label(n, 'Well', x0, y0, x1, y1)`)


def namespace():
    """Names visible to `./wf py` code."""
    return {k: v for k, v in globals().items() if not k.startswith('_')}
