# Agent system refactor: integrated world model, skills, questions, eval

> **Summary:** replace the separate, fragile pieces of the Wylde Flowers toolkit (straight-line navigation, save readings
> after most walks, pixel heuristics as triggers, a 3,700-line `wf.py`) with one integrated **world model** (scene
> graph + per-area costmap + a belief about Tara's position), **skills** that only query and act through it, one
> **question protocol** to the agents (the only LLM), and an **eval system** that counts hits and misses of every
> prediction. Built alongside the old code and swapped in area by area, judged by a fixed benchmark; every replaced
> part is listed in a removal ledger.

Status: design, 2026-10-30. Supersedes the navigation parts of `2026-10-29-nav-learning-loop-design.md`.

## 1. Goal, constraints, success

**Goal** (AGENTS.md): agents pass quests from minimal docs; gaps get filled. The refactor serves that by making
movement and interaction reliable and measurable, so agent time goes to quest decisions, not to fighting the tools.

**Constraints**
- Only the `./wf` daemon can capture the screen (L71). Mouse-only movement (L54). The game stays in front and its
  clock runs between calls (L47, L63). Python 3.12 in `.venv` (uv).
- **No LLM API in the tools.** The LLM is only the agents (supervisor, quest agent), as coordinator and supervisor.
  Tools never guess past their evidence: they ask (section 6).
- Offline tests before live use; the first live use of anything new is a small plan step for the quest agent
  under supervision (memory: supervise-dont-drive).
- The process layer stays: plans in `runs/<ts>-<task>/plan.md`, progress, escalation, stuck retros, stuck ledger.

**Success** = the benchmark (section 7.2), run before (baseline) and after each migration step:
- 0 user interrupts and 0 unresolved stuck episodes per benchmark task;
- calls, game minutes and agent thinking time per bed / per trip below targets set from the baseline;
- the eval hit rates (section 7.1) at or above their thresholds.

## 2. Architecture

```
 Agents (LLM): supervisor ─ coordinates, plans, reviews, retros
               quest agent ─ follows plan.md, answers tool questions, escalates
        │  ./wf CLI (commands)          ▲ answers: ./wf answer <id> <value>
        ▼                               │ questions: ASK <id> <kind> … (structured, with an annotated image)
 ┌──────────────────────────── daemon (only process that can capture) ────────────────────────────┐
 │ skills/      medium game functions: walk, replant, water, talk, sleep …  (@action: proof + track)│
 │   │ query / act                                                                                  │
 │ world/       scene graph (areas, entities, exits) · costmap per area · Tara belief · view       │
 │   ▲ observe(evidence)                                                                            │
 │ runtime/     sources → evidence: game log · save · screen · own inputs;  actuators: click, key…  │
 │ ask/         the question protocol: open questions, answers, learned rules                      │
 │ eval/        every prediction + its outcome → hits / misses per component; benchmark runner     │
 │ track/       runs: plan.md, log.jsonl, progress.md, waits, stuck rule, escalation               │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Rules:
- **One direction of data:** sources → evidence → world → skills → actuators; proofs and prediction outcomes →
  eval and track.
- **Game files are the main ground truth** (log lines, the save). The screen is supporting evidence; anything
  uncertain on screen becomes a question, never a guess.
- **Small packages with one job each**, each with offline tests (fake game, recorded log lines, saved screens).
  `wf.py` keeps only the CLI and daemon wiring.

### 2.1 Open-source pieces

| Library / pattern | Where | Used for |
|---|---|---|
| `networkx` (scene-graph pattern of Hydra/Kimera) | `world/graph.py` | areas, places, entities, exits as one graph; A* between areas |
| Nav2 `costmap_2d` pattern, in numpy (no ROS) | `world/costmap.py` | per-area grid with layers: solid, walls, refused, walked, inflation |
| grid A* (own ~40 lines of numpy, or `pyastar2d`) | `world/costmap.py` | paths within an area around obstacles |
| `filterpy` (the `robot_localization` / EKF pattern) | `world/belief.py` | Tara's position + uncertainty; readings only when needed |
| Mineflayer shape (`bot.world`, `pathfinder` goals, skill plugins) | overall layout | one shared world state; `walk(goal)`; skills as plain functions |
| Voyager pattern (a growing skill library) | `skills/`, `ask/` | agents add / fix skills and rules; answers become stored rules |
| `py_trees` / HTN planners | not now | plans in markdown cover it; a later option |

New dependencies: `networkx`, `filterpy` (pure Python / numpy). Grid A* is our own unless it proves slow.

## 3. World model (`world/`)

**Entities** (`entities.py`): one record per thing, whichever source told us about it.
```
Entity(id, kind, area, pos(x, z), size r, solid | walkable, uses=[water, plant…], state={…},
       sources=[(src, t, evidence)], confidence)
```
Sources: the save (beds/crops, inventory), game-log lines with a position (hives, well, NPCs, doors), scene changes
(exits, anchors), learned places, docs (shop hours, schedules). Same kind + same area + within 0.5 units = the same
entity; sources merge; `explain(id)` shows them, so a wrong entity can be traced and removed.

**Scene graph** (`graph.py`, networkx): nodes = areas, places, entities, exits; edges = contains, connects (exits),
walkable route (proven trail), each with cost and evidence. Routes between areas = A* on this graph.

**Costmap per area** (`costmap.py`): numpy grid, 0.5 units per cell, layers:

| Layer | From |
|---|---|
| solid | solid entities by size (hives, well, house) |
| walls | stuck / blocked points with the walking direction |
| refused | refused clicks (fade after 1 game hour) |
| walked | cells she really crossed (cheaper) |
| inflation | a margin around solid cells |

Within an area: grid A* → waypoints a screen hop apart.

**Tara's belief** (`belief.py`, filterpy): area, (x, z), uncertainty, entity in reach, moving or not.

| Event | Effect |
|---|---|
| our click | predicted move (calibration); uncertainty grows |
| log line with her position or an entity she used | exact (≈ 0) |
| bubble of a known entity in reach | near that entity, small uncertainty |
| tracker: stopped / didn't move | corrects the prediction |
| save reading | exact; only when `needs_fix()`: uncertainty > 3 units, or the end of an off-screen walk |

**View** (`view.py`, calibration per area): `on_screen(e)`, `click_point(e)` (the visible part of the target, or its
approach cell when a solid entity in front covers it: the hives-over-bed case, S12), `screen_cells()` for question
images.

**Queries** (skills use only these): `where(id | name)`, `tara()`, `in_reach()`, `route(goal)`, `needs_fix()`,
`entities(kind=…, state=…)`, `explain(id)`.

**Persistence:** event logs stay the truth (`tools/nav/facts.jsonl`, the game log, `ask/` answers); the world
rebuilds from them on start, caches per area (`tools/world/<Area>.json`), updates live via `observe()`.

## 4. Runtime (`runtime/`)

| Source | Evidence | Notes |
|---|---|---|
| `log.py` (one reader of the game log) | player actions with entity + position, pathfinding failures, stuck positions, scene changes, quest / stats / inventory, pollen, clock | the main ground truth; one pattern table, each pattern tested on real lines |
| `save.py` | crops / beds, inventory, money, exact position on demand | readings only when the world asks |
| `screen.py` | mode, texts, bubble location + highlight, Tara moving / stopped | reports confidence; low confidence → a question |
| `inputs.py` | our clicks and keys, time-stamped | dead reckoning, refused-click evidence |

Actuators (`act.py`): `click`, `key`, `focus`, `pause` / `resume` (checks the mode before and after; no blind Escape),
`wait_settle`. The only code that touches the game.

## 5. Skills (`skills/`) and `walk`

- Medium-size functions by area of play (garden, well, home, people, shops, ui), as in `tools/game/` today (L77):
  each walks, answers its own confirmations, **proves** the result from the log (line at the target's position),
  and is tracked (`@action`: args, time, screen, result, nested tree).
- **`walk(goal)`**, one entry point, mode by distance and evidence:

| Mode | When | How | Save reading |
|---|---|---|---|
| in reach | the target's bubble is up | nothing | no |
| on screen | `view.on_screen(target)` | click `view.click_point(target)`; the game pathfinds | no |
| same area | off screen | costmap A* waypoints, one click per hop | only if `needs_fix()` |
| other area | another scene | graph route; exits give free anchors | only if `needs_fix()` |

- **Stuck rule** (user, L75): position changes < 2 units over 3 moves while not at the goal; a refused click is a
  move without progress (L82); checked on every move, inside long calls (L80). On stuck: `ask step` (section 6);
  after 2 unhelpful answers the agent escalates.

## 6. Question protocol (`ask/`): the bridge to the LLM

- A tool that can't decide **stops** and prints `ASK <id> <kind>: <question>` with the goal (task, plan step,
  target), the context (Tara's belief, what was tried), and an **annotated image** (roads, walked cells, walls /
  refused clicks, route, entities, coordinate ticks; L74).
- Kinds: `step` (next click toward a goal), `menu` (which menu / which button), `pick` (which card / item), `confirm`
  (is this the right target), `place` (where is X), `decide` (a choice for the plan: escalates to the supervisor).
- The agent answers `./wf answer <id> <value>`; the tool applies it, checks the outcome, and **stores it as a rule**
  only if it worked: menu signature → button, item icon → name (L78), screen situation + goal → step, place → pos.
  The same situation never asks twice.
- Rules carry sources and hit / miss counts (section 7); a rule that misses twice is dropped and asks again.
- `NEED_VISION …` / `./wf teach …` become this protocol (kept as aliases during migration).

## 7. Eval (`eval/`)

### 7.1 Hits and misses of every prediction
Each component records `predict(component, what, value)` and later `outcome(id, value)`; the eval scores it:

| Component | Prediction | Outcome from |
|---|---|---|
| belief | Tara at (x, z) ± u | the next exact fix (log / reading) |
| view | click point visible / reachable | the click moved her vs refused / hit another entity |
| costmap / route | waypoint reachable | arrived vs blocked |
| screen | mode / menu id / bubble kind | the next log line / answer |
| skills | action done | its proof line |
| stuck rule | stuck / not stuck | the agent's answer moved her or not; user "stuck" = a miss |
| ask rules | rule applied | the outcome after applying it |

`./wf eval` = hit rate per component and per area, trend per day, the worst misses with evidence. Thresholds per
component (e.g. belief within 1 unit ≥ 90 %, click point ≥ 95 %) are set from the baseline.

### 7.2 Benchmark (run in this order)
| Task | From → to | Measures |
|---|---|---|
| A. Garden day | wake in the house → replant wilted beds, water all, back to bed | calls, game min, thinking s per bed; stuck; interrupts |
| B. Trips | house → garden → well → ranch → town fountain → home | per leg: calls, game min, readings, stuck |
| C. NPC + menus | find Violet's shop, talk to her | questions asked, answers that worked, calls |

`./wf bench <A|B|C>` writes a run directory like any task (plan, progress, waits, eval), so results compare by number.
The **baseline** = today's toolkit on A and B before any migration step.

**Baseline (2026-10-30, toolkit b74b0c9 + the S13/S17 click guard; `tools/bench/results.jsonl`)**

| Task | Calls | Game min | Save readings | Stuck (real) | Escalations | Done | Eval |
|---|---|---|---|---|---|---|---|
| A garden day | 21 | 110 | 25 | 4 (1) | 1 | 3 of 5 beds replanted, 0 watered; step 2 of 4 | belief 6 % (1/18), skills 0/6, click 81 %, stuck 25 %, ask 2/2 |
| B trips | 25 | 110 | 13 | 1 (0) | 2 | legs 1–2 of 6; leg 3 never left the Farm | belief 27 % (3/11), click 73 %, stuck 0/1, ask 1/1 |

Causes are in the stuck ledger (S13–S18) and the runs' retros. Thinking time is not comparable yet: the gaps include
supervisor fixes between escalations (B: 1,303 s); `waits` must skip gaps around escalations (fix in M3).

**Targets for M3 (proposed; to be confirmed by the user)**

| Measure | A garden day | B trips |
|---|---|---|
| finished | all steps | all 6 legs |
| user interrupts / unresolved stuck | 0 / 0 | 0 / 0 |
| calls | ≤ 2 per bed (A: ~4 per bed now) | ≤ 4 per leg |
| save readings | ≤ 2 for the whole task | ≤ 1 per leg |
| stuck alarms that are false | 0 | 0 |
| eval belief (within 1 unit) | ≥ 80 % | ≥ 80 % |
| eval click moved her / skills proved | ≥ 90 % / ≥ 90 % | ≥ 90 % / — |

## 8. Orchestration (exists, kept)
Plans per task (L76), progress with timestamps, escalation, stuck retros against `retros/stuck-ledger.md`, one game
command per call, supervisor plans and reviews, the quest agent plays. New: plans reference skills and `walk`; the
`ask` protocol is in the agent's manifest; `./wf eval` is part of every debrief.

## 9. Migration (grow alongside, then remove)

Each step: its own implementation plan, offline tests, a small live step for the quest agent, the benchmark, then
its removals.

| # | Step | Benchmark gate |
|---|---|---|
| M0 | `eval/` + `bench` + baseline (today's code) | baseline numbers recorded |
| M1 | `runtime/log.py`, `save.py`, `act.py` (sources and actuators, wrapping today's functions) | no regressions on A |
| M2 | `world/` entities + graph + costmap + belief + view, fed by M1 | eval: belief and click-point rates measured |
| M3 | `walk()` on the world model; skills move to `skills/` and use only world queries | A and B ≥ baseline, targets met |
| M4 | `ask/` protocol and rule store; menus catalogue; question images from `view` | C runs with questions answered once |
| M5 | removals (ledger below), `wf.py` reduced to CLI + daemon | all of A, B, C at target |

## 10. Removal ledger

| Old | Replaced by | Remove when | Status |
|---|---|---|---|
| `go_world` straight hops, side-steps, `detour`, `HOP_BOX` clamping | `walk` + costmap A* + `view.click_point` | M3 gate | open |
| `goto_point`, `graph_route`, `run_route`, `map_walk` (map compass) | `walk` (graph + costmap); map only as a compass for unknown areas | M3 gate | open |
| `checkpoint()` readings after most walks | belief + `needs_fix()` | M3 gate | open |
| `nav.py` place / trail / back-link / wall functions | `world/graph.py`, `world/costmap.py` | M3 gate | open |
| `tools/nav/objects.json` | world entities | M2 gate | replaced in shadow by `tools/world/entities.json`; remove at M3 (still read by the old planner) |
| road colour masks, `road_colors.json`, `to_road`, `fill_pin`, coverage matrix, `improve` | costmap walked layer; map pins only on demand | M3 gate | open |
| bubble kind as an action trigger (`act:<kind>`) | log proofs; bubble kind = advisory evidence | M3 gate | open |
| `NEED_VISION` / `teach` (`road`, `next`, `step`) | `ask/` protocol | M4 gate | open |
| substring OCR menu handling in skills | menu catalogue + `ask menu` | M4 gate | open |
| `track_point` / `track.json` stuck tracker | belief-based stuck rule in `world/` + `track/` | M3 gate | open |
| `tools/game/` (current skills) | `skills/` on the world model | M3 gate | open |
| keyboard route remnants (`routes/*.txt`, disabled `walk:`/`path:`/`route:`) | — | M5 | open |
| the bulk of `wf.py` (input, capture, OCR, nav, runs) | `runtime/`, `world/`, `track/`; `wf.py` = CLI + daemon | M5 | open |

A step is not done while one of its ledger rows is open.

## 11. Testing
- Offline: fake game (as `tools/test_game.py`), recorded log lines per pattern, saved screens per menu / bubble,
  a costmap / A* suite with the hive-row layout, belief filter cases (drift, fixes, needs_fix).
- Live: first use of each step = a small plan step for the quest agent; then the benchmark.
- Eval thresholds guard regressions after each step.

## 12. Open questions (to settle in the step plans)
- Costmap cell size (0.5) and inflation margin; confirm on the hive row and the house porch.
- Entity merge distance for moving NPCs (they need a time-based position, not a fixed one).
- How the screen's "mode" is learned for new menus (catalogue entries from `ask menu` answers).
