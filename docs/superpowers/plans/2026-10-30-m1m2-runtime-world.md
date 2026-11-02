# M1+M2: Runtime Evidence and World Model Implementation Plan

**Status (2026-11-02):** implemented. `tools/runtime/` stays; the `tools/world/` coordinate model (belief, costmap, view, zoom) is **superseded** by `specs/2026-10-31-object-graph-navigation-design.md` and scheduled for removal there (§10 step 5). Do not extend it.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One parser turns the game log (and our own clicks) into typed evidence; one world model (entities, scene
graph, costmap, Tara's belief, view) is built from that evidence and from the save, and its predictions are scored
by the M0 eval, so M3 can move `walk` and the skills onto it.

**Architecture:** New packages `tools/runtime/` (sources → `Ev` evidence; actuators) and `tools/world/` (state +
queries), alongside the old code. Pure modules with offline tests on recorded lines and synthetic layouts; the daemon
feeds `world.observe()` from the log reader after every command (shadow mode: the world predicts, the eval scores it,
nothing acts on it yet). Old code stays untouched until M3.

**Tech Stack:** Python 3.12, numpy, `networkx`, `filterpy` (added to `.venv` with uv), stdlib unittest.

**Spec:** `docs/superpowers/specs/2026-10-30-agent-system-refactor-design.md` (§3 world, §4 runtime, §7 eval, §9 M1–M2)

## Global Constraints

- Tools never call an LLM (spec §1). Offline tests before live; live = a small plan step for the quest agent.
- No behaviour change for play in this plan (shadow mode): skills and walking keep using the old code until M3.
- Ground truth = game log lines and the save; the screen is supporting evidence (spec §2).
- Costmap 0.5 units per cell; solid entity default radius 0.6; inflation 0.5; refused clicks fade after 1 game hour;
  `needs_fix()` when uncertainty > 3.0 units (spec §3).
- Entity merge: same kind, same area, within 0.5 units (spec §3); moving NPCs are not merged by position (open question
  → kind `NPC` keeps one entity per name).
- `./wf stop` after editing daemon code; one game command per call; commit only on request.

## Review Focus

- Log lines of unknown shape (most lines): `parse_line` returns None, never raises.
- A line with an entity and no area context (log lines carry no scene): the reader stamps the current area from the
  last scene evidence; before any scene evidence the area is `None` and such entities are held, not guessed.
- Two hives logged as `BeeHive(Clone)` 1.25 apart are two entities, not merged (0.5 merge distance).
- Belief with no evidence for many clicks: uncertainty keeps growing and `needs_fix()` turns True; it never reports a
  confident wrong position.
- An area without calibration: `view.on_screen` returns False and `click_point` None (no projection guesses).

---

### Task 1: `runtime/log.py`: one parser for the game log

**Files:** Create `tools/runtime/__init__.py`, `tools/runtime/log.py`, `tools/fixtures/game_log.txt` (≈60 real lines
copied from `./wf log --tail 5000`, one or more per kind below); Test: `tools/test_runtime.py`

**Interfaces — Produces:**
- `@dataclass Ev: kind: str; day: int | None; hour: float | None; line: str; f: dict` (fields per kind)
- `parse_line(line: str) -> Ev | None`, kinds and fields (exact):

| kind | from | fields |
|---|---|---|
| `action` | `> <name> me=Player target=<Obj>[(Clone)][ (n)] at (x, y, z)` | name, target, x, z |
| `action` | same without `at` | name, target |
| `pathfail` | `Player failed to pathfind from (x,y,z) to [<Obj>(Clone)] at (x,y,z)` | x, z (her), tx, tz, target or None |
| `stuck` | `Player locomotion failed at <Scene> (x,y,z)` / `Path blocked timeout exceeded at (x,y,z)` | scene or None, x, z |
| `scene` | `[GAME] ChangeScene <Scene>/<Link>` | scene, link |
| `spawn` | `[MODE] Spawning player at <Scene>/<Point>` / `at last known position` | scene or None, point |
| `building` | `[TRIGGER] OnEnterBuilding <B>` / `OnExitBuilding <B>` | building, enter (bool) |
| `pollen` | `[ACTOR] BeeHive(Clone) (BeeHive) produced n pollen, current pollen is a/b` | produced, current, max |
| `stat` | `[STATS] <key> = <value>` | key, value |
| `quest` | `[QUEST] Start quest X` / `Complete quest X` / `Complete goal X:g` | event, quest, goal or None |
| `day` | `[TRIGGER] OnDayStarted` / `[TIME] Day n` | day |
| `forecast` | `[TIME] Forecast is <W> today` | weather |
- The `[Dn h:mm:ss AM]` prefix → `day`, `hour` (float).
- `class LogReader(path, start=None)`: `new() -> list[Ev]` (its own read position; `start=None` = end of file now).

- [ ] **Step 1:** tests: one per table row on fixture lines (exact field values, e.g. `> water me=Player
  target=GardenBed (4) at (5.84, 0.10, -31.59)` → `Ev('action', 148, 21.67, …, {'name': 'water', 'target':
  'GardenBed', 'x': 5.84, 'z': -31.59})`); `test_unknown_line_is_none` (`'Waypoint Farm/Dog links to …'`);
  `test_reader_only_new_lines` (temp file, append, `new()` twice).
- [ ] **Step 2:** run `.venv/bin/python tools/test_runtime.py` → FAIL (no module).
- [ ] **Step 3:** implement (one ordered pattern table; first match wins).
- [ ] **Step 4:** run → OK.

### Task 2: `runtime/act.py` + `runtime/save.py`: actuators and the save

**Files:** Create `tools/runtime/act.py`, `tools/runtime/save.py`; Test: `tools/test_runtime.py`

**Interfaces — Produces:**
- `act.bind(wf)`; `act.click(x, y) -> str | None` (refuses with `'NO MOVE: a menu is open (…)'` via `wf.menu_open`,
  else `wf.go_to`), `act.key(k)`, `act.pause() -> bool`, `act.resume() -> bool` (check `state()['mode']` before and
  after; never a blind Escape: pause only from gameplay, resume only from the pause menu), `act.settle()`.
- `save.bind(wf)`; `save.crops() -> list[dict]` (x, z, state, wilted, watered — from `wf.farm_status()`),
  `save.inventory() -> dict[str, int]`, `save.reading() -> tuple[str, float, float]` (wraps `wf.pos()`; the only
  2.5 s call; counts itself in `save.READINGS`).
- [ ] **Step 1:** tests with a fake wf: `test_click_refuses_menu`, `test_pause_only_from_gameplay` (state = pause menu
  → `pause()` sends no key, returns True), `test_resume_only_from_pause_menu`, `test_crops_normalised` (`'##0'` →
  `'empty'`), `test_reading_counts`.
- [ ] **Step 2–4:** FAIL → implement → OK.

### Task 3: `world/entities.py` + `world/graph.py`

**Files:** Create `tools/world/__init__.py`, `tools/world/entities.py`, `tools/world/graph.py`; Test: `tools/test_world.py`

**Interfaces — Produces:**
- `@dataclass Entity(id, kind, area, x, z, r=0.6, solid=True, uses=list, state=dict, sources=list)`;
  `WALKABLE_KINDS = {'GardenBed'}` (solid False); `KIND_OF = {'BeeHive': 'BeeHive', 'GardenBed': 'GardenBed',
  'Well': 'Well', 'Bed': 'Bed'}` (log target → kind; unknown targets keep their own name as kind).
- `class Entities`: `observe(ev: Ev, area: str | None) -> Entity | None` (action/pathfail with a target and position
  → upsert; merge rule from Global Constraints; `area None` → held in `pending`, returned None), `add(kind, area, x, z,
  src, **kw)`, `find(kind=None, area=None, near=None, within=None) -> list[Entity]`, `explain(id) -> list`.
- `graph.build(entities, facts, places) -> networkx.DiGraph`: nodes = areas, places (learned), exits/anchors (from
  `nav.nodes(facts)` src exit/anchor/arrived/trail), entities; edges `connects` (exit→anchor, cost 5), `walk`
  (proven trail pairs from `nav.trail(facts)`, cost = length × 0.5), `contains` (area→node). Map-only places
  (`src == 'map'`) are **not** added (S18: no area guessing).
- `graph.route(G, start_area, goal_node) -> list[str] | None` (A* over connects+walk between areas).
- [ ] **Step 1:** tests: `test_two_hives_not_merged` (x 0.22 and 1.47), `test_same_hive_merged_sources` (two lines
  same position → 1 entity, 2 sources), `test_no_area_held` (area None → pending), `test_map_places_excluded`,
  `test_route_farm_to_beach_via_exit` (facts fixture: Farm exit → RuralBeach anchor).
- [ ] **Step 2–4:** FAIL → implement → OK. Add `networkx` with `uv add networkx` first.

### Task 4: `world/costmap.py`: layers and grid A*

**Files:** Create `tools/world/costmap.py`; Test: `tools/test_world.py`

**Interfaces — Produces:**
- `class Costmap(area, bounds=(x0, z0, x1, z1), cell=0.5)`: layers `solid`, `walls`, `refused`, `walked` (numpy
  arrays); `add_solid(x, z, r)`, `add_wall(x, z, dx, dz)` (blocks the cell and the next cell in direction dx, dz),
  `add_refused(x, z, game_hour)`, `add_walked(x0, z0, x1, z1)` (marks the cells on the segment), `cost(now_hour) ->
  ndarray` (inf for solid+inflation 0.5 and walls; refused cells inf until 1 game hour old; walked cells 0.5;
  unknown 1.0).
- `astar(cm, start (x, z), goal (x, z), now_hour, reach=0.0) -> list[(x, z)] | None` (8-connected; goal reached
  within `reach`; returns world points), `waypoints(path, hop=8.0) -> list[(x, z)]` (thin to points ≤ hop apart, keep
  turns).
- `build(area, entities, facts, now_hour) -> Costmap` (solid from entities, walls from `nav.walls(facts)` minus
  objects, refused from `no_move` facts with target, walked from `nav.trail(facts)` segments).
- [ ] **Step 1:** tests on the D149 hive row (hives x = -2.28 … 6.47 step 1.25 at z -23.46; bed 1 at (-1.7, -25.3);
  Tara at (-1.3, -21.7)): `test_path_goes_round_the_row` (path exists, every point ≥ 0.6 from every hive, its first
  turn is west of x -2.9), `test_no_path_when_enclosed` (a ring of solids → None), `test_refused_fades` (blocked at
  hour 10.0, free at 11.1), `test_waypoints_spacing`.
- [ ] **Step 2–4:** FAIL → implement → OK.

### Task 5: `world/belief.py` + `world/view.py`

**Files:** Create `tools/world/belief.py`, `tools/world/view.py`; Test: `tools/test_world.py`

**Interfaces — Produces:**
- `class Belief`: state area, x, z, `u` (std, units), `moving`, `in_reach`; `click(dx, dz)` (predict: x += dx,
  z += dz, u = sqrt(u² + (0.15 + 0.1·|d|)²)), `fix(x, z, sigma)` (Kalman update per axis with variance sigma²; log
  position sigma 0.05, bubble-in-reach sigma 1.0, save reading sigma 0.05), `scene(area, x=None, z=None)` (new area:
  position from the spawn/anchor if given, else unknown u=99), `needs_fix() -> bool` (u > 3.0),
  `predicted() -> (area, x, z, u)`. Uses `filterpy.kalman.KalmanFilter` (2-D, identity model) — add with `uv add
  filterpy`.
- `view.on_screen(H, belief, x, z, box=(200, 200, 1720, 980)) -> bool`; `view.click_point(H, belief, target, solids)
  -> (sx, sy) | None` (the target's screen point; if a solid entity's screen footprint (r → px via H) covers it,
  the point of the approach cell on the near side; None if H is None).
- [ ] **Step 1:** tests: `test_uncertainty_grows_then_fix` (10 clicks of 2 units → `needs_fix()`; one log fix →
  u < 0.1), `test_new_scene_unknown`, `test_click_point_avoids_hive_in_front` (bed behind a hive from Tara north of
  the row → the returned point maps to ground not inside any hive radius), `test_no_calibration_no_point`.
- [ ] **Step 2–4:** FAIL → implement → OK.

### Task 6: `world/__init__.py` World + shadow mode in the daemon + eval

**Files:** Create `tools/world/model.py`; Modify `tools/wf.py` (serve loop: after each command feed new log evidence
and our clicks into the world; `./wf world [entities|tara|route <goal>|explain <id>]`); Test: `tools/test_world.py`

**Interfaces — Consumes:** Tasks 1–5. **Produces:**
- `class World`: `observe(ev)`, `clicked(dx, dz)`, `reading(area, x, z)`, `where(name_or_id)`, `tara()`,
  `in_reach()`, `route(goal) -> list[(area, x, z)]` (graph between areas + costmap A* waypoints inside),
  `needs_fix()`, `entities(**filters)`, `explain(id)`; `World.load(facts, save)` rebuilds from the event logs.
- Eval hooks (component names exact): `world_belief` — when a reading arrives, `record` the world's predicted position
  vs the reading (hit ≤ 1.0 unit); `world_route` — when the old code's walk ends, `record` whether the world's
  predicted route existed (`route()` not None) and the walk arrived (both or neither = hit).
- [ ] **Step 1:** tests: `test_world_from_log_fixture` (feed the fixture: 7 hives + well + beds as entities in Farm
  after a `scene` Ev for Farm), `test_world_tara_follows_actions` (an `action` Ev at a bed → tara within 1.0 of it,
  u ≤ 1.0), `test_route_bed_from_strip` (the hive-row layout: route exists and avoids hives).
- [ ] **Step 2:** FAIL → implement → OK; then `./wf stop`, `./wf world entities` (sandbox off) lists the Farm hives,
  well and beds from the real log.
- [ ] **Step 3 (live, quest agent, supervised):** a tiny plan run `world-shadow`: resume, walk house → well → bed 3
  with the old `./wf goto` / game functions; afterwards `./wf eval` shows `world_belief` and `world_route` counts next
  to the old `belief`. Expected: world_belief rate > old belief rate on the same readings.
- [ ] **Step 4:** docs: AGENTS.md layout rows for `tools/runtime/`, `tools/world/`; learnings L84; spec removal ledger
  row `tools/nav/objects.json` → status "replaced by world entities (shadow), remove at M3".
