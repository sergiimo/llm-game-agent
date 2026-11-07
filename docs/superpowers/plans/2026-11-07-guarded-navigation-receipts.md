# Guarded Navigation Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove per-hop supervisor latency and prevent graph-compass contradictions before a navigation click.

**Architecture:** A pure navigation-receipt module joins the existing learned navigation graph, calibration, and
durable task estimate. The universal play loop exposes the receipt to the model, guards waypoint decisions, folds
proved moves into the estimate, and renders the same evidence into the human decision log.

**Tech Stack:** Python, unittest, existing `tools/nav.py`, durable `tools/game/turn.py` loop.

**Spec:** `docs/superpowers/specs/2026-11-07-guarded-navigation-receipts-design.md`

## Global Constraints

- One physical input per continuation.
- Calibrated world compass is authoritative over directional prose.
- Unknown route or calibration stays unknown.
- Preserve current dirty-worktree changes and the stopped gameplay task.

## Review Focus

- Unknown destination produces an unresolved receipt and no invented graph heading.
- Scene changes discard an estimate from the old coordinate frame.
- Missing calibration logs screen direction but does not reject a waypoint.
- A legitimate waypoint within one compass sector is accepted.
- A waypoint over one compass sector away is refused before input and logged with both headings.

---

### Task 1: Pure navigation receipt and waypoint assessment

**Files:**
- Create: `tools/game/navigation.py`
- Modify: `tools/nav/map.json`
- Test: `tools/test_navigation_receipt.py`

**Interfaces:**
- Produces: `receipt(task, observation) -> dict`, `assess(action, receipt) -> dict`, and
  `advance(task, experience) -> None`.

- [x] Write tests for resolved/unresolved destinations, calibrated compass, mismatch threshold, missing calibration,
      estimate advancement, and scene replacement.
- [x] Run the focused tests and verify RED.
- [x] Implement the minimum pure receipt/assessment/advance behavior.
- [x] Run the focused tests and verify GREEN.

### Task 2: Universal turn integration and readable evidence

**Files:**
- Modify: `tools/game/play.py`
- Modify: `tools/game/turn.py`
- Modify: `tools/test_turn.py`

**Interfaces:**
- Consumes: Task 1's receipt, assessment, and advance functions.
- Produces: `TurnContext.navigation`, pre-input navigate guard, canonical decision receipt, and timestamped readable
  Graph/Waypoint lines.

- [x] Write tests proving the model sees graph compass, contradictory input is not performed, and `decisions.md`
      contains graph and waypoint compass/alignment.
- [x] Run the focused tests and verify RED.
- [x] Integrate the receipt into context, guard, reducer, and decision logging.
- [x] Run focused and full turn/navigation tests and verify GREEN.

### Task 3: Remove ordinary per-hop supervisor handoff

**Files:**
- Modify: `.claude/skills/wylde-play/SKILL.md`
- Modify: `.claude/agents/wylde-quest.md`

**Interfaces:**
- Consumes: the model-visible navigation receipt and guard refusal.
- Produces: local child ownership of frame inspection and clear-road waypoint continuation.

- [x] Update the gameplay instructions so the child reads its own full-scale frame and continues ordinary hops.
- [x] Reserve escalation for unresolved route evidence, repeated guard refusal, or a real surprise.
- [x] Run relevant skill/static checks and the project test suite.

