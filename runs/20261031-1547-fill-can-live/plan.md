# Plan: fill-can-live

- **Goal:** live-test well.fill_can from the garden with the can empty
- **Done when:** `fill_can()` navigates from the bed to the well, produces one valid Well proof, persists `Well can=full`,
  and ends with the game paused. Any duplicate interaction is recorded as a tool gap.
- **Brief:** `docs/actions.md` A7 · `docs/mechanics/basic-actions.md` (Approach a target) · `tools/game/well.py`.
- **Review:** D156 09:40, Tara beside garden bed at (0.8,-27.3), can definitely empty from `out_of_water`; game
  paused. Only well interaction authorized—no bed, hive, planting, harvesting, sleep, or purchases. One NeedVision
  answer maximum. Hard limit 8 calls.

## Step 1: Fill at the well
- **Do:** `./wf resume`, then `./wf py "fill_can()"` once.
- **Signal:** action succeeds; log contains `fill_watering_can … target=Well`, `full_watering_can … target=Well`, or
  “My watering can is already full!”.
- **Done when:** valid Well proof returned.
- **Budget:** 7 calls, 50 game minutes (revised: one NeedVision recovery needs pause, label, resume, retry).
- **If stuck:** inspect one NeedVision image, answer once, rerun; otherwise pause and stop partial.

## Step 2: Verify persisted state
- **Do:** `./wf pause`, `./wf log --tail 12`, `./wf graph show Garden`.
- **Signal:** `Well can=full@…(log)` and no unrelated gameplay action after the start mark.
- **Done when:** proof and graph state agree; duplicate Well interactions counted.
- **Budget:** 3 calls.
- **If stuck:** preserve logs and report partial; do not interact again to verify.

## Step 3: Finish
- **Do:** update progress and `./wf run end done|partial`; keep the game paused.
- **Signal:** paused overlay.
- **Done when:** result recorded.
- **Budget:** 1 call.
- **If stuck:** leave paused.
