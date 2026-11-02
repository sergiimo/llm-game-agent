"""The garden (L77): position-free (spec 2026-11-02): `replant_all` / `water_all` / `harvest_all` run the graph chain
(objects/chain.py); `goto_bed` walks to a bed by the object loop. Log (D148): `> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written
when the planting panel closes (also when cancelled), `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered. Planting panel = "Inventory / Seeds" picker: cards show icon + count only (Green Bean 26,
Carrot 10, Tulip 22 on D148); clicking one opens its detail card (title + Select)."""
import os
import re

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


def _chain(task, seed=None, graph=None, gpath=None):
    """Run a chain task (objects/chain.py, spec 2026-11-02) on the home garden: load the object graph, expire yesterday's
    watered hints, run, ALWAYS save the graph (a NeedVision answer reads it from disk). Returns the run summary."""
    from objects import chain, graph as OG
    gpath = gpath or os.path.join(OG.DEFAULT_DIR, 'Farm.json')
    if graph is None:
        graph = OG.Graph()
        graph.load(gpath)
    m = re.match(r'D(\d+)', core.WF.game_stamp() or '') if hasattr(core.WF, 'game_stamp') else None
    if m:
        graph.new_day(int(m.group(1)))
    try:
        return chain.run(task, 'GardenBed@Garden', graph, seed=seed)
    finally:
        graph.save(gpath)


@action
def replant_all(seed=None, **kw):
    """Every wilted bed of the home garden: remove, replant (seed=None: the same crop), water. Chain strategy: no
    positions; an unexpected frame raises NeedVision (answer with ./wf anchor, call again)."""
    return _chain('replant', seed, **kw)


@action
def water_all(**kw):
    """Water every home-garden bed that is growing and not watered today (chain strategy)."""
    return _chain('water', **kw)


@action
def harvest_all(**kw):
    """Pick every ripe home-garden bed (chain strategy)."""
    return _chain('harvest', **kw)
