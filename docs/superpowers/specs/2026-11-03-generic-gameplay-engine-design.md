# Generic gameplay engine — design

> **Summary:** one loop `achieve(goal)` replaces every task function. The world graph is built from the save, the
> game log and frames (new regions and their objects appear by themselves); actions live in a learned transition table
> (seeded from what we know, filled from play, vision for the rest); goals are queries over node state, from a goal
> library or written by the quest agent. The LLM orchestrates (picks/writes goals, answers questions); the engine
> decides clicks from the table.

Status: approved 2026-11-03 (D185); rev. 2 after the plan review (kinds.json, one state vocabulary, read_card, pending record). Supersedes the task layer of `game/laws.py` (L124–L137).

## 1. Purpose and success
User (D185): "why are you so specific with my tasks? can't come up with generic game play engine?" — and "find a new
garden south of the house and plant all by flowers; this should test adding a new graph node and building a graph of
beds inside that node".

Decisions taken: transition table learned from play (A) + seeded from known actions (B-style) + LLM orchestration;
goals = a library of named chores **and** raw queries the agent writes.

Success:
1. Watering, replanting, harvesting and planting a garden run on **one loop with no per-goal code** (offline fake and live).
2. Planting the south garden: the engine **adds the region node and a graph of its 12 beds** from the save, walks there
   by the graph, plants them — no garden-specific code.
3. A new object kind (e.g. bee hive honey) works by **adding one goal line**; its transitions are learned (vision fills
   the unknown ones once, then they replay).
4. Metric per run: vision calls per goal, clicks per target, surprises; vision calls per goal fall as the table fills.

Kept rules: interaction laws (Tara at centre, a visible object is clicked, every click recorded, bubble loop),
uncertainty → vision, memory is a hint (events > save > frame), stuck = 3 still clicks, stops (clock 23:00–06:00,
non-English UI, LAWS_STUCK), no buying / sleeping without the user, one `./wf` command per call.

## 2. Layers
```
LLM quest agent ── picks a library goal or writes a query; answers NEED_VISION; reports
      │
engine.achieve(goal) ── targets → navigate → transition → verify → repeat (one loop)
      │
plan (table lookup)  nav (reach)  act (click + record)  observe (frame)  learn (graph, table, labels)
      │
world/graph (Farm.json)   actions.json (transitions)   goals.json (library)
```
Existing modules keep their jobs: `observe` (frame only), `act` (one click + full record), `nav` (reach any fitting
node, search order, stuck), `learn` (memory, bubble/object labels, DB settle). New: `world.py`, `plan.py`, `engine.py`.

## 3. World graph (`game/world.py`, data in `objects/graph/Farm.json`)
**Sources, no per-object code:**
1. **Save:** every entity with a position (crops/beds today; any list with `x`/`z` later) → a node of its kind with `pos`
   and its saved state.
