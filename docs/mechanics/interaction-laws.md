# Interaction laws

> **Summary:** four laws (user, D183) for any task that acts on objects. 1. Tara is always at the centre of the
> frame. 2. A click on a visible object is very reliable, so vision's only job at the start is "give the click point of
> the first node". 3. Every click produces feedback (log events, short-lived text, bubble changes, cards), so record it
> right after the click and update state from it. 4. Bubbles guide the next click: click every bubble that fits the task
> until none is left, then go back to 2. No layouts, grids or positions are carried between steps.

Why (L124): the graph-chain runner (spec 2026-11-02 §10) chained four guesses (vision geometry → fitted layout → click
point → camera-shift proof) before the game confirmed anything. Runs 1, B and C each broke on a different link, and the
bad state carried over to the next call. These laws keep one guess per click and let the game confirm it at once.

## Mechanics (what the game does)
| # | Law | Facts |
|---|---|---|
| M1 | **Tara is always at the frame centre** | The camera follows her: she stands at **(960, 540)** in the 1920×1080 frame (`chain_step.CENTRE`), in every area, at every zoom. A screen offset from the centre is her direction and distance to the object (the zoom changes only the scale). Her position never needs to be asked or estimated. |
| M2 | **A click on a visible object reaches it** | The game pathfinds to a clicked object (around buildings, over most low fences) and stops in front of it with its bubble showing. If it is already in reach, the click **interacts** (bed → card, well → fill). A click on open ground only walks. Exception: some fence spots fail (`Jump failed while pathfinding`, D151): click the object from Tara's side. See [basic-actions](basic-actions.md). |
| M3 | **Every action leaves feedback, some only briefly** | Four channels, from most to least lasting: (a) **game log** event lines (`> unplant`, `> unplant_impl`, `> plant`, `totalPlanted.X`, `> water`, `> out_of_water`, `> grab_item`, `> plant_growing`, `> fill_watering_can`), which stay; (b) **cards/panels** (Remove card, planting picker), which stay until closed; (c) **bubble changes** (a bubble vanishes, its icon changes, the water-drop sub-icon goes after watering, a seedling bubble appears after removing), which last until Tara moves; (d) **on-screen text** (pickup notices, short messages), which disappears after about 1–2 s ❓ (to measure). Channels (c) and (d) are lost unless frames are captured right after the click. |
| M4 | **Bubbles show what is in reach and its state** | A bubble appears above every object in reach, several at once; clicking any bubble runs its action, highlighted or not. A crop bubble with a pale-blue **water drop** = needs water **or** wilted; a seedling bubble without a sub-icon = empty bed; the orange "!" sub-icon is not verified yet. Kinds and the drop flag: `affordances.scan()`. |

## Rules (any task: replant, water, harvest, forage, talk)
1. **Never locate Tara.** She is at the centre (M1). Describe everything as an offset from the centre ("the bed
   up-right of her"). Questions never ask "which bed is she at".
2. **First node: vision gives one click point.** If a bubble that fits the task is visible, go to rule 4. Otherwise ask
   vision **one** question on the current frame: *"Give the click point (x, y in the 1920×1080 frame) of the nearest
   <target kind> [that looks <state>]. If none is visible, answer `none` and the direction to walk."* Click that point.
   Vision gives a point to click, never a layout, grid or map of everything. Cheap checks on the answer: inside the
   frame, not on the HUD (clock, map, journal or inventory buttons). `none` → click open ground in that direction, then
   ask again.
3. **Record every click result before deciding anything.** After each click capture: the frame before, a burst after
   (immediately, ~0.5 s, ~1.5 s, settled), the new log lines, the bubbles before/after (`scan()`), and any card or text.
   Update state from it in this order of trust: **log event > card > bubble change > text > vision.** A result that
   none of these explains (no event, no card, no bubble change, no move) → ask vision on the burst frames: "what
   happened after this click?"
4. **Bubble loop.** While a bubble that fits the task is visible: click it (nearest to the centre first), record the
   result (rule 3), update state, repeat. No fitting bubble left → back to rule 2 for the next node.
5. **Failure = reset, not diagnosis.** On anything unexpected: close cards (`ui.close()`), take a fresh frame, go back to
   rule 4 or 2. No stored layout, grid or position survives a failure.
6. **Memory is a hint, never a gate.** The graph and the save say what to look for (save: "4 wilted"; graph: the crop
   last planted in a bed) and when to stop (save count = 0). They never decide where to click and never block a click.
7. **Done** = the save count for the task is 0, or vision answers `none` for the target from a fresh frame and the save
   can't tell. Report the counts before and after.

### Example: replant every wilted bed
`while save says wilted > 0:` drop bubbles visible → click the nearest → the log says `unplant` (wilted: Remove →
same crop → water) or something else (growing/dry: record it, close the card) → next drop bubble. No drop bubble →
vision: "click point of the nearest wilted bed" → click → its bubble or card appears → continue the loop.

## Tool status
| Piece | Status |
|---|---|
| Centre constant, bubble scan with kinds and drop flag | ✅ `chain_step.CENTRE`, `affordances.scan()` |
| Event read after a click | ✅ `chain_step.click_target` (log only) |
| Click-result record (burst frames + bubbles before/after + text) | ❌ to build (rule 3) |
| Vision "click point of the first node" question | ❌ to build; `loop.answer(n, X, Y)` is the nearest existing shape |
| `replant_all()` / `water_all()` / `harvest_all()` on these laws | ❌ to rebuild; today they run the graph-chain runner (A18) |
