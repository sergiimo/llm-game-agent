---
name: wylde-navigate
description: Move Tara around Fairhaven in Wylde Flowers — recorded routes, the map, walking with WASD, unsticking, and recognising arrival. Use when the next step requires going somewhere in the game.
---

# Navigating

## Default: click-to-move (L49)
`./wf look` → pick the destination (object or ground point) → `./wf do go:<x>:<y>` (game coords = look coords ÷ 0.4).
The game pathfinds around fences/objects; Tara stops in front of a clicked object with its bubble shown, then
`./wf do key:space`. One `go:` per on-screen hop; chain hops with a look between for far places. `NO MOVE` = clicked a
non-walkable spot. Use the keyboard (`walk:`/`bubble:`/routes) only as a fallback.

## Recorded routes
`./wf route --list` shows them; `./wf route <name>` replays one. Routes are dead-reckoning (direction:seconds)
and assume the **start position written in the route's first comment line**. Verify arrival with
`./wf state` (an area banner OCRs as text, e.g. "Hazel Wylde's Farm") or `./wf look`.

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
- **Stuck**: `do` prints `BLOCKED walk:<dir>` (or `NO BUBBLE: BLOCKED`) when the screen didn't change. Side-step perpendicular 0.5 s, re-look, retry. Approaching objects: `docs/mechanics/basic-actions.md` → Approach a target. Lamp posts, stair edges and
  gate pillars snag Tara (learnings L7).
- Area change = letterbox + location banner bottom-left (sometimes a short camera pan). Wait about 2 s, then `./wf state`.

## After a successful new walk
Save it to `routes/<from>-to-<to>.txt` with a first-line comment describing the exact start spot, and mention it
in the playbook note.
