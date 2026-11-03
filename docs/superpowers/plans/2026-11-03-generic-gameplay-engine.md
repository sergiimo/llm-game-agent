# Generic Gameplay Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One loop `achieve(goal)` over a self-building world graph and a learned transition table replaces the task functions (`water_all`, `replant_all`, `harvest_all`, `plant_all`).

**Architecture:** `kinds.json` describes each object kind as data (where it comes from in the save, how its save fields map to state, clustering gap, area name, frame markers); `world.py` builds the graph from the save, today's log and click results; `plan.py` holds the transition table (`actions.json`) and finds transition paths; `steps.py` runs a row's steps with checked expectations; `engine.py` loops (targets → `nav.search` → steps → verify → learn); `ask.py` owns the one vision question and its pending record. `observe`/`act`/`nav`/`learn` stay. Revision 2 after review (16 findings, 8 high); revision 3 (user): places are grouped only by distance (area nodes over objects of every kind), kind and state are filters; a missing required parameter is asked (`NEED_INPUT`).

**Tech Stack:** Python 3 (repo `.venv`), unittest, Pillow/numpy (existing), JSON data files.

**Spec:** `docs/superpowers/specs/2026-11-03-generic-gameplay-engine-design.md` (§3 vocabulary and §4 schema updated with this revision).

**Starting point:** the working tree holds the uncommitted L137 south-garden code (`graph.cluster_beds/ensure_region/pos_of/node_at/screen_dir`, position-based `toward`, `act` `Click.at` + `learn.place`, `nav` heading, `garden.discover/plant_all`, `laws.plant_task`, `wf.beds_left(key, beds)`, tests `NewGarden`; all green). Commit it first: `git commit -m "wip: south garden discovery (L137) - base for the engine"`.

## Global Constraints
- Interaction laws stay: Tara at CENTRE (960, 540); a visible object is clicked; every click recorded (`act.click`); bubble loop; across calls only the vision counter, last trace and the pending question (STATE).
- Uncertainty → vision: an unknown transition/step/target raises `NEED_VISION <kind>` (`click|button|name`) with a framed PNG, never a guess.
- Memory is a hint, never a gate (law 6): node state never blocks a click; trust order events > save > frame.
- **One state vocabulary** (all code, data, tests): `stage` (`empty|growing|producing|produced`), `watered` (bool), `wilted` (bool), `ready` (bool), `crop` (name; from cards/events only — the save has no crop type), `can` on node `Tara` (`full|empty`, hint only).
- **No goal or kind names in engine code**: anything kind- or goal-specific lives in `kinds.json`, `actions.json`, `goals.json`.
- Stuck = 3 still seek clicks in a row (`nav.STUCK_CLICKS`); stops: game time ≥ 23:00 or < 06:00, non-English UI (`WrongLanguage`), `LAWS_STUCK` after 4 vision asks without progress; per-call click cap 40.
- Never buy, never sleep; a missing item stops the goal with a report.
- A missing `required` goal parameter is never defaulted: `achieve` returns `NEED_INPUT <goal>: <param>? (seen: …)`.
- Graph structure = distance only: areas cluster objects of every kind; no per-kind group nodes for new data; filters (`kind`, state, `region`) select targets.
- "!" (`ready`) never makes a target unless the goal's `where` asks for `ready: true`; only the water drop means "needs water".
- Expectations: a `"?"` gap is filled after 2 agreeing observations; revised after 3 agreeing contradictions with none confirming since.
- `chains.py`/`chains.json` and `laws` task functions stay untouched until Task 8 (suites stay green between tasks).
- Tests: `.venv/bin/python -m unittest tools/<test>.py`; test_laws, test_game, test_graph, test_affordances, test_wf_safety, test_runtime, test_map_vectors, test_loop stay green after every task.
- Never commit: `5`, `tools/evals/predictions.jsonl`, `runs/`, `tools/objects/graph/Farm.json`, `tools/game/observed*.jsonl`.

