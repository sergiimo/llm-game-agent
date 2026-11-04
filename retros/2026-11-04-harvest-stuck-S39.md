# Stuck retro S39: engine harvest, D188 12:20

> **Summary:** the live harvest wandered around the beehives and stopped "done" with 7 ready beds left. Read the
> ledger first: S37/S38 were also target identity by readings. This time the fix is structural (position, vision).

## What happened
- Start: Tara outside the north garden's west fence, no positioned event since her last walk.
- Strategy A needs an exact position; there was none, so the old nav search ran.
- The one bed bubble in view read `water*` with no "!" (a ready bed, by the save). It did not fit `pick`; the search
  explored free ground around the hives (5 arrival misses, 3 still clicks = STUCK).
- `_only_maybes`: all 7 targets had an unknown crop (`!flowers` assumed) and no fitting bubble showed -> "done".
- Every garden click read screen `overlay` with no text, so nav logged each walk as a surprise interaction.
- The supervisor stopped the agent and paused the game.

## Did earlier fixes hold?
- S37/S38 (vision for target identity): held in principle. The engine just didn't ask: it trusted readings.

## Fixes (L159, tests in tools/test_engine.py VisitBeds)
1. No exact position + bed bubbles in view + none fits the row -> vision's start question (the bubble of the
   nearest ready, non-flower bed). Its click: a Collect card is finished by the row, and the pick event = exact position.
2. "Only maybes left" counts as done only with an exact position and the targets' points on screen.
3. Bed to bed: the target's point on screen but no bubble there -> a short walk to the ground below it (dead reckoned
   from that click, `where.walked(to=)`), only when no fitting bubble is in view; checked by the bubble appearing.
4. A textless overlay is gameplay (`act.on_card`): no false surprise, no close.
