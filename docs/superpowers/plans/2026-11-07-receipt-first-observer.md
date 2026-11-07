# Receipt-First Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each settled action receipt the coherent, compact next model view while retaining vector-first navigation and durable recovery.

**Architecture:** Introduce immutable view receipts at the adapter boundary, bind model decisions to captured candidates, and pass the post-action observation directly into the next turn. Incrementally cache world sources and emit only task-relevant projections; preserve existing task/experience persistence during migration.

**Tech Stack:** Python 3.12, Pillow, NumPy, DINOv2 object vectors, immutable dataclasses/JSON, unittest.

**Spec:** `docs/superpowers/specs/2026-11-07-receipt-first-observer-design.md`

## Global Constraints

- One primitive input maximum per decision.
- Every visual fact in a view comes from one full-resolution frame.
- Vectors remain the primary current-frame navigation evidence.
- Graph, save and log readers provide clues and proof; they never select an action.
- Stale screen-relative decisions issue zero input.
- Never repeat uncertain input after restart.
- Keep public gameplay aliases on the universal `play` boundary.

## Review Focus

- Camera/modal changes between model decision and input must produce `stale_view` with zero input (Task 3).
- Restart at intent/outcome/integration boundaries must preserve recoverability without replay (Task 6).
- Disabled, untrained, empty and failed vector searches must remain distinguishable (Task 4).
- Log rotation/save replacement/cache invalidation must rebuild once without stale facts (Task 5).
- Large graphs and hundreds of turns must not expand normal `NEXT` beyond the bounded projection (Task 5).

---

### Task 1: Reuse every action receipt as the next observation

**Files:**
- Modify: `tools/game/primitives.py`
- Modify: `tools/game/turn.py`
- Test: `tools/test_play.py`
- Test: `tools/test_turn.py`

**Interfaces:**
- Produces: `GameAdapter.take_outcome_observation(experience_id) -> dict | None`; `TurnLoop._finish(...) -> dict | None` for every action.

- [ ] Add failing tests proving one action's captured after-frame is exactly the next context frame and no third `observe()` occurs.
- [ ] Run the focused tests and confirm the current third observation fails them.
- [ ] Generalize the read-only receipt slot to every captured outcome and return it from `_finish()`.
- [ ] Pass that receipt to `_context(task, observation)` after an action.
- [ ] Run `test_turn`, receipt/latency tests, and the basic gate.
- [ ] Commit `perf: reuse action receipt as next model view`.

### Task 2: Make production observation single-frame coherent

**Files:**
- Modify: `tools/game/primitives.py`
- Modify: `tools/game/play.py`
- Modify: `tools/game/observe.py`
- Test: `tools/test_turn.py`
- Test: `tools/test_play.py`

**Interfaces:**
- Consumes: caller-owned PIL image from `GameAdapter.observe()`.
- Produces: `_clues(store, frame_context) -> dict`; no clue reader captures a frame.

- [ ] Add failing production-provider tests that reject hidden `WF.grab()` calls and duplicate log reads.
- [ ] Pass frame-derived hour/light and one already-read log snapshot into `_clues()`.
- [ ] Derive rain and scene from that snapshot; remove `observe.clock()` and repeated `today_log()` calls from `_clues()`.
- [ ] Preserve the no-argument clue-provider compatibility adapter only for tests/legacy read-only callers.
- [ ] Run coherence tests and the basic gate.
- [ ] Commit `perf: make observer clues single-frame coherent`.

### Task 3: Bind actions to immutable views and captured candidates

**Files:**
- Create: `tools/game/view.py`
- Modify: `tools/game/primitives.py`
- Modify: `tools/game/turn.py`
- Modify: `tools/game/params.py`
- Test: `tools/test_turn.py`
- Test: `tools/test_play.py`

**Interfaces:**
- Produces: `view.new_id(frame_path, image) -> str`; `view.candidates(observation) -> list[dict]`; action fields `view_id`, `candidate` or `control`.
- Produces: `GameAdapter.preflight(action, observation) -> prepared action` or `StaleView` before WAL/input.

- [ ] Add failing tests for stable candidate/control IDs and a changed camera/modal refusing input.
- [ ] Add immutable view IDs and candidate/control IDs to observations and `TurnContext`.
- [ ] Resolve target/control IDs from the persisted view; retain explicit coordinates only for free-ground waypoints.
- [ ] Implement a cheap scene/mode/frame-registration preflight that never performs full OCR/DINO/world refresh.
- [ ] Persist `view_id` and resolved ID in the intent; map stale preflight to a zero-input surprise/need.
- [ ] Run guard, modal, movement and stale-turn suites.
- [ ] Commit `feat: bind model actions to immutable views`.