## Review Focus
1. Two gardens with look-alike bubbles: an event's position maps to the right region's member; a fitting bubble in another garden does not count for a region-limited goal (Task 5 test `test_a_bubble_in_another_garden_is_not_a_target`).
2. A save older than today's work: log events after the save's time win, applied in order (Task 2 tests `test_log_after_the_save_wins_in_order`).
3. `out_of_water` mid-run: refill sub-goal from the table, then the same goal resumes, nothing counted twice (Task 5 test `test_refill_subgoal_then_resume_without_double_count`).
4. An unknown bubble on a new kind: one NEED_VISION, the answer stored as a row, replayed with zero vision next call (Task 6).
5. Re-running refresh: idempotent; a known area keeps its name; object ids stable by position (Task 2 tests).

## File Structure
| File | Responsibility |
|---|---|
| `tools/test_engine.py` (new) | `FakeGame` (data-driven) + all engine tests |
| `tools/game/kinds.json` (new) | optional overrides per kind: `save_has` (state fields that identify the kind in the save), field→state map, `area` name stem, `markers` (state → frame marker) |
| `tools/game/world.py` (new) | graph from save/log/clicks: objects of any kind, distance clusters → area nodes + `next_to` edges, state, `place`, `query`, `count`, `inventory`, `catalogue`, `nodes` |
| `tools/game/actions.json` (new) | transition rows (seeded) |
| `tools/game/plan.py` (new) | rows load/save, `fits`, `match`, `path`, `effects_of_event`, counters |
| `tools/game/steps.py` (new) | run a row's steps with `expect` checks; own observation log `observed-steps.jsonl` |
| `tools/game/ask.py` (new, from `laws`) | `draw_grid`, `parse_point`, STATE (asks, trace, **pending**), `ask(kind, question, pending)`, `late()`, `summary()` |
| `tools/game/goals.json` (new) | goal library with `required` params |
| `tools/game/engine.py` (new) | `achieve(goal, answer=None, **params)` |
| `tools/game/learn.py` (modify) | `new_row`, `settle_rows` (gaps/revise on `actions.json`); `place` → `world.place` |
| `tools/objects/graph.py` (modify) | keep `pos_of`, `node_at`, `screen_dir`, `toward`, `learn_toward`; cluster code moves to `world.py` (shims kept until Task 8) |
| Task 8 | `garden.py`/`laws.py` → one-line wrappers; `chains.*` deleted; CLI; docs |

---

### Task 0: Data-driven fake game

**Files:** Create `tools/test_engine.py` (class `FakeGame`, test class `Fake`).

**Interfaces:**
- Produces `FakeGame(objects, behaviour, inventory=None, zone='near')`:
  - `objects`: list of `{'id', 'kind', 'pos': (x, z), 'state': {...}, 'zone', 'bubble_pt', 'body_pt'}`.
  - `behaviour`: list of fake transitions `{'kind', 'when', 'bubble': {...}, 'card'?: str, 'buttons'?: [labels], 'event', 'effect'}` (independent of `actions.json`, so the engine is tested against a game, not against its own table).
  - WF API used by the engine: `grab` (frames differ after a walk), `log_mark/log_since`, `run_action('click:x:y')`, `state` (mode/texts: a card shows its `card` text and `buttons`), `wait_settle`, `run_log`, `run_dir`, `farm_status` (`{'crops': [...]}` from GardenBed objects: `x, z, plantState '##'+stage, isWatered, isWilted`), `save_inventory()` (`{name: count}`), `ask_vision`, `game_hour` (default 13.0), `light_period`, `event_kind`, `learn_bubble`, `bubble_crop`.
  - `scan()` → `Affordance(kind, None, bubble_pt, False, 0.0, drop, ready)` for objects in Tara's zone (`drop` = not watered and stage growing/producing, or wilted; `ready` = stage produced); none while a card is open.
  - Clicking a bubble applies the first matching behaviour: `event` → log line `[D185 9:00:00 AM] > <event> me=Player target=<Kind>(Clone) at (<x>, 0.10, <z>)`; a `card` opens until a listed button is pressed (`press` → effect + event); `pick_card` picks a seed. Open ground → walk to `step_zone` if set.
- Patches for `ui.texts/shows/press/press_bubble/pick_card/close`, `affordances.scan`, `core.bind`.

