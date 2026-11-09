# Turn Latency Pass 1 Implementation Plan

> **Outcome (2026-11-09): rejected after live test.** Removing the fixed click delay reduced `turn.perform` from
> 1.193 s to 0.811 s, but the canonical settle then waited longer and `turn.capture` grew from 1.196 s to 1.773 s.
> Total measured engine time increased from 2.444 s to 2.650 s. The code and its provisional test were reverted.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the redundant fixed click delay and prove the reduction on the same live gameplay path.

**Architecture:** `GameAdapter.capture()` already owns post-input settling and returns the canonical settled frame. The low-level `run_action()` must therefore not add a second unconditional delay for click inputs; event dirtiness and scene-change bookkeeping remain unchanged.

**Tech Stack:** Python, unittest, canonical SQLite timing events, live Wylde Flowers gameplay.

**Spec:** `requirements.md` R3 and R5.

## Global Constraints

- Every live turn must eventually complete within 3 seconds end to end; this pass only removes the easiest measured bottleneck.
- One gameplay input per turn, with the existing settled outcome capture and evidence unchanged.
- Live gameplay is the acceptance test; unit tests are regression support only.
- Preserve the user's unrelated dirty worktree changes.

## Review Focus

- Click actions still mark the render segment dirty when no scene transition occurs.
- Click actions do not sleep before the canonical outcome settle begins.
- Non-click interaction actions retain any delay needed for scene-change accounting.
- Exactly one physical input is issued.
- Canonical timing continues to attribute perform and capture separately.

---

### Task 1: Remove the duplicate click wait

**Files:**
- Modify: `tools/wf.py`
- Test: `tools/test_runtime_data.py`

**Interfaces:**
- Consumes: `run_action(spec: str)` and `GameAdapter.capture()`'s existing settle contract.
- Produces: click actions return immediately after input and bookkeeping; capture remains the sole settle owner.

- [ ] **Step 1: Write the failing behavior test**

Add a test that runs a click through `run_action()`, records calls in order, and asserts that input and segment bookkeeping occur without an intervening fixed sleep. Keep scene-change and dirty-segment collaborators real where cheap; patch only macOS input/capture boundaries.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m unittest tools.test_runtime_data.<test-case> -v`

Expected: FAIL because current `run_action()` calls `time.sleep(0.5)` after a click.

- [ ] **Step 3: Implement the minimal branch change**

Change `run_action(spec: str)` so plain click navigation skips the unconditional delay while interaction actions that may open cards or cross scenes preserve their existing behavior. Do not modify settling, capture, focus, or evidence code.

- [ ] **Step 4: Verify GREEN and focused regressions**

Run: `.venv/bin/python -m unittest tools.test_runtime_data tools.test_turn tools.test_wf_safety -v`

Expected: PASS.

- [ ] **Step 5: Run one live action turn**

Use the active model-owned task for one safe, visible, same-surface waypoint before the 18:00 sleep boundary. Compare that turn's `turn.perform`, `turn.capture`, `server.dispatch`, and end-to-end values with turns 37–44 in `runs/wf.sqlite3`.

Expected: `turn.perform` falls by about 0.5 seconds, physical movement/evidence remains correct, and no extra input occurs.

- [ ] **Step 6: Record the measured result**

Append the before/after values and verdict to the active run's next `retro-N.md`. If the live action fails, revert this pass and preserve the failed timing as evidence.
