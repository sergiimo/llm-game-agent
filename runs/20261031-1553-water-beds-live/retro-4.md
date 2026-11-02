# Retro 4: no computed return from the Well after refill

## Outcome
Step 2 watered two beds at `(3.34,-25.34)` and `(5.84,-25.34)`, then proved `out_of_water` at bed 6 and refilled
the can at 12:18:36. The return stopped with `NeedVision` before another action. R1 is 10/12, the can is full, and
the game is paused beside the Well.

## Cause
The direct south line crosses the hive row. The route model had no clickable first waypoint out of the Well nook,
although the saved annotated frame shows open ground around the west/left end of the hive row.

## Earlier fixes
- Small batches and exact action proof held: both successful waters are preserved and no third was claimed.
- Refill-on-proof held and left the can full.
- S21–S26 target-click fixes did not supply a return waypoint around this side of the hive wall.

## Fix
Answer the saved vision question with game point `660:810`, on open ground at the west end of the hives, then retry
one `water_next()`. `wf teach step` records the resulting movement as route evidence for future returns.
