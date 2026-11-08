# Tracker-only Tara Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Tara appearance vectors from gameplay observations and waypoint authorization while retaining the fixed centre/feet tracker guard.

**Architecture:** `game.play._vector_scope` selects only graph object kinds. `GameAdapter` passes `exclude=('Tara',)`
through the observation adapter into detector competition while preserving the unresolved-region all-object fallback.
`GameAdapter.prepare` authorizes waypoints against the confirmed tracker candidate only; unknown frames no longer
depend on Tara vectors for classification.

**Tech Stack:** Python, unittest, existing object-vector and gameplay-turn framework.

**Spec:** `docs/superpowers/specs/2026-11-08-tracker-only-tara-navigation-design.md`

## Global Constraints

- Preserve the 240 px tracker clearance.
- Do not weaken modal, lineage, target-road, or movement-result checks.
- Use TDD and make no unrelated refactor.

## Review Focus

- A vector candidate labelled Tara cannot reject a waypoint.
- A tracker candidate labelled Tara still rejects a waypoint inside 240 px.
- Region scopes with and without learned kinds never inject Tara.
- An OCR-uncertain rendered frame remains unknown without independent positive world evidence.
- Object vector candidates remain available and unchanged.

---

### Task 1: Tracker-only Tara safety

**Files:**
- Modify: `tools/test_play.py`
- Modify: `tools/test_turn.py`
- Modify: `tools/game/play.py`
- Modify: `tools/game/primitives.py`

**Interfaces:**
- Consumes: `_vector_scope(graph, *candidates, learned_kinds=None) -> dict`; `GameAdapter.prepare(action, observation) -> dict`
- Produces: object-only vector scope and tracker-only waypoint clearance.

- [x] **Step 1: Write failing scope and guard tests**

Change the House scope expectation to `['Bed', 'HouseExit']`. Add a real `GameAdapter.prepare` test where a waypoint
is within 96 px of a `source='vector'` Tara candidate but over 240 px from `source='tracker'`, and assert preparation
succeeds. Add the inverse tracker-distance assertion.

- [x] **Step 2: Run focused tests and verify RED**

Run: `.venv/bin/python -m unittest tools.test_play.PlayCase.test_house_vector_scope_includes_the_learned_exit_and_bed tools.test_turn.Turns.test_waypoint_uses_only_confirmed_tara_tracker_for_clearance`

Expected: scope still contains `Tara`, and the false vector candidate rejects the waypoint.

- [x] **Step 3: Implement the minimal behavior**

Remove Tara injection from `_vector_scope`; remove the Tara-vector gameplay-classification branch; filter waypoint Tara
hits to confirmed tracker candidates; update comments and human-facing action guidance.

- [x] **Step 4: Run focused and gameplay suites**

Run the focused tests, `tools.test_play`, `tools.test_turn`, compilation, and `git diff --check`. Record any unrelated
pre-existing failures explicitly.
