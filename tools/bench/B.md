# Plan: bench B — trips

- **Goal:** benchmark B (spec 2026-10-30 §7.2): house → garden → well → ranch → town fountain → home, one leg per
  step; measured by `./wf bench report` (calls, game minutes, readings, stuck per leg).
- **Done when:** step 6 ends in the farmhouse.
- **Brief:** .claude/skills/wylde-navigate/SKILL.md · docs/world/locations.md (Farm, Town Center, RuralBeach)
- **Review:** template; daytime only (start before 12:00), shops irrelevant.

## Step 1: House to the garden
- **Do:** `./wf goto farm-garden`
- **Signal:** `NEAR farm-garden` / `ARRIVED`
- **Done when:** NEAR or ARRIVED (a map-only place answers a coarse NEAR: that counts as done)
- **Budget:** 9 calls, 30 min
- **If stuck:** on `NEED_VISION step` Read the image, `./wf teach step X:Y`, re-run; 2 unhelpful answers → escalate

## Step 2: Garden to the well
- **Do:** `./wf goto well`
- **Signal:** the well's can bubble
- **Done when:** ARRIVED/NEAR well
- **Budget:** 9 calls, 20 min
- **If stuck:** as step 1

## Step 3: Well to the ranch
- **Do:** `./wf goto ruined-ranch`
- **Signal:** ChangeScene RuralBeach, then NEAR ruined-ranch
- **Done when:** in RuralBeach, NEAR or ARRIVED ruined-ranch (coarse NEAR counts)
- **Budget:** 15 calls, 60 min
- **If stuck:** as step 1

## Step 4: Ranch to the town fountain
- **Do:** `./wf goto fountain-square`
- **Signal:** ChangeScene Town, then NEAR fountain-square
- **Done when:** in Town, NEAR or ARRIVED fountain-square (coarse NEAR counts)
- **Budget:** 18 calls, 90 min
- **If stuck:** as step 1

## Step 5: Town back to the farm
- **Do:** `./wf goto farmhouse`
- **Signal:** ChangeScene Farm, NEAR farmhouse
- **Done when:** on the farm, NEAR or ARRIVED farmhouse (coarse NEAR counts)
- **Budget:** 18 calls, 90 min
- **If stuck:** as step 1

## Step 6: Into the house
- **Do:** `./wf goto House:in`
- **Signal:** `OnEnterBuilding House`
- **Done when:** inside the farmhouse
- **Budget:** 6 calls, 15 min
- **If stuck:** as step 1
