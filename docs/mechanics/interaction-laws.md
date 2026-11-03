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
| M4 | **Bubbles show what is in reach and its state** | A bubble appears above every object in reach, several at once; clicking any bubble runs its action, highlighted or not. A crop bubble with a pale-blue **water drop** = needs water **or** wilted; a seedling bubble without a sub-icon = empty bed; **only the drop means "needs water"** (a crop icon without it — tulip, bean — is never clicked to water); the orange **"!"** sub-icon (top right, `Affordance.ready`) = its product is **ready to collect, not an order to collect** (flowers serve the bees; collect only when the task says so). Kinds, drop and ready flags: `affordances.scan()`. **Soil (user D185):** light-brown bed soil = needs water, dark brown = watered (median grey of soil pixels ≥ 88 dry, ≤ 80 wet, daylight; `affordances.soil_map` / `dry_spots`, a heat map of dry soil on the frame). |

## Rules (any task: replant, water, harvest, forage, talk)
1. **Never locate Tara.** She is at the centre (M1). Describe everything as an offset from the centre ("the bed
   up-right of her"). Questions never ask "which bed is she at".
2. **First node: see → map → step, then vision (user D185).** If a bubble that fits the task is visible, go to rule 4.
   Otherwise, at most `SEEK_TURNS` (6) rounds (a bubble without the task's sub-icon is never clicked; bubble kinds are
   learned from the bubbles the task does click, `wf.learn_bubble`): (1) **graph**: the last event's target says which node she is at
   (`target=Well` after a refill, `target=BeeHive` after a hive click) → the graph's screen direction from that node to the
   target node (`graph.toward`, edges `toward` or `TOWARD` defaults: Well → hives → beds) → a step; (1b) **water: dry soil** → walk to the nearest light-brown blob of the soil heat map (`dry_spots`; it also sees
   beds behind the hive row); (a) **see** the target node by its appearance vectors (`objects/db/<kind>`,
   e.g. GardenBed) on the frame → click the nearest match (not the one under Tara; a match whose click names another node,
   e.g. a hive, is never clicked again this call) → rule 4; (b) not seen and **inside the target's region** (her last event named a node of the Garden: a bed, a hive, the well) →
   **explore**: the map has nothing finer here (like inside a house), so click **free ground** (away from every bubble and
   detected object) in a direction not tried yet this call, 300 px out, to bring more nodes into view; (b') outside the
   region → **map**: open
   it, Tara's pin + the node's map picture (`objects/map_db`, e.g. MapGarden) + the road route between them give a
   direction → (c) **step**: click 320 px from the centre in that direction (camera looks north like the map); she didn't
   move → turn ±35°, then a shorter step → back to rule 4. A seek click is a **walk** only when the burst frames show she moved (a bubble set that changes while she stands still
   is flicker), or its event is on the **target** node (a step toward the beds that lands on a bed = arrived, back to
   rule 4). **Stuck = 3 seek clicks in a row without either** (and no task work): stop clicking, vision gets the trace.
   A step or explore click that another object takes (it logs that object's event, e.g. `beehive_progress`) is
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
7. **Done** = beds left for the task is 0 (`wf.beds_left`: the save minus today's log, by position, L136), or vision answers `none` for the target from a fresh frame and the save
   can't tell. Report the counts before and after.

### Example: replant every wilted bed
`while save says wilted > 0:` drop bubbles visible → click the nearest → the log says `unplant` (wilted: Remove →
same crop → water) or something else (growing/dry: record it, close the card) → next drop bubble. No drop bubble →
vision: "click point of the nearest wilted bed" → click → its bubble or card appears → continue the loop.

## Framework: observe → act → learn → nav, goals on top (L134, L138: the generic engine)
| Module | Job | Never |
|---|---|---|
| `game/observe.py` | Read the frame: bubbles (kind, `drop`, `ready`), soil heat map, **the closest node** (where she is), detections, screen mode/texts, clock + light, language | act; carry anything between frames |
| `game/act.py` | One click + its full record (`Click`: burst frames, moved, log events, the event's node and position, bubbles before/after, screen, short-lived text); close cards | decide |
| `game/world.py` + `kinds.json` | **The world graph** from the save (every positioned object; kind by `save_has`, or named by a log event on it), today's log (`target=Kind at (x, y, z)`, newer than the save wins) and click results. **Places are grouped only by distance** (areas over objects of every kind: `Garden` = 12 beds + 8 hives, `GardenSouth` = 12 beds); kind and state are filters (`query`, `count`) | group by kind |
| `game/plan.py` + `actions.json` | **The transition table**: per action `when` / `bubble` / `steps` / `effect` / `needs`, seeded (water, fill_can, remove_wilted, plant, pick, out_of_water) + learned; `path` = BFS over effects | use a learned row before 2 agreeing sightings |
| `game/steps.py` | Run a row's steps (click_bubble, press, press_space, pick_card, read_card, close) with checked expectations; every field observed (`observed-steps.jsonl`) | — |
| `game/ask.py` | The ONE vision question (`click` cell / `button` / `name` key=value) with a pending record; the grid; the clock stop; LAWS_STUCK after 4 | guess |
| `game/learn.py` | Memory hints; bubble kinds from the event after a click; object looks relabelled; **new rows from play** (frame change / event / vision's name) and `settle_rows` (gaps after 2 agreeing, revisions after 3 agreeing contradictions); graph directions that reached their node | gate a click (law 6) |
| `game/nav.py` | `search` / `seek`: any bubble that fits — the area known from the last event (look-alike beds), else the closest node → graph/position direction; marker (dry soil); vectors; explore free ground inside the area / map outside; stuck after 3 still clicks; the trace | click a bubble without the target's sub-icon |
| `game/engine.py` + `goals.json` | `achieve(goal, answer=None, **params)`: refresh → targets (filter) → nearest → path → needs (missing item = stop; can = sub-goal from the table) → nav in the target's area → steps → events update the world → done = filter empty. Missing required params → `NEED_INPUT` with the values seen | goal or kind names in code |
A new chore = one goal line (`{kind, where, make}`) or a raw query; an unknown bubble is learned once and replayed.

## Tool status
| Piece | Status |
|---|---|
| Centre constant, bubble scan with kinds and drop flag | ✅ `laws.CENTRE`, `affordances.scan()` |
| Click-result record (burst frames + new log lines + bubbles before/after + screen + burst OCR) | ✅ `laws.record_click` → `Click` (run log `click`, frames in `<run>/clicks/`) |
| See → map → step before vision (`laws._seek`: `_see` detect, `_map_direction` map pin + MapGarden + road route, `_step`) | ✅ offline tests `Seek`; map direction checked on `.shots/map_last.png`; live check pending |
| Vision "click point of the next node" (one grid cell) | ✅ `NEED_VISION click` (`wf.ask_vision('click', …)`), answer `click='Q14'`; `LAWS_STUCK` after 4 asks without progress |
| `./wf achieve <goal> k=v [answer=X]`; `water_all` / `replant_all` / `harvest_all(crops)` / `plant_all(seed, region)` = one-line goals | ✅ `game/engine.py` (offline `tools/test_engine.py`); live: south-garden planting (Task 9) |
| Transition table, surprises, gap filling, revisions, learned rows | ✅ `game/plan.py` + `actions.json`, `learn.settle_rows` (chains.json removed, L138) |
| World graph (areas by distance, filters, `./wf world kinds|nodes`) | ✅ `game/world.py`, `kinds.json` |
| Graph memory (law 6): per group today's tally per event (removed/planted/watered/harvested/growing_seen/can_ran_dry), crops grown, last event, the can; read back as a hint in the vision question | ✅ `objects/graph.note_click` / `hint`, fed by every recorded click and press; saved in `graph/Farm.json` |
| Framework split (observe / act / learn / nav, goals in the engine) | ✅ L134/L138, tests `test_laws` (Framework, Reach, Record, Points), `test_engine` (Nav, Loop, Learning) |
| `nav.reach(fits, kind=…)` (also `laws.reach`): the low-level navigation — any node of a kind whose bubble fits (the same search), returns the bubble, doesn't click; replaces `goto_bed` (L133) | ✅ offline tests `Reach` |
| Old graph-chain runner (anchor question, layout fit, camera-shift proof, `./wf anchor`) | ❌ removed (L124) |
