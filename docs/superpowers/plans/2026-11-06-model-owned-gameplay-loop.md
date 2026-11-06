# Model-Owned Gameplay Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or
> superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the gameplay model own every observe → decide → one-action cycle, with atomic code primitives,
advisory graph clues, durable interaction transactions, and immediate evidence integration.

**Architecture:** Add a generic persisted task/transaction state and a one-turn controller API. Split transition
execution into pure next-step recommendations plus one-input primitives. Replace `engine.tend_garden()`'s hidden loops
with a garden domain adapter that supplies coverage and policy to the model-owned turn interface. Reuse `brief.py`,
`experience.py`, and `integrate.py`; keep `./wf garden` as the public entry point.

**Tech Stack:** Python 3, dataclasses/JSON, existing PIL/game capture stack, `unittest`, existing `./wf` daemon and run
logging.

**Spec:** `docs/superpowers/specs/2026-11-06-model-owned-gameplay-loop-design.md`

## Global constraints

- Before implementation, preserve the current dirty live fixes in a named commit or patch; do not overwrite them.
- Pause the game before coding and keep it paused until a bounded live gate.
- One continuation executes at most one game input.
- Persist intent before input and result after integration.
- A projection never establishes object identity; a positioned event does.
- Model vision is optional and model-selected; low-level code never invokes it.
- `runs/<run>/log.jsonl` is the one reasoning/action timeline.
- Keep only basic architectural tests plus one captured end-to-end replay; remove scheduler-overfit tests after the
  replacement gate is green.

---

### Task 1: Preserve the baseline and build the complete one-turn core

**Files:** current dirty live fixes; create `tools/game/task_state.py`, `turn.py`, `primitives.py`; modify
`tools/game/brief.py`, `steps.py`, `experience.py`, and `integrate.py`; add focused core tests.

- [ ] Pause the game. Run `git diff --check`, narrow existing garden tests, and preserve all current requested work as
      a named baseline commit before structural edits.
- [ ] Implement durable `TaskState`, `Interaction`, and `Intent` with atomic persistence, monotonic turn IDs, stale-turn
      rejection, and pending-intent reconciliation that never repeats an uncertain input.
- [ ] Implement immutable `TurnContext`, `Recommendation`, `Decision`, and `Surprise`. Context includes card/screen,
      full-scale frame path, visible affordances, graph clues with freshness/source, coverage, active transaction,
      last outcome, interrupts, recommendation, and allowed decisions.
- [ ] Split transition execution into pure next-step recommendation plus one-input primitives. A primitive persists
      intent, performs zero or one input, captures/integrates one experience, and persists the result; it never asks
      vision, chooses a target, or advances another step.
- [ ] Route all mismatches into a model-visible surprise. The model may request `look` or select world, appearance,
      transition, gap, unresolved, or stop correction. Apply representable corrections idempotently using the same
      experience ID; runtime never patches code.
- [ ] Log clues, recommendation, decision, intent, outcome, integration, and correction under one `turn_id` in the
      active `log.jsonl`.
- [ ] Add only contract tests: serialization/recovery, one-input invariant, stale accept refusal, optional look, late
      event-owned identity, and surprise routing. Run them plus `tools/test_experience.py`.
- [ ] Commit the integrated core and obtain one task-scoped spec/quality review.

### Task 2: Migrate garden end-to-end and prove the captured failure

**Files:** create `tools/game/garden_policy.py` and
`tools/fixtures/garden/tulip-collect-plant-water.json`; modify `engine.py`, `wf.py`, `ask.py`, and garden tests/docs.

- [ ] Extract the real tulip run's frames, events, cards, and experience IDs into one deterministic fixture containing
      evidence rather than inferred graph state.
- [ ] Implement garden as pure domain policy: coverage targets and recommendations only, with no input or model call.
      Preserve one active transaction across approach → inspect → collect/remove → plant → water → verify; carry crop
      across calls; bind the actual bed only from positioned events.
- [ ] Encode the agreed rules: ready hives/crops, protected flowers unless authorized, water-drop ambiguity, same-crop
      replant, any available crop when none requested, water after planting unless rain, sleep on rain/dark or a new
      task after 19:00, hard stop after 23:00, and refill when the can is empty.
- [ ] Replace `tend_garden()`'s `while remaining`, local `replanting`, target scheduler, and nested vision callbacks with
      `garden_turn`. Bare `./wf garden` observes and returns `NEXT`; a continuation executes exactly one primitive and
      returns the next context or terminal summary.
- [ ] Prove the fixture over separate calls: target tulip → `!` → Collect → harvest event → Seeds → choose Tulip →
      confirm → water → verify/cover. Every input has a distinct turn/intent/experience and an interruption at any
      boundary resumes the exact phase.
- [ ] Keep basic policy/identity/safety tests; remove old scheduler-order assertions that block the new public behavior.
- [ ] Run the focused core tests, captured replay, and basic engine/CLI suite; commit and obtain one task-scoped review.

### Task 3: Runtime cleanup, fast live fix cycle, and final review

**Files:** modify `tools/wfc.py`, run logging/watch code, remaining overfit tests, `docs/mechanics/interaction-laws.md`,
`docs/INDEX.md`, `AGENTS.md`, and verified progress/learnings/retro files.

- [ ] Make mutable learning data (`actions.json`, graph JSON, observations, embeddings) hot: it must not trigger daemon
      restart. Python and true schema/config changes still restart it.
- [ ] Make `runs/<run>/log.jsonl` the single reasoning/action timeline. Keep `experiences.jsonl` only as a machine replay
      journal and remove duplicate reasoning streams.
- [ ] Run the compact offline gate: core contracts, pure garden policy, captured replay, experience replay, and basic
      engine/CLI tests. Delete remaining tests that only preserve hidden scheduler internals.
- [ ] Start one bounded south-garden run driven by a `gpt-6-luna` low child while the parent watches `log.jsonl`.
      Required live loop: issue found → pause → preserve experience/frame → add/update replay → smallest fix → focused
      tests → immediately resume the same durable transaction. Do not restart the whole task.
- [ ] Pass criteria: every bed/hive covered; one intent/experience per input; no projected identity treated as fact;
      obvious recommendations accepted quickly; every surprise gets a model correction/gap choice; planting followed
      by water unless raining; no learning-triggered daemon restart.
- [ ] Update only verified docs and retro evidence. Run `superpowers:verification-before-completion`, dispatch one broad
      final review, fix its blocking findings in one wave, and commit all requested files on `main`.

## Completion criteria

- The gameplay model—not `tend_garden`, `steps`, or policy code—chooses every next action.
- A command performs no more than one input and always leaves a durable intent/outcome trail.
- Active phase, crop, provisional target, actual event-owned node, and completed actions survive every continuation.
- Graph/detector data is visible to the model with freshness/provenance but never owns identity or control.
- Any surprise is reviewed by the model and routed to data learning, a gap, or a human issue.
- The captured tulip trace and one live full garden pass succeed without hidden scheduler recovery logic.
- The complete reasoning/action history is reconstructable from one run `log.jsonl`.
