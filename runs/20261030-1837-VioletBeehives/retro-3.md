# Retro 3: step 4 escalated again (same strip behind the hives), D149 10:10 am

## What happened (from log.jsonl, not impressions)
`replant(1)` → `goto(bed 1)`: 60 clicks in 159 s, 52 refused; ~28 `> beehive_progress` log lines = the clicks landed
on hive sprites (bed 1 is behind the hive row from the camera's view). 4 readings only, so STUCK came at 159 s.

## Earlier fixes: held?
- L81 click the on-screen target: ❌ the target is occluded by hives; clicks open hive cards.
- L80 stuck inside calls: ⚠️ fired, but late: refused clicks didn't count as moves.
- L74 vision step: ❌ never asked: game functions raised STUCK, and my plan said "escalate at once on STUCK".
- Ledger rule "a repeated cause gets a tool fix": ✅ applied now (S11 → S12 same spot).

## Causes
1. Occlusion: from north of the hive row, the screen point of anything south of it is a hive.
2. The stuck rule ignored refused clicks.
3. The plan/tool skipped the designed escape hatch (vision with goal + layers).

## Fixes (L82)
- A refused click is a move without progress (`note_click` → `track_point`): STUCK in ~3 clicks.
- `move.goto` on STUCK asks `NEED_VISION step` (goal, image with roads/trail/walls/route) and fails with that
  question; the agent answers `./wf teach step X:Y` and re-runs; escalate after 2 answers that didn't help.
- Plan rev 6: step 4 "If stuck" = answer the vision question first.
