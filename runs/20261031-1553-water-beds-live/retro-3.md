# Retro 3: stale water classification on an already-watered bed

## Outcome
The revised routine clicked a bubble at the bed already watered at 11:17. The exact line was `> plant_growing ...`
rather than `water` or `out_of_water`, so no progress was counted. A Tulip info card opened; the game was paused and
R1 remained 6/12.

## Cause
`water_next()` still trusted the visual bubble kind before using its exact log proof. The just-watered bed retained a
growing-plant bubble that the detector labelled as water (or attached to the wrong owner).

## Earlier fixes
- S30's log-based due set held: no false watering or duplicate was counted.
- Its action selection did not hold because it still trusted the noisy bubble classifier—the repeated multi-active
  cause now requires removing that dependency, not another threshold tweak.

## Fix
- Select a due bed from save plus today's exact log positions, walk to it, and click the projected bed object itself.
- Accept the actual bed only from `water`/`out_of_water` log evidence at a due position.
- Close one leftover passive card before the direct attempt; retain the small batches and immediate pauses.
