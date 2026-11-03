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
2. **First node: see → map → step, then vision (user D185).** If a bubble that fits the task is visible, go to rule 4.
   Otherwise, at most `SEEK_TURNS` (6) rounds: (0) an **unknown bubble** not tried yet → click it once: its event labels
   it (`wf.learn_bubble`, gap filling for bubble kinds); (1) **graph**: the last event's target says which node she is at
   (`target=Well` after a refill, `target=BeeHive` after a hive click) → the graph's screen direction from that node to the
   target node (`graph.toward`, edges `toward` or `TOWARD` defaults: Well → hives → beds) → a step; (a) **see** the target node by its appearance vectors (`objects/db/<kind>`,
   e.g. GardenBed) on the frame → click the nearest match (not the one under Tara; a match whose click names another node,
   e.g. a hive, is never clicked again this call) → rule 4; (b) not seen and **inside the target's region** (her last event named a node of the Garden: a bed, a hive, the well) →
   **explore**: the map has nothing finer here (like inside a house), so click **free ground** (away from every bubble and
   detected object) in a direction not tried yet this call, 300 px out, to bring more nodes into view; (b') outside the
   region → **map**: open
   it, Tara's pin + the node's map picture (`objects/map_db`, e.g. MapGarden) + the road route between them give a
   direction → (c) **step**: click 320 px from the centre in that direction (camera looks north like the map); she didn't
   move → turn ±35°, then a shorter step → back to rule 4. A step or explore click that an object takes (it logs that object's event, e.g. `beehive_progress`) is
   **blocked**, never progress. Every try goes into a trace; only when these give nothing, ask vision **one** question
   on the current frame, with the trace, so vision **debugs the algorithm** (what blocked it) and answers a cell of free
   ground around the blocker, or the target: *"Give the click point (x, y in the 1920×1080 frame) of the nearest
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

## Actions DB as chains (user, D183)
Each game function is a chain of steps; each step = an action and the result it should leave on screen. The DB is
`tools/game/chains.json` (code: `game/chains.py`): per step `events` (log event types), `card` (text on the card/panel
that opens, `null` = stays in gameplay), `bubble` (the clicked object's bubble after: `gone | plant | drop | no-drop | same`),
`text` (short-lived message, OCR'd from the burst frames) and its `source` (game day, wiki). `"?"` = a gap.
- Every recorded click is checked against its step (`laws.record_click(..., chain, idx)`, or by its event for bubble-loop
  clicks): a mismatch is a **surprise** (run summary `surprises`, run log `click` row); every field goes to
  `tools/game/observed.jsonl`.
- **Gaps fill from the game:** `./wf py "from game import chains; chains.gaps()"` lists each gap with what was seen;
  `chains.gaps(apply=True)` writes a value once **2 observations agree** and none differ (never from one sighting). The
  wiki has no UI-level detail for beds (Garden Bed page: only "water each day, 4 crops"), so the game is the source.
- A new function adds its chain to the DB first (steps + what is known, `?` for the rest), then passes `chain`/`idx` to
  `record_click`.

## Tool status
| Piece | Status |
|---|---|
| Centre constant, bubble scan with kinds and drop flag | ✅ `laws.CENTRE`, `affordances.scan()` |
| Click-result record (burst frames + new log lines + bubbles before/after + screen + burst OCR) | ✅ `laws.record_click` → `Click` (run log `click`, frames in `<run>/clicks/`) |
| See → map → step before vision (`laws._seek`: `_see` detect, `_map_direction` map pin + MapGarden + road route, `_step`) | ✅ offline tests `Seek`; map direction checked on `.shots/map_last.png`; live check pending |
| Vision "click point of the next node" (one grid cell) | ✅ `NEED_VISION click` (`wf.ask_vision('click', …)`), answer `click='Q14'`; `LAWS_STUCK` after 4 asks without progress |
| `replant_all()` / `water_all()` / `harvest_all()` on these laws | ✅ `game/laws.py` (offline tests `tools/test_laws.py`); live check pending |
| Actions DB as chains, surprises, gap filling | ✅ `game/chains.py` + `chains.json` |
| Graph memory (law 6): per group today's tally per event (removed/planted/watered/harvested/growing_seen/can_ran_dry), crops grown, last event, the can; read back as a hint in the vision question | ✅ `objects/graph.note_click` / `hint`, fed by every recorded click and press; saved in `graph/Farm.json` |
| Old graph-chain runner (anchor question, layout fit, camera-shift proof, `./wf anchor`) | ❌ removed (L124) |