- [ ] **Step 1: Failing tests** class `Fake`: `test_a_dry_bed_shows_a_drop_and_watering_logs_its_position`, `test_a_card_opens_and_a_button_finishes_it`, `test_walking_changes_frames`.
- [ ] **Step 2:** `-m unittest tools.test_engine.Fake` → FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: Commit** `git commit -m "engine: data-driven fake game for tests"`.

### Task 1: Transition table (`actions.json`, `plan.py`)

**Files:** Create `tools/game/actions.json`, `tools/game/plan.py`; Test class `Table`.

**Interfaces:**
- Row: `{"id", "kind", "when": {key: value|"a|b"}, "bubble": {"kind"?: "a|b", "drop"?: bool, "ready"?: bool} | null, "event"?: str, "steps": [...], "effect": {...}, "needs"?: {...}, "source", "seen", "ok", "surprises"}`; `bubble null` + `event` = an event-only row.
- Step: `{"do": "click_bubble"|"click_object"|"press"|"press_space"|"pick_card"|"close"|"read_card", "arg"?: str, "store"?: state key, "expect"?: {"events"?: [...], "card"?: str, "log"?: regex, "bubble"?: str, "text"?: str}}`. `read_card` stores the card's first line into `store` (e.g. `crop`).
- Seed rows: `water` (GardenBed, when `{stage: growing|producing, watered: false, wilted: false}`, bubble `{drop: true}`, steps `[click_bubble expect events [water]]`, effect `{watered: true}`); `out_of_water` (event-only, effect `{"Tara.can": "empty"}`); `fill_can` (Well, bubble `{kind: fill_can|full_watering_can}`, `[click_bubble expect events [fill_watering_can|full_watering_can]]`, effect `{"Tara.can": "full"}`); `remove_wilted` (GardenBed, when `{wilted: true}`, bubble `{drop: true}`, steps `[click_bubble expect card "This plant has wilted", read_card store crop, press_space, press Remove expect events [unplant_impl]]`, effect `{stage: empty, wilted: false, watered: false}`); `plant` (GardenBed, when `{stage: empty}`, bubble `{kind: plant}`, steps `[click_bubble expect card Seeds, pick_card $seed, press Select expect events [plant] log totalPlanted]`, effect `{stage: growing, crop: $seed, watered: false}`, needs `{item: "$seedSeed"}`); `pick` (GardenBed, when `{stage: produced}`, bubble `{kind: pickup}`, `[click_bubble expect events [grab_item]]`, effect `{stage: growing, ready: false}`); `info_growing` (event-only `plant_growing`, effect `{}`). Sources `seed: game D148/D149/D183/D185`.
- `plan.py` produces: `DB`; `rows(kind=None)`, `save_rows(rows)`; `fits(row) -> Callable[[Affordance], bool]`; `match(kind, state, aff) -> list[row]`; `path(kind, state, make, params, depth=3) -> list[row]|None` (BFS over effects; `$x` from params; `$same` = current value; rows with `bubble.ready` only when `make`/`where` mention `ready`); `effects_of_event(event, params=None) -> dict` (`$seed` unresolved → key dropped); `count(row_id, ok: bool)`.

- [ ] **Step 1: Failing tests** class `Table`:
```python
def test_path_from_wilted_to_planted_and_watered(self):
    p = plan.path('GardenBed', {'stage': 'growing', 'wilted': True, 'crop': 'Tulip'}, {'crop': '$same', 'watered': True}, {})
    self.assertEqual([r['id'] for r in p], ['remove_wilted', 'plant', 'water'])
def test_a_wilted_bed_has_no_one_step_water_path(self):
    self.assertNotEqual(plan.path('GardenBed', {'stage': 'growing', 'wilted': True, 'watered': False}, {'watered': True}, {})[0]['id'], 'water')
def test_plant_needs_the_seed_item(self):
    self.assertEqual(plan.path('GardenBed', {'stage': 'empty'}, {'crop': 'Tulip'}, {'seed': 'Tulip'})[0]['needs'], {'item': 'TulipSeed'})
def test_event_effects_and_unresolved_params(self):
    self.assertEqual(plan.effects_of_event('out_of_water'), {'Tara.can': 'empty'})
    self.assertEqual(plan.effects_of_event('plant'), {'stage': 'growing', 'watered': False})
def test_no_path_is_none(self):
    self.assertIsNone(plan.path('BeeHive', {'ready': True}, {'ready': False}, {}))
```
- [ ] **Steps 2–4:** FAIL → implement → PASS. **Step 5: Commit** `git commit -m "engine: transition table (seeded rows) and path planning"`.

