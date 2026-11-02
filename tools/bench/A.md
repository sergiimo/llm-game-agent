# Plan: bench A — garden day

- **Goal:** benchmark A (spec 2026-10-30 §7.2): from waking in the house, replant the wilted beds, water every bed,
  back to bed; measured by `./wf bench report`.
- **Done when:** `./wf routines` shows no wilted beds and R1 DONE (after an autosave) and
  Tara is in bed (next day 7:00).
- **Brief:** docs/routines.md (R1, wilted beds) · docs/actions.md (A7–A9, A11) · .claude/skills/wylde-navigate/SKILL.md
- **Review:** template; the supervisor checks the start state (morning, in the house) before dispatch.

## Step 1: Orient
- **Do:** `./wf resume`, `./wf state`, `./wf routines`
- **Signal:** gameplay, a morning clock, the routines status
- **Done when:** you know how many beds are wilted and dry
- **Budget:** 4 calls, 10 min
- **If stuck:** a menu is open → `./wf state` names it; close it per docs/ui/

## Step 2: Replant the wilted beds
- **Do:** `./wf py "replant_all()"`; on `NEED_VISION step` Read the image and answer
  `./wf teach step X:Y`, then re-run the same line
- **Signal:** `✓ garden.replant_all` with a summary of the beds done
- **Done when:** the call prints ✓ and the summary lists every wilted bed
- **Budget:** 15 calls, 120 min
- **If stuck:** 2 vision answers that didn't help → `./wf run escalate 2 stuck`

## Step 3: Water every dry bed
- **Do:** `./wf py "water_all()"`
- **Signal:** `✓ garden.water_all` with a summary of the beds watered
- **Done when:** ✓ and the summary lists every dry bed
- **Budget:** 10 calls, 90 min
- **If stuck:** as step 2

## Step 4: Back to bed
- **Do:** `./wf goto House:in`, then docs/actions.md A11 (pink bed; click it, `./wf do key:space`, `text:Yes`)
- **Signal:** log `Spawning player at Farm/Bed`, `OnDayStarted`
- **Done when:** next day 7:00
- **Budget:** 10 calls, 40 min
- **If stuck:** daytime sleep refused → `./wf run step 4 skip daytime sleep refused`
