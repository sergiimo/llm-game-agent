# Plan: zoom-walk (L85 validation + M3 walk)

- **Goal:** check the zoom gauge (Tara's mask height) in the garden, then walk with zoom-aware clicks: fill the can
  at the well, walk to bed 8; scored by `./wf eval`.
- **Done when:** steps 1–4 done, eval printed.
- **Brief:** docs/mechanics/basic-actions.md (Camera zoom, Interaction bubbles) · AGENTS.md rules 7–8
- **Review:** rev 2: `goto farm-garden` is the old map route (map-only place) and froze her (3 clicks W/SW, no move); step 2 now uses the world walk to bed 8 and a plain click test first. rev 1: supervisor 2026-10-30; no planting/watering; finish before 22:30 game time. On any problem: `./wf look`,
  Read it, describe it before naming a cause.

## Step 1: Orient on open ground (reference zoom)
- **Do:** `./wf resume`, `./wf state`, `./wf tara-box`
- **Signal:** `mask … height ~178 px … zoom ~1.0` (she is on open farmland west of the garden)
- **Done when:** the zoom line is printed (copy it)
- **Budget:** 4 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: Click test, then into the garden by the world walk, measure
- **Do:** `./wf do go:1150:540 --look` (one plain click on the gravel path toward the garden, north-east of her; Read the
  look: did she move?), then `./wf py "goto(bed(8))"`, then `./wf tara-box`, then `./wf look` and Read it
- **Signal:** she moves on the click; `✓ move.goto(bed 8 …)`; zoom ≈ 1.6–1.9 in the garden
- **Done when:** zoom line copied + image description
- **Budget:** 8 calls, 30 min
- **If stuck:** if the plain click doesn't move her: stop and escalate with the look description (clicks not reaching
  the game). NEED_VISION → Read the image, `./wf teach step X:Y`; 2 unhelpful answers → escalate

## Step 3: Fill the can
- **Do:** `./wf py "affordances.scan()"` (bubbles → objects: are they matched now?), then `./wf py "fill_can()"`
- **Signal:** `✓ well.fill_can()`; log `target=Well`
- **Done when:** ✓, or FAILED with an image description
- **Budget:** 8 calls, 30 min
- **If stuck:** as step 2

## Step 4: To bed 8, report
- **Do:** `./wf py "goto(bed(8))"`, then `./wf eval`, `./wf world tara`
- **Signal:** `✓ move.goto(bed 8 …)`
- **Done when:** eval printed
- **Budget:** 6 calls, 20 min
- **If stuck:** as step 2
