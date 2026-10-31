# Plan: day-walk (M3, after arrival-by-bubble)

- **Goal:** from the bedroom in the morning: fill the can at the well and walk to bed 8 with the world walk; check
  arrival by bubble, the zoom, and the bubble scan in daylight; scored by `./wf eval`.
- **Done when:** steps 1–4 done, eval printed.
- **Brief:** docs/mechanics/basic-actions.md (Camera zoom, Interaction bubbles) · AGENTS.md rules 7–8
- **Review:** rev 2 (D150 7:30): click the target itself, the game pathfinds; guessed occlusion removed; tooltip cleared before vision. rev 1: supervisor 2026-10-31; no planting/watering; on any problem `./wf look`, Read it, describe it first.

## Step 1: Orient
- **Do:** `./wf resume`, `./wf state`, `./wf world tara`
- **Signal:** gameplay, Wednesday morning, in the house
- **Done when:** printed
- **Budget:** 4 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: Fill the can
- **Do:** `./wf py "fill_can()"`
- **Signal:** `✓ well.fill_can()`; log `target=Well` (`fill_watering_can` or `full_watering_can`)
- **Done when:** ✓, or FAILED + image description; on NEED_VISION answer once (`./wf teach step X:Y`), re-run
- **Budget:** 10 calls, 40 min
- **If stuck:** 2 unhelpful vision answers → escalate

## Step 3: Bubbles vs image at the well
- **Do:** `./wf look` + Read it, `./wf py "affordances.scan()"`, `./wf tara-box`; compare scan vs image
- **Signal:** the scan lists the bubbles you see; tara-box zoom line
- **Done when:** comparison + zoom line in the step note
- **Budget:** 3 calls, 5 min
- **If stuck:** report the mismatch, continue

## Step 4: To bed 8, report
- **Do:** `./wf py "goto(bed(8))"`, then `./wf tara-box`, `./wf eval`
- **Signal:** `✓ move.goto(bed 8 …)` (ARRIVED by bubble or position); zoom ≈ 1.6–1.9 among the beds
- **Done when:** ✓ + zoom line + eval
- **Budget:** 8 calls, 30 min
- **If stuck:** as step 2
