---
name: wylde-navigate
description: Move Tara around Fairhaven in Wylde Flowers by clicking (click-to-move), the map, and recognising arrival. Use when the next step requires going somewhere in the game.
---

# Navigating (mouse only, L54)

## Click-to-move: the only way to move
`./wf look` → pick the destination (object or ground point) → `./wf do go:<x>:<y>` (game coords = look coords ÷ 0.4).
The game pathfinds around fences/objects; Tara stops in front of a clicked object with its bubble shown, then
`./wf do key:space`. One `go:` per on-screen hop; chain hops with a look between for far places. `go:` returns when
Tara herself stops (tracker, L52).
- `ALREADY THERE` → she's at the object: act. `NO MOVE` → not walkable: click a ground point nearer to Tara.
- **Leaving a building:** click the floor at the doorway (bottom edge of the room).
- Keyboard walking (`walk:`/`path:`/`route:`/`bubble:`) is disabled in the tool. There is no keyboard fallback.

## Exact position (L62)
`./wf pos` → `POS <scene> (x, y, z)`: engine world coords from a fresh autosave (the game goes to the background for
~2.5 s, then comes back). Ground = x/z. `NO NEW SAVE` = nothing changed since the last save, which still holds.
Use at arrivals or when lost, not every step. `./wf calib` (≈45 s, 8 short hops on open ground, no fences or water
nearby) teaches the current scene's screen ↔ ground mapping (outdoors it is the same camera everywhere, so a new outdoor scene borrows an existing fit; each indoor area needs its own, L66).

**Navigation learns by itself (self-improvement loop):** every `go:` is remembered; checkpoints (end of `goto`/edge,
scene change, stuck, `./wf pos`) measure where Tara really is and append a fact to `tools/nav/facts.jsonl`.
- `./wf pos --learn <name>` = this spot is place `<name>`. `./wf goto <name>` then walks there by calibrated clicks
  (≈10 s, 1–2 readings, < 0.8 units off; Farm D146: 0.04 and 0.01).
- **Graph first, map last.** If the map fails once (`map did not open`, `NEED_VISION`), don't retry it: `./wf pos`,
  then `./wf plan <node>` / `./wf goto <node>` (graph nodes like `House:in` are not in the map's place list).
  `goto` does this by itself when the map won't open.
- **Exits are stored only when traced** (calibrated area): an untraced crossing keeps the link without a position.
  A building door then walks toward the other side's anchor (same coordinates); a scene link prints "needs exploring".
- **4 layers, coarse → fine:** L4 map (place pins, outdoors only) → L3 graph → L2 calibration → L1 image prints.
  `goto` plans at the finest layer that knows the place: a learned place = `ARRIVED` (exact); a place known only
  from the map = `NEAR` (±2–12 units: look, click the last bit, then `./wf pos --learn <name>`); unknown to the graph =
  the map route, re-planned by the graph after each scene change.
- **Each scene has its own coordinates** (L65): data lives in `tools/nav/<Scene>/` and `tools/nav/<Scene>/<Building>/`;
  scenes connect only through learned exits → anchors.
- `./wf go-world X Z` = walk to a world point in this scene.
- **World graph:** nodes = learned places, map places (coarse), scene/building **anchors** (`Farm/LinkTown`, `House:in`,
  `House:out`) and the **exits** that lead to them; `./wf plan <name>` shows the route (walk / link / replay), `./wf goto
  <name>` runs it, falling back to the map route. Each crossing teaches a link by itself. Areas: `Farm`, `Farm/House`
  (indoors = its own area: buildings share the outdoor coords). An area without calibration can't be walked by the graph.
- **Place fingerprints:** every checkpoint stores an image vector; once a scene's image guesses prove right (≥ 20, 80 %),
  they replace the 2.5 s reading at trip starts. `learn nav` shows the accuracy.
- **Walls (L67):** when a walk stops against a barrier, the game log gives her exact position for free; `go-world`
  then steps sideways (detour) and the detour point becomes a graph node, so the next plan goes around by itself.
- **Coverage (L67):** `./wf coverage` = matrix of map cells (outdoors) / world cells (indoors): digit = layers present
  (map pin, reading, confirmed prediction, print), `·` = road without data, `@` = Tara. Every checkpoint fills a missing
  map pin when she stands on a road. `./wf improve [N]` fills her cell's gaps, then walks to the nearest uncovered road
  cell, N cells (≈ 1 game hour for 3; outdoors only). If pins are never taken, check `./wf road` (0% on a road =
  teach this lighting period with `./wf road --calibrate`).
- `NO MOVE` spots are avoided for 1 game hour. `./wf learn nav` = what each layer knows per area, then calibration,
  places, edges, blocks, recent facts
  (delete a bad fact's line to undo it). Edges marked `suspect-wall` need a human decision.

## Finding the way
- `./wf key m` opens the map: the pink pin is Tara and a dotted line marks the current quest route. Close with Esc.
- World connections: `docs/world/overview.md` (Map), `docs/world/locations.md` (verified landmarks) and
  `reference/wiki/<Area>.md` → "Connections" (e.g. Town Center → Farm exits top-left by the Blacksmith).
- Old keyboard routes in `routes/*.txt` are disabled, but their comments still describe landmarks along the way.

## Arrival
Area change = letterbox + location banner bottom-left (sometimes a short camera pan); the log shows `ChangeScene` /
`OnEnterBuilding` / `OnExitBuilding`. Then `./wf state`.
