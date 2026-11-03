# Generic Gameplay Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One loop `achieve(goal)` over a self-building world graph and a learned transition table replaces the task functions (`water_all`, `replant_all`, `harvest_all`, `plant_all`).

**Architecture:** `world.py` builds/refreshes graph nodes, regions and state from the save + today's log; `plan.py` holds the transition table (`actions.json`) and finds a path of transitions from a node's state to the goal's `make`; `steps.py` runs a row's steps with checked expectations; `engine.py` is the loop (targets → nav.reach → steps → verify → learn) with goals from `goals.json` or raw queries. `observe`/`act`/`nav`/`learn` stay.

**Tech Stack:** Python 3 (repo `.venv`), unittest, Pillow/numpy (existing), JSON data files.

**Spec:** `docs/superpowers/specs/2026-11-03-generic-gameplay-engine-design.md`

**Starting point:** the working tree holds the uncommitted L137 south-garden code (`graph.cluster_beds/ensure_region/pos_of/node_at/screen_dir`, position-based `toward`, `act` `Click.at` + `learn.place`, `nav` heading, `garden.discover/plant_all`, `laws.plant_task`, `wf.beds_left(key, beds)`, tests `NewGarden`, all green). Commit it as the base (`git commit -m "wip: south garden discovery (L137) - base for the engine"`) before Task 1; Task 1 moves its clustering into `world.py`.

## Global Constraints
- Interaction laws stay: Tara at CENTRE (960, 540); a visible object is clicked; every click recorded (`act.click`); bubble loop; no positions carried between calls except the vision counter + last trace (STATE).
- Uncertainty → vision: an unknown transition/step/target raises `NEED_VISION <kind>` with a framed PNG, never a guess.
- Memory is a hint, never a gate; trust order events > save > frame.
- Stuck = 3 still seek clicks in a row (`nav.STUCK_CLICKS`); stops: game time ≥ 23:00 or < 06:00, non-English UI (`WrongLanguage`), `LAWS_STUCK` after 4 vision asks without progress.
- Never buy, never sleep; a missing item stops the goal with a report.
- "!" (ready) never makes a target by itself; only the water drop means "needs water".
- Rows/expectations: a gap `"?"` is filled after 2 agreeing observations; an expectation is revised after 3 agreeing contradictions with none confirming since.
- Tests: `.venv/bin/python -m unittest tools/<test>.py`; all of test_laws, test_game, test_graph, test_affordances, test_wf_safety, test_runtime, test_map_vectors, test_loop stay green.
- Never commit: `5`, `tools/evals/predictions.jsonl`, `runs/`, `tools/objects/graph/Farm.json`, `tools/game/observed.jsonl`.

## Review Focus
1. Two gardens with look-alike bubbles: an event's position must map to the right region's member; a bubble in the wrong garden must not count for a goal limited to another region.
2. A save older than today's work: `count(query)` must subtract today's log events by position (no searching for beds already done).
3. A transition whose need fails mid-run (`out_of_water`): sub-goal (refill at the well) then back to the same goal, without double-counting.
4. An unknown bubble/transition for a new kind: one NEED_VISION, the answer stored as a row, then replayed with zero vision on the next call.
5. Re-running discovery/refresh: idempotent (no duplicate regions/members/edges) and a known region keeps its name.

## File Structure
| File | Responsibility |
|---|---|
| `tools/game/world.py` (new) | save/log → nodes with state; clustering → regions/groups/members/edges; `query`, `count`, `catalogue` |
| `tools/game/actions.json` (new, replaces `chains.json`) | transition rows (seeded) |
| `tools/game/plan.py` (new) | load/save rows, `match`, `path`, param substitution, row counters |
| `tools/game/steps.py` (new) | run a row's steps (`click_bubble`, `click_object`, `press`, `press_space`, `pick_card`, `close`) with `expect` checks |
| `tools/game/goals.json` (new) | goal library |
| `tools/game/engine.py` (new) | `achieve(goal, answer=None, **params)` loop, needs → sub-goals, done, NEED_VISION kinds |
| `tools/game/learn.py` (modify) | row learning (new rows, counts), settle on `actions.json`; `place` → `world.place` |
| `tools/objects/graph.py` (modify) | keep `pos_of`, `node_at`, `screen_dir`, `toward`, `learn_toward`; move `cluster_beds`/`ensure_region` to `world.py` |
| `tools/game/laws.py`, `garden.py` (modify) | task layer removed; `water_all`… become wrappers over `achieve` |
| `tools/wf.py`, `tools/wfc.py` (modify) | `./wf achieve <goal|json> [k=v…] [answer=…]`, `./wf world kinds`; `beds_left` → `world.count` |
| `tools/test_engine.py` (new) | data-driven fake game + acceptance tests |
| docs | `interaction-laws.md`, `AGENTS.md`, `.claude/agents/wylde-quest.md`, `docs/actions.md` A18, `docs/learnings.md` L138 |

