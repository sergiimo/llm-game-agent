"""The garden (L77): beds from the save, and what to do with them. Every function walks to its bed, handles its own
confirmations, and proves the result with the game log line at that bed's position.
Log (D148): `> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written
when the planting panel closes (also when cancelled), `[STATS] totalPlanted.<Seed>` = planted; `> water … at
(x, y, z)` = watered. Planting panel = "Inventory / Seeds" picker: cards show icon + count only (Green Bean 26,
Carrot 10, Tulip 22 on D148); clicking one opens its detail card (title + Select)."""
from dataclasses import dataclass
import os
import re

from objects import loop
from objects.query import Q

from . import affordances, core, ui, well
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


_WATER_AT = re.compile(r'> water\b[^\n]*?target=GardenBed[^\n]*? at \((-?[\d.]+), -?[\d.]+, (-?[\d.]+)\)')


def beds_due():
    """Dry beds not already proved watered in today's log. This stays current between autosaves and lets a routine
    consume whichever one of several simultaneously active bed bubbles the game actually used."""
    try:
        lines = core.WF.today_log()[0]
    except AttributeError:  # small fakes expose only log_since
        lines = core.log_text(0).splitlines()
    done = [(float(m.group(1)), float(m.group(2))) for line in lines if (m := _WATER_AT.search(line))]
    return [b for b in beds(dry=True)
            if not any(abs(b.x - x) < 0.5 and abs(b.z - z) < 0.5 for x, z in done)]


def _click_due_water_bubble(due):
    """Click a visible water bubble only when its projected owner is one of the exact beds still due today.
    This uses the user's arrival rule without trusting an unowned/stale water-looking bubble."""
    for a in affordances.scan():
        if a.kind not in affordances.KINDS['water'] or a.entity is None:
            continue
        if not any(abs(b.x - a.entity.x) < 0.5 and abs(b.z - a.entity.z) < 0.5 for b in due):
            continue
        core.WF.run_action(f'click:{a.pt[0]}:{a.pt[1]}')
        core.WF.wait_settle()
        return True
    return False


def bed(n):
    return next(b for b in beds() if b.id == n)


def _bed(b):
    return bed(b) if isinstance(b, int) else b


@action
def goto_bed(**state):
    """Walk to a bed with the given graph state (`goto_bed(crop=None)` = an unplanted one) on the object loop: clicks the
    bed as soon as it is visible. Returns the loop's Arrival (the bed's bubble is up); doesn't plant. NeedVision
    propagates (answer with `loop.answer(n, X, Y)` and call again)."""
    return loop.goto(Q(kind='GardenBed').where(**state), core.WF)


@action
def unplant(b):
    """Dig up a wilted plant: bubble → wilted card → confirm "Remove" (all inside). Refuses a healthy plant."""
    b = _bed(b)
    if not b.wilted:
        raise Failed(f'{b}: not wilted; unplant only digs up wilted plants')
    mark = core.WF.log_mark()
    # Never press the currently highlighted bubble blindly: at the north bed rows it can still be a hive behind Tara.
    # Prefer an already-visible exact owned bubble before considering navigation; highlight is irrelevant to agents.
    if not affordances.use('unplant', b):
        goto(b)
    if not core.seen(r'> unplant\b', mark, wait=0, at=(b.x, b.z)) and not affordances.use('unplant', b):
        from . import walk
        if not walk.click_object(b):
            if affordances.scan():
                raise Failed(f'unplant {b}: other bubbles are visible but none belongs to this wilted bed')
            ui.press_bubble()
    if not core.seen(r'> unplant\b', mark, wait=1.5, at=(b.x, b.z)):
        raise Failed(f'unplant {b}: target click did not open this bed\'s wilted card')
    return _finish_unplant(b, mark)


def _finish_unplant(b, mark):
    """Finish an already-open wilted card and require the exact bed removal proof."""
    for _ in range(2):  # card → confirmation, then exact Remove button
        if ui.shows('remove', wait=0.5) and not core.seen(r'> unplant_impl', mark, wait=0):
            ui.press('Remove')
        else:
            ui.press_bubble()
        if core.seen(r'> unplant_impl', mark, wait=1.5, at=(b.x, b.z)):
            return b
    prove(f'unplant {b}', r'> unplant_impl', mark, at=(b.x, b.z), wait=0)


