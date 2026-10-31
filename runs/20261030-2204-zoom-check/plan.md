# Plan: zoom-check (L85)

- **Goal:** measure Tara's on-screen height in the garden (camera zoomed in) and on open farmland, by the tracker
  (`./wf tara-box`) and by eye in the screenshot, to calibrate the zoom gauge.
- **Done when:** steps 1–3 done with numbers and image descriptions for both places.
- **Brief:** docs/mechanics/basic-actions.md (Camera zoom) · AGENTS.md rules 7–8
- **Review:** supervisor 2026-10-30; no planting/watering/quest work; daytime/evening only.

## Step 1: Garden measurement
- **Do:** `./wf resume`, `./wf state`, then `./wf tara-box`, then `./wf look` and Read the image
- **Signal:** a tara box line; the image shows Tara among the beds
- **Done when:** note: tara-box height px, and your estimate of Tara's height in the look image (look image px; the
  look is 0.4 scale) plus where her head and feet are
- **Budget:** 5 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: Walk out to open farmland
- **Do:** from the look image pick open ground south of the garden, away from bubbles and objects, and click it:
  `./wf do go:<x>:<y>`; repeat (one click per call, a look between) until the view shows open grass/road without
  beds (the camera zoomed out)
- **Signal:** the look image shows open farmland; Tara visibly smaller
- **Done when:** on open ground, camera zoomed out
- **Budget:** 8 calls, 30 min
- **If stuck:** describe the image; never click a bubble or an object

## Step 3: Open-farmland measurement
- **Do:** `./wf tara-box`, then `./wf look` and Read it
- **Signal:** a tara box line
- **Done when:** note: tara-box height px and your image estimate, as in step 1
- **Budget:** 3 calls, 10 min
- **If stuck:** report what you see
