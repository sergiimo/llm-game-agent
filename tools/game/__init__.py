"""Game functions for agents (L77). `./wf py "<code>"` runs code with these names in scope; `./wf call garden.water_all`
runs one. Chores are goals of the engine (`achieve`, L138); `smoke` holds the proven primitives (L147)."""
from . import affordances, badges, core, garden, integrate, smoke, track, ui  # noqa: F401 (integrate: the boundary)
from .ask import NeedVision  # noqa: F401
from .core import Failed, bind  # noqa: F401
from .engine import achieve  # noqa: F401
from .garden import harvest_all, plant_all, replant_all, water_all  # noqa: F401
from .nav import reach  # noqa: F401
from .smoke import fill_can, morning, plant_garden  # noqa: F401
from .ui import close, press, press_bubble, shows  # noqa: F401


def namespace():
    """Names visible to `./wf py` code."""
    return {k: v for k, v in globals().items() if not k.startswith('_')}
