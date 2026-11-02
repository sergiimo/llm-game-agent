"""The garden (L77): `replant_all` / `water_all` / `harvest_all` run the interaction laws (game/laws.py,
docs/mechanics/interaction-laws.md, L124); `goto_bed` walks to a bed by the object loop. Log (D148): `> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written
when the planting panel closes (also when cancelled), `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered. Planting panel = "Inventory / Seeds" picker: cards show icon + count only (Green Bean 26,
Carrot 10, Tulip 22 on D148); clicking one opens its detail card (title + Select)."""

from objects import loop
from objects.query import Q

from . import core
from .core import action


@action
def goto_bed(**state):
    """Walk to a bed with the given graph state (`goto_bed(crop=None)` = an unplanted one) on the object loop: clicks the
    bed as soon as it is visible. Returns the loop's Arrival (the bed's bubble is up); doesn't plant. NeedVision
    propagates (answer with `loop.answer(n, X, Y)` and call again)."""
    return loop.goto(Q(kind='GardenBed').where(**state), core.WF)


def crop_name(card_text):
    """The crop a bed card names: its first line ("Green Bean / The unripe fruit … / This plant has wilted")."""
    return card_text.split(' / ', 1)[0].strip()


@action
def replant_all(seed=None, click=None):
    """Every wilted bed: remove, replant (seed=None: the same crop, read from the Remove card), water. Clicks every
    water-drop bubble on screen; with none, raises NEED_VISION click: answer by calling again with click='<grid cell>'
    (or click='none' when no wilted bed is left)."""
    from . import laws
    return laws.run('replant', click=click, seed=seed)


@action
def water_all(click=None):
    """Water every growing, dry bed (water-drop bubbles); NEED_VISION click as replant_all."""
    from . import laws
    return laws.run('water', click=click)


@action
def harvest_all(click=None):
    """Pick every ripe bed (pickup bubbles); NEED_VISION click as replant_all."""
    from . import laws
    return laws.run('harvest', click=click)
