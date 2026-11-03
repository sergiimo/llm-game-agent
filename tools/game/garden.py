"""The garden (L77): `replant_all` / `water_all` / `harvest_all` run the interaction laws (game/laws.py,
docs/mechanics/interaction-laws.md, L124); reaching a bed is `laws.reach` (any bed whose bubble fits). Log (D148): `> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written
when the planting panel closes (also when cancelled), `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered. Planting panel = "Inventory / Seeds" picker: cards show icon + count only (Green Bean 26,
Carrot 10, Tulip 22 on D148); clicking one opens its detail card (title + Select)."""

from . import core
from .core import action


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
def harvest_all(click=None, ready=False):
    """Pick every ripe bed (pickup bubbles); ready=True also collects "!" (ready) bubbles - "!" is not an order to
    collect (flowers serve the bees, user D185). NEED_VISION click as replant_all."""
    from . import laws
    return laws.run('harvest', click=click, task=laws.harvest_task(ready))