### Task 2: World graph (`kinds.json`, `world.py`) — rev. 3: distance-only areas

**Files:** Create `tools/game/kinds.json`, `tools/game/world.py`; Modify `tools/objects/graph.py` (`cluster_beds`/`ensure_region` stay until Task 8), `tools/game/garden.py` (`discover` calls `world.refresh`), `tools/game/learn.py` (`place` → `world.place`; delete `BED_STATE_OF`); Test class `World`.

**Save facts (probed D185, read-only):** positioned objects live in `scenes[].addedObjects|updatedObjects[]` (`prefabId`, `position`, `actorState.userState.entries`); prefab ids are opaque. Farm: beds (state has `isWatered`+`lastTimeRefreshed`), 8 bee hives (state `pollen`, z ≈ -23.5, next to the north garden), the 12 empty south beds, plus ~80 unnamed objects (fences, forage, spawns). `currentPlayerPosition` = Tara at save time. Zero positions are placeholders.

**Interfaces:**
- `kinds.json`: `{"GardenBed": {"save_has": ["isWatered", "lastTimeRefreshed"], "state": {"stage": ["plantState", {"##0": "empty", "": "empty", "##growing": "growing", "##producing": "producing", "##produced": "produced"}], "watered": ["isWatered", "bool"], "wilted": ["isWilted", "bool"], "ready": ["plantState", {"##produced": true, "*": false}]}, "area": "Garden", "markers": {"watered=false": "dry_soil"}}, "BeeHive": {"save_has": ["pollen"], "area": "Hives"}}`.
- `world.py` produces:
  - `save_objects(save) -> list[{'kind', 'pos': (x, z), 'scene', 'raw': {field: value}}]` — every positioned object (non-zero), kind by `save_has`, else by a prefab name learned from the log (`graph.extra['prefabs']`), else `None` (unnamed: counted for the catalogue, not added).
  - `refresh(graph, save, today_lines, save_time) -> dict[str, list[str]]` — objects (save + log `target=<Kind>... at`) → nodes `<Kind>#<x>,<z>` (0.1; an existing node of that kind within `NEAR` 1.2 reused); clusters per scene by distance only (single linkage, gap = clamp(2 × median nearest-neighbour distance of distinct positions, 4, 12)) → area nodes (type `region`, parent = the scene node, `pos` = centre); names: a known area within 2 × gap keeps its name; else the main kind's `area` stem if free (areas claimed north first); else stem + compass from the nearest named area; `next_to` edges (neighbours within 1.5 × own NN distance, screen dir); then today's log events newer than `save_time` applied in order via `place`; `Tara` node `pos` = last positioned event today, else `currentPlayerPosition`. Idempotent. Returns `{area: [new node ids]}`.
  - `place(graph, kind, at, events, effects=None, frame=None) -> str|None` — the object at `at` (creates it when unknown); effects from `plan.effects_of_event`; `frame` → state with source `frame`; learns `prefab -> kind` when the position matches an unnamed save object. Returns the object id.
  - `area_of(graph, node_or_pos) -> str|None`; `query(graph, flt) -> list[str]` (`flt` = `{'kind'?, 'region'?, <state key>: value|"a|b"}`; `region` matches the area chain); `count(graph, flt) -> int`.
  - `inventory(save, today_lines) -> dict[str, int]`; `catalogue(graph) -> str`; `nodes(graph) -> list[dict]` (area, kinds with counts, pos, state summary) for `./wf world nodes`.
- Consumes: `plan.effects_of_event` (Task 1).

