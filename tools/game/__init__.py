"""Game functions for agents (L77). `./wf py "<code>"` runs code with these names in scope; `./wf call garden.water 3`
runs one. Add behaviour by adding a function to the module of its area."""
from . import core, garden, move, track, ui, well  # noqa: F401
from .core import Failed, bind  # noqa: F401
from .garden import Bed, bed, beds, harvest, plant, replant, unplant, water  # noqa: F401
from .move import goto  # noqa: F401
from .ui import close, press, press_bubble, shows  # noqa: F401
from .well import fill_can  # noqa: F401


def namespace():
    """Names visible to `./wf py` code."""
    return {k: v for k, v in globals().items() if not k.startswith('_')}
