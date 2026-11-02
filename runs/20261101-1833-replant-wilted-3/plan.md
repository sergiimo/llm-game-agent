# Plan: replant-wilted-3

- **Goal:** Replant the wilted beds with the SAME crop that wilted (user, D183): bed 7 (already empty, was Green Bean) + the 7 wilted beds.
- **Done when:** each bed proved by `unplant_impl` + `totalPlanted.<Seed>` + `> plant` at the same bed; `./wf routines` shows 0 wilted (or the seeds of a crop ran out); game paused.
- **Brief:** `docs/actions.md` A18; `tools/game/garden.py replant_visible`; retro `retros/2026-11-01-replant-hive-wrong-target.md`.
- **Review:** Rewritten for "replant same" with geometry-free tools `plant_visible(seed, at)` / `replant_visible()` (L116; offline tests green). Seeds owned: Tulip 4, Carrot 10, Green Bean Seeds x6 (the unnamed save item; the panel opens on Green Bean, L117). Earlier: Revised from step 1 after two tool fixes (math import L113; wrong-bed match L114). Bed 7 already unplanted. Third fix: plant bubble was mislabelled `unplant_impl` (L115). Ready. Previous run failed because Tara's belief was stale (±5, NEEDS FIX) so `affordances.scan()` matched no bubble to a bed; fixed (scan now takes a save reading first; offline test added, suites green). Tara stands between the bed rows at (0.8,-27.3), D183 11:30, game paused. Seeds owned: TulipSeed x4, CarrotSeed x10. No navigation, no generic Space. Cheapest model.

## Step 1: Plant Green Bean in empty bed 7 (also proves Green Bean seeds are owned)
- **Do:** `./wf resume`; then `./wf py "plant_visible('Green Bean', at=(3.34, -29.09))"`.
- **Signal:** `totalPlanted.GreenBean…` and `> plant … at (3.34, 0.10, -29.09)`. No walking in the trace.
- **Done when:** bed 7 planted with Green Bean.
- **Budget:** 2 calls, 15 game min.
- **If stuck:** `./wf pause`, report the exact error (e.g. "no Green Bean card" = seeds not owned; "N plant bubbles" = list them), stop.

## Step 2: Fast replant loop (user flow): spot drop bubble → click → wilted → remove → plant same → water
- **Do:** `./wf resume`, then `./wf py "replant_visible()"` up to 4 separate times (4 Green Bean seeds left; each call fixes one bed incl. watering, and waters dry beds it meets), then `./wf pause`.
- **Signal:** per call `✓ garden.replant_visible` with `unplant_impl`, `totalPlanted`, `> plant`, `> water` all at the same bed.
- **Done when:** 4 beds fixed, or a call fails (Read its NEED_VISION frame, describe it, stop).
- **Budget:** 6 calls, 60 game min.
- **If stuck:** `./wf pause`, Read the NEED_VISION frame, report what it shows, stop.

## Step 3: Recount
- **Do:** `./wf routines`; leave paused.
- **Signal:** wilted count (expected 2 if all wilted beds are Green Bean).
- **Done when:** exact remaining wilted count reported.
- **Budget:** 1 call, 0 game min.
- **If stuck:** report the last proofs only.
