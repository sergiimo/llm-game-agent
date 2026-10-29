# Navigation learning loop: design (2026-10-29)

> **Summary:** navigation joins the self-improvement loop (docs/self-improvement.md). Every checkpoint appends one
> fact (predicted vs measured world position) to `tools/nav/facts.jsonl`. Calibration, place positions, blocked spots
> and edge reliability are **computed from the facts** and used immediately. `./wf learn nav` reports them, and only
> "suspect wall" needs review.

## Decisions (user)
- Scope: navigation only. Readings only at **checkpoints** (L62 `pos` costs ~2.5 s). Changes are applied
  **automatically and reported**; only a permanent wall / edge removal waits for review.
- Approach A: one append-only fact log; every other view is derived (a cache is fine, history is never overwritten).

## Ground truth
`pos()` (L62): background → autosave → `currentPlayerPosition` + day/time/season/weather from the same save.
Weather = `time.weatherDays[0]` (code), plus `event` while `weatherEventStart ≤ now ≤ weatherEventEnd`.

## Segment and checkpoint (wf.py)
- Segment, in memory and in `.shots/nav_segment.json`: `from` (last reading: scene, x, z, day, hour) and
  `clicks` (each `go:` screen click since then), plus `dirty` (a key/act/click/text input may have moved her: no
  prediction).
- **Checkpoint** = `pos()` → append fact → new segment from that reading. Triggered by:
  - the end of `goto`, `edge replay` or `go-world`
  - `STILL MOVING` (a stuck walk)
  - a scene event in the log after a click (`ChangeScene`, `Spawning player`, `OnEnter/ExitBuilding`): `to` = the
    spawn/door point, a free anchor
  - `./wf pos` (with `--learn <name>` = this spot is that place)
- `NO MOVE` appends a **no_move fact without a reading**: she didn't move, so nothing to measure. Its target
  = `from` + the calibrated offsets of the earlier clicks + the offset of this click (if calibrated).

## Fact (one JSON line)
`t, day, hour, season, weather, scene, from[x,z]|null, to[x,z]|null, pred[x,z]|null, clicks[[sx,sy]…], goal, edge,
result (arrived|short|moved|no_move|scene|still), dirty`. Deleting a line = undo.

## Derived views (tools/nav.py, pure functions, no game I/O)
| View | Rule |
|---|---|
| Calibration per scene | samples = clean single-click segments (`from`, `to`, 1 click, not dirty, same scene). Fit a homography; drop samples with residual > 3 × median (min 0.3) and refit. Kept in `tools/calib.json` (cache); `wf calib` just makes 8 such samples on purpose. |
| Place positions | median `to` of the last 10 `arrived` facts with that goal (per scene). |
| Blocked spots | `no_move` targets: blocked for 1 game hour after the fact. |
| Edge status | per edge, recency-weighted ok/fail: `ok`, `flaky` (< 70 %), `blocked-now` (failed in the last game hour), `suspect-wall` (failed on ≥ 3 different days and none of the last 3 ok, **review**). |
| Prediction error | `pred` vs `to` per scene, early half vs late half of the facts (should shrink). |

## Use in play
- `go-world X Z` / `goto <place>` when the place has a world position in the current scene: dead-reckon from the
  segment, hop ≤ the on-screen box (screen point clamped to x 200–1720, y 200–980), avoid blocked spots (rotate ±35°),
  `NO MOVE` → half the hop (≤ 2 times), then checkpoint. If still > 0.8 units off, one corrective round
  from the real reading (max 2 checkpoints per trip). Otherwise `goto` falls back to the map route (L57) and its
  arrival checkpoint teaches the place's world position for next time.
- `edge replay` checkpoints at the end and prints the edge status. A `suspect-wall` edge is still replayed but flagged.

## Report: `./wf learn nav`
Calibration per scene (samples, kept, error), places (n, spread), edges with status, active blocks, prediction-error
trend, last 8 facts with `t` (to delete a bad one by hand).

## Testing
`tools/test_nav.py` (stdlib unittest, `python3 -I tools/test_nav.py`): synthetic homography recovered from noisy
samples including outliers; place median; block expiry; edge status rules; segment → fact prediction. Live check:
calibrate from facts on the Farm, `pos --learn` a spot, walk away, `goto` it twice: the 2nd trip uses world mode
and lands < 0.8 units off with ≤ 2 readings.

# Phase 2: units → graph → vectors (2026-10-29)
User decisions: build all three, in this order; the bubble catalog stays a separate "what" classifier (only its labels
may ever be joined with positions).

## 1. Units: map pixels → world
- A checkpoint taken while the map pin is known (`wf where`, map-route `goto` arrival) stores `pin: [mx, my]`.
- Per scene, axis-aligned fit `x = a·mx + b`, `z = c·my + d` (the map is north-up and the camera never rotates; least
  squares, ≥ 2 pairs that differ on both axes). A map place (`map.json`) belongs to the scene with the nearest pin pairs
  (≤ 150 map px) and gets a world point marked `src: map` (coarse). Real arrivals (`src: arrived`) override it.

