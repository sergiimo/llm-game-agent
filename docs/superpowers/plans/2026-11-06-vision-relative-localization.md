# Vision Relative Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist model-vision direction and qualitative distance from Tara to a region and use it in later navigation briefs.

**Architecture:** Add a generic relative observation to the object graph. Parse optional localization metadata at the engine's vision-answer boundary, persist it before acting, and expose it in the next decision brief.

**Tech Stack:** Python, unittest, JSON object graph.

**Spec:** `docs/superpowers/specs/2026-11-06-vision-relative-localization-design.md`

## Global Constraints

- Do not manufacture exact world coordinates from vision.
- Preserve legacy answer syntax.
- Persist provenance and game time.

## Review Focus

- Invalid compass or distance values must be rejected before input.
- A waypoint answer must retain localization metadata while still clicking the requested cell.
- Plain `inside` must remain compatible.
- Relative evidence must survive graph save/load.
- Exact coordinate sources must retain priority.

---

### Task 1: Relative graph observation

**Files:** Modify `tools/objects/graph.py`; test `tools/test_graph.py`.

- [x] Add failing round-trip and direction-derivation tests.
- [x] Implement `observe_relative` and `relative_to`.
- [x] Run graph tests.

### Task 2: Vision answer integration

**Files:** Modify `tools/game/engine.py`, `tools/game/brief.py`; test `tools/test_engine.py`.

- [x] Add failing tests for structured `inside` and `walk` answers.
- [x] Parse and persist localization before the action.
- [x] Request and report localization in vision briefs.
- [x] Run focused and full tests (full suite retains one unrelated bubble-truth corpus failure).
