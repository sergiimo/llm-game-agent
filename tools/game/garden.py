"""The garden (L77): `replant_all` / `water_all` / `harvest_all` run the interaction laws (game/laws.py,
docs/mechanics/interaction-laws.md, L124); reaching a bed is `laws.reach` (any bed whose bubble fits). Log (D148): `> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written
when the planting panel closes (also when cancelled), `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered. Planting panel = "Inventory / Seeds" picker: cards show icon + count only (Green Bean 26,
Carrot 10, Tulip 22 on D148); clicking one opens its detail card (title + Select)."""

import math

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


COMPASS = ((0, 1, 'North'), (0, -1, 'South'), (1, 0, 'East'), (-1, 0, 'West'))


def discover():
    """Gardens from the save -> graph (L137): the save's beds clustered by position; the cluster the graph already
    knows (or the northernmost, by the house) is `Garden`; every other cluster becomes a NEW region node named by its
    direction from `Garden` (e.g. `GardenSouth`) with its bed group and one member per bed (row/col, position, state,
    neighbour edges). Frame-free: the save is ground truth. Returns {region: [new node ids]} and saves the graph."""
    from objects import graph as OG
    from . import learn as L
    own = L.MEMORY['graph'] is None
    if own:
        L.open_memory()
    g = L.MEMORY['graph']
    try:
        clusters = OG.cluster_beds(core.WF.farm_status()['crops'])
        if not clusters or g is None:
            return {}
        home = OG.pos_of(g, 'Garden')
        if home:
            base = min(clusters, key=lambda c: (c['centre'][0] - home[0]) ** 2 + (c['centre'][1] - home[1]) ** 2)
        else:
            base = clusters[0]   # northernmost: the garden by the house
        out = {'Garden': OG.ensure_region(g, 'Garden', base['beds'])}
        for c in clusters:
            if c is base:
                continue
            dx, dz = c['centre'][0] - base['centre'][0], c['centre'][1] - base['centre'][1]
            stem = 'Garden' + max(COMPASS, key=lambda t: t[0] * dx + t[1] * dz)[2]
            name, k = stem, 2
            while name in g.nodes and OG.pos_of(g, name) and math.dist(OG.pos_of(g, name), c['centre']) > OG.CLUSTER_GAP:
                name, k = f'{stem}{k}', k + 1   # another garden in the same direction
            out[name] = OG.ensure_region(g, name, c['beds'])
        try:
            core.WF.run_log('graph', what='discover', regions={k: len(v) for k, v in out.items()})
        except Exception:   # noqa: BLE001
            pass
        return out
    finally:
        if own:
            L.close_memory()


@action
def plant_all(seed='Tulip', region='GardenSouth', click=None):
    """Plant `seed` in every empty bed of the garden `region` (found by `discover()` from the save): the graph's
    direction from the garden she is at, then the bubble loop on the empty-bed (seedling) bubbles -> the seed's card ->
    Select. NEED_VISION click as replant_all. Stops when the region has no empty bed left (save minus today's log)."""
    from . import laws
    discover()
    return laws.run('plant', click=click, seed=seed, task=laws.plant_task(region))
