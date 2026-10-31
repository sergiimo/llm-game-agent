# Retro 1: bench A step 2 escalated (D149 11:00–12:50); baseline, no tool changes during it

## Numbers (./wf bench report, ./wf eval)
21 calls, 110 game min, 104 s thinking, **25 save readings**, 4 STUCK (1 real), 1 escalation; 3 of 5 beds replanted,
none watered after the can ran dry. Eval: belief 1/18 (6 %), skills 0/6, click 35/43 (81 %), stuck 1/4, ask 2/2.

## Episodes
| Eval id | What | Real? |
|---|---|---|
| …-19 | walking clicks landed on the open pause/Settings menu → **audio sliders moved to ~0 (user setting changed)** | miss (a menu, not geometry) |
| …-31 | already within reach of bed 4, `goto` reported no progress | miss (false alarm) |
| …-41 | `plant` → `water` → `fill_can` → `goto well` from among the beds while a tooltip overlay showed | miss |
| …-60 | `goto well` led onto the hive row (well behind it); 2 vision answers got her round the west end | hit |

## Earlier fixes: held?
- L80/L82 stuck detection: fires fast now, but 3 of 4 alarms were false: progress is measured without "already at the
  goal" and while an overlay is open.
- L81 click on screen: clicks go through overlays (pause, settings, tooltips) — the worst failure: it changed a setting.
- L77 skills: `plant()` hides a well trip inside (water → fill_can), so one call walks across the farm.
- Belief: dead reckoning is within 1 unit only 6 % of the time — the reason readings (25) are everywhere.

## Fixes (go into the refactor, spec §3–5; one safety fix now)
1. **Now (safety, allowed during the baseline): never click to move while a menu/overlay is open** — `go_to` refuses
   unless the screen mode is gameplay (pause, settings, cards, tooltips → close first or stop). Ledgered as a ruling.
2. Stuck rule: "not at the goal" must be checked (within reach = done, not stuck) and alarms suppressed while an
   overlay is open. → M3 (belief + walk).
3. Skills: no hidden long trips: `plant` doesn't water; watering is its own call that plans the can refill. → M3.
4. Belief accuracy 6 % → the M2 filter must be measured against this number.