---

### Task 1: World graph from save + log (`world.py`)

**Files:** Create `tools/game/world.py`; Modify `tools/objects/graph.py` (remove `cluster_beds`, `_grid`, `ensure_region`, `CLUSTER_GAP` after moving); Test `tools/test_engine.py` (class `World`).

**Interfaces:**
- Produces:
  - `SAVE_KINDS = {'crops': 'GardenBed'}` (save list → node kind).
  - `state_of_crop(c: dict) -> dict` → `{'stage': 'empty'|'growing'|'producing'|'produced', 'watered': bool, 'wilted': bool, 'ready': bool}` (`ready = stage == 'produced'`).
  - `refresh(graph, save: dict, today_lines: list[str]) -> dict[str, list[str]]` — positioned entities → members; clusters (gap 6.0) → regions named `Garden` for the cluster nearest an existing `Garden` pos (else northernmost) and `<Area><Compass>` (`GardenSouth`) for new ones; group `GardenBed@<Region>` with `pattern {rows, cols}`; members `GardenBed@<Region>#r<row>c<col>` (rows north→south, cols west→east) with `pos`, save state; `next_to` edges (east `[1,0]`, south `[0,1]`); then today's log events applied by position (`world.place`). Returns `{region: [new ids]}`; idempotent.
  - `place(graph, kind: str, at: tuple, events: list[str], effects: dict) -> str|None` — member at `at` (≤ 1.2 units) gets the effects; returns its group id.
  - `query(graph, kind, where: dict) -> list[str]` — member ids whose state matches; `where` values: literal, `'a|b'` alternatives, `'region'` key matches the member's region chain.
  - `count(graph, kind, where) -> int` = `len(query(...))`.
  - `catalogue(graph) -> str` — kinds, state keys with values seen, regions, transitions per kind (rows from `plan.rows()`).

- [ ] **Step 1: Write the failing tests** in `tools/test_engine.py` class `World`, using save crops `NORTH` (12 growing/watered at x∈{-1.66,0.84,3.34,5.84}, z∈{-25.34,-29.09,-31.59}) and `SOUTH` (12 `##0` at x∈{2.64,6.39,10.14,13.89}, z∈{-59.36,-63.11,-66.86}) on a tmp copy of `tools/fixtures/graph_seed.json`:
```python
def test_refresh_adds_the_south_garden_and_its_beds(self):
    out = world.refresh(g, {'crops': NORTH + SOUTH}, [])
    self.assertEqual(len(out['GardenSouth']), 14)
    self.assertEqual(g.nodes['GardenBed@GardenSouth#r1c1'].extra['pos'], [2.64, -59.36])
    self.assertEqual(g.nodes['GardenBed@GardenSouth#r1c1'].state['stage']['value'], 'empty')
    self.assertEqual(world.count(g, 'GardenBed', {'region': 'GardenSouth', 'stage': 'empty'}), 12)
    self.assertEqual(world.refresh(g, {'crops': NORTH + SOUTH}, [])['GardenSouth'], [])   # idempotent

def test_todays_log_counts_by_position(self):
    log = ['[D185 9:00:00 AM] > plant me=Player target=GardenBed(Clone) at (2.64, 0.10, -59.36)']
    world.refresh(g, {'crops': NORTH + SOUTH}, log)
    self.assertEqual(world.count(g, 'GardenBed', {'region': 'GardenSouth', 'stage': 'empty'}), 11)

def test_a_bed_event_in_the_south_is_placed_there(self):
    world.refresh(g, {'crops': NORTH + SOUTH}, [])
    self.assertEqual(world.place(g, 'GardenBed', (6.39, -63.11), ['water'], {'watered': True}), 'GardenBed@GardenSouth')
```
- [ ] **Step 2: Run** `.venv/bin/python -m unittest tools.test_engine.World -v` → FAIL (no module `game.world`).
- [ ] **Step 3: Implement** `world.py` (move clustering/grid/members from `graph.py`; log effects come from a `log_effects` argument the engine passes from `plan.effects_of_event`; until Task 2 exists use `{'plant': {'stage': 'growing'}, 'water': {'watered': True}, 'unplant_impl': {'stage': 'empty', 'wilted': False}}` as the default `EVENT_EFFECTS` in `world.py`, replaced in Task 2).
- [ ] **Step 4: Run** the `World` tests → PASS; run `test_graph`, `test_laws` → still OK.
- [ ] **Step 5: Commit** `git add tools/game/world.py tools/objects/graph.py tools/test_engine.py && git commit -m "engine: world graph from save + log (regions, beds, state, query/count)"`.

