# Plan: replant-wilted-flowers

- **Goal:** D183 remove and replant all 8 wilted flower beds with Tulips; verify no wilted beds remain
- **Done when:** `./wf py "print(len(beds(wilted=True)))"` reports 0 and every removed bed has both exact-position `unplant_impl` and `totalPlanted.TulipSeed` proof. If the known four-seed shortage remains, stop safely with the other beds still planted/wilted and return `decision-needed` before spending or substituting crops.
- **Brief:** `docs/routines.md` (Wilted rule), `docs/actions.md` A18, `docs/mechanics/farming.md` (Verified in-game), `tools/game/garden.py` (`beds`, `unplant`, `plant`, `replant`), `.claude/skills/wylde-play/SKILL.md` §§1–2.
- **Review:** Ready with a constrained partial path. D183 has 8 wilted beds and the last save has only 4 TulipSeed. Removal is destructive, but explicitly authorized by “get wilted flowers re-planted”; purchases and vegetable substitution are not. Process at most four beds, in two-bed batches, then verify/recount and request the seed decision. Do not harvest ripe crops or water unrelated beds in this run.

## Step 1: Replant the first two wilted beds
- **Do:** Use the supervisor's fresh preflight; do not repeat orientation. Run `./wf resume`, then the direct map route `./wf goto farm-garden` once, then `./wf py "for b in beds(wilted=True)[:2]: replant(b, 'Tulip')"`. Run `./wf pause` after the call.
- **Signal:** Two exact-position `> unplant_impl` lines and two increments of `totalPlanted.TulipSeed`; the action tree shows both nested `unplant` and `plant` successful.
- **Done when:** A fresh bed recount has two fewer wilted beds and no removed bed is left empty.
- **Budget:** 5 `./wf` calls, 45 game min.
- **If stuck:** Stop the batch immediately; follow L75 escalation and preserve all remaining wilted beds. Never use blind clicks or remove another bed.

## Step 2: Replant two more wilted beds
- **Do:** Re-read the fresh wilted list, then run `./wf py "for b in beds(wilted=True)[:2]: replant(b, 'Tulip')"` once more. Run `./wf pause` after the call.
- **Signal:** Two more `unplant_impl` proofs and two more Tulip planting-stat proofs.
- **Done when:** Four total beds were safely replaced and the Tulip seed supply has not been exceeded.
- **Budget:** 4 `./wf` calls, 35 game min.
- **If stuck:** Stop and escalate; do not compensate with manual clicking or a different seed.

## Step 3: Recount and finish or request the seed decision
- **Do:** Run `./wf routines` plus a wilted-bed recount. If no beds remain wilted, end done. If four remain as expected, leave them intact and return `RESULT: decision-needed` asking whether to buy Tulip seeds or substitute an owned crop. Keep the game paused.
- **Signal:** Exact remaining wilted count and current seed inventory from save/state evidence.
- **Done when:** Zero wilted beds, or a safe decision boundary with every unprocessed bed still intact and the game paused.
- **Budget:** 3 `./wf` calls, 5 game min.
- **If stuck:** Report the last proven bed list and pause; do not spend, sleep, harvest, or remove another bed.
