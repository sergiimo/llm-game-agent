# Unified Stop Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a user stop leave no managed gameplay agent or local automation capable of game input.

**Architecture:** Add a tested local shutdown boundary to `tools/wfc.py` for the daemon, recording thread, watcher,
and socket. Define the complementary supervisor protocol in the gameplay instructions, then record the discovered
cursor symptom and fix in the active retro.

**Tech Stack:** Python 3, `unittest`, macOS `pkill`/`pgrep`, Markdown operational contracts.

**Spec:** `docs/superpowers/specs/2026-11-07-unified-stop-contract-design.md`

## Global Constraints

- Do not terminate the Wylde Flowers process or unrelated Python/Codex processes.
- `./wf stop` must not contact or start the daemon.
- Use one game command per tool call.
- Preserve unrelated dirty-worktree changes.

## Review Focus

- No daemon or watcher exists: stop still succeeds and removes a stale socket.
- One target resists termination: every target is attempted and stop returns nonzero with the survivor.
- `pkill` or `pgrep` cannot execute: stop reports failure instead of claiming success.
- A watcher command includes an arbitrary run path: matching remains based on the owned executable name.
- Supervisor-managed agents remain outside CLI ownership and are explicitly verified by the supervisor.

---

### Task 1: Verified local automation shutdown

**Files:**
- Modify: `tools/wfc.py`
- Test: `tools/test_runtime_data.py`

**Interfaces:**
- Produces: `stop_local_automation(run=subprocess.run, unlink=os.unlink) -> tuple[list[str], list[str]]`, returning
  attempted target labels and survivor/error descriptions.
- Consumes: `LOCAL_AUTOMATION`, a tuple of `(label, process_pattern)` pairs.

- [x] **Step 1: Write failing tests** for all targets attempted, stale socket removal, survivor failure, and no daemon
  startup through `main()`.
- [x] **Step 2: Run** `uv run python -m unittest tools.test_runtime_data` and verify the new tests fail because the
  shutdown boundary does not exist.
- [x] **Step 3: Implement** the minimal shutdown boundary and route the `stop` CLI branch through it.
- [x] **Step 4: Run** the focused suite and verify it passes.

### Task 2: Supervisor stop protocol and retro

**Files:**
- Modify: `.claude/skills/wylde-supervise/SKILL.md`
- Modify: `AGENTS.md`
- Modify: `runs/20261107-1628-go-home/retro-1.md`
- Modify: `retros/2026-11-07-go-home-wrong-save-slot.md`

**Interfaces:**
- Consumes: TaskStop/collaboration interruption, zero-input durable-task stop, run closure, `./wf stop`, and OS process
  verification.
- Produces: one ordered response to a user stop that covers managed and local ownership without claiming one can do
  the other's job.

- [x] **Step 1: Add** the ordered stop protocol and explicit verification invariant to supervisor and root instructions.
- [x] **Step 2: Add** the cursor-jump root cause and unified-stop improvement/fix to both retro documents.
- [x] **Step 3: Inspect** the diff for contradictions with recording and watcher guidance.

### Task 3: Verification

**Files:**
- Test: existing repository suites

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: evidence that the CLI behavior, safety rules, and current stopped state agree.

- [x] **Step 1: Run** `uv run python -m unittest tools.test_runtime_data tools.test_wf_safety`.
- [x] **Step 2: Run** the repository's broad unittest command with a bounded timeout; report pre-existing failures by
  name rather than hiding them.
- [x] **Step 3: Run** an OS process query (not `./wf status`) and verify no local automation process remains.
- [x] **Step 4: Review** the final diff and status without modifying unrelated files.
