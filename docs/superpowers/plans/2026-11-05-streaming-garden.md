# Streaming Garden Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bubble-first streaming garden pass that inspects and immediately tends every bed with minimal model reasoning.

**Architecture:** The graph supplies traversal coverage; live bubbles/cards/events supply current state. A scheduler visits
one bed, immediately runs all enabled chores for it, rescans, and advances only after the bed is complete or safely
unresolved. Existing garden wrappers and a new `./wf garden` command share the scheduler.

**Tech Stack:** Python, unittest, existing `game.engine`, transition rows, affordance scanning, world graph.

**Spec:** `docs/superpowers/specs/2026-11-05-streaming-garden-design.md`

## Global Constraints

- Bubbles/cards/events, never plant appearance, establish watering/readiness state.
- Ready flowers are never harvested.
- No purchases, crop substitution, sleeping, or implicit empty-bed planting.
- Every new behavior is developed RED then GREEN.
- Preserve unrelated runtime graph/eval/navigation artifacts in the dirty worktree.

## Review Focus

- A bed with several chores completes them before traversal advances.
- A flower-ready bubble is visited but never harvested.
- An ambiguous drop routes from actual card/event feedback rather than a guessed state.
- Beds outside the requested region are never clicked or counted as covered.
- A missing seed or no-progress navigation returns unresolved coverage instead of claiming completion.

---

### Task 1: Streaming per-bed scheduler

**Files:**
- Modify: `tools/game/engine.py`
- Test: `tools/test_engine.py`

**Interfaces:**
- Consumes: graph GardenBed nodes, `affordances.scan`, transition rows and existing guarded navigation/step execution.
- Produces: `tend_garden(region, chores, answer=None, max_clicks=...) -> dict` with `visited`, `acted`, `flowers`,
  `unresolved`, chore counts, clicks, vision, and stop.

- [ ] **Step 1: Write failing tests** for immediate per-bed action ordering, flower skipping, region isolation, and
  unresolved coverage on missing seed/no progress. Assert real FakeGame click/event order and final bed state.
- [ ] **Step 2: Run the focused tests and verify RED** because `tend_garden` does not exist.
- [ ] **Step 3: Implement the minimal streaming scheduler**, reusing current bubble ownership, row execution, refill,
  evidence learning, and navigation guards. Log one `garden_visit` row per completed or unresolved bed.
- [ ] **Step 4: Run focused engine tests and verify GREEN.**
- [ ] **Step 5: Commit** with message `engine: tend garden beds in one streaming pass`.

### Task 2: Public garden command and default task routing

**Files:**
- Modify: `tools/game/garden.py`
- Modify: `tools/game/__init__.py`
- Modify: `tools/wf.py`
- Modify: `docs/routines.md`
- Test: `tools/test_engine.py`
- Test: `tools/test_wf_safety.py` or a focused CLI test module

**Interfaces:**
- Consumes: `engine.tend_garden` from Task 1.
- Produces: `garden.do(region='Garden', answer=None, max_clicks=...)`; CLI `./wf garden`; existing `water_all`,
  `harvest_all`, and `replant_all` route through the scheduler with their respective chore enabled.

- [ ] **Step 1: Write failing wrapper/CLI tests** proving `garden.do` enables `replant,harvest,water` in that order,
  single-task wrappers use the same scheduler, and CLI defaults to `Garden`.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Implement wrappers, CLI dispatch, concise output, and routine documentation.**
- [ ] **Step 4: Run focused tests, then the complete `tools/test_*.py` suite.**
- [ ] **Step 5: Commit** with message `garden: add one-command streaming maintenance`.

### Task 3: Separate perception logging from model vision

**Files:**
- Modify: `tools/game/brief.py`
- Modify: `tools/runwatch.py`
- Test: `tools/test_brief.py`
- Test: `tools/test_runwatch.py`

**Interfaces:**
- Consumes: the detector/heatmap portion of a decision brief.
- Produces: a `perception` run event summarizing detected kinds/points; existing `vision` events remain model questions.

- [ ] **Step 1: Write failing tests** proving heatmap detection logs `perception`, while a model question logs `vision`,
  and the watcher renders distinct labels.
- [ ] **Step 2: Run focused tests and verify RED.**
- [ ] **Step 3: Add the logging boundary without duplicating images or model calls.**
- [ ] **Step 4: Run focused and complete suites.**
- [ ] **Step 5: Commit** with message `logging: distinguish perception from model vision`.