### Task 2: Transition table (`actions.json`, `plan.py`)

**Files:** Create `tools/game/actions.json`, `tools/game/plan.py`; Test `tools/test_engine.py` (class `Table`).

**Interfaces:**
- Row schema (spec §4): `{"id", "kind", "when", "bubble", "steps", "effect", "needs", "events", "source", "seen", "ok", "surprises"}`; `steps[]`: `{"do", "arg"?, "expect"?}` with `expect` keys `events|card|bubble|text|log`.
- Seed rows (ids): `water` (GardenBed `{stage: growing|producing, watered: false}` drop bubble → click_bubble, expect events `water` → effect `{watered: true}`, needs `{Tara.can: full}`); `out_of_water` (event → effect `{Tara.can: empty}`, no steps: an event-only row); `fill_can` (Well bubble `fill_can|full_watering_can` → click_bubble, expect events `fill_watering_can|full_watering_can` → `{Tara.can: full}`); `remove_wilted` (GardenBed `{wilted: true}` drop bubble → click_bubble expect card `This plant has wilted`, `press_space`, `press Remove` expect events `unplant_impl` → `{stage: empty, wilted: false}`); `plant` (GardenBed `{stage: empty}` bubble `plant` → click_bubble expect card `Seeds`, `pick_card $seed`, `press Select` expect events `plant`, log `totalPlanted` → `{stage: growing, crop: $seed, watered: false}`, needs `{item: "$seed Seed"}`); `pick` (GardenBed `{stage: produced}` bubble `pickup` → click_bubble expect events `grab_item` → `{stage: growing, ready: false}`); `info_growing` (event `plant_growing` → no effect, `bubble: gone`). `source: "seed: game D148/D149/D183/D185"`.
- Produces in `plan.py`:
  - `rows(kind=None) -> list[dict]`, `save_rows(rows)`; `DB` path constant.
  - `match(kind, state: dict, bubble) -> list[dict]` (rows whose `when` holds and whose `bubble` fits `Affordance` kind/drop/ready).
  - `path(kind, state: dict, make: dict, params: dict, depth=3) -> list[dict]|None` (BFS over rows' effects; `$name` resolved from params; `$same` = the state's current value).
  - `effects_of_event(event: str) -> dict` (event-only rows + rows whose last step expects that event).
  - `count(row_id, ok: bool)` updates `seen/ok/surprises`.
- Consumes: Task 1 `EVENT_EFFECTS` replaced by `plan.effects_of_event`.

- [ ] **Step 1: Failing tests** class `Table`:
```python
def test_path_from_wilted_to_planted_and_watered(self):
    p = plan.path('GardenBed', {'stage': 'growing', 'wilted': True}, {'crop': 'Tulip', 'watered': True}, {'seed': 'Tulip'})
    self.assertEqual([r['id'] for r in p], ['remove_wilted', 'plant', 'water'])
def test_plant_needs_the_seed_item(self):
    self.assertEqual(plan.path('GardenBed', {'stage': 'empty'}, {'crop': 'Tulip'}, {'seed': 'Tulip'})[0]['needs'], {'item': 'Tulip Seed'})
def test_event_effects(self):
    self.assertEqual(plan.effects_of_event('out_of_water'), {'Tara.can': 'empty'})
def test_no_path_is_none(self):
    self.assertIsNone(plan.path('BeeHive', {'ready': True}, {'ready': False}, {}))
```
- [ ] **Step 2: Run** `-m unittest tools.test_engine.Table` → FAIL.
- [ ] **Step 3: Implement** `actions.json` (the 7 seed rows) and `plan.py`; switch `world.py` to `plan.effects_of_event`.
- [ ] **Step 4: Run** `Table` + `World` → PASS.
- [ ] **Step 5: Commit** `git add tools/game/actions.json tools/game/plan.py tools/game/world.py tools/test_engine.py && git commit -m "engine: transition table (seeded rows) and path planning"`.

### Task 3: Step runner (`steps.py`)

