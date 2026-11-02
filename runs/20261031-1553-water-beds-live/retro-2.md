# Retro 2: an active bubble watered a different due bed

## Outcome
The post-fix retry successfully watered one dry bed at `(-1.66, -29.09)`, advancing R1 from 5/12 to 6/12. The exact
bed API had requested `(-1.66, -25.34)`, so its position-specific proof rejected the action and stopped. The game was
paused and the successful bed was not retried.

## Cause
Several valid bed bubbles were active simultaneously. The older `water(b)` path uses approximate screen geometry to
select one exact identity; the click reached a different dry bed. That is acceptable for the daily routine, but not
for the exact-bed function's contract.

## Earlier fixes
- L97 held: the walk no longer crashed on scalar bed state.
- Exact proof held: `water(b)` did not falsely attribute the other bed to its requested target.
- L93's multi-active principle existed in the object loop, but R1 still used the older exact-target API.

## Fix
- Keep `water(b)` strict for callers that require one identity.
- Add `water_next()` for R1: use any active water bubble, identify the actual due bed by the exact log position, and
  filter all positions already watered today so a stale save cannot cause repeats.
- Update R1 to use small `water_next()` batches and record the live Rusty-can capacity of five beds per fill.
