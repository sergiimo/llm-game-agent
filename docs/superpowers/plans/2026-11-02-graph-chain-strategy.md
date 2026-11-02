# Graph-Chain Strategy Implementation Plan

> **Status: superseded (L124, D184).** The runner this plan built (anchor, layout, camera-shift proof) was removed; see docs/mechanics/interaction-laws.md.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Garden skills act from a graph memory: a vision anchor fixes which node Tara is at and the visible states, then a runner moves node by node along pattern relations, checks each step against the predicted state, and asks vision on anything unexpected — with no positions anywhere.

**Architecture:** `tools/objects/graph.py` gains pattern cells, generated `neighbour` relations, confident states and a Tara node. New `anchor.py` (vision question + validated answer → graph) and `chain.py` (locate a neighbour tile by pattern fit, expectations, the task runner). `tools/game/garden.py` exposes `replant_all/water_all/harvest_all` on the runner; the position-based garden/affordance code is removed.

**Tech Stack:** Python 3.12 (`.venv`), unittest (`.venv/bin/python tools/test_<x>.py`), networkx (graph), existing DINOv2 detection (`tools/objects/detect.py`), PIL.

**Spec:** `docs/superpowers/specs/2026-11-02-graph-chain-strategy-design.md`

## Global Constraints
- **No positions:** no world x/z, screen projection, calibration, belief or `checkpoint`/`pos` in any new or changed code; log lines are read for their **event type** only.
- Member ids: `<Kind>@<Group region>#r<row>c<col>`, rows/cols 1-based, north row first, west to east (existing `pattern.order`).
- States: `phase ∈ {empty, growing, ripe, wilted}`, `crop` (name or None), `watered_today` (bool); hint shape `{value, game_time, source, conf}`, `source ∈ {vision, step, event, save-count}`; vision sets `conf=1.0`.
- Save is read **only** as per-group counts (`wilted`, `dry`, `ripe`, `empty`).
- Vision runs only at task start, on entering a region, and on unexpected events; every unexpected raises exactly one question (`NEED_VISION`), never a guess (AGENTS.md rule 9).
- Game functions keep `@action` + proofs; live game work is done by the quest agent (cheapest model), not in unit tests.
- Commits only when the user has asked for them in this run.

## Review Focus
1. **Only 1–2 tiles visible** (zoomed camera): pattern fit can't decide the neighbour → must raise vision, not click the nearest tile. Test in Task 3.
2. **Anchor answer names a label that isn't on the frame or a cell outside the pattern** (e.g. `r4c1` in a 3×4 group) → rejected with the expected shape. Test in Task 2.
3. **Day change** with a stale graph: `watered_today` hints from yesterday must not make `water_all` skip dry beds. Test in Task 1.
4. **Seeds of the wilted crop run out mid-task** (`pick_card` fails after Remove): the runner must stop with that bed recorded `phase=empty, crop=None` and report it, not continue. Test in Task 5.
5. **Can empties mid-chain** (`> out_of_water`): sub-task `fill_can`, re-anchor, return to the same pending node exactly once. Test in Task 5.

---

### Task 1: Graph cells, neighbours, confident states, Tara

