"""The garden (L77): beds from the save, and what to do with them. Every function walks to its bed, handles its own
confirmations, and proves the result with the game log line at that bed's position.
Log (D148): `> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written
when the planting panel closes (also when cancelled), `[STATS] totalPlanted.<Seed>` = planted; `> water … at
(x, y, z)` = watered. Planting panel = "Inventory / Seeds" picker: cards show icon + count only (Green Bean 26,
Carrot 10, Tulip 22 on D148); clicking one opens its detail card (title + Select)."""
from dataclasses import dataclass

from . import core, ui, well
from .core import Failed, action, prove
from .move import goto


@dataclass
class Bed:
    id: int
    x: float
    z: float
    state: str          # empty / seed / growing / producing / produced (save plantState; empty = '##0')
    wilted: bool
    watered: bool
    scene: str = 'Farm'   # the garden's area (graph walks to it from anywhere, L79)

    def __str__(self):
        flags = ' wilted' * self.wilted + ' watered' * self.watered
        return f'bed {self.id} ({self.x:.1f}, {self.z:.1f}) {self.state}{flags}'


def beds(wilted=None, dry=None, ripe=None, empty=None):
    """Garden beds from the last autosave, numbered by row (north first) then west → east; filters by state."""
    out = []
    for c in core.WF.farm_status()['crops']:
        st = (c.get('plantState') or '').strip('#')
        st = 'empty' if st in ('', '0') else st
        out.append(Bed(0, float(c['x']), float(c['z']), st, c.get('isWilted') == 'true', c.get('isWatered') == 'true'))
    out.sort(key=lambda b: (-round(b.z, 1), b.x))
    for i, b in enumerate(out, 1):
        b.id = i
    keep = [b for b in out
            if (wilted is None or b.wilted == wilted)
            and (dry is None or (not b.watered and b.state not in ('produced', 'empty')) == dry)
            and (ripe is None or (b.state == 'produced') == ripe)
            and (empty is None or (b.state == 'empty') == empty)]
    return keep


def bed(n):
    return next(b for b in beds() if b.id == n)


def _bed(b):
    return bed(b) if isinstance(b, int) else b


@action
def unplant(b):
    """Dig up a wilted plant: bubble → wilted card → confirm "Remove" (all inside). Refuses a healthy plant."""
    b = _bed(b)
    if not b.wilted:
        raise Failed(f'{b}: not wilted; unplant only digs up wilted plants')
    goto(b)
    mark = core.WF.log_mark()
    for _ in range(3):  # Space opens the card, then the "Are you sure you want to remove …?" prompt, then removes
        if ui.shows('remove', wait=0.5) and not core.seen(r'> unplant_impl', mark, wait=0):
            ui.press('Remove')
        else:
            ui.press_bubble()
        if core.seen(r'> unplant_impl', mark, wait=1.5, at=(b.x, b.z)):
            return b
    prove(f'unplant {b}', r'> unplant_impl', mark, at=(b.x, b.z), wait=0)


@action
def plant(b, seed='Tulip'):
    """Plant `seed` in an empty bed: bubble → planting panel → the seed's card → Select; then water it."""
    b = _bed(b)
    goto(b)
    mark = core.WF.log_mark()
    ui.press_bubble()
    if not ui.shows('Seeds', wait=2.0):  # `> plant` is logged only when the panel closes, so check the screen
        raise Failed(f'plant {b}: the planting panel did not open (screen: {core.screen()})')
    ui.pick_card(seed)
    ui.press('Select')
    prove(f'plant {seed} in {b}', rf'totalPlanted\.{seed}', mark)
    water(b)
    return b


@action
def water(b):
    """Water a bed; refills the can at the well when the pour doesn't happen, then tries once more."""
    b = _bed(b)
    for attempt in range(2):
        goto(b)
        mark = core.WF.log_mark()
        ui.press_bubble()
        if core.seen(r'> water ', mark, at=(b.x, b.z)):
            return b
        if attempt == 0:
            ui.close()
            well.fill_can()
    prove(f'water {b}', r'> water ', mark, at=(b.x, b.z), wait=0)


@action
def harvest(b):
    """Pick a ripe bed's crop."""
    b = _bed(b)
    goto(b)
    mark = core.WF.log_mark()
    ui.press_bubble()
    prove(f'harvest {b}', r'grab_item|> harvest', mark)
    return b


@action
def replant(b, seed='Tulip'):
    """A wilted bed → dig up → plant `seed` → water."""
    b = _bed(b)
    unplant(b)
    plant(b, seed)
    return b