- [ ] **Step 1: Failing tests** class `World` (save built from NORTH/SOUTH beds + 8 hives + 2 unnamed objects, in `scenes[0]` Farm):
  - `test_refresh_adds_the_south_area_with_its_12_beds` — `out['GardenSouth']` holds the area + 12 bed objects; `count(g, {'kind': 'GardenBed', 'region': 'GardenSouth', 'stage': 'empty'}) == 12`.
  - `test_hives_next_to_the_beds_share_their_area` — the 8 hives' area is `Garden` (grouping by distance, not kind).
  - `test_a_lone_object_is_an_area_of_one`.
  - `test_refresh_is_idempotent_ids_stable_and_names_kept` — second refresh returns no new ids; ids `GardenBed#2.6,-59.4` unchanged.
  - `test_log_after_the_save_wins_in_order` (unplant_impl then plant on (2.64, -59.36) → `stage` `growing`).
  - `test_a_new_kind_appears_from_the_log` (`target=Mailbox at (…)` far from all → a new object + area).
  - `test_an_unnamed_save_object_is_named_by_a_log_event` (prefab learned; next refresh adds all objects of that prefab).
  - `test_inventory_minus_todays_planting`; `test_tara_position_from_the_last_event_else_the_save`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `World` + `test_laws` + `test_graph` → PASS.
- [ ] **Step 5: Commit** `git commit -m "engine: kinds.json + world graph (distance-only areas) from save/log/clicks"`.

### Task 3: Step runner (`steps.py`)

**Files:** Create `tools/game/steps.py`; Test class `Steps`.