@action
def plant(b, seed='Tulip'):
    """Plant `seed` in an empty bed: bubble → planting panel → the seed's card → Select. Doesn't water (M3: one job
    per skill; `water(b)` is its own call)."""
    b = _bed(b)
    mark = core.WF.log_mark()
    affordances.press('plant', b)
    if not ui.shows('Seeds', wait=2.0):  # `> plant` is logged only when the panel closes, so check the screen
        other = core.seen(r'> unplant ', mark, wait=0)  # the 2 s above let the log catch up
        if other and not core.seen(r'> unplant ', mark, wait=0, at=(b.x, b.z)):
            ui.close()  # another bed's Remove card: close it, never confirm
            raise Failed(f'plant {b}: the click opened another bed ({other.strip()}); closed it, nothing removed')
        raise Failed(f'plant {b}: the planting panel did not open (screen: {core.screen()})')
    ui.pick_card(seed)
    ui.press('Select')
    prove(f'plant {seed} in {b}', rf'totalPlanted\.{seed}', mark)
    return b


@action
def water(b):
    """Water a bed. Only when the game says the can is empty (`> out_of_water` at this bed) does it fill the can at the
    well and come back (M3: no hidden trips without cause)."""
    b = _bed(b)
    mark = core.WF.log_mark()
    affordances.press('water', b)  # its bubble if showing (no walk), else walk there first
    if core.seen(r'> water ', mark, at=(b.x, b.z)):
        return b
    if not core.seen(r'> out_of_water ', mark, wait=0, at=(b.x, b.z)):
        raise Failed(f'water {b}: no `> water` and no `> out_of_water` at this bed (screen: {core.screen()})')
    ui.close()
    well.fill_can()
    mark = core.WF.log_mark()
    affordances.press('water', b)
    prove(f'water {b} (after filling the can)', r'> water ', mark, at=(b.x, b.z))
    return b


@action
def water_next():
    """Water one still-due bed for the daily routine. Several bubbles can be active and their visual kind/owner can
    be noisy, so walk to a due bed and click that bed object directly; the exact action-log position identifies and
    consumes whichever due bed the game actually used. Refills only after an exact `out_of_water` proof."""
    from . import walk
    for _ in range(2):
        due = beds_due()
        if not due:
            raise Failed('water next bed: no dry unwatered bed remains today')
        target = due[0]
        if core.WF.state()['mode'] != 'gameplay':
            ui.close()  # a prior growing-plant info card may be under the pause overlay
        mark = core.WF.log_mark()
        if not _click_due_water_bubble(due):
            goto(target)
        line = core.seen(r'> \w+\b[^\n]*target=GardenBed', mark, wait=0)
        if not line:
            if not walk.click_object(target):
                raise Failed(f'water next dry bed: due bed {target} is not directly clickable after arrival')
            line = prove('water next dry bed', r'> \w+\b[^\n]*target=GardenBed', mark)
        if '> water ' in line:
            m = _WATER_AT.search(line)
            actual = next((b for b in due if m and abs(b.x - float(m.group(1))) < 0.5
                           and abs(b.z - float(m.group(2))) < 0.5), None)
            if actual is None:
                raise Failed(f'water next dry bed: action hit a bed outside the due set: {line}')
            return actual
        if '> out_of_water ' in line:
            ui.close()
            well.fill_can()
            continue
        raise Failed(f'water next dry bed: direct bed click did not offer water: {line}')
    raise Failed('water next dry bed: still out of water after filling the can')


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
    """A wilted bed → dig up → plant `seed` (water is its own call)."""
    b = _bed(b)
    unplant(b)
    plant(b, seed)
    return b


def _bed_at(line):
    """The bed a log line names (`… at (x, y, z)`), by the save's bed positions; None if none within 0.5."""
    p = core.log_pos(line)
    return next((b for b in beds() if abs(b.x - p[0]) < 0.5 and abs(b.z - p[1]) < 0.5), None) if p else None


def crop_name(card_text):
    """The crop a bed card names: its first line ("Green Bean / The unripe fruit … / This plant has wilted")."""
    return card_text.split(' / ', 1)[0].strip()


def _scan_text(seen):
    return ', '.join(f'{a}{" +drop" if a.drop else ""}' for a in seen) or 'no bubbles'


