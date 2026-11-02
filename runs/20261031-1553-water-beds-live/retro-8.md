# Retro 8: final helper reused stale position after a goal-dot success

## Outcome
The step-2 goal dot directly watered `(3.34,-29.09)`, raising R1 to 11/12. The final `water_next()` then reopened
that just-watered bed twice and asked vision; no final water occurred. The game is paused and the can remains full.

## Cause
The helper's world walk did not refresh from the direct goal-dot action. Its routing evidence still referenced the
west-side position although the live reading placed Tara at `(3.3,-27.1)`, close to the remaining bed.

## Earlier fixes
- S35's exact goal-dot method held and completed step 2.
- Today's due-log filter held: the repeated info interactions were not counted as watering.
- Generic world-state refresh did not hold across the manual direct-object action.

## Fix
There is one known remaining coordinate, `(0.84,-29.09)`. Use the new annotation's yellow goal dot `1228:856` once,
pause immediately, and require that exact water coordinate plus `R1 DONE`; do not invoke generic routing first.