2. **Game log:** every `target=Kind at (x, y, z)` line → create/update the node of that kind at that position; its
   event changes its state (via the table's effects).
3. **Frames:** bubbles + detections → the closest node (where she is), objects in view. Look-alike bubbles (beds in two
   gardens) are resolved by the last event's position.
4. **Seeded:** nodes without positions (House, Well, Bed …) and hand-taught directions, marked `source: seed`; learned
   values replace them.

**Structure derived:** nodes of one kind are clustered by position (gap 6 units). A cluster inside no known region →
new region node `<Area><Compass>` (e.g. `GardenSouth`: kind of the area, compass from the nearest known region), a
group node `<Kind>@<Region>` with a grid pattern, one member per object (`#r<row>c<col>`, rows north→south), `next_to`
edges with screen directions. Directions between any two nodes: learned `toward` edge → else from their positions
(camera looks north: world +x = screen right, +z = screen up) → else unknown (nav explores).

**Kinds as data** (`game/kinds.json`, review rev. 2): per kind its save list and field → state map, clustering gap,
area name stem, frame markers (`watered=false` → dry soil), and nodes for position-less kinds. No kind names in code.

**State** = key/value per node, one vocabulary: `stage` (`empty|growing|producing|produced`), `watered`, `wilted`,
`ready`, `crop` (from cards/events only: the save has no crop type), `Tara.can` (hint only), each with `source` (event > save >
frame) and game time. Queries read it; `beds_left` generalises to `count(query)` = save state minus today's log events
by position.

## 4. Transition table (`game/actions.json`, replaces `chains.json`)
One row per action an object offers:
```json
{"kind": "GardenBed", "when": {"plant": "empty"}, "bubble": {"kind": "plant"},
 "steps": [{"do": "click_bubble"},
           {"do": "pick_card", "arg": "$seed", "expect": {"card": "Seeds"}},
           {"do": "press", "arg": "Select", "expect": {"events": ["plant"], "log": "totalPlanted"}}],
 "effect": {"plant": "$seed"}, "needs": {"item": "$seed Seed"},
 "source": "seed: game D148", "seen": 0, "ok": 0, "surprises": 0}
```
- **Step primitives** (the only code per step type): `click_bubble`, `click_object`, `press <label>`, `press_space`,
  `pick_card <name>`, `close`, `read_card` (stores the card's first line into a state key, e.g. `crop`).
- **`bubble`** = `{kind?: "a|b", drop?: bool, ready?: bool}` or null for an event-only row (`out_of_water`). Each step's `expect` is checked like chains are today (events, card, bubble, text) and
  feeds surprises / gaps / revisions.
- **`needs`** = a precondition on another node (Tara's can full, an item in the inventory). A failed need observed in
  the log (`out_of_water`) becomes a learned effect (`Tara.can = empty`) and the planner adds a sub-goal (`Well`
  → can full) from the table itself.
- **Seeded rows** (B): water a dry bed; out_of_water; fill can at the well; wilted → Remove (Space, confirm) → empty;
  empty → plant seed; pick ripe; plant_growing (info card, no change). Each marked `source: seed`.
- **Learned rows:** a click on a bubble with no matching row is recorded (bubble kind + sub-icons → steps taken →
  events → state diff) as a new row with `seen 1`; it is trusted after 2 agreeing sightings (the gap rule).
- **Sub-icons decide meaning**, not crop icons: drop = needs water or wilted; "!" = ready (never a reason to act by
  itself); bubble kinds are learned labels.

## 5. Goals (`game/goals.json` + raw queries)
A goal = `{kind, where, make, params, order?, limit?}`:
```json
"water":   {"kind": "GardenBed", "where": {"stage": "growing|producing", "watered": false, "wilted": false}, "make": {"watered": true}},
"replant": {"kind": "GardenBed", "where": {"wilted": true}, "make": {"crop": "$same", "watered": true}},
"plant":   {"kind": "GardenBed", "where": {"region": "$region", "stage": "empty"}, "make": {"crop": "$seed"}, "required": ["seed", "region"]},
"harvest": {"kind": "GardenBed", "where": {"ready": true, "crop": "$crops"}, "make": {"ready": false}, "required": ["crops"]}
```
- **Library** entries are what the agent uses for chores (`./wf achieve plant region=GardenSouth seed=Tulip`).
- **Raw queries**: the agent writes the same shape (`./wf achieve '{"kind": "BeeHive", "where": {"ready": true},
  "make": {"ready": false}}'`). `./wf world kinds` prints the catalogue the agent picks from: kinds, their state keys
  and values seen, regions, known transitions per kind.
- `$same` = keep the crop read from the object (replant); `$crops` = an explicit list, no default (open question 1).

## 6. The loop (`game/engine.py`)
```
achieve(goal, answer=None):
  stops (clock, language) → world.refresh (save + today's log; new regions/objects appear)
  targets = query(goal) ; if none → DONE (summary)
  path = plan.path(kind, state(target), goal.make)       # table BFS, ≤ 3 transitions (wilted → empty → planted → watered)
  if no path → explore_transition(target) or NEED_VISION ("what does this object's bubble do?")
  t = path[0] ; unmet needs → sub-goal first (refill …)
  bubble = nav.reach(fits = t.bubble on a node of `kind` in the target's region)   # bubble loop: any fitting target, nearest
  run t.steps (act.click / ui) ; verify effect by events → else surprise, close cards, continue
  learn (state, table counts, graph directions, labels) ; repeat
```
- **Any fitting target** is fine (no particular member): the bubble that fits the next transition in the target region is
  clicked; its event position says which bed it was and updates that member.
- **Done = the query is empty** (save + today's log + events this call). No per-goal stop rules.
- Navigation as now (`nav.seek`): closest node → graph/position direction (+ heading between areas) → marked targets
  (dry soil for `watered: false`, a learned "marker" per state key) → vectors → explore free ground inside the region /
  map outside → stuck → one vision question with the trace.

## 7. LLM orchestration
- The quest agent picks a library goal or writes a query, calls `./wf achieve …`, and gets either a summary
  (`done N, left 0, clicks, vision, surprises, learned rows`) or `NEED_VISION <kind>` with a framed PNG:
  `click` (a grid cell: the next node / free ground), `button` (which on-screen text to press next), `name` (what an
  unknown icon/card is). It answers by calling again with `answer=…`.
- The question's context is kept as a **pending record** (`{kind, goal, params, row, step, bubble}`) so the answer
  lands on the right row/step (`game/ask.py`).
- **Every answer is stored as data**: a click cell becomes a step/target, a button a step, a name a label. The next
  time the engine replays it without asking (A = C with memory).
- The agent reports learned rows and surprises as `[docs]` gaps; the supervisor reviews `actions.json` diffs.

## 8. Learning (`game/learn.py`)
Per click/step: bubble kind from the next event; object relabel when the game proves a detection was another kind;
member state from events by position; table counts (`seen/ok/surprises`); new rows from unmatched clicks; gaps filled
after 2 agreeing observations, expectations revised after 3 agreeing contradictions (`settle_db` after each run);
`toward` directions that reached their node.

## 9. Errors and stops
Unknown → vision (never a guess); a step whose expectation fails → surprise, close cards, re-plan from fresh state;
missing item → stop (never buy); no seeds/can → sub-goal or stop; clock/language/LAWS_STUCK as now; per-call click cap.

## 10. Migration (what changes)
| Now | Then |
|---|---|
| `laws.TASKS`, `DONE_ON`, `_handle`, `_replant`, `_plant`, `_fill_can` | `goals.json` + `actions.json` rows + `engine` |
| `garden.water_all / replant_all / harvest_all / plant_all / discover` | thin wrappers: `achieve('water')` … (kept for agents/docs) |
| `chains.json` / `chains.py` | `actions.json` (rows carry `steps[].expect`); `chains.py` gap/revise logic moves to `learn` |
| `objects/graph.TOWARD`, `NODE_OF`, `CROP_KINDS`, `BED_STATE_OF`, `wf.DONE_AT` | seeded graph edges / table effects / learned labels |
| `wf.beds_left` | `world.count(query)` (save state minus today's events by position) |
| `observe`, `act`, `nav`, `learn` | kept (nav gets `marker` per state key instead of `soil=True`) |

## 11. Testing
- A **data-driven fake game**: objects with kind, position, state, bubbles, and transitions read from a fake table — the
  same fake runs every goal. Acceptance: water / replant / harvest / plant-south pass with no per-goal code; a BeeHive
  goal passes after one fake vision answer and then without it.
- Unit: clustering → regions/groups/members/edges; query + count from save + log; plan BFS; step runner with expects;
  learning a new row; needs → sub-goal (can).
- Live (one plan, reused while testing): plant the south garden with tulips (12 beds, 18 TulipSeed): region node added,
  beds graph built, all 12 planted, vision calls ≤ 2.

## 12. Open questions
1. Harvest default: which crops are collected and which are left for the bees? (Until answered, `crops` must be given.)
2. Does the save list other positioned entities (hives, trees, fences) to seed more of the graph? To check in the save.
3. Region names: `GardenSouth` style (compass from the nearest known region) — OK, or should the agent/user name them?
