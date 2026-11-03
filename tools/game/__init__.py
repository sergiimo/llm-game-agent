"""Game functions for agents (L77). `./wf py "<code>"` runs code with these names in scope; `./wf call garden.water_all`
runs one. Add behaviour by adding a function to the module of its area."""
from . import affordances, core, garden, move, track, ui, walk, well  # noqa: F401
from .core import Failed, bind  # noqa: F401
from .garden import discover, harvest_all, plant_all, replant_all, water_all  # noqa: F401
from .laws import reach  # noqa: F401
from .move import goto  # noqa: F401
from .ui import close, press, press_bubble, shows  # noqa: F401
from .well import fill_can  # noqa: F401
from objects import loop  # noqa: F401
from objects.loop import answer, available, label  # noqa: F401  (asks + latest bubble-active graph nodes)


def namespace():
    """Names visible to `./wf py` code."""
    return {k: v for k, v in globals().items() if not k.startswith('_')}
