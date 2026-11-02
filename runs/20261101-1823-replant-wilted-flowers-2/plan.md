# Plan: replant-wilted-flowers-2

- **Goal:** At the bed grid, resolve/select exact bed bubbles and replant four wilted beds with owned Tulip seeds
- **Done when:** Four wilted beds are replaced with owned Tulip seeds, each proved by exact-position `unplant_impl` plus `totalPlanted.TulipSeed`; remaining wilted beds stay intact and game is paused.
- **Brief:** `docs/actions.md` A18; `docs/self-improvement.md` unknown-bubble rule; `tools/game/garden.py` replant/unplant; prior S38 retro.
- **Review:** Ready. Tara is already among the beds, so no route/map call. The fixed selector clicks an exact bed-owned compatible/unknown bubble immediately; known hive bubbles are rejected. First prove one bed, then batch the other three. Cheapest model only.

## Step 1: Prove one exact wilted-bed interaction
- **Do:** Run `./wf resume`, then `./wf py "replant_visible('Tulip')"`. It must choose an already-visible exact wilted-bed bubble and never navigate; pause after the call.
- **Signal:** Exact bed `> unplant` then `> unplant_impl`, followed by `totalPlanted.TulipSeed`; no `beehive_progress`.
- **Done when:** One wilted bed is newly planted and the action tree succeeds.
- **Budget:** 3 calls, 20 game min.
- **If stuck:** Pause and stop on `UNKNOWN_BUBBLE` or wrong target; do not navigate or press Space generically.

## Step 2: Replant the remaining three covered by owned seeds
- **Do:** Run `./wf py "[replant_visible('Tulip') for _ in range(3)]"`, then `./wf pause`.
- **Signal:** Three exact `unplant_impl` and three Tulip planting proofs; no hive action.
- **Done when:** Four total beds were replaced in this run.
- **Budget:** 2 calls, 45 game min.
- **If stuck:** Stop the batch at the first missing exact proof; leave all unprocessed beds intact.

## Step 3: Recount and report seed decision
- **Do:** Run `./wf routines` and a read-only wilted recount. Keep paused.
- **Signal:** Exact remaining wilted count; expected four.
- **Done when:** Report `decision-needed` for remaining beds without purchase/substitution.
- **Budget:** 2 calls, 5 game min.
- **If stuck:** Report last proven count; no more input.