**Files:** Create `tools/game/steps.py`; Modify `tools/game/learn.py` (move `chains.observe/gaps/revise` logic to work on a row's step `expect`, writing `tools/game/observed.jsonl` rows `{row, step, field, expected, got, verdict}`); Test class `Steps`.

**Interfaces:**
- Produces: `run(row: dict, params: dict, bubble) -> Outcome` where `Outcome = {'ok': bool, 'events': list, 'at': (x, z)|None, 'node': str|None, 'surprises': list, 'clicks': list[act.Click], 'failed_step': int|None}`. `click_bubble` clicks `bubble.pt` via `act.click`; `press <label>` = `ui.press`; `press_space` = `ui.press_bubble`; `pick_card <name>` = `ui.pick_card`; `close` = `ui.close`. Each step's `expect` checked (events ⊇, card substring of screen texts, `log` regex in new log lines, bubble/text as `chains.actual`); a failed `expect` → `ok False`, close cards, `failed_step` set.
- Consumes: `act.click`, `ui.*`, `observe.texts`, `learn.check_step(row_id, idx, actual)`.

- [ ] **Step 1: Failing tests** (fake from Task 6's `FakeGame` — write the minimal fake here and grow it in Task 6): `test_plant_row_runs_three_steps_and_reports_the_event`, `test_a_failed_expect_stops_and_closes_the_card` (card text differs → `ok False`, `failed_step == 0`, screen back to gameplay), `test_steps_record_observations` (observed.jsonl gets one row per step field).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "engine: step runner with checked expectations"` (files: steps.py, learn.py, test_engine.py).

### Task 4: Goals (`goals.json`) and the loop (`engine.py`)

**Files:** Create `tools/game/goals.json`, `tools/game/engine.py`; Test class `Loop`.

**Interfaces:**
- `goals.json` (state keys from Task 1): `water {kind GardenBed, where {stage: growing|producing, watered: false, wilted: false}, make {watered: true}}`; `replant {where {wilted: true}, make {crop: $same, watered: true}}`; `plant {where {region: $region, stage: empty}, make {crop: $seed}}`; `harvest {where {ready: true, crop: $crops}, make {ready: false}}` (`$crops` required: no default, spec open question 1).
- Produces: `achieve(goal: str|dict, answer=None, max_clicks=40, **params) -> dict` summary `{'goal', 'done', 'left', 'clicks', 'vision', 'subgoals', 'surprises', 'learned', 'stop'}`; raises `NeedVision` (kinds `click`, `button`, `name`) or `LawsStuck`/`WrongLanguage`.
- Loop (spec §6): stops (`laws._late`-equivalent clock, language) → `world.refresh(graph, save, today)` → `targets = world.query(...)`; empty → `stop 'done: query empty'` → `p = plan.path(...)` for the nearest target's state (targets ordered by distance of their region `pos` to `here`), no path → `NEED_VISION name` ("what does this object's bubble do?") → unmet `needs`: `Tara.can` → sub-goal `{kind Well, make {Tara.can: full}}` (recursion depth 1); `item` missing in the save inventory → `stop 'missing <item>'` → `bubble = nav.search(Target(fits=row.bubble, kind, region of target, node=target group, soil=(make has watered)), res)`; none → `laws._ask`-style `NEED_VISION click` with the trace → `steps.run(row, params, bubble)` → `world.place` the outcome → loop.
- `answer=`: a grid cell for `click` (clicked like `laws.run(click=)`), a label for `button` (stored as the failed step's replacement in the row), a name for `name` (stored as the bubble's label via `learn`).

- [ ] **Step 1: Failing tests** class `Loop` (on the Task 6 fake): `test_water_goal_waters_every_dry_bed_and_stops_on_empty_query`, `test_empty_can_makes_a_refill_subgoal_then_continues`, `test_plant_goal_finds_the_south_garden_and_plants_12` (asserts region added, 12 `crop == Tulip`, vision 0), `test_replant_keeps_the_crop`, `test_harvest_without_crops_is_rejected` (`ValueError('harvest needs crops=')`), `test_missing_seed_stops` (`stop` startswith `missing`), `test_late_stops_before_any_click`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `git commit -m "engine: goals library and the achieve loop"`.

### Task 5: Learning new rows + settle on the table

**Files:** Modify `tools/game/learn.py`, `tools/game/engine.py`; Test class `Learning`.

**Interfaces:**
- Produces: `learn.new_row(kind, state, bubble, outcome) -> dict` (a row with `source 'learned D<day>'`, `seen 1`, effect = the state diff seen after the event (`world.place` before/after) or the `answer`), stored by `plan.save_rows`; trusted (used by `path`) after `seen ≥ 2` with the same effect. `learn.settle()` = gaps (2 agreeing) + revise (3 agreeing contradictions) over `actions.json` steps; called by `engine.achieve` in `finally`.
- Engine: a target whose bubble matches no row → one exploratory `click_bubble` → `new_row` → if no event/effect → `NEED_VISION name`.

- [ ] **Step 1: Failing tests:** `test_a_new_kind_is_learned_with_one_vision_answer_then_replayed` (fake BeeHive with `ready` and a `collect_honey` behaviour unknown to the table: first `achieve({'kind': 'BeeHive', 'where': {'ready': True}, 'make': {'ready': False}})` raises NeedVision `name` at most once; after `answer=`, a second call on another ready hive asks nothing, `vision == 0`); `test_revise_after_three_contradictions` (row step expect bubble `same`, 3× `gone` → `gone`); `test_gap_filled_after_two`.
- [ ] **Step 2–4:** run → FAIL → implement → PASS.
- [ ] **Step 5: Commit** `git commit -m "engine: learn new transitions from play; settle the table after each run"`.

### Task 6: Data-driven fake game (grows with Tasks 3–5)

**Files:** `tools/test_engine.py` (`FakeGame`), no product code.

**Interfaces:** `FakeGame(objects: list[dict], table: list[dict], inventory: dict, zones)` — each object `{kind, pos, state, zone, bubble_pt}`; `scan()` shows bubbles of objects in Tara's zone (kind/drop/ready from state: drop if `watered False` or `wilted`, ready if `stage produced`), hidden while a card is open; clicks run the object's fake behaviour from `table` (its own copy of transitions) and append log lines `> <event> me=Player target=<Kind>(Clone) at (x, 0.10, z)`; open ground clicks walk to `step_zone`; `farm_status()`/`save` from objects; frames differ after a walk (`moved`).

- [ ] Steps live in Tasks 3–5 (each grows the fake for its tests). Final check: `-m unittest tools.test_engine` → all PASS. Commit with Task 5.

### Task 7: Wrappers, CLI, removal of the task layer, docs

**Files:** Modify `tools/game/garden.py` (`water_all(click=None)` → `engine.achieve('water', answer=click)`; same for `replant_all(seed=None)`, `harvest_all(crops=None)` (raises without crops), `plant_all(seed, region)`; delete `discover`), `tools/game/laws.py` (delete `TASKS`, `DONE_ON`, `_handle`, `_replant`, `_plant`, `_fill_can`, `_run`, `run`, `plant_task`, `harvest_task`; keep `draw_grid`, `parse_point`, state counter, `_ask`, `_late`, re-exports), `tools/game/__init__.py` (export `achieve`), `tools/wf.py` + `tools/wfc.py` (`achieve` command: `./wf achieve <name|json> [k=v ...] [answer=X]`; `world` subcommand `kinds` → `world.catalogue`; `beds_left` → wrapper over `world.count`), delete `tools/game/chains.py` + `chains.json` (rows moved to `actions.json`), move `test_laws` acceptance cases that still apply into `test_engine` and delete the rest.
- Docs: `docs/mechanics/interaction-laws.md` (Framework section → engine: world/plan/steps/engine; tool status), `AGENTS.md` (tools/game row + rule 10 mention `./wf achieve`), `.claude/agents/wylde-quest.md` (how to pick/write a goal, `./wf world kinds`, NEED_VISION kinds `click|button|name`, answer=), `docs/actions.md` A18, `docs/learnings.md` L138.

- [ ] **Step 1:** write `test_wrappers_call_achieve` (garden.water_all → achieve('water')) and `test_cli_parses_goal_and_params` (wfc argument parsing for `./wf achieve plant seed=Tulip region=GardenSouth`).
- [ ] **Step 2–4:** FAIL → implement → all suites PASS (list in Global Constraints).
- [ ] **Step 5: Commit** `git commit -m "engine: task functions become goals; remove the laws task layer and chains; docs (L138)"`; `./wf stop`.

### Task 8: Live acceptance (south garden)

**Files:** `runs/<ts>-engine-plant-south/plan.md` (not committed); reuse it for every retry (memory: reuse-run-plan).

- [ ] **Step 1:** supervisor checks the game is free (log/clock vs our last command), writes the run plan: `./wf world kinds` → `./wf achieve plant seed=Tulip region=GardenSouth` → answer NEED_VISION kinds → until `stop done: query empty` or LAWS_STUCK → `./wf routines` + `./wf world kinds` → report: region added (yes/no), beds graph (12 members), planted count, vision calls (target ≤ 2), surprises, learned rows.
- [ ] **Step 2:** dispatch one haiku `wylde-quest` agent; hands off until it reports.
- [ ] **Step 3:** fix from the report (learning row + doc fix per surprise), retry on the same plan until done.
