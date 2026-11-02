# Basic actions & tools

> **Summary:** one interaction model: get the target's **icon bubble** on screen → **click that bubble** (or Space when it
> is the highlighted one). Tools aren't
> equipped by hand; the game uses the right tool for the target (can at a bed, axe at a log/tree, pickaxe at a rock, rod
> at a fishing spot). Tools sit in the inventory section **Tools**. Every tool use costs energy.

**The per-action table lives in [../actions.md](../actions.md)** (recipe → expected hits/drops/energy → verify signal →
what to do if it differs). Print the rows a job needs: `./wf actions chop rock pickup`. This file keeps the shared
interaction model: approaching targets, gotchas, movement.

## Interaction bubbles (verified, user 2026-10-30; D148–D149)
- **Sub-icons (D183, user):** a crop bubble with a pale-blue **water drop** at its top right = the crop needs water **or has wilted** (any crop icon carries it; `affordances.has_drop`). An orange **"!"** sub-icon = another state, not yet verified (probe/vision). Empty bed = seedling bubble without a sub-icon.
- **Clicking any bubble triggers its action**, highlighted or not. The **highlight** (orange ring) only marks the one
  **Space** would use. So with several bubbles on screen (several beds, a bed and the well), **click the bubble of the
  object you want** instead of pressing Space: it can't pick the wrong one.
- Several bubbles show at once when several objects are in reach; each sits above its own object.
- A bubble may already show for an object you were about to walk to (the well's can bubble from the beds): **use it,
  don't walk**.
- **A click on an object or bubble is an interaction, not a step**: clicking the bed she stands at opens its planting
  picker (world-shadow-2). To walk, click open ground away from bubbles and objects.
- **To reach an object, click the object itself as soon as it's visible** (verified D150: one click on the well's
  roof walked her round the hives to the well and turned her to it; the can bubble showed). Clicking a spot near it
  (where she stood last time) can land on something in front of it (a hive).
- Proof is the game log line (`> water … at (x, y, z)`, `> fill_watering_can … target=Well`), not the screen.
- Tools: `game/affordances.py` (`scan` = every bubble with its kind, point, highlight and drop sub-icon, from the
  frame only), used by the chain garden functions (`./wf py "water_all()"`, `replant_all()`, `harvest_all()`).

## Camera zoom (verified, user 2026-10-30)
- The camera **zooms in** in some places — the **garden** by the farmhouse is one. The same screen distance is then a
  shorter ground distance: measured D149 in the garden ≈ **1.7×** the open-farm scale (bubbles of adjacent beds 276 px
  apart for 2.5 units; rows 180 px apart for 3.75 units). Anything that turns screen points into ground points (clicks,
  bubbles → objects, the position estimate) must use the zoom of the zone she is in (`tools/nav/<Area>/zoom.json`,
  learned from exact log evidence).

## Gotchas (verified)
- **Wood/drops count only after pickup** (Space at the bag "+" bubble). When an axe bubble and a pickup bubble overlap,
  the **axe wins**, which wastes a swing: step `walk 0.3` until the "+" bubble is the highlighted one.
- Check progress in the tracker popup or the journal (J), not by counting swings.
- **NPCs walk around.** Space is wasted if they move off mid-bubble. Look first and press when they're stationary.

## Approach a target (any object)
**Click-to-move is the only way to move (L49, L54).** `./wf look`, then `./wf do go:<x>:<y>` with the target's game coords
(look coords ÷ 0.4). The game **pathfinds** (around walls and buildings; she **jumps over low fences**) and Tara stops **in front of a clicked
object with its bubble shown** (well: `bubble@` in the state line); it does NOT interact, so then `./wf do key:space`.
Click the object itself (well, bed, NPC, mushroom) or a ground point next to it. Target must be on screen; for far
places chain `go:` hops (look between). `go:` returns when Tara herself stops (tracker, L52).
- **Fences are no obstacle (user, 2026-10-31):** the game lets Tara jump over the low garden/farm fences, so a click
  on a point or object on the other side of a fence works directly. Gates and arches are **not** needed as hops; don't
  route through them. ⚠️ Not everywhere: D151 a click west of the garden's west fence gave `Player locomotion failed …
  Jump failed while pathfinding` and she stayed inside (loop-live-3). If the log shows that line, click a point on her
  side of the fence or toward a gap.
- The loop (`fill_can()`, `goto_bed(…)`) clicks the target as soon as it is visible (user rule); stuck → it writes `ask-<n>.png` (+ clean `ask-<n>.frame.png`) in the run dir and raises NeedVision (two asks per goal, then Failed). Answer with `./wf py "answer(n, X, Y)"` (a walkable point toward the target) or, when the target is visible but not detected, teach it: `./wf py "label(n, 'Well', x0, y0, x1, y1)"`; then re-run the call. A wrong box → label it as what it really is (`label(n, 'Grass', …)`): rival kinds take the spot from then on.
- **Every object whose bubble is showing is available now.** Several nearby objects can be available simultaneously
  (six adjacent beds were observed). The loop stores each bubble's kind and click point as transient graph-node state;
  `goto_bed()` succeeds on any available bed matching its query rather than walking to a preselected member. Tara is a
  transient graph node with `near` edges to those objects; each edge notes their screen-relative direction
  (`north`, `south-east`, etc.). `./wf py "available()"` lists each active node with its direction, bubble kind and
  exact bubble click point. Bubble ownership is resolved against **all objects in the current region** before the goal
  query is applied (e.g. a beehive bubble remains a hive and cannot satisfy `goto_bed()`).
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
- The object graph stays singular. Nodes that visibly exist on the illustrated map may have optional map examples;
  descendants use their nearest represented ancestor (a bed → Garden, a stove → House). Seed examples from existing
  labelled map points with `./wf graph map-seed .shots/map_full.png`; inspect a saved map with
  `./wf graph map-heatmap <node> <map.png> [out.png]`. Nodes without a map representation return that fact rather than
  inventing a parallel node. The later far/lost navigator can derive a compass direction from Tara's map pin to the
  heatmap peak.
- A target with no bubble from any side is probably decoration. Note it in the quest file and locations.md.

## Energy
Each tool use costs energy ([energy.md](energy.md); `./wf state` shows ⚡N%). **Out of energy** → Tara says "I have no strength left!" (EN ❓) (Space dismisses) and tool use stops. **Default: stop energy work and report / plan sleep; don't eat**
unless the goal needs it the same day (`./wf tips energy`). Early game: about 2–3 logs of chopping per full bar.
