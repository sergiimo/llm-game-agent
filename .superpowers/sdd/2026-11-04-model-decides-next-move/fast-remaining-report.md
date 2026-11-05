# Fast-flow remaining report

## Offline implementation and verification

- Task 4: `finish_card` uses fresh target crop evidence for on-way Collect cards and asks with `collect_open` when unknown. `runwatch` maps engine stops beginning `RED FLAG` to `STOP`.
- Task 5: explicit object clicks share `_click_bed`, route through Task 3 attribution and Collect handling, and preserve bubble-only `_visit`. Decision briefs persist position provenance; graph crop fallback requires fresh event/walk provenance. Explicit-click bubble icon evidence is limited to 30px, and crop answers are not prewritten to the intended node.
- Commit: `c808e16 Handle explicit bed clicks and on-way Collect cards`.
- Focused: 67 passed (`CardFromAWalk`, `ClickTheBed`, `VisitBeds`, `ModelDecides`, `CollectOnTheWay`, `test_runwatch`).
- Full discovery: 549 passed, 5 expected failures. Footer in `full-suite-final.log`.

## Task 6 live gate

Run directory: `runs/20261105-1754-model-decides-next-move-harvest/`. The plan was written and reviewed (3 steps, review OK), and Step 1 was started. The unfiltered watcher was attempted. The first live read (`./wf log`) hung. `tail -3 .shots/actions.log` showed only focus-mode entries, confirming no game input/action was logged. Process inspection found a stuck `wfc log` client and wedged daemon/server channel after exact stale-client/duplicate-server cleanup; `./wf stop` did not clear it. The live gate is blocked before observation. There is no live trace, time table, retro, or pass result.

Follow-up: repair the recurring `.shots/wf.sock` / daemon request stall, then resume Step 1 with the reviewed plan and watcher. No claim is made that Task 6 passed.
