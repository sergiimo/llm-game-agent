# Fast-flow remaining report

## Offline implementation and verification

- Task 4: `finish_card` uses fresh target crop evidence for on-way Collect cards and asks with `collect_open` when unknown. `runwatch` maps engine stops beginning `RED FLAG` to `STOP`.
- Task 5: explicit object clicks share `_click_bed`, route through Task 3 attribution and Collect handling, and preserve bubble-only `_visit`. Decision briefs persist position provenance; graph crop fallback requires fresh event/walk provenance. Explicit-click bubble icon evidence is limited to 30px, and crop answers are not prewritten to the intended node.
- Commit: `c808e16 Handle explicit bed clicks and on-way Collect cards`.
- Focused: 67 passed (`CardFromAWalk`, `ClickTheBed`, `VisitBeds`, `ModelDecides`, `CollectOnTheWay`, `test_runwatch`).
- Full discovery: 549 passed, 5 expected failures. Footer in `full-suite-final.log`.

## Task 6 live gate — failed

Run directory: `runs/20261105-1754-model-decides-next-move-harvest/`. The plan was reviewed, Step 1 and Step 2 were started, and the unfiltered watcher was run. After cache initialization, status/log/save worked. The game was resumed from D189 4:20 PM. Three explicit object clicks and four decide/vision questions produced zero picks. The first selected projected point moved Tara without bed proof; the next moved her closer but yielded only `beehive_progress*`; a repeat at the same target/point logged `moved=false`, no event/card, and unrelated beehive bubbles. Per the stop rule, no further target was clicked. The game was paused, Step 2 escalated, and the run ended `failed`.

Time table (attempt 4): 56 game minutes, 3 clicks, 4 vision questions, 0 picks. Watch output is in `runs/20261105-1754-model-decides-next-move-harvest/watch.md`; full trace and failure analysis are in `retro-1.md`. Retro and learning updates: `runs/20261105-1754-model-decides-next-move-harvest/retro-1.md`, `retros/stuck-ledger.md` S43, `docs/learnings.md` L178, `docs/progress.md`.

Cause: projected screen coordinates were based on stale save position and remained unsuitable after Tara moved. The repeat guard did not stop an unchanged target/point click. S39/S42 protections against wrong-row bubbles held; projection refresh and no-progress refusal need a code fix and offline regression before another live attempt.

## Follow-up stale-position guard and live result

- Commit `47faa4e Reask decisions when Tara position changed` adds pending position/source/target metadata and re-asks before an explicit click when current known position differs materially from the saved decision position. Regression verified zero click and a refreshed point. Focused suite: 68 passed. Full suite: 550 tests, OK (5 expected failures); full footer is in `full-suite-stale-guard.log`.
- Follow-up run: `runs/20261105-1819-model-decides-next-move-harvest-guarded/`. The plan was reviewed, unfiltered watcher ran, Step 2 was started then escalated, and the game was paused before ending the run failed. It recorded 13 `./wf` calls, 9:11 wall minutes, 1 accepted ground walk, 3 vision questions, 0 picks, 1 issue, and 1 escalation. One accepted walk to K10 visibly moved Tara but emitted no position event; later briefs continued to use the stale save position and projected ready beds over hives. The two visible right-hand beds were correctly identified as Tulips from full-scale evidence and settled without input. L10 was rejected as Tara's own spot. J10 was rejected because the prior answer had consumed the walk question; neither rejected answer generated game input. No more input was attempted.
- This is a live gate failure, not a pass or infrastructure block. The guard handles a changed position when fresh position evidence exists, but a no-event walk leaves stale `save` provenance. A rejected answer also needs to preserve or reissue the pending question. Added L179, S44, and the run retro. Do not resume the gate until both behaviors have offline regression coverage.

## L179/S44 offline closure

- RED: `ModelDecides.test_no_event_walk_invalidates_saved_object_projection_but_keeps_frame_evidence` observed `position_source='save'` instead of `unknown`; `ModelDecides.test_rejected_decision_answer_preserves_pending_for_a_corrected_walk` observed the pending decision was absent after the own-spot rejection.
- GREEN: added `where.invalidated_by_unpositioned_walk()` and made `brief._position` return unknown before consulting the save. This keeps object `screen` points None and `in_view` empty, while the same brief still carries live bubbles and heatmap detections. `_answer` restores the same pending decision when validation raises `core.Failed` before input.
- Focused: 70 tests passed, including VisitBeds, ModelDecides, CollectOnTheWay, ClickTheBed, CardFromAWalk, and runwatch (`focused-final.log`). Full suite: 552 tests, OK (5 expected failures), 315.162s (`full-suite-final.log`).
- These offline fixes close the gaps from L179/S44. The final supervised live run confirmed unknown projections after a no-event walk, then failed safely when a second frame-ground click did not move Tara; see the final gate evidence below.

## Final supervised live gate — failed safely

Run directory: `runs/20261105-1839-model-decides-next-move-harvest-final/`. Plan was reviewed; unfiltered watcher ran; Step 1 completed, Step 2 started then escalated, Step 3 started. Game started paused and was resumed for the attempt. At D189 6:50 PM the full-scale decision image showed unknown position and no object screen points. A shell-split walk answer was rejected before input; the pending decision remained available and a corrected quoted H10 answer moved Tara at 7:10 PM. The next brief still reported unknown position, confirming L179/S44's offline fix. O9 was selected from the exact full-scale frame as open path-side ground; its click returned `view unchanged; still` at 7:18 PM. The game was paused immediately; no further live input was made.

Final watcher table: attempt 2, 5.72 wall minutes (6:32 total run elapsed), 1.1 minutes in calls, 2.85 minutes thinking, longest think 34.1s, 8 game minutes, 2 clicks (1 walk, 1 still), 3 vision questions, 0 picks; no red flags, own-spot or wrong-row clicks. Gate failed because one decide answer did not move. Step 2 was escalated, run ended failed. Retro: `runs/20261105-1839-model-decides-next-move-harvest-final/retro-1.md`. Learning L180 records the unresolved no-move ground click. This does not meet the stuck ledger's three-move threshold. The game remains paused. The final live gate did not pass; no more live retries were made.
