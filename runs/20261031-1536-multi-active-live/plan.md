# Plan: multi-active-live

- **Goal:** live-test goto_bed multi-active bubble state, Tara-relative edges, and available()
- **Done when:** `goto_bed()` returns at a real garden bed; `available()` lists every resolved bubble-active bed with
  point and Tara-relative direction; the look confirms the reported bubbles; the game is paused without interaction.
- **Brief:** `docs/mechanics/basic-actions.md` (Approach a target) · `tools/objects/loop.py` · live regression for L93.
- **Review:** D156 08:40, Tara near the mine bridge/herb pickup west of the garden, game paused. No Space, planting,
  watering, harvesting, purchases, or sleep. Click-to-move only inside `goto_bed()`. Hard limit 12 calls; one answered
  NeedVision maximum, then stop partial. Capture `available()` before any new navigation observation.

## Step 1: Resume and orient
- **Do:** `./wf resume`, then `./wf look`; inspect Tara's position and confirm gameplay.
- **Signal:** gameplay frame, no menu/dialogue.
- **Done when:** start frame copied to the run directory and location recorded.
- **Budget:** 2 calls, 10 game minutes.
- **If stuck:** `./wf pause` and stop; do not dismiss unexpected UI.

## Step 2: Run multi-active goto
- **Do:** `./wf py "goto_bed()"` once. If it raises NeedVision, inspect its image and use one `./wf py "answer(...)"`
  or `label(...)`, then rerun once.
- **Signal:** `Arrival(node=GardenBed#…, region='Garden', point=(…), frames=…)`.
- **Done when:** the call returns Arrival without pressing a bubble.
- **Budget:** 4 calls, 40 game minutes.
- **If stuck:** after one answered ask or any wrong interaction, `./wf pause` and report partial.

## Step 3: Inspect the active graph
- **Do:** immediately run `./wf py "available()"`, then `./wf look`; copy the look into the run directory.
- **Signal:** one or more GardenBed rows with `direction`, `bubble`, and `point`; bubbles at those points in the image.
- **Done when:** record reported rows versus visible bubbles, including whether multiple nodes are active.
- **Budget:** 3 calls, 10 game minutes.
- **If stuck:** preserve the outputs and continue to pause.

## Step 4: Finish safely
- **Do:** `./wf pause`, update progress, `./wf run end done|partial`.
- **Signal:** pause overlay.
- **Done when:** game paused and result recorded.
- **Budget:** 3 calls.
- **If stuck:** `./wf pause` remains the only input.
