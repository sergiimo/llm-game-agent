# Streaming Garden Design

## Intent

Make routine garden maintenance one fast, low-reasoning command. The world graph keeps stable GardenBed identities and
positions, while live bubbles are the authoritative current reading. The routine visits each graph bed once and acts
immediately after reading it instead of surveying the whole garden before beginning work.

## Goals

- `./wf garden` performs a complete pass over a garden.
- At each bed: inspect its live bubble, immediately perform every applicable chore, then mark the bed visited.
- Chores are: replant a wilted crop with the same crop and water it; harvest ready non-flowers; water dry growing crops.
- Ready flowers stay for bees. Empty beds stay empty unless a separate planting command supplies a seed policy.
- Finish only when every graph bed in the selected region has a fresh visit result or a recorded safe failure.
- Use model vision only when navigation or a bubble reading cannot be resolved by code.
- Individual `water_all`, `harvest_all`, and `replant_all` commands use the same visit-and-act scheduler with a narrower
  set of enabled chores.

## Non-goals

- No purchases, crop substitution, automatic planting of empty beds, sleeping, or harvesting flowers.
- No removal of graph object identities.
- No model inference of watering need from plant appearance; only bubble/card/action feedback may establish it.

## Data and evidence

The graph supplies the expected bed set and traversal coverage. A bed is not considered visited because it was merely
projected on screen. A live bubble at its proven point, a card, or a positioned game event is required. Bubble icon and
badge readings update that graph node immediately. Every action is verified by its existing card/event transition row.

The scheduler keeps a per-call `visited` set. After acting on a bed it rescans because replanting and harvesting change
the bubble. It completes all enabled chores for that bed before moving on. A final result reports visited, acted,
skipped-flower, and unresolved bed IDs.

## Chore precedence at one bed

1. Wilted/drop with wilt proof: remove, replant the same crop, water.
2. Ready non-flower: harvest.
3. Dry growing crop: water; refill the can through the existing subgoal if required.
4. Ready flower: skip and record.
5. Otherwise: record fresh/no-action and advance.

If a drop bubble is ambiguous between dry and wilted, click it once and route from the resulting water event or wilted
card. The routine never guesses.

## Interface

- `game.garden.do(region='Garden', answer=None, max_clicks=...) -> result`
- `engine.tend_garden(region, chores, answer=None, max_clicks=...) -> result`
- CLI: `./wf garden [region=Garden] [answer=...]`

`chores` is an ordered set drawn from `replant`, `harvest`, and `water`. Existing task wrappers call the same scheduler
with one enabled chore so bubble-first streaming becomes the default garden strategy.

## Logging

Each node produces a `garden_visit` run row with its bubble reading, chosen chore, proof, and result. Detector output is
logged as `perception`; model questions remain `vision`; chosen actions remain `decision`/`click`. This keeps heatmap
perception distinct from model vision.

## Safety

- Stop before 23:00 and outside reliable daylight.
- Never click a bubble owned by another kind or another garden.
- Never mark a bed visited from a stale projection alone.
- Missing seeds stop that bed's replant but do not erase completed work; the command returns unresolved beds.
- A no-progress repeat, unexpected event, or wrong-object proof stops the pass and records a gap.

## Approaches considered

- Separate survey then action: rejected because it revisits beds and delays obvious work.
- Sequential whole-garden goals: rejected because replant, harvest, and water each traverse the garden separately.
- Streaming node scheduler: selected because it reads and completes one bed at a time while retaining coverage over all
  graph nodes.
