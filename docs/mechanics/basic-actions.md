# Basic actions & tools

> **Summary:** one interaction model: walk next to the target until its **icon bubble** shows → **Space**. Tools aren't
> equipped by hand; the game uses the right tool for the target (can at a bed, axe at a log/tree, pickaxe at a rock, rod
> at a fishing spot). Tools sit in the inventory section **Tools**. Every tool use costs energy.

**The per-action table lives in [../actions.md](../actions.md)** (recipe → expected hits/drops/energy → verify signal →
what to do if it differs). Print the rows a job needs: `./wf actions chop rock pickup`. This file keeps the shared
interaction model: approaching targets, gotchas, movement.

## Gotchas (verified)
- **Wood/drops count only after pickup** (Space at the bag "+" bubble). When an axe bubble and a pickup bubble overlap,
  the **axe wins**, which wastes a swing: step `walk 0.3` until the "+" bubble is the highlighted one.
- Check progress in the tracker popup or the journal (J), not by counting swings.
- **NPCs walk around.** Space is wasted if they move off mid-bubble. Look first and press when they're stationary.

## Approach a target (any object)
**Click-to-move is the only way to move (L49, L54).** `./wf look`, then `./wf do go:<x>:<y>` with the target's game coords
(look coords ÷ 0.4). The game **pathfinds** (around fences, through gate gaps) and Tara stops **in front of a clicked
object with its bubble shown** (well: `bubble@` in the state line); it does NOT interact, so then `./wf do key:space`.
Click the object itself (well, bed, NPC, mushroom) or a ground point next to it. Target must be on screen; for far
places chain `go:` hops (look between). `go:` returns when Tara herself stops (tracker, L52).
- `ALREADY THERE` = she was already at the object (its bubble shows): act.
- `NO MOVE` = not walkable (wall, furniture, water, a menu open): click a ground point nearer to Tara.
- `STILL MOVING` = long path: look and continue.
- **Leave a building:** click the floor at the doorway (bottom edge of the room) → log `OnExitBuilding`. ❓ verify per building.
- Keyboard walking (`walk:`/`path:`/`route:`/`bubble:`) is disabled in the tool (user rule, L54).
- **Only press Space when the state line shows `bubble@x,y`**, and the bubble is the one you want (next to a tree the
  axe bubble wins over a pickup).

What forageables look like on the 0.4 look: **Mushroom** = small grey-brown cap on a pale stem, about Tara's head size,
often next to grey rocks (easy to read as a pebble). **Thistle** = purple flower (also picked with a "+" bubble).

## Finding targets
- Where things are: [../world/locations.md](../world/locations.md) (per-area resources) → quest file notes → map `M` + `./wf look`.
- A target with no bubble from any side is probably decoration. Note it in the quest file and locations.md.

## Energy
Each tool use costs energy ([energy.md](energy.md); `./wf state` shows ⚡N%). **Out of energy** → Tara says "I have no strength left!" (EN ❓) (Space dismisses) and tool use stops. **Default: stop energy work and report / plan sleep; don't eat**
unless the goal needs it the same day (`./wf tips energy`). Early game: about 2–3 logs of chopping per full bar.
