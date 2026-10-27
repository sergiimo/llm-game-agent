# Basic actions & tools

> **Summary:** one interaction model: walk next to the target until its **icon bubble** shows → **Space**. Tools aren't
> equipped by hand; the game uses the right tool for the target (can at a bed, axe at a log/tree, pickaxe at a rock, rod
> at a fishing spot). Tools sit in the inventory section **Tools**. Every tool use costs energy.

| Action | Target / where | Tool | How | Status |
|---|---|---|---|---|
| Plant | empty garden bed (sprout bubble) | seeds | Space → planting panel → seed card → **Select (EN ❓)** | ✅ |
| Fill can | the well (watering-can bubble) | watering can | Space | ✅ |
| Water | planted bed (potato + drop bubble) | watering can | Space (1 fill waters a bed) | ✅ |
| Forage | items on the ground (mushrooms…) | — | **[Approach a target](#approach-a-target-any-object)** → `bubble@` shown → `./wf do key:space` → check `log: … grab_item` + toast/tracker ("Mushroom: 2/2"). A bag "+" bubble can be **another plant** (e.g. Thistle thistle), so check the log/toast before counting | ✅ |
| Talk / give / quest hand-in | NPC bubble | — | wait until the NPC **stands still** and its bubble shows → Space → interaction menu (topic bubbles; the highlighted one + Space). The bubble icon shown *before* Space (e.g. sprout) is just one topic; the quest topic is the icon with **"!"** (highlighted by default) → Space → dialogue/popups → the menu reopens → Esc | ✅ (Wed d3) |
| Sleep | your bed (pink, left room; zzz bubble) | — | Space → "Yes, I suppose (EN ❓)" | ✅ |
| Chop | **fallen logs** (and trees) on the farm, not the decorative pile by the well | axe (Rusty Axe), auto | stand beside the log → **axe bubble** → Space, ~3–4 presses per log (each swing ≈10 game min + energy) → wood + sticks drop on the ground → pick up each with Space at its "+"/bag bubble (free). Tree + log can show 2 axe bubbles: Space chops the top one. Extra Space on a depleted target does nothing | ✅ (Wed d3) |
| Break rocks | rocks/boulders (farm, mine) | pickaxe | expected: same pattern | ❓ |
| Fish | fishing spots (sign with a fish; ripples) | rod (from Bruno) + bait | ❓ | ❓ |
| Eat | inventory | food | `I` → section **Food** → click the item (e.g. Cream of Mushroom Soup) → click **Eat** → count −1, part of the energy restored → Esc ×2. **Only when** a same-day need justifies it (`./wf tips food`) | ✅ (Wed d3) |
| Buy | shopkeeper at the counter, during opening hours | coins | Space at the shopkeeper → coin icon → Space → click the item card → Space ("Buy (1)") → Esc ×2 ([../ui/screens/shop.md](../ui/screens/shop.md)) | ✅ (Wed d3) |
| Open inventory | — | — | `I`; sections incl. Seeds, Tools | ✅ |

## Gotchas (verified)
- **Wood/drops count only after pickup** (Space at the bag "+" bubble). When an axe bubble and a pickup bubble overlap,
  the **axe wins**, which wastes a swing: step `walk 0.3` until the "+" bubble is the highlighted one.
- Check progress in the tracker popup or the journal (J), not by counting swings.
- **NPCs walk around.** Space is wasted if they move off mid-bubble. Look first and press when they're stationary.

## Approach a target (any object)
**Default: click-to-move (L49, verified Thu d4).** `./wf look`, then `./wf do go:<x>:<y>` with the target's game coords
(look coords ÷ 0.4). The game **pathfinds** (around fences, through gate gaps) and Tara stops **in front of a clicked
object with its bubble shown** (well: `bubble@` in the state line); it does NOT interact, so then `./wf do key:space`.
Click the object itself (well, bed, NPC, mushroom) or a ground point next to it. Target must be on screen; for far
places chain `go:` hops (look between) or use a route. `NO MOVE` = not walkable / already there; `STILL MOVING` = long
path, look and continue. Fall back to the keyboard procedure below only if `go:` fails.

Keyboard fallback, verified Wed d3 19:40 (2nd mushroom after an agent spent ~25 calls on blind nudges):
1. `./wf look`. **Tara is the figure near the screen centre** (≈ game 960,600; the camera follows her). Find the target
   and take direction = target − Tara (the larger axis; diagonals `ne/nw/se/sw` exist).
2. `./wf do bubble:<dir>:1.5`. It walks in 0.25 s steps until a bubble shows, then prints `bubble at (x,y)`.
3. **Only press Space when the state line shows `bubble@x,y`.** Space without a bubble does nothing, so never
   alternate tiny walks (`walk:x:0.05`) with Space.
4. `BLOCKED …` (rock, fence, river bank; also on plain `walk:`) → side-step ~0.5 s perpendicular, away from the obstacle,
   `--look` again (the camera re-frames, so the target moves on screen), then approach from that side.
5. `bubble:` stops at the **first** bubble, even an unrelated one (the bed zzz on the way to the stove). Check the bubble's position is at your target; if not, pass it with plain `walk:`. An extra Space while a dialogue is closing can re-trigger the target: close dialogues with `./wf advance`.
6. `NO BUBBLE` with Tara next to the target → approach once from another side. After **3 approaches with no bubble**
   it's decoration: note it and take another target.

What forageables look like on the 0.4 look: **Mushroom** = small grey-brown cap on a pale stem, about Tara's head size,
often next to grey rocks (easy to read as a pebble). **Thistle** = purple flower (also picked with a "+" bubble).

## Finding targets
- Where things are: [../world/locations.md](../world/locations.md) (per-area resources) → quest file notes → map `M` + `./wf look`.
- A target with no bubble from any side is probably decoration. Note it in the quest file and locations.md.

## Energy
Each tool use costs energy ([energy.md](energy.md); `./wf state` shows ⚡N%). **Out of energy** → Tara says "I have no strength left!" (EN ❓) (Space dismisses) and tool use stops. **Default: stop energy work and report / plan sleep; don't eat**
unless the goal needs it the same day (`./wf tips energy`). Early game: about 2–3 logs of chopping per full bar.
