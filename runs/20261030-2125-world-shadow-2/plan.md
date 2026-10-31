# Plan: world-shadow-2 (M3 gate)

- **Goal:** walk a few legs with today's tools while the world model predicts in shadow; compare the eval
  `world_belief` with the old `belief` on the same readings.
- **Done when:** steps 1–4 done and `./wf eval` shows `world_belief` and `belief` counts.
- **Brief:** .claude/skills/wylde-navigate/SKILL.md · AGENTS.md rules 7–8
- **Review:** supervisor 2026-10-30 (M2 plan Task 6 step 3); no quest work, no menus; daytime.

## Step 1: Orient
- **Do:** `./wf resume`, `./wf state`, `./wf world tara`
- **Signal:** gameplay; a tara line with a position
- **Done when:** both printed
- **Budget:** 4 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: To the well
- **Do:** `./wf goto well`
- **Signal:** ARRIVED/NEAR well
- **Done when:** at the well
- **Budget:** 6 calls, 20 min
- **If stuck:** on `NEED_VISION step` Read the image, `./wf teach step X:Y`, re-run; 2 unhelpful answers → escalate

## Step 3: To the garden, bed 8
- **Do:** `./wf py "goto(bed(8))"`
- **Signal:** `✓ move.goto(bed 8 …)`
- **Done when:** ✓ printed
- **Budget:** 6 calls, 20 min
- **If stuck:** as step 2

## Step 4: Back to the well, then report
- **Do:** `./wf goto well`, then `./wf world tara`, `./wf eval`
- **Signal:** the eval lists `world_belief`
- **Done when:** eval printed
- **Budget:** 6 calls, 20 min
- **If stuck:** as step 2
