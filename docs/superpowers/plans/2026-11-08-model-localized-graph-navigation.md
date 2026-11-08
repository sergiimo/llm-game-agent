# Model-Localized Graph Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every navigation decision start from a compact vector-backed semantic localization and graph route, with model vision used only to create missing vector coverage and the map used only as the third-stage fallback.

**Architecture:** Extend the existing navigation receipt with a bounded `localization` packet containing the weak prior hint, current-frame vector landmarks expressed relative to Tara at frame centre, and the relevant graph route/slice. The gameplay model owns reconciliation and movement; the runtime exposes evidence and cascade stage without choosing the route. Update the play contract so existing vectors skip vision, a no-vector frame triggers model vision plus vector creation for a unique graph object, and only unresolved localization proceeds to the map.

**Tech Stack:** Python 3, existing object graph/vector detector, SQLite-backed universal turn loop, unittest.

**Spec:** `docs/superpowers/specs/2026-11-08-model-localized-graph-navigation-design.md`

## Global Constraints

- Follow canonical `requirements.md`, especially R1–R6.
- A restart begins with unknown semantic location; prior location is only a labelled hint.
- Vector detections are the primary usable localization evidence and suppress model vision.
- Model vision runs only when the current frame has no vectors and first attempts to create a vector for an identifiable unique graph object.
- The outdoor map is cascade stage 3 only.
- No engine guard chooses a semantic route; one model decision still performs at most one game input.
- Prompt/state projections remain bounded and must not grow with run history.
- Live Farm-to-Town gameplay is the acceptance boundary; no wrong/no-move action may be normalized.

## Review Focus

- A vector for an unrelated current-region object must still be exposed as usable localization evidence, not silently trigger vision.
- Multiple vectors must remain bounded and carry stable graph-node identity where available.
- A no-vector frame must explicitly request vision/vector creation before suggesting the map.
- A restart must not promote the previous belief from hint to current fact.
- The graph slice must contain the route edge that contradicted the failed `north toward the bridge` objective.

---

### Task 1: Bounded vector/graph localization receipt

**Files:**
- Modify: `tools/game/navigation.py`
- Modify: `tools/game/turn.py`
- Test: `tools/test_navigation_receipt.py`
- Test: `tools/test_turn.py`

**Interfaces:**
- Consumes: `navigation.receipt(task, observation, graph)` with current `candidates`, graph nodes/edges, active destination, and optional task-local navigation belief.
- Produces: `navigation.localization` with `stage`, `current`, `prior_hint`, bounded `landmarks`, and bounded `graph_slice`; each landmark includes node/kind, current-frame point, and its screen relation to centre-frame Tara.

- [ ] **Step 1: Write failing receipt tests**

Add tests asserting that a vector candidate for a unique graph node produces stage `vectors`, includes its node and screen-relative relation, retains the route edge, and does not request vision; a frame with no vectors produces stage `vision`, `current: unknown`, and `next: identify_unique_object_and_create_vector`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest test_navigation_receipt -v`
Expected: FAIL because `navigation.localization` is absent.

- [ ] **Step 3: Implement the compact localization projection**

Add private bounded helpers in `tools/game/navigation.py` for centre-relative landmark relations and route/visible-landmark graph slicing. Extend `receipt()` without reading files or capturing a second frame. Carry the packet through the existing `TurnContext.navigation`; do not duplicate it into history projections.

- [ ] **Step 4: Verify focused receipt/context tests GREEN**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest test_navigation_receipt test_turn -v`
Expected: new localization tests PASS; report any unrelated pre-existing failures by name.

### Task 2: Three-stage model-owned localization contract

**Files:**
- Modify: `.claude/skills/wylde-play/actions/navigation.md`
- Modify: `.claude/skills/wylde-play/actions/INDEX.md`
- Modify: `.claude/agents/wylde-quest.md`
- Test: `tools/test_brief.py`

**Interfaces:**
- Consumes: `NEXT.navigation.localization` from Task 1.
- Produces: an explicit agent workflow: vectors+graph → no-vector model vision and vector creation → unresolved outdoor map; then semantic belief update plus one route-serving action.

- [ ] **Step 1: Write failing contract tests**

Add assertions that navigation instructions make existing vectors suppress model vision, require vector creation from a vision-identified unique graph object before map use, name the map as stage 3, and require the belief’s next objective to follow the receipt graph route from the localized position.

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest test_brief -v`
Expected: FAIL on the missing strict cascade language.

- [ ] **Step 3: Update the gameplay contract**

Document the exact receipt fields and decision order. Remove language that permits vision when vectors exist or treats the map as the first ambiguity tool. State that a wrong returned vector is a vector-system defect and blocks route continuation until repaired.

- [ ] **Step 4: Verify contract and navigation tests GREEN**

Run: `PYTHONPATH=tools .venv/bin/python -m unittest test_brief test_navigation_receipt -v`
Expected: PASS.

### Task 3: Live Farm-to-Town acceptance and terminal retro

**Files:**
- Runtime data: `runs/<new-farm-to-town-run>/`
- Modify only for observed gaps: the smallest responsible runtime/skill/test file
- Create: `runs/<new-farm-to-town-run>/retro-1.md`

**Interfaces:**
- Consumes: the new localization receipt and agent contract.
- Produces: a clean live run reaching `Farm/LinkTown`, SQLite timing rows, and an R1–R6 retro.

- [ ] **Step 1: End the contaminated ten-turn benchmark and start a fresh single-goal Farm-to-Town run**

Confirm the clock is before 19:00; otherwise use the pre-approved sleep workflow first. Start from unknown operational belief.

- [ ] **Step 2: Execute the live route with one cheapest gameplay owner**

Before each movement, require receipt stage, semantic localization, graph next edge, and route-serving visible road. Stop and fix every refusal, wrong direction, no-move, or cascade violation before continuing.

- [ ] **Step 3: Verify the exact acceptance boundary**

Require captured `Farm/LinkTown` region/transition evidence. Nearby movement, bridge arrival, or a plausible frame does not pass.

- [ ] **Step 4: Record timings and terminal retro**

Summarize action and sub-call durations from SQLite, audit R1–R6, and suggest remaining system fixes to the user.

## Self-review

- Spec coverage: vector fast path, no-vector vision/vector creation, map stage 3, weak prior hint, bounded graph route, model-owned action, and live acceptance are each assigned.
- Type consistency: Task 2 consumes the exact `navigation.localization` packet produced by Task 1.
- Proportion: two focused implementation tasks plus one live acceptance task; no unrelated navigation refactor.