@action
def plant_visible(seed, at=None):
    """Plant `seed` through the one visible `plant` bubble (an empty bed): no walking, no geometry. The planting panel
    shows seed cards by icon (tools/items, ui.pick_card). `> plant … at (x, z)` is logged when the panel closes, so
    the bed is proved after Select; at=(x, z) must be that bed. Several plant bubbles → stop (can't tell which)."""
    seen = affordances.scan()
    plants = [a for a in seen if a.kind == 'plant']
    if len(plants) != 1:
        raise Failed(f'plant {seed}: {len(plants)} plant bubbles visible, need exactly one: {_scan_text(seen)}; '
                     + core.ask_vision(f'which bubble is the plant bubble of the empty bed for {seed}?'))
    mark = affordances.click(plants[0])
    if not ui.shows('Seeds', wait=2.0):
        other = core.seen(r'> \w+ ', mark, wait=0)
        ask = core.ask_vision('what opened instead of the planting panel?')  # before close: the frame shows it
        ui.close()
        raise Failed(f'plant {seed}: the planting panel did not open ({other or core.screen()}); closed; {ask}')
    try:
        ui.pick_card(seed)
    except Failed as e:  # pick_card's message carries the NEED_VISION frame (taken before closing)
        ui.close()  # its detail card …
        ui.close()  # … then the panel
        raise Failed(f'plant {seed}: no {seed} card picked in the planting panel: {e}')
    ui.press('Select')
    # any totalPlanted stat: pick_card proved the card's title, and some seeds' stat keys are unresolved hashes
    # (D183: Green Bean = `totalPlanted.#-145752244`); `> plant … at` below proves the bed
    prove(f'plant {seed}', r'totalPlanted\.', mark)
    line = core.seen(r'> plant ', mark, wait=1.5)
    if at and not core.seen(r'> plant ', mark, wait=0, at=at):
        raise Failed(f'plant {seed}: planted, but at {line and line.strip()} not at {at}; '
                     + core.ask_vision(f'which bed got the {seed}?'))
    return _bed_at(line)


@action
def water_visible(at):
    """Water the bed at (x, z) through a visible drop bubble: click drop bubbles until `> water … at` is this bed
    (watering another dry bed on the way is fine). Empty can (`> out_of_water`) → fill at the well, then rescan."""
    tried, filled = set(), False
    for _ in range(8):
        drops = [a for a in affordances.scan() if a.drop and a.pt not in tried]
        if not drops:
            break
        tried.add(drops[0].pt)
        mark = affordances.click(drops[0])
        if core.seen(r'> water ', mark, wait=1.5, at=at):
            return at
        if core.seen(r'> out_of_water ', mark, wait=0) and not filled:
            ui.close()
            well.fill_can()
            tried, filled = set(), True
        elif not core.seen(r'> water ', mark, wait=0):
            ui.close()  # a card, not a watering: close it, try the next drop
    raise Failed(f'water {at}: no visible drop bubble watered it (tried {len(tried)})')


@action
def replant_visible(seed=None):
    """One visible bed fixed, fast (user, D183): spot bubbles (drop sub-icon first: needs water OR wilted, any crop
    icon) → click → the game logs `> unplant` (wilted) → remove → plant the same crop (seed=None: the crop the card
    names) → water. A click that just watered a dry bed is fine: keep looking. Bed identity = the game log line, never
    geometry. Nothing to click → Failed with NEED_VISION (the agent navigates by the graph or looks)."""
    tried, watered, seen = set(), [], []
    for _ in range(len(beds())):
        seen = affordances.scan()
        offered = [a for a in seen if a.pt not in tried and (a.drop or a.kind in ('unplant', 'unknown'))]
        if not offered:
            break
        offered.sort(key=lambda a: (not a.drop, a.kind != 'unplant'))
        a = offered[0]
        tried.add(a.pt)
        mark = affordances.click(a)
        line = core.seen(r'> (unplant|water|out_of_water) [^\n]*target=GardenBed', mark, wait=1.5)
        b = _bed_at(line)
        text = ' / '.join(ui.texts())
        core.WF.run_log('bed_probe', node=b.id if b else None, point=list(a.pt), bubble=a.kind, drop=a.drop,
                        ocr=text[:240], action=line or None)
        if line and '> unplant ' in line:  # the game opened the Remove card: this bed has wilted
            if not b:
                raise Failed(f'unplant at no known bed: {line.strip()}; ocr={text[:120]!r}')
            _finish_unplant(b, mark)
            plant_visible(seed or crop_name(text), at=(b.x, b.z))
            water_visible((b.x, b.z))
            return b
        if line and '> water ' in line:
            watered.append(b.id if b else line)
        elif line and '> out_of_water ' in line:
            ui.close()
            well.fill_can()
            tried = set()
        else:
            ui.close()
    raise Failed(f'no visible wilted bed (tried {len(tried)}, watered {watered}): {_scan_text(seen)}; '
                 + core.ask_vision('where are the wilted beds? (none visible → navigate to the garden by the graph)'))


def _chain(task, seed=None, graph=None, gpath=None, detect_fn=None):
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
        return chain.run(task, 'GardenBed@Garden', graph, seed=seed, detect_fn=detect_fn)
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
