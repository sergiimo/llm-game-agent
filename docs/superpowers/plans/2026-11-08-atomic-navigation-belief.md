# Atomic Navigation Belief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the gameplay model atomically replace its short-lived navigation belief and issue one action, while code enforces only evidence freshness, save lineage, clock safety, and input safety.

**Architecture:** Store one bounded `_navigation_belief` inside the active navigation task's SQLite payload. A decision carries `belief_update` beside its primitive; the turn boundary validates and persists that update before the primitive guard runs, and binds the primitive to the new belief revision and next objective. Graph, map, and vector outputs remain labelled evidence, never hard route authorities.

**Tech Stack:** Python 3 dataclasses, existing SQLite task store and universal gameplay turn loop.

**Spec:** `docs/superpowers/specs/2026-11-06-model-owned-gameplay-loop-design.md`

## Global Constraints

- Each continuation performs at most one game input.
- A gameplay task restart begins with unknown operational belief; historical state is advisory only.
- The selected save lineage, current frame/turn, menu safety, and the 19:00 sleep cutoff remain hard engine checks.
- At or after 19:00, ordinary navigation is refused and the model must make return-home/sleep its objective.
- Dynamic belief remains in SQLite task state, never `Farm.json`.
- Graph/map/vector readings are evidence for the model and cannot veto a coherent model-owned route decision.
- Per the user's explicit verification constraint, the only completion gate is a fresh live bed-to-well evaluation; do not run the offline test suite.
- Do not commit or push unless the user asks.

## Review Focus

- A stale frame or stale turn must not update belief or issue input.
- A save-lineage mismatch must permit only observation or stopping.
- A guard refusal may persist a valid belief update but must issue zero inputs.
- A surprise may be atomically replanned only from the current frame and must change the bound objective.
- The 19:00 cutoff must not block the home/sleep workflow itself.

---

### Task 1: Atomic model-owned navigation belief

**Files:**
- Modify: `tools/game/turn.py`
- Modify: `tools/game/play.py`
- Modify: `tools/game/navigation.py`
- Modify: `tools/runtime/run_reports.py`

**Interfaces:**
- Consumes: current `TurnContext`, task-local SQLite payload, navigation evidence receipt.
- Produces: validated `Decision.belief_update`, persisted `_navigation_belief`, and one action bound to its revision/objective.

- [ ] Add a bounded, replacement-only navigation belief schema with goal, assessment, current semantic location, confirmed/blocked/rejected/unknown evidence, and next objective.
- [ ] Require the current frame in `evidence_refs`, validate the goal against the active navigation task, persist the replacement belief before action preparation, and log its SQLite event ID/turn.
- [ ] Bind each navigation action to the new belief revision and exact next objective; allow a contradiction/no-progress surprise to use the same atomic replan-and-act boundary.
- [ ] Remove graph compass alignment as an action veto; retain it as advisory diagnostic evidence and as a post-action surprise signal.
- [ ] Expose belief plus clearly labelled graph/map/vector advisories in `TurnContext` and the human decision report.
- [x] Enforce the 19:00 cutoff for ordinary navigation while allowing explicit home/sleep navigation, and freeze the
  game automatically after each settled universal gameplay receipt so reasoning cannot drift past the cutoff.

### Task 2: Agent contract and live proof

**Files:**
- Modify: `.claude/agents/wylde-quest.md`
- Modify: `.claude/skills/wylde-play/actions/INDEX.md`
- Modify if a verified gap occurs: the smallest affected runtime/skill file and `retros/stuck-ledger.md`

**Interfaces:**
- Consumes: the atomic decision contract from Task 1.
- Produces: gameplay instructions that reconcile evidence into one belief before every navigation input.

- [ ] Document the exact decision JSON, evidence ordering, belief replacement semantics, atomic replan behavior, and the after-19:00 go-home/sleep rule.
- [ ] End the stale late-night evaluation, sleep, and begin a fresh unknown-state bed-to-well task on the new day.
- [ ] Run only the live bed-to-well evaluation with the existing cheapest gameplay agent.
- [ ] Analyze and fix every refusal, wrong-direction movement, no-progress episode, or inefficient action before resuming.
- [ ] Finish only when the live evaluation reports PASS and the human report shows belief → guarded action → outcome for each movement.

## Completion Criteria

- The model reconciles current visual, graph, map, vector, and outcome evidence into one task-local semantic belief.
- Belief replacement and its one primitive are one versioned decision; stale or contradictory evidence cannot race the input.
- Engine guards validate evidence freshness, lineage, time, menus, and primitive safety without choosing a route.
- No ordinary navigation continues at or after 19:00; the model returns home and sleeps.
- A fresh live bed-to-well evaluation passes.
