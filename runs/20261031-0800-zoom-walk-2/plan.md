# Plan: zoom-walk-2 (L85 + M3 walk, after S22–S24 fixes)

- **Goal:** check the zoom gauge where Tara is visible in the garden, the bubble scan at night against the image,
  then fill the can and walk to bed 8 with the world walk; then bed (it's late).
- **Done when:** steps 1–5 done.
- **Brief:** docs/mechanics/basic-actions.md (Camera zoom, Interaction bubbles) · docs/actions.md A11 (sleep) ·
  AGENTS.md rules 7–8
- **Review:** supervisor 2026-10-31; sleeping approved at step 5 (she must sleep by ~23:30; pass-out at 02:00); no
  planting/watering. On any problem: `./wf look`, Read it, describe it before naming a cause.

## Step 1: Orient + measure
- **Do:** `./wf resume`, `./wf state`, `./wf tara-box`, `./wf look` and Read it
- **Signal:** a mask line; is she visible (not behind the hives)?
- **Done when:** both copied + one-line image description
- **Budget:** 5 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: Bubbles vs image
- **Do:** `./wf py "affordances.scan()"` and compare with the step-1 image (which bubbles, over which objects,
  which one highlighted)
- **Signal:** the scan lists the bubbles you see
- **Done when:** comparison written in the step note
- **Budget:** 2 calls, 5 min
- **If stuck:** report the mismatch, continue

## Step 3: Fill the can
- **Do:** `./wf py "fill_can()"`
- **Signal:** `✓ well.fill_can()`; log `target=Well`
- **Done when:** ✓, or FAILED + image description; on NEED_VISION answer once (`./wf teach step X:Y`), re-run
- **Budget:** 8 calls, 30 min
- **If stuck:** 2 unhelpful vision answers → escalate

## Step 4: To bed 8, measure in the garden
- **Do:** `./wf py "goto(bed(8))"`, then `./wf tara-box` (she should be visible among the beds), `./wf eval`
- **Signal:** `✓ move.goto(bed 8 …)`; zoom ≈ 1.6–1.9
- **Done when:** ✓ + zoom line copied
- **Budget:** 8 calls, 30 min
- **If stuck:** as step 3

## Step 5: To bed
- **Do:** `./wf goto House:in`, then docs/actions.md A11 (pink bed: click it, `./wf do key:space`, `text:Yes`)
- **Signal:** log `Spawning player at Farm/Bed`, `OnDayStarted`
- **Done when:** next day 7:00
- **Budget:** 12 calls, 60 min
- **If stuck:** as step 3; if it gets past 23:30 and she isn't in, escalate at once
