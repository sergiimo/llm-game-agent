"""The garden (L77): one streaming pass inspects a bed, acts immediately, then advances. Log (D148):
`> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written when the planting
panel closes, `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered."""
from .core import action


def crop_name(card_text):
    """The crop a bed card names: its first line ("Green Bean / The unripe fruit … / This plant has wilted")."""
    return card_text.split(' / ', 1)[0].strip()


def _go(goal, click, **params):
    from . import engine
    return engine.achieve(goal, answer=click, **{k: v for k, v in params.items() if v is not None})


def _tend(chores, click=None, region='Garden', max_clicks=40, crops=None):
    from . import engine
    return engine.tend_garden(region, chores, answer=click, max_clicks=max_clicks, crops=crops)


@action
def do(region='Garden', click=None, max_clicks=40, crops=None):
    """Treat every bed and hive: harvest/collect, plant empty beds, replant wilted crops, and water.

    `crops` explicitly authorizes named flowers that the default routine preserves for bees.
    """
    return _tend(('plant', 'replant', 'harvest', 'water'), click, region, max_clicks, crops)


@action
def water_all(click=None, region='Garden', max_clicks=40):
    """Water every growing, dry bed (goal `water`)."""
    return _tend(('water',), click, region, max_clicks)


@action
def replant_all(seed=None, click=None, region='Garden', max_clicks=40):
    """Every wilted bed: remove, replant the same crop (read from the wilted card), water (goal `replant`); `seed`
    plants that crop instead."""
    if seed:
        from . import engine
        return engine.achieve({'kind': 'GardenBed', 'where': {'wilted': True}, 'make': {'crop': seed, 'watered': True}},
                              answer=click)
    return _tend(('replant',), click, region, max_clicks)


@action
def harvest_all(crops=None, click=None, region='Garden', max_clicks=40):
    """Pick the ripe beds of `crops` (goal `harvest`). No default: "!" is not an order to collect (user D185: flowers
    serve the bees), so without crops the engine answers NEED_INPUT with the crops seen."""
    if crops:
        return _go('harvest', click, crops=crops, region=region)
    return _tend(('harvest',), click, region, max_clicks)


@action
def plant_all(seed=None, region=None, click=None):
    """Plant `seed` in every empty bed of the area `region` (goal `plant`; `./wf world nodes` lists the areas)."""
    return _go('plant', click, seed=seed, region=region)


def summary(res):
    return (f"garden: visited {len(res['visited'])}, hives {len(res.get('hives_visited', []))}, "
            f"honey {res.get('honey', 0)}, acted {len(res['acted'])}, flowers {len(res['flowers'])}, "
            f"unresolved {len(res['unresolved'])}, harvested {res['harvested']}, replanted {res['replanted']}, "
            f"watered {res['watered']}, clicks {res['clicks']}, vision {res['vision']}, stop: {res['stop']}")