## 2. Graph in world units
- **Nodes** `<scene>:<name>`: learned places (arrivals), converted map places, **anchors** (scene checkpoints named
  from the log: `Spawning player at X` → `X`, `OnEnterBuilding B` → `B:in`, `OnExitBuilding B` → `B:out`) and
  **exits** (dead-reckoned point where the click/Space that changed scene was aimed: `<A>:exit>…`).
- **Edges:** `walk` between any two nodes of a scene (cost = distance + 5 per recent failed trip to the target),
  `link` exit → anchor (cost 5), `replay` for `edges.json` recipes between known anchors (cost 3; `suspect-wall` =
  removed).
- **Plan:** Dijkstra from the current position (virtual node, walk edges to its scene). **Execute:** walk = `go_world`;
  link = `go_world` to the exit, then up to 2 pushes 1.5 units further the same way until the scene changes;
  replay = `edge_replay`. `goto` uses the graph first and falls back to the map route.

## 3. Vectors: place fingerprints
- At every checkpoint, before the reading: a Vision feature print of the frame without the HUD (y ≥ 180,
  downscaled), stored in `tools/nav/<area>/prints.jsonl` by fact `t`.
- **Prediction:** k = 3 nearest prints of the same scene (≥ 5 stored), weighted → world point + nearest distance.
  Each checkpoint records `img: {pred, d}`; the reading is the label, so the error is known.
- **Gate (derived):** image localisation is used instead of a reading (start of `go_world` when the segment is
  unknown) only when, over that scene's last 20 evaluated facts with d below the cut, ≥ 80 % were within 1.5 units.
  `wf learn nav` shows the accuracy.

# Phase 3: map layer + storage per coordinate frame (2026-10-29)
Checked first (L65): every scene has its own world coordinates (Farm east edge x ≈ +25 → Town spawn x −71.7, y 6.3);
buildings share their scene's (L64). So storage follows the coordinate frames:
```
tools/nav/facts.jsonl            all facts (`scene` = area: 'Farm', 'Farm/House')
tools/nav/map.json               L4: places (map px) + fits {scene: map -> world} (cache, refit on every pin fact)
tools/nav/spawn_inside.json      spawn anchors that are indoors
tools/nav/<Scene>/               calib.json (L2, cache) + prints.jsonl (L1)
tools/nav/<Scene>/<Building>/    same coordinates, indoor camera: its own calib.json + prints.jsonl
```
- **4 layers per area:** L4 map (outdoors only; pins are ignored indoors) → L3 graph → L2 calibration → L1 prints.
  `wf learn nav` prints one line per area with what each layer knows.
- **Coarse map nodes** carry a radius r = max(2, 2 × the scene's map-fit error). Walking to one ends `NEAR` (fact
  result `near`, never `arrived`, so a coarse point never becomes the place); `wf pos --learn <name>` at the real spot
  makes it exact. A map-route arrival is also recorded as `near` with its pin (a map pair).
- **Fallback:** `goto` = graph (finest layer that knows the place) → map route; after each scene change on the map
  route the graph re-plans (the new scene may know the place).

# Phase 4: walls, free readings, coverage improver (2026-10-29, L67)
- **Free readings:** after a click, `Player locomotion failed at <Scene> (x, y, z)` / `Path blocked timeout exceeded at
  (x, y, z)` in the log = exact position → fact `stuck` (src `log`), segment restarts there. Not a calibration sample,
  not a prediction error.
- **Walls:** `stuck` points per area; a straight walk passing within 1 unit of one (not starting at it) costs +50.
  `go_world` on a stuck hop tries sideways hops (70°, −70°, 110°, −110°, 3 units); the first free one ends in a reading
  stored as `via` → a graph node `<area>:via(x,z)`.
- **Coverage:** outdoors one grid over the map picture (40 map px cells, facts placed by pin or by world → map through
  the scene fit), indoors a 3-unit world grid per area. Layers per cell: L4 pin (outdoors), L3 reading, L2 prediction
  confirmed < 1 unit, L1 print. Road cells come from the last map picture (`.shots/map_last.png`).
- **Continuous fill:** each checkpoint (not scene/still) opens the map once when its cell lacks a pin and Tara is on a
  road. `wf improve N`: reading → fill pin → one short hop for L2 → go to the nearest uncovered road cell (coarse
  radius) → repeat; never the same target twice.
- **No guessed positions (L68):** an exit is stored only when traced from a reading in a calibrated area. An untraced
  crossing still creates the exit node and its link, with no position: a building door gets `aim` = the other side's
  anchor (same coordinates), a scene link costs a flat 30 and its step returns "needs exploring". The first traced
  crossing gives it a position.
