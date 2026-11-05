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