**Files:**
- Modify: `tools/objects/graph.py` (Graph methods; `apply_log` loses positions)
- Modify: `tools/objects/graph/Farm.json` (migrate members; add `GardenBed@FarGarden` group with `pattern: null`; add `Tara` node)
- Modify: `tools/wf.py` (`graph sync` calls `apply_log(graph, lines, at=graph.state_value('Tara', 'at'))`)
- Modify: `tools/game/well.py:47` (`apply_log(g, [line], at=None)`: Well events need no member)
- Create: `tools/objects/migrate_cells.py` (one-shot: `GardenBed#<index>` → `GardenBed@Garden#r<r>c<c>` from `index` and the group's `cols`; drops `index`)
- Test: `tools/test_graph.py`

**Interfaces:**
- Produces:
  - `cell(member_id: str) -> tuple[int, int]` (row, col) from the id
  - `Graph.member_at(group_id: str, row: int, col: int) -> Node | None`
  - `Graph.neighbours(member_id: str) -> dict[str, str]` (`{'E': id, 'W': id, 'N': id, 'S': id}` present ones), generated from the group pattern, not stored
  - `Graph.hops(a: str, b: str) -> list[tuple[str, str]]` (list of `(direction, member_id)` steps along neighbours, same group; `[]` if a == b; None if not connected)
  - `Graph.set_state(id, key, value, game_time, source, conf=1.0)` (adds `conf`)
  - `Graph.phase(id) -> str | None`, `Graph.needs(group_id, pred) -> list[str]` member ids where `pred(node)` is true
  - `Graph.new_day(day: int)`: every `watered_today` hint whose game_time day ≠ `day` → `False`, `source='event'`
  - `apply_log(graph, lines, at: str)`: event types only; `> plant|water|unplant_impl` update the member `at` (the chain's current node), never a position
- Consumes: existing `Graph.load/save/members/set_state/state_value`

- [ ] **Step 1: Write failing tests** in `tools/test_graph.py`, class `Cells`:
  `test_cell_parses_id` (`cell('GardenBed@Garden#r2c3') == (2, 3)`); `test_neighbours_from_pattern` (3×4 group: `neighbours('…#r1c1') == {'E': '…#r1c2', 'S': '…#r2c1'}`; `r2c2` has all four); `test_hops_along_row_then_column` (`hops(r1c1, r2c3)` has length 3 and ends at `r2c3`); `test_set_state_keeps_conf`; `test_new_day_clears_yesterdays_watered` (hint at `D182` → `False` after `new_day(183)`, a `D183` hint stays `True`); `test_apply_log_uses_chain_node` (line `> water … at (9, 0, 9)` with `at='…#r2c1'` sets `watered_today=True` on `r2c1`; no position parsed); `test_migrated_farm_has_cells` (loaded `Farm.json`: every `GardenBed@Garden` member id matches `#r\dc\d`, no member has `index`, a `Tara` node exists, `GardenBed@FarGarden` group exists).
- [ ] **Step 2: Run** `.venv/bin/python tools/test_graph.py` → the new tests FAIL (AttributeError / KeyError).
- [ ] **Step 3: Implement** the Graph methods; write `migrate_cells.py` and run it once on `tools/objects/graph/Farm.json` (copy to a temp file in the test via `graph_copy`, as existing tests do). `neighbours` uses `pattern.rows/cols` of the member's group; `hops` walks columns first, then rows.
- [ ] **Step 4: Run** `.venv/bin/python tools/test_graph.py` and `tools/test_loop.py` → all PASS (update any loop test fixture that used `GardenBed#<n>` ids to the cell ids).
- [ ] **Step 5: Commit** (if approved): `git add tools/objects/graph.py tools/objects/migrate_cells.py tools/objects/graph/Farm.json tools/test_graph.py tools/test_loop.py && git commit -m "graph: pattern cells, neighbours, confident states, Tara (no positions)"`

### Task 2: Vision anchor — question, answer format, apply, save-count check

**Files:**
- Create: `tools/objects/anchor.py`
- Modify: `tools/wf.py` (command `anchor "<answer>"` → `anchor.answer(text)`; prints the applied changes or the rejection)
- Test: `tools/test_anchor.py`

**Interfaces:**
- Consumes: Task 1 `Graph.member_at/set_state/neighbours`, `cell`; `detect.Detection` (`point`, `box`)
- Produces:
  - `Anchor(group: str, at: tuple[str, str], states: dict[str, dict])` dataclass — `at=(label, member_id)`, `states[label] = {'member': id|None, 'phase': str|None, 'crop': str|None, 'watered_today': bool|None}`
  - `parse(text: str, labels: set[str], graph) -> Anchor` — raises `AnchorError(expected_shape: str)` on: unknown group, label not in `labels`, cell outside the pattern, unknown state word
  - `question(img, dets: list, task: str, graph, unexpected: str) -> tuple[str, dict]` — draws labels `A, B, …` (left→right, top→bottom) on tiles + Tara marker via `core.ask_vision`, returns `(prompt, {label: Detection})`, stores the label map for `answer`
  - `apply(graph, anchor, labels: dict, game_time: str) -> list[tuple[str, str, object]]` — sets `Tara.at`, member states (`source='vision'`, `conf=1.0`); unnamed labels get members from the pattern relative to `at` via `identity.assign`
  - `count_mismatch(graph, group: str, save_counts: dict) -> dict[str, tuple[int, int]]` — `{state: (graph, save)}` where they differ
  - `answer(text: str) -> str` — parse + apply the pending question; returns a one-line summary
- Answer grammar (exact): `group: <group>   at: <L>=r<R>c<C>   <L>=[r<R>c<C> ]<phase>[(<crop>)][ dry|watered] …   <L>=?`

- [ ] **Step 1: Write failing tests** `tools/test_anchor.py`: `test_parse_spec_example` (the spec §5 example → `at == ('B', 'GardenBed@Garden#r2c1')`, `states['B']['phase'] == 'wilted'`, `states['B']['crop'] == 'Green Bean'`, `states['C']['watered_today'] is False`, `states['E']['phase'] is None`); `test_rejects_unknown_label` (label `Z` not on frame → `AnchorError`, message contains `at: <L>=r<R>c<C>`); `test_rejects_cell_outside_pattern` (`B=r4c1` on 3×4 → `AnchorError`); `test_apply_sets_tara_and_states` (`Tara.at` = r2c1; r2c1 phase wilted, source vision, conf 1.0); `test_unnamed_labels_follow_pattern` (synthetic detections in a 2×3 grid, only `at` named → other labels mapped to neighbours of r2c1); `test_count_mismatch` (graph 3 wilted, save 4 → `{'wilted': (3, 4)}`).
- [ ] **Step 2: Run** `.venv/bin/python tools/test_anchor.py` → FAIL (module missing).
- [ ] **Step 3: Implement** `anchor.py` (regex parser per the grammar; label drawing on a copy of `img` with PIL; pending label map kept in the run dir as `anchor-pending.json` beside `core.ask_vision`'s frame) and the `wf anchor` command (one `elif cmd == 'anchor'` branch calling `anchor.answer`).
- [ ] **Step 4: Run** `tools/test_anchor.py` and `tools/test_wf_safety.py` → PASS.
- [ ] **Step 5: Commit** (if approved): `git add tools/objects/anchor.py tools/wf.py tools/test_anchor.py && git commit -m "anchor: structured vision answer applied to the graph"`

### Task 3: Locate a neighbour tile by pattern fit

**Files:**
- Create: `tools/objects/chain.py` (locate + expectations; runner in Task 5)
- Test: `tools/test_chain.py`

**Interfaces:**
- Consumes: Task 1 `Graph.neighbours/member_at`, `cell`; `identity.assign`, `identity.dedupe_for`; `detect.Detection`
- Produces:
  - `class Unexpected(Exception)` with `.why: str`
  - `locate(graph, at: str, target: str, dets: list) -> Detection` — fit `dets` to the group grid **relative to the tile nearest the frame centre = `at`** (camera follows Tara); return the tile whose (row, col) offset equals `cell(target) - cell(at)`; raises `Unexpected('pattern fit: …')` when fewer than 2 tiles are visible in the needed direction or the fit is ambiguous
  - `click_tile(det, bubbles) -> tuple[int, int]` — reuse `loop.click_point` (body away from bubbles)

- [ ] **Step 1: Write failing tests** in `tools/test_chain.py`, class `Locate`: `test_east_neighbour_on_full_grid` (synthetic 3×4 tile points, centre tile = r2c2 → `locate(.., r2c2, r2c3)` returns the tile right of centre); `test_two_steps_south_east` (target r3c3 from r2c2 → down-right tile); `test_only_one_tile_visible_is_unexpected` (Review Focus 1: a single detection → `Unexpected`); `test_target_out_of_view_is_unexpected` (target r1c4 with only the 2×2 around centre visible → `Unexpected`); `test_no_positions_imported` (`chain` module source contains none of `calib_load`, `checkpoint`, `world()`, `log_pos`).
- [ ] **Step 2: Run** `.venv/bin/python tools/test_chain.py` → FAIL.
- [ ] **Step 3: Implement** `locate` (cluster tile points into rows/cols with `identity._cluster`, take the cluster indices of the centre tile as `at`, index offset → tile) and `click_tile`.
- [ ] **Step 4: Run** `tools/test_chain.py` → PASS.
- [ ] **Step 5: Commit** (if approved): `git add tools/objects/chain.py tools/test_chain.py && git commit -m "chain: locate neighbour tiles by pattern fit"`

### Task 4: Expectations — bubble look and event type per predicted state

**Files:**
- Modify: `tools/objects/chain.py`
- Test: `tools/test_chain.py`

**Interfaces:**
- Consumes: `affordances.Affordance` (`kind`, `drop`, `pt`), Task 1 `Graph.phase/state_value`
- Produces:
  - `expected_bubble(graph, node_id) -> callable[[Affordance], bool]` — `wilted` or (`growing` and not `watered_today`) → `a.drop`; `empty` → `a.kind == 'plant'`; `ripe` → `a.kind == 'pickup'`; unknown phase → any bubble
  - `bubble_near(affs: list, tile_pt: tuple, max_dx=110, max_up=(40, 260)) -> Affordance | None` — the bubble above the clicked tile (screen-relative to the tile just clicked, not to the world)
  - `EVENTS = {'unplant': r'> unplant ', 'removed': r'> unplant_impl ', 'plant': r'> plant ', 'planted': r'totalPlanted\.', 'water': r'> water ', 'dry_can': r'> out_of_water ', 'pickup': r'> grab_item '}`
  - `event(mark: int, name: str, wait: float) -> str | None` — `core.seen(EVENTS[name], mark, wait)` without `at=`

- [ ] **Step 1: Write failing tests** class `Expect`: `test_wilted_expects_drop`, `test_empty_expects_plant_bubble`, `test_ripe_expects_pickup`, `test_unknown_phase_accepts_any`, `test_bubble_near_picks_the_one_above_the_tile` (two bubbles; the one 120 px above the tile wins, one 400 px away is ignored), `test_event_ignores_position` (fake log line with an arbitrary `at (…)` matches `water`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the four names above.
- [ ] **Step 4: Run** `tools/test_chain.py` → PASS.
- [ ] **Step 5: Commit** (if approved): `git commit -am "chain: predicted-state expectations"`

### Task 5: The runner and the garden tasks

**Files:**
- Modify: `tools/objects/chain.py` (`run`, `TASKS`)
- Modify: `tools/game/garden.py` (`replant_all`, `water_all`, `harvest_all`)
- Modify: `tools/game/__init__.py` (exports)
- Test: `tools/test_chain.py` (class `Runner`, with a `FakeGarden`)

**Interfaces:**
- Consumes: Tasks 1–4; `anchor.question`; `garden._finish_unplant`, `ui.pick_card`, `ui.press`, `well.fill_can`; `affordances.scan/click`
- Produces:
  - `TASKS: dict[str, Task]`, `Task(needs: callable[[graph, id], bool], act: callable[[graph, id, Affordance], None], done_events: tuple[str, ...])` for `replant`, `water`, `harvest`
  - `run(task: str, group: str, graph, seed: str | None = None, max_steps: int = 40) -> dict` — returns `{'done': [ids], 'skipped': [(id, why)], 'vision': n, 'steps': n}`; raises `loop.NeedVision` (prompt from `anchor.question`) when `Tara.at` is unknown or on `Unexpected`; after `./wf anchor …` the agent calls `run` again and it continues from the graph state
  - `garden.replant_all(seed=None)`, `garden.water_all()`, `garden.harvest_all()` — `@action` wrappers: `chain.run(<task>, 'GardenBed@Garden', graph)`, save the graph, return the summary
- Before the loop: if `Tara.at` is not inside `group`'s region, `loop.goto(Q(kind=<group kind>))` (existing region/relation route, no positions) then `Tara.at = None` → anchor.
- Runner order per iteration: `needs` list → pick fewest `hops` from `Tara.at` → for each hop: detect tiles, `locate`, click tile, `bubble_near` + `expected_bubble` (mismatch → `Unexpected`) → set `Tara.at` → at the target: `act` → `event` checks → `apply_log(graph, lines, at)`; `> out_of_water` → push `fill_can`, then `Tara.at = None` (re-anchor), resume the same pending node once.
- After the loop: `anchor.count_mismatch(graph, group, save_counts)` (save counts from `farm_status()` counts only); any mismatch → one `NeedVision` naming it, then return.

- [ ] **Step 1: Write failing tests** class `Runner` with `FakeGarden` (3×4 states; frame = tile points + bubbles derived from states; clicking a tile sets Tara there; clicking a bubble fires the log event for that tile; a Remove card + seed panel like `test_game.FakeGame`): `test_first_call_asks_anchor` (no `Tara.at` → `NeedVision`); `test_replant_all_fixes_every_wilted_bed` (after a scripted anchor answer: 3 wilted → all `growing`, `watered_today` True, `vision == 1`, no position read — patch `core.log_pos`-free: assert `FakeGarden.position_reads == 0`); `test_stale_hint_triggers_one_vision_then_continues` (graph says r1c2 dry but tile shows plant bubble → exactly one `NeedVision`, after answer the run completes); `test_seeds_run_out_marks_bed_empty_and_stops` (Review Focus 4: `pick_card` fails on the 2nd bed → result `skipped` has that bed with `why` containing `no seeds`, its phase `empty`, run stops); `test_out_of_water_fills_and_returns_once` (Review Focus 5: `fill_can` called once, the pending bed watered, re-anchor counted); `test_water_all_after_day_change` (Review Focus 3: yesterday-watered beds are watered again after `new_day`); `test_enters_region_before_anchoring` (Tara.at = `House` → `loop.goto` called once with kind `GardenBed`, then `NeedVision` anchor); `test_count_mismatch_asks_once` (fake save says 1 more wilted than the graph after the loop → exactly one `NeedVision` mentioning `wilted`).
- [ ] **Step 2: Run** `.venv/bin/python tools/test_chain.py` → FAIL.
- [ ] **Step 3: Implement** `TASKS`, `run`, and the three `garden.*_all` wrappers (graph path: `tools/objects/graph/Farm.json`; the test injects a copy).
- [ ] **Step 4: Run** `tools/test_chain.py`, `tools/test_game.py`, `tools/test_graph.py` → PASS.
- [ ] **Step 5: Commit** (if approved): `git add tools/objects/chain.py tools/game/garden.py tools/game/__init__.py tools/test_chain.py && git commit -m "chain runner: replant_all/water_all/harvest_all"`

### Task 6: Remove the position-based garden and affordance code

**Files:**
- Modify: `tools/game/garden.py` (delete `plant`, `water`, `water_next`, `_click_due_water_bubble`, `beds_due`, `unplant`, `replant`, `plant_visible`, `water_visible`, `replant_visible`, `_bed_at`, `_WATER_AT`, `Bed`/`beds`/`bed` position fields)
- Modify: `tools/game/affordances.py` (delete `_owner`, `BUBBLE_UP/DX` owner use, `SAME`, the belief readings in `scan()`/`use()`, `relevant()` target matching, `press()`; `scan()` returns kind/pt/highlighted/drop only)
- Modify: `tools/game/core.py` (delete `log_pos`; `seen(at=…)` parameter removed)
- Modify: `tools/objects/identity.py` (delete `member_from_log`, `_LOG`)
- Modify: `tools/game/__init__.py`, `docs/actions.md` (A18 → `replant_all`), `docs/mechanics/basic-actions.md`, `docs/routines.md` (water/replant via `*_all`)
- Test: `tools/test_game.py`, `tools/test_affordances.py`, `tools/test_graph.py` (delete tests of removed functions; keep `has_drop`, `pick_card`, `_finish_unplant`, vision tests)

**Interfaces:**
- Consumes: Task 5 `garden.*_all`
- Produces: no new names; after this task `grep -rnE "log_pos|_bed_at|_WATER_AT|member_from_log|calib_load|checkpoint\(|\.world\(\)" tools/game tools/objects` prints nothing

- [ ] **Step 1: Write the failing guard test** in `tools/test_chain.py`: `test_game_and_objects_have_no_position_code` — reads every `.py` under `tools/game` and `tools/objects` and asserts none contains `log_pos`, `_bed_at`, `_WATER_AT`, `member_from_log`, `calib_load`, `checkpoint(`, `.world()`.
- [ ] **Step 2: Run** `.venv/bin/python tools/test_chain.py` → FAIL listing the offending files.
- [ ] **Step 3: Delete** the code listed under Files; move the still-needed callers (`walk.py`, `move.goto`) to `loop.goto` / region relations where they served the garden, or leave `walk.py` untouched if it only serves non-garden trips (it is removed in the follow-up plan, see below).
- [ ] **Step 4: Run** all suites: `for t in test_chain test_anchor test_graph test_game test_affordances test_loop test_wf_safety test_runtime; do .venv/bin/python tools/$t.py; done` → all PASS.
- [ ] **Step 5: Commit** (if approved): `git commit -am "remove position-based garden/affordance code (spec 2026-11-02 §7)"`

### Task 7: Live check (quest agent, supervised)

**Files:**
- Create: `runs/<YYYYMMDD-HHMM>-graph-chain-replant/plan.md` (via `./wf run start`)
- Modify: `docs/actions.md` (A18 Expect from the run), `docs/learnings.md` (surprises)

- [ ] **Step 1:** Supervisor writes the run plan: `./wf resume`; `./wf py "replant_all()"` → expect `NEED_VISION` (anchor) → agent Reads the frame, answers `./wf anchor "…"` → `./wf py "replant_all()"` again until it returns; `./wf pause`; `./wf routines`.
- [ ] **Step 2:** Dispatch the quest agent (haiku). Done when: the result lists every wilted bed it had seeds for as done, `vision` ≤ number of surprises + 1, and the agent reports zero position reads (`./wf run report` has no `nav pos` events during the run).
- [ ] **Step 3:** Record Expect values in `docs/actions.md` A18 and any surprise in `docs/learnings.md`.

---

**Follow-up plan (not in this plan):** remove `tools/world/` (belief, costmap, view, zoom, entities with x/z), `tools/nav.py` coordinate routes, `tools/nav/*/calib.json`, `checkpoint`/`pos` in `wf.py`, and `game/walk.py` geometry (spec 2026-10-31 §10 step 5; spec 2026-11-02 §7 rows 1). It touches `wf.py`'s trip commands and needs its own plan once trips run on region relations.

---

## Revision B tasks (spec §10: vision gives the layout)
Global constraints above still apply. Additional: layout is stored in **frame pixels** on the group node (`layout`
extra: `{'pitch': [px, py], 'ref_offset': [dx, dy]}`); grid for the anchor image = columns `A–X` (80 px), rows `1–16`
(67.5 px) over 1920×1080; cell centre of `F8` = (5·80+40, 7·67.5+33.75); fit residual limit 0.35 × pitch; move-proof
tolerance ±0.4 pitch. Review Focus additions: (6) a phase-correlation peak on a near-uniform frame (night) must give
Unexpected, not a fake shift; (7) an anchor answer naming only one bed with no previous layout must be REJECTED.

### Task 8: Layout from the vision answer (anchor)
**Files:** Modify `tools/objects/anchor.py`, `tools/wf.py` (`ask_vision` anchor branch draws the A–X × 1–16 grid +
CENTRE marker on the full-size frame, no detector labels), `docs/actions.md` A18, `.claude/agents/wylde-quest.md`;
Test `tools/test_anchor.py`.
**Interfaces — Produces:** `parse(text, graph) -> Anchor` (grammar of spec §10: `group:`, `ref: r<R>c<C>@<cell>`,
beds `r<R>c<C>@<cell> <state>`; cell = `[A-X](1[0-6]|[1-9])`); `cell_point(cell: str) -> (x, y)`;
`fit_layout(beds: dict[member_id, (x, y)], ref: str, prev: dict|None) -> dict` (`{'pitch', 'ref_offset', 'residual'}`,
raises `AnchorError` when < 2 distinct cols and rows and no `prev`, or residual > 0.35 × pitch); `apply(graph, anchor,
game_time, scene=None)` sets `Tara.at = ref`, states, and the group's `layout`; `question(img, task, graph, unexpected,
core=None)` (no `dets`). Old label-based `parse/apply/_grid/_label_letters` removed.
- [ ] Step 1: failing tests — `test_parse_spec10_example` (the §10 example → ref `GardenBed@Garden#r1c2`, 5 beds,
  r3c1 phase None); `test_cell_point` (`F8` → (440, 506.25)); `test_fit_layout_from_four_beds` (beds at F8/L8/F12/L12
  → pitch ≈ (480, 270), ref_offset of r1c2@L8 ≈ (920−960, 506.25−540)); `test_single_bed_without_prev_rejected` (RF 7);
  `test_inconsistent_beds_rejected` (one bed 1 pitch off → residual > 0.35 → AnchorError); `test_apply_sets_layout_and_ref`;
  `test_real_ask_vision_anchor_grid` (real `wf.ask_vision` kind='anchor' → full-size image, grid letters drawn,
  prompt has `ref:` example and `./wf anchor`).
- [ ] Step 2: run `.venv/bin/python tools/test_anchor.py` → FAIL.
- [ ] Step 3: implement; least-squares fit with numpy (`x = ox + (col−col_ref)·px`, `y = oy + (row−row_ref)·py`).
- [ ] Step 4: run `tools/test_anchor.py`, `tools/test_wf_safety.py` → PASS. Step 5: commit.

### Task 9: Layout-based step and phase-correlation move proof (chain)
**Files:** Modify `tools/objects/chain_step.py`, `tools/objects/chain.py`; delete `tools/objects/lines.py` if unused;
Test `tools/test_chain.py` (FakeGarden renders a textured frame that scrolls with Tara).
**Interfaces — Consumes:** Task 8 group `layout`, `anchor.question(img, task, graph, unexpected, core)`.
**Produces:** `layout_point(graph, at, target) -> (x, y)` (raises `Unexpected('no layout')` without one);
`camera_shift(img0, img1) -> (dx, dy, peak)` (phase correlation on downscaled grayscale; `peak` = normalised
correlation peak); `prove_move(layout, shift, d)` raises `Unexpected('move not proved: …')` unless the shift is one
pitch opposite to `d` (±0.4 pitch; other axis < 0.4 pitch) and `peak ≥ 0.1`; a failed proof clears the group layout.
`run(task, group, graph, seed=None, max_steps=40, wf=None)` (no `detect_fn`). Before each step and before asking:
if not gameplay → `ui.close()`.
- [ ] Step 1: failing tests — `test_layout_point_east_neighbour`; `test_camera_shift_measures_scroll` (textured
  image shifted by (−480, 0) → dx ≈ −480 ± 8); `test_uniform_frame_is_unexpected` (RF 6: flat dark frames → peak
  < 0.1 → Unexpected); `test_overshoot_two_pitches_rejected`; `test_no_move_rejected`; the existing Runner tests
  ported to the textured FakeGarden (replant_all fixes every wilted bed, seeds run out, out_of_water, day change,
  region entry, count check); `test_open_card_closed_before_asking` (a card open at run start → `ui.close()` before
  the anchor question).
- [ ] Step 2: run `.venv/bin/python tools/test_chain.py` → FAIL. Step 3: implement. Step 4: run all suites
  (`test_chain test_anchor test_graph test_game test_affordances test_loop test_wf_safety test_runtime test_walk`)
  → PASS. Step 5: commit.

### Task 10: Live check B (supervised)
Same as Task 7 with the new anchor format: the agent answers `ref:` + beds by grid cell. Done when `replant_all()`
returns a summary, vision calls ≤ surprises + 1.
