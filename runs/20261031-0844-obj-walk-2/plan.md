# Plan: obj-walk-2 (clean re-run)

- **Goal:** walk well → bed 8 → well with objects clicked first and use points learned; scored by `./wf eval`.
- **Done when:** steps 1–4 done, eval printed.
- **Brief:** docs/mechanics/basic-actions.md (Interaction bubbles, Camera zoom) · AGENTS.md rules 7–8
- **Review:** re-run: obj-walk step 3 was disturbed by a manual window move (user). supervisor 2026-10-31; no planting/watering (it rains); image first on any problem.

## Step 1: Orient at the well
- **Do:** `./wf resume`, `./wf state`, `./wf py "fill_can()"` (the can bubble shows: it should click it at once)
- **Signal:** `✓ well.fill_can()`; log `target=Well`
- **Done when:** ✓
- **Budget:** 4 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: To bed 8
- **Do:** `./wf py "goto(bed(8))"`, then `./wf tara-box`
- **Signal:** `✓ move.goto(bed 8 …)`; zoom line
- **Done when:** ✓ + zoom copied
- **Budget:** 8 calls, 30 min
- **If stuck:** NEED_VISION → Read the image, `./wf teach step X:Y` once; then escalate

## Step 3: Back to the well (the object, from the beds)
- **Do:** `./wf py "fill_can()"`
- **Signal:** `✓ well.fill_can()`; she reaches the well by clicking it (not a standing spot)
- **Done when:** ✓
- **Budget:** 8 calls, 30 min
- **If stuck:** as step 2

## Step 4: Report
- **Do:** `./wf world entities Well`, `./wf eval`, `./wf pause`
- **Signal:** the Well with its use points; eval printed
- **Done when:** printed
- **Budget:** 3 calls, 5 min
- **If stuck:** report
