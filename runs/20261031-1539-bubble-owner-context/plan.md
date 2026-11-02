# Plan: bubble-owner-context

- **Goal:** resolve bubbles against all current-region objects so beehive bubbles cannot satisfy goto_bed
- **Done when:** ownership sees beds, hives, well and other current-region objects before applying the bed query; the
  three live beehive bubbles activate hives rather than a bed; regression tests pass; a live rerun reaches a real bed.
- **Brief:** `runs/20261031-1536-multi-active-live/look-arrival.jpg` · L93 ·
  `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` · `tools/objects/loop.py`.
- **Review:** user verified the three jar bubbles are beehives. Game remains paused during code/test work. The fix must
  preserve query-state filtering: a nonmatching nearby bed may be active globally but cannot satisfy `goto_bed(state…)`.

## Step 1: Fix contextual ownership
- **Do:** follow `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md`; make the loop detect all object
  candidates belonging to the current region plus query candidates, assign bubbles across that full set, then test
  arrival only against query matches.
- **Signal:** synthetic stacked hive/bed regression assigns an unknown bubble to the nearer hive and rejects bed arrival.
- **Done when:** focused regression passes.
- **Budget:** 25 min.
- **If stuck:** keep the game paused and return the ambiguous detection/ownership set.

## Step 2: Verify and document
- **Do:** run `tools/test_loop.py`, `tools/test_graph.py`, the `goto_bed` wrapper test; update `docs/learnings.md` and
  the object-loop design with the live beehive correction.
- **Signal:** all relevant tests pass and docs say ownership is resolved before query filtering.
- **Done when:** offline checks and `git diff --check` pass.
- **Budget:** 25 min.
- **If stuck:** preserve the failing test and report partial.

## Step 3: Live rerun
- **Do:** `./wf resume`; run `./wf py "goto_bed()"`; `./wf pause`; inspect `./wf py "available()"` and one gameplay
  look (resume/look/pause only if needed). Never press Space or a bubble.
- **Signal:** beehive bubbles may appear in `available()` as BeeHive nodes but do not return bed Arrival; eventual
  Arrival is at a visible bed bubble with Tara-relative direction, or is proved by one matching bed interaction log
  (`out_of_water target=GardenBed`) after a click. A hive interaction never proves bed arrival.
- **Done when:** live outcome recorded and game paused.
- **Budget:** 14 calls, 90 game minutes (revised after live `beehive_progress` exposed a missing hive-only bubble map).
- **If stuck:** one NeedVision correction maximum; otherwise stop partial.
