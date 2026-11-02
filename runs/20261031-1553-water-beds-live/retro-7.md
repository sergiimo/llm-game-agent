# Retro 7: interpolated route point hit an already-watered bed

## Outcome
The reviewed `1200:760` click did not move Tara. It logged `plant_growing` at the already-watered bed
`(0.84,-25.34)`, and the L75 detector required escalation. No water occurred; R1 remains 10/12 and the game is paused.

## Cause
The point was halfway along the annotated goal arrow but lay within a garden-bed hitbox. In a dense object grid,
interpolating screen points does not guarantee walkable ground.

## Earlier fixes
- L75 held and stopped after one non-moving interaction.
- Exact log attribution held and identified the already-watered bed.
- S34's halfway-point assumption failed.

## Fix
Do not interpolate again. Use the annotation's yellow goal dot itself at `1375:812` as a deliberate click that may
either move toward bed 6 or interact with it. Pause immediately and decide only from the exact log/routine delta.
