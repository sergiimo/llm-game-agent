"""The interaction laws (wiki/mechanics/interaction-laws.md, user D183-D185, L124-L138) now run in the generic engine
(game/engine.py, spec 2026-11-03): goals (goals.json) over a world graph (world.py) with a learned transition table
(actions.json, plan.py, steps.py), one vision question at a time (ask.py), navigation in nav.py. This module keeps the
names older callers import."""
from .act import BURST, EVENT_WAIT, Click, click as record_click  # noqa: F401
from .ask import (CELL_H, CELL_W, COLS, EARLY, LATE, MAX_ASKS, ROWS, draw_grid, late, parse_point)  # noqa: F401
from .nav import EXPLORE_R, MAP_STEP_R, SEEK_TURNS, STEP_R, STUCK_CLICKS, Target, reach  # noqa: F401
from .observe import CENTRE, HUD, LawsStuck, WrongLanguage, check_language, closest_node  # noqa: F401
