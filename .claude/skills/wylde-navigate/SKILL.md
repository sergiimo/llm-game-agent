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

## Finding the way
- `./wf key m` opens the map: the pink pin is Tara and a dotted line marks the current quest route. Close with Esc.
- World connections: `docs/world/overview.md` (Map), `docs/world/locations.md` (verified landmarks) and
  `reference/wiki/<Area>.md` → "Connections" (e.g. Town Center → Farm exits top-left by the Blacksmith).
- Old keyboard routes in `routes/*.txt` are disabled, but their comments still describe landmarks along the way.

## Arrival
Area change = letterbox + location banner bottom-left (sometimes a short camera pan); the log shows `ChangeScene` /
`OnEnterBuilding` / `OnExitBuilding`. Then `./wf state`.
