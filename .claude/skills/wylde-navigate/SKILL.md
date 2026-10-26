---
name: wylde-navigate
description: Move Tara around Fairhaven in Wylde Flowers — recorded routes, the map, walking with WASD, unsticking, and recognising arrival. Use when the next step requires going somewhere in the game.
---

# Navigating

## Prefer recorded routes
`./wf route --list` shows them; `./wf route <name>` replays one. Routes are dead-reckoning (direction:seconds)
and assume the **start position written in the route's first comment line**. Verify arrival with
`./wf state` (an area banner OCRs as text, e.g. "Ферма Хейзел Уайлд") or `./wf look`.

## Finding the way
- `./wf key m` opens the map: the pink pin is Tara and a dotted line marks the current quest route. Close with Esc.
- World connections: `docs/world/overview.md` (Map) and `reference/wiki/<Area>.md` → "Connections"
  (e.g. Town Center → Farm exits top-left by the Blacksmith; Farm → Beach bottom-left).

## Getting to an interactable (beds, well, NPCs, doors)
`./wf do bubble:<dir>[:<max_s>]` walks in 0.25 s steps until an interaction bubble appears (`bubble@x,y` in the
state line), then `./wf do key:space`. Bubbles fade in only once Tara stops. Don't push into objects for seconds,
since that can open their panel (learnings L25/L26).

## Walking
- `./wf walk <dir> <sec>` / `./wf path up:1.2 left:3 nw:0.8`. Directions are screen-relative (W=up …), with
  diagonals ne/nw/se/sw. Speed is about 1 screen-width per 4–5 s.
- Walk in chunks of ≤ 4 s, then `./wf look` to check position.
- **Stuck** (screen unchanged after a walk): side-step perpendicular 0.5 s and retry. Lamp posts, stair edges and
  gate pillars snag Tara (learnings L7).
- Area change = letterbox + location banner bottom-left (sometimes a short camera pan). Wait about 2 s, then `./wf state`.

## After a successful new walk
Save it to `routes/<from>-to-<to>.txt` with a first-line comment describing the exact start spot, and mention it
in the playbook note.