### Task 4: Report effective vector scope and cache perception

**Files:**
- Modify: `tools/objects/store.py`
- Modify: `tools/objects/detect.py`
- Modify: `tools/game/observe.py`
- Modify: `tools/game/primitives.py`
- Test: `tools/test_objects.py`
- Test: `tools/test_turn.py`

**Interfaces:**
- Produces: `detect.inspect_scope(store, kinds, region) -> {searched, disabled, untrained}`.
- Produces: frame feature cache keyed by `(view_id, model_revision)` and store revision metadata.

- [ ] Add failing tests distinguishing disabled, untrained, no-match and detector error.
- [ ] Add effective-scope inspection without changing current competitor semantics.
- [ ] Cache one `Store`/sample revision per observer and one DINO feature tensor per view.
- [ ] Skip world-vector inference for modal-only views.
- [ ] Verify appearance corrections invalidate only affected store/vector revisions.
- [ ] Run object detection tests, observer tests and the basic gate.
- [ ] Commit `perf: cache vectors and expose effective scope`.

### Task 5: Incremental world snapshot and compact model projection

**Files:**
- Create: `tools/game/snapshot.py`
- Modify: `tools/game/play.py`
- Modify: `tools/game/history.py`
- Modify: `tools/game/turn.py`
- Test: `tools/test_play.py`
- Test: `tools/test_runtime_data.py`

**Interfaces:**
- Produces: `WorldSnapshot.refresh(save_reader, log_reader, graph) -> WorldDelta` with save/log/graph revisions.
- Produces: `snapshot.project(task, observation, world_delta) -> dict` containing relevant clues/resources only.

- [ ] Add failing tests for unchanged revisions avoiding reparsing, log rotation rebuilding once, and bounded context size.
- [ ] Implement revisioned save/log cursors and graph refresh invalidation.
- [ ] Project current ancestry, visible candidate hints, relevant exits/routes, active resources and changed/conflicting facts.
- [ ] Remove full graph serialization and accumulated internal task parameters from normal `NEXT`; retain explicit query APIs.
- [ ] Replace repeated workflow decoration with compact `result`, `need`, `view`, `memory`, `resources` fields while keeping trace rows.
- [ ] Run compact-history, world, graph, trade and garden suites.
- [ ] Commit `feat: emit compact revisioned world views`.

### Task 6: Settle-frame reuse, durability and final cutover

**Files:**
- Modify: `tools/wf.py`
- Modify: `tools/game/primitives.py`
- Modify: `tools/game/integrate.py`
- Modify: `.claude/skills/wylde-play/SKILL.md`
- Modify: `.claude/skills/wylde-play/actions/INDEX.md`
- Modify: `docs/mechanics/interaction-laws.md`
- Modify: `tools/basic_gate.py`
- Test: `tools/test_turn.py`
- Test: `tools/test_play.py`
- Test: `tools/test_experience.py`

**Interfaces:**
- Produces: settle result containing the final full frame; durable integration refuses to clear WAL on journal failure.

- [ ] Add failing tests proving settle's final frame becomes the receipt and journal failure cannot mark an experience applied.
- [ ] Return the final full frame from the settling boundary and eliminate the following capture.
- [ ] Make canonical intent/outcome/integration writes durable before clearing pending state; propagate evidence-write failures.
- [ ] Retire legacy universal-path `see_all()` error swallowing, full workflow display tests and redundant observation paths.
- [ ] Update gameplay docs to the receipt-first view/action contract.
- [ ] Run the fast gate, focused universal suites, full offline suite and `git diff --check`.
- [ ] Record the three known missing-live-evidence fixtures separately from implementation failures.
- [ ] Commit `feat: cut over to receipt-first observer`.

## Self-review

- Spec coverage: all normal, modal, surprise, correction, cache, restart and durability requirements map to Tasks 1-6.
- Type consistency: observation receipts flow Task 1→3; view IDs Task 3→5; vector scope Task 4→5; final settle/durability Task 6.
- Proportion: tasks specify interfaces and boundary tests without prescribing internal bodies.
- Execution: native sequential implementation is preferred because each task changes the contract consumed by the next.