**Interfaces:**
- Produces `run(row, params, bubble, node_state) -> dict` `{'ok', 'events', 'at', 'node', 'frame', 'surprises', 'clicks', 'failed_step', 'stored'}`; `click_bubble` = `act.click(bubble.pt, 'bubble')` (its `frame` = the bubble's drop/ready before the click); `press` = `ui.press`; `press_space` = `ui.press_bubble`; `pick_card` = `ui.pick_card`; `close` = `ui.close`; `read_card` → `stored[store] = garden.crop_name(' / '.join(ui.texts()))`. Each `expect` checked; a failure → `ok False`, `failed_step`, cards closed. Observations to `tools/game/observed-steps.jsonl`: `{row, step, field, expected, got, verdict}`.
- Consumes: Task 0 fake, Task 1 rows.

- [ ] **Step 1: Failing tests:** `test_plant_row_runs_and_reports_the_event_position`, `test_read_card_stores_the_crop`, `test_a_failed_expect_stops_and_closes_the_card`, `test_observations_are_logged_per_step_field`.
- [ ] **Steps 2–4:** FAIL → implement → PASS. **Step 5: Commit** `git commit -m "engine: step runner with checked expectations"`.

### Task 4: The question (`ask.py`)

**Files:** Create `tools/game/ask.py` (moved from `laws`: `draw_grid`, `parse_point`, STATE load/save/reset, `_late` → `late(res)`, `summary`); Modify `laws.py` to import them from `ask` (no behaviour change); Test class `Ask`.

**Interfaces:**
- STATE: `{'goal', 'asks', 'history', 'trace', 'pending': {'kind': 'click'|'button'|'name', 'goal', 'params', 'row'?, 'step'?, 'bubble'?: [x, y], 'node'?}}`.
- `ask(kind, question, pending, res) -> NoReturn` raises `NeedVision` whose prompt ends with `answer: ./wf achieve <goal> [params] answer=<…>`; `LawsStuck` after `MAX_ASKS` 4.
- `take_answer(goal) -> (pending, answer)|None`.

- [ ] **Step 1: Failing tests:** `test_pending_record_survives_to_the_next_call`, `test_answer_hint_names_the_goal_not_a_task_function`, `test_laws_still_uses_the_moved_helpers` (run one `test_laws` path).
- [ ] **Steps 2–4.** **Step 5: Commit** `git commit -m "engine: ask.py (one question, pending record, grid)"`.

### Task 5: Goals and the loop (`goals.json`, `engine.py`)

**Files:** Create `tools/game/goals.json`, `tools/game/engine.py`; Modify `tools/game/nav.py` (`Target.soil: bool` → `Target.marker: str|None`; `seek` uses `observe.soil` when `marker == 'dry_soil'`); Test class `Loop`.

**Interfaces:**
- `goals.json`: `water {kind GardenBed, where {stage: growing|producing, watered: false, wilted: false}, make {watered: true}}`; `replant {where {wilted: true}, make {crop: $same, watered: true}}`; `plant {where {region: $region, stage: empty}, make {crop: $seed}, required [seed, region]}`; `harvest {where {ready: true}, make {ready: false}, required [crops], where_param {crop: $crops}}`.
- `achieve(goal, answer=None, max_clicks=40, **params) -> dict` `{'goal', 'done', 'left', 'clicks', 'vision', 'subgoals', 'surprises', 'learned', 'stop'}`; missing `required` → returns `{'stop': 'NEED_INPUT <goal>: <param>? (seen: <values of that key among matching objects>)'}` before any click (generic, from data).
- Loop: `ask.late` / language → `world.refresh` → `targets = world.query(...)`; empty → `stop 'done: query empty'` → nearest target region by `graph.toward`/pos → `p = plan.path(...)` (none → Task 6 explore) → `needs.item`: `world.inventory(...)[item] < 1` → `stop 'missing <item>'` → `t = p[0]`; `marker` = `kinds.json` marker for the goal's `make` keys → `nav.search(Target(fits=plan.fits(t) ∧ bubble's node in the target's region (via last event / closest node), kind, region, node=group, marker), res)`; none → `ask.ask('click', …)` → `steps.run` → `world.place(outcome)`; an outcome event whose effect is on another node (`Tara.can: empty`) → sub-goal `plan.path` to restore it (any kind with a row producing `{Tara.can: full}` → its node), depth 1, then the same target again; `res['done']` counts only verified effects.
- `answer=` with `ask.take_answer`: `click` → `act.click` the cell then continue; `button` → patch the pending row's failed step `{"do": "press", "arg": answer}`; `name` → handled in Task 6.

- [ ] **Step 1: Failing tests** class `Loop`: `test_water_goal_waters_every_dry_bed_and_stops_on_empty_query`, `test_refill_subgoal_then_resume_without_double_count`, `test_plant_goal_finds_the_south_garden_and_plants_12` (region added, 12 members `crop == Tulip`, vision 0), `test_a_bubble_in_another_garden_is_not_a_target`, `test_replant_keeps_the_crop_read_from_the_card`, `test_missing_required_param_asks_with_the_values_seen`, `test_missing_seed_stops`, `test_late_stops_before_any_click`, `test_click_cap_stops`.
- [ ] **Steps 2–4:** FAIL → implement → all suites PASS. **Step 5: Commit** `git commit -m "engine: goals library and the achieve loop"`.

### Task 6: Learning new transitions

**Files:** Modify `tools/game/learn.py`, `tools/game/engine.py`; Test class `Learning`.

**Interfaces:**
- `learn.new_row(kind, state, aff, outcome, answer=None) -> dict` — effect = the node's state diff from the outcome's event via `world.place` **plus** the frame change of the clicked bubble (`ready` true → gone ⇒ `ready: false`; drop gone ⇒ `watered: true`) **or** the vision `answer` (`name`: `"<state key>=<value>"`); `source 'learned D<day>'`, `seen 1`; trusted by `plan.path` after `seen ≥ 2` with the same effect.
- Engine: no path → one exploratory `click_bubble` on the target's fitting bubble (any bubble owned by that node) → `new_row`; no effect derivable → `ask.ask('name', 'what changed on this <kind> after the click? answer key=value', pending)`.
- `learn.settle_rows()` = gaps + revise over `actions.json` steps from `observed-steps.jsonl`; `engine.achieve` calls it in `finally`.

- [ ] **Step 1: Failing tests:** `test_a_new_kind_is_learned_with_one_answer_then_replayed` (fake BeeHive `ready` → `collect` card-less event `beehive_collect`; first `achieve({'kind': 'BeeHive', 'where': {'ready': True}, 'make': {'ready': False}})` learns from the frame change with ≤ 1 NEED_VISION; second call on another ready hive: `vision == 0`), `test_revise_after_three_contradictions`, `test_gap_filled_after_two`.
- [ ] **Steps 2–4.** **Step 5: Commit** `git commit -m "engine: learn new transitions from play; settle the table after each run"`.

### Task 7: Metrics and the catalogue

**Files:** Modify `tools/game/engine.py`, `tools/game/world.py`; Test class `Report`.

**Interfaces:** summary gains `vision_per_target`, `clicks_per_target`; each run appends `{goal, done, vision, clicks, surprises, learned}` to the run log (`run_log('engine', …)`); `world.catalogue(graph)` lists kinds, state keys with values seen, areas with counts, rows per kind (trusted / learning), unnamed save prefabs with counts; `world.nodes(graph)` rows for `./wf world nodes`.

- [ ] Tests `test_summary_has_per_target_metrics`, `test_catalogue_lists_kinds_regions_rows`; FAIL → implement → PASS; **Commit** `git commit -m "engine: metrics and world catalogue"`.

### Task 8: Wrappers, CLI, removals, docs

**Files:**
- `tools/game/garden.py`: `water_all(click=None)` = `return engine.achieve('water', answer=click)`; `replant_all(seed=None, click=None)`; `harvest_all(crops, click=None)`; `plant_all(seed='Tulip', region='GardenSouth', click=None)` — one line each; delete `discover`.
- `tools/game/laws.py`: delete the task layer (`TASKS`, `DONE_ON`, `plant_task`, `harvest_task`, `_left_in_save`, `_fill_can`, `chains_observe_remove`, `_replant`, `_plant`, `_handle`, `_ask`, `_late`, `_done_looking`, `run`, `_run`); keep a module docstring pointing to `engine` + re-exports used by `wf.py` (`draw_grid`, `LawsStuck`).
- Delete `tools/game/chains.py`, `tools/game/chains.json`; `act.click(chain=, idx=)` params removed; `learn.check/STEP_OF/text_gaps` removed (steps check instead).
- `tools/objects/graph.py`: delete the shims, `TOWARD` becomes seeded `toward` edges written by `world.refresh` from `kinds.json` (`"toward": {"Well->GardenBed@Garden": [0.69, 0.73], …}`); `NODE_OF`/`CROP_KINDS` in `observe` read `kinds.json`.
- `tools/wf.py`: `beds_left(key, beds)` → `world.count` with `{'dry': {stage: growing|producing, watered: false, wilted: false}, 'wilted': {wilted: true}, 'empty': {stage: empty}}`; `routines` uses it; new commands in `wf.py`/`wfc.py`: `achieve <name|json> [k=v ...] [answer=X]`, `world kinds`, `world nodes`.
- Tests: `test_laws.py` keeps classes `Points`, `Vision` (grid → `ask`), `Record`, `Mechanics`, `Language`, `CardText`→`Steps`, `BedsLeft`, `Framework` (closest node, late), `Seek`, `Reach`; deletes `BubbleLoop`, `ChainsDB`, `Memory`, `Retest`, `NewGarden` (covered by `test_engine` `Loop`, `Learning`, `World`); `test_game` drop test unchanged.
- Docs: `docs/mechanics/interaction-laws.md` (Framework → engine: kinds/world/plan/steps/ask/engine; tool status), `AGENTS.md` (tools/game row; rule 10: `./wf achieve`), `.claude/agents/wylde-quest.md` (pick/write a goal, `./wf world kinds`, NEED_VISION `click|button|name`, `answer=`), `docs/actions.md` A18, `docs/learnings.md` L138.

- [ ] **Step 1:** tests `test_wrappers_call_achieve`, `test_cli_parses_goal_params_and_answer`, `test_routines_counts_from_world`.
- [ ] **Steps 2–4:** FAIL → implement → every suite in Global Constraints PASS.
- [ ] **Step 5: Commit** `git commit -m "engine: task functions become goals; remove the laws task layer and chains; docs (L138)"`; `./wf stop`.

### Task 9: Live acceptance (south garden)

**Files:** `runs/<ts>-engine-plant-south/plan.md` (not committed), reused for every retry.

- [ ] **Step 1:** check the game is free (log/clock vs our last command); write the run plan: `./wf world kinds` → `./wf achieve plant seed=Tulip region=GardenSouth` → answer NEED_VISION → until `stop done: query empty` / missing / LAWS_STUCK → `./wf routines`, `./wf world kinds` → report: region added, 12 bed members, planted count, vision calls (≤ 2), surprises, learned rows.
- [ ] **Step 2:** dispatch one haiku `wylde-quest` agent; hands off until it reports.
- [ ] **Step 3:** fix from the report (a learning row + doc fix per surprise); retry on the same plan until done.
