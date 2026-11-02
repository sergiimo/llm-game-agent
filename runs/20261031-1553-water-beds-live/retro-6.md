# Retro 6: the first taught gap point was not enough

## Outcome
The due-owner filter correctly rejected the visible `beehive_progress` bubbles, then fallback navigation again raised
`NeedVision`. No action occurred. R1 remains 10/12, the can is full, and the game is paused.

## Cause
The first teaching click moved Tara around the west end but did not give the route model enough coverage to reach bed
6. The latest annotated frame still shows the due goal southeast, with Tara among the west garden plots.

## Earlier fixes
- S33's owner filter held and prevented another hive interaction.
- S32's first teaching point produced real movement, but one point did not solve the whole return leg.

## Fix
Teach a second bounded point at `1200:760`, halfway along the yellow goal direction and below the hive row. Pause and
inspect whether it moved or interacted before issuing another watering call.
