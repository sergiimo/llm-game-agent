"""The garden (L77): chores as goals of the engine (game/engine.py, spec 2026-11-03): each is one `achieve` call on a
goal from game/goals.json. NEED_VISION: answer by calling again with click='<grid cell>' (or 'none'). Log (D148):
`> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written when the planting
panel closes, `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered."""
from .core import action


def crop_name(card_text):
    """The crop a bed card names: its first line ("Green Bean / The unripe fruit … / This plant has wilted")."""
    return card_text.split(' / ', 1)[0].strip()


def _go(goal, click, **params):
    from . import engine
    return engine.achieve(goal, answer=click, **{k: v for k, v in params.items() if v is not None})


@action
def water_all(click=None):
    """Water every growing, dry bed (goal `water`)."""
    return _go('water', click)


@action
def replant_all(seed=None, click=None):
    """Every wilted bed: remove, replant the same crop (read from the wilted card), water (goal `replant`); `seed`
    plants that crop instead."""
    if seed:
        from . import engine
        return engine.achieve({'kind': 'GardenBed', 'where': {'wilted': True}, 'make': {'crop': seed, 'watered': True}},
                              answer=click)
    return _go('replant', click)


@action
def harvest_all(crops=None, click=None):
    """Pick the ripe beds of `crops` (goal `harvest`). No default: "!" is not an order to collect (user D185: flowers
    serve the bees), so without crops the engine answers NEED_INPUT with the crops seen."""
    return _go('harvest', click, crops=crops)


@action
def plant_all(seed=None, region=None, click=None):
    """Plant `seed` in every empty bed of the area `region` (goal `plant`; `./wf world nodes` lists the areas)."""
    return _go('plant', click, seed=seed, region=region)
