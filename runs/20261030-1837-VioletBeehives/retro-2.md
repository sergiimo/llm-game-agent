# Retro 2: step 4 escalated (stuck behind the hive row), D149 9:22 am

## What happened
`./wf py "replant(1)"` from the strip behind the hives: the graph plan (side-step west, then south to bed 1) bumped a
hive at x -2.28 that the objects store didn't know yet; STUCK fired after 47 s (L80 worked: aborted the call, the
agent escalated at once, 2 calls this round).

## Earlier fixes: held?
- L80 stuck inside calls: ✅ (S10 missed it; now caught in 47 s).
- L79 graph + object walls: ⚠️ objects are learned only when the log names them, so a not-yet-seen hive is invisible;
  our straight segments need a complete obstacle map.
- Supervision (memory supervise-dont-drive): ✅ the first live use was a one-bed test step in the plan.

## Cause
We plan straight segments over a partial obstacle map. The game has a full one: clicking an object makes Tara
pathfind around everything to it (L49).

## Fix
`goto_point`: when the target is on screen (calibration projects it inside the click box), click the object itself
once and let the game pathfind; check arrival with a reading. Our graph only for targets off screen (L81).
