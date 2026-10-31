# Plan: world-walk (M3 first live use)

- **Goal:** first live use of `walk` on the world model: bed → well → bed → well, with as few save readings as the
  belief allows; scored by `./wf eval` (world_belief, click, skills).
- **Done when:** steps 1–4 done and `./wf eval` printed.
- **Brief:** .claude/skills/wylde-navigate/SKILL.md · AGENTS.md rules 7–8
- **Review:** rev 2 (bubbles as actions: a click on any bubble = its action; affordances.use). rev 1: supervisor 2026-10-30 (M3 plan Task 3); no planting/watering; daytime. If stuck: `./wf look`, Read the
  image, describe what it shows in the escalation (user rule: image first, then theory).

## Step 1: Orient
- **Do:** `./wf resume`, `./wf state`, `./wf world tara`
- **Signal:** gameplay; a tara line
- **Done when:** both printed
- **Budget:** 4 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: Check the bubbles, then fill the can from where she stands
- **Do:** `./wf look` (Read the image: which bubbles show, over which objects), then `./wf py "affordances.scan()"`
  (what the tool matched: kind @x,y → object), compare both in your note; then `./wf py "fill_can()"`.
- **Signal:** `✓ well.fill_can()`; log `target=Well`
- **Done when:** ✓ printed, or a clear FAILED with your image description
- **Budget:** 6 calls, 20 min
- **If stuck:** describe the image; a menu → one `./wf do key:escape`; NEED_VISION → `./wf teach step X:Y`; 2 unhelpful → escalate

## Step 3: To bed 8
- **Do:** `./wf py "goto(bed(8))"`
- **Signal:** `✓ move.goto(bed 8 …)`
- **Done when:** ✓ printed
- **Budget:** 6 calls, 20 min
- **If stuck:** as step 2

## Step 4: Back to the well, report
- **Do:** `./wf goto well`, then `./wf world tara`, `./wf eval`
- **Signal:** ARRIVED well; eval printed
- **Done when:** eval printed
- **Budget:** 6 calls, 20 min
- **If stuck:** as step 2
