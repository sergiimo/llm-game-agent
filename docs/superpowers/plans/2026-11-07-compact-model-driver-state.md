# Compact Model Driver State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep model-owned turns fast as a run grows by storing current durable state and evidence IDs in `task.json`, while retaining complete immutable evidence in the canonical journals.

**Architecture:** `task.json` contains current task/subgoal state, compact verified results, and experience IDs. `log.jsonl` remains the canonical intent/outcome envelope and `experiences.jsonl` the immutable raw replay journal. A fail-closed migration removes legacy inline outcome bodies only after proving the journals contain matching intent and outcome records; `NEXT` exposes a compact task view and labels cached observations.

**Tech Stack:** Python 3, dataclasses/JSON/JSONL, existing atomic `TaskStore`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-06-model-owned-gameplay-loop-design.md`

## Global Constraints

- One continuation performs zero or one physical input and never retries an uncertain input.
- Preserve complete immutable experience and intent evidence in canonical journals.
- Migration must fail closed before deleting an inline legacy outcome that cannot be reconstructed.
- Current live root, stack, financial reservations, verified results, and turn ID must survive migration.
- No explicit game pause for off-game work; losing focus freezes the game.

## Review Focus

- A 100-outcome run keeps `task.json` and `NEXT` bounded instead of embedding outcome bodies.
- Restart completion, cancellation, and surprise reconciliation reconstruct exact records from journals.
- A legacy task migrates once, preserves IDs/results, and refuses incomplete journal evidence.
- Cached `./wf play` output is visibly distinguished from a fresh versioned `read` observation.
- Physical actions keep write-ahead crash safety without serializing the whole history four times.

---

### Task 1: Compact history owner and fail-closed migration

**Files:**
- Create: `tools/game/history.py`
- Modify: `tools/game/task_state.py`
- Test: `tools/test_play.py`

**Interfaces:**
- Produces: `history.records(log_path, evidence_refs) -> list[dict]`, `history.compact(task, log_path) -> bool`, and `history.public_task(task) -> dict`.
- `TaskState.evidence_refs` owns root experience IDs; subgoals keep their existing `evidence_refs`.

- [ ] Write failing tests proving a legacy inline task migrates to IDs/results, reconstructs exact records, stays bounded, and refuses a missing journal row.
- [ ] Run the focused tests and verify the expected size/history failures.
- [ ] Implement journal indexing, compact public task projection, schema marker, and atomic one-time migration.
- [ ] Run the focused tests and verify green.

### Task 2: Make every runtime consumer use canonical records

**Files:**
- Modify: `tools/game/turn.py`
- Modify: `tools/game/play.py`
- Test: `tools/test_play.py`

**Interfaces:**
- Consumes: Task 1 journal record loader and compact task projection.
- Produces: completion, cancellation, observation reconciliation, and subgoal resume based on evidence IDs plus journal records; no inline `result.outcomes`.

- [ ] Write failing restart tests for sleep/trade completion, cancellation, and reconciliation using compact persisted state.
- [ ] Run them and verify failure on missing inline outcome bodies.
- [ ] Replace inline outcome accumulation with IDs and load records only at evidence-verification boundaries.
- [ ] Run the focused tests and verify green.

### Task 3: Bound the public turn and action persistence surfaces

**Files:**
- Modify: `tools/game/turn.py`
- Modify: `tools/game/play.py`
- Modify: `tools/game/primitives.py`
- Modify: `tools/test_play.py`
- Modify: `tools/test_runtime_data.py`

**Interfaces:**
- Produces: compact `NEXT`, explicit `observation_freshness`, and action persistence whose bytes do not scale with journal history.

- [ ] Replace the tests that require full history in `NEXT` with a failing 100-outcome size/action-bound test through the public CLI.
- [ ] Run it and verify RED against the current multi-megabyte shape.
- [ ] Use `public_task` in `TurnContext`; preserve WAL/final atomic saves while excluding archived journal bodies.
- [ ] Run focused latency, runtime, and task-state tests and verify green.

### Task 4: Update operating knowledge and migrate the live run

**Files:**
- Modify: `docs/superpowers/specs/2026-11-06-model-owned-gameplay-loop-design.md`
- Modify: `.claude/skills/wylde-play/actions/INDEX.md`
- Modify: `AGENTS.md` when present in the worktree, otherwise report the external instruction source.
- Modify: current run `task.json` through the tested atomic migration.

**Interfaces:**
- Documents: bare `./wf play` is cached; versioned `read` is fresh; unfocus freezes time without opening Pause.

- [ ] Update the spec and action skill to name the compact/journal ownership and freshness contract.
- [ ] Run the tested migration against a copy of the live task and compare root/turn/stack/financial fields and evidence IDs.
- [ ] Migrate the live task atomically only after the comparison passes.

### Task 5: Verification

**Files:**
- Test: existing owning suites.

- [ ] Run compact-state, turn, runtime, trade, cancellation, and recovery suites.
- [ ] Run the repository's broad test command and report every baseline failure by name.
- [ ] Run `CapturedAcceptance` separately; do not represent its three known live-evidence failures as passing.
- [ ] Run `git diff --check` and measure migrated `task.json` plus cached `NEXT` sizes.
