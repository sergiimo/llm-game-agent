# Retro 1: zoom-walk-2 step 5 escalated (D149 9:30–11:30 pm)

## Evidence
- Zoom gauge: hidden behind the hives → mask 818 px (rejected by the new plausibility check for clicks; the
  `tara-box` printout still shows the raw value); visible beside the beds → **1.82** (expected 1.6–1.9) ✅.
- `affordances.scan()` at night: 1 of 3 honey bubbles found, at a point matching none (image-checked) ❌.
- `fill_can()`: walked her to the well, then "no clickable point" because she was already there; Space filled the can
  (`> fill_watering_can`) — walk doesn't treat "the target's bubble is up / she's within reach of the target" as arrived.
- `goto(bed(8))`: "no progress" at (-1.1, -21.0) though she later stood by the beds; world_belief 0/4 (errors 6–13).
- `goto House:in` ×2 from the back strip: "exit did not change scene" (old graph route).
- Rescue (supervisor, emergency at 23:30): one click to the gap by the house, then the bed through the window → slept.

## Causes (what the evidence supports)
1. walk's arrival test uses the belief only; the belief was 6–13 units off, so "arrived" was never seen even when the
   target's bubble was up.
2. Night bubble detection is still weak (1/3 live).
3. Old graph route for House:in fails from the back strip.

## Next fixes
- walk: arrived when the target's relevant bubble is on screen (affordances) or when the action's log line appears.
- bubbles: tune on real night frames (keep one saved from the next night run).
- belief: re-check the zoom-scaled click prediction (k 1.82 applied?) against the next readings (world_belief).
