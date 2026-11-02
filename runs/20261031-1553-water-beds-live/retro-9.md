# Retro 9: annotation goal dot belonged to another bed

## Outcome
The step-3 click `1228:856` opened `plant_growing` at already-watered `(5.84,-29.09)`. No water occurred; R1 remains
11/12, the only due bed is `(0.84,-29.09)`, the can is full, and the game is paused.

## Cause
The yellow annotation dot showed a direction/route point, not the identity of the requested bed. Treating it as the
target was wrong in the dense grid.

## Earlier fixes
- Exact log attribution and immediate pause held.
- S36's direct-click approach avoided stale routing but chose the wrong visual identity.

## Fix
Use the exact miss as a same-frame anchor. With Tara saved at `(5.8,-27.1)`, the miss is the bed directly two units
south at screen `1228:856`. The current zoomed calibration maps the remaining bed's -5 world-x difference to -614
screen-x and almost no y difference, yielding `614:853`. Click once and require `(0.84,-29.09)` plus R1 DONE.
