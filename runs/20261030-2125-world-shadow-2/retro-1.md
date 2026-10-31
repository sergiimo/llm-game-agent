# Retro 1: world-shadow-2 step 4 escalated (D149 6:49–7:00 pm)

## Evidence (image first, then logs)
- ask.jpg: Tara standing ON the top-row bed (3.34, -25.34); the Inventory / Seeds picker open (Green Bean 26, Carrot 10,
  Tulip 18); red X (refused clicks) clustered at her feet.
- Game log ×3: `> plant me=Player target=GardenBed at (3.34, 0.10, -25.34)` during `goto well`.
- The old goto's question: "well 2 world units south of her" — the well is ~6 units NW. `./wf world tara`: at the bed ±0.05.

## Cause
The old `goto` walked from a wrong estimate (6 units off): short clicks at her feet landed on the bed under her = an
interaction (the seed picker), not a step; the menu guard then (correctly) refused further clicks. The new world model
had her position right. (My first theory — a "Seeds"-word check — was not supported by this evidence; dropped.)

## Fixes
- `./wf goto <learned place in this area>` walks on the world model (`walk`), not the old estimate.
- `go_to` refuses a short click (≤ 1.5 units) that lands on an entity under her when the world is sure (±1).
