# Universal Model Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing model-owned `TurnLoop` the only public gameplay driver, with every workflow expressed as
skill/document knowledge and every coded gameplay operation limited to one guarded input.

**Architecture:** Extend the current durable task into a stack of model-owned subgoals and expose it through one
`./wf play` turn API. Domain aliases construct or resume that task but never call legacy schedulers. Keep graph,
vectors, routes, policies, and saves as clues; keep Python actuators atomic; move workflow sequencing into the
`wylde-play` skill and action docs.

**Tech Stack:** Python 3, dataclasses/JSON, existing PIL/Vision capture, existing graph/vector stores, `unittest`,
existing daemon/run logging.

**Spec:** `docs/superpowers/specs/2026-11-06-model-owned-gameplay-loop-design.md`

## Global Constraints

- Preserve the current feature-branch commits and all live graph/vector/run artifacts before structural edits.
- Keep the game paused except during bounded live verification.
- One continuation performs zero or one physical input and returns control to the model.
- No public gameplay command may call a code-owned multi-step workflow.
- Movement counts as progress only when it reduces the active goal or yields relevant evidence.
- Every mismatch blocks further input until the model records a correction, gap, constraint, or human escalation.
- Graph/vector corrections preserve source frame, experience ID, model rationale, and provenance.
- Every player-visible action/workflow is documented in the `wylde-play` skill/action docs.
- `runs/<run>/log.jsonl` remains the one chronological reasoning/action timeline.
- Use strict RED → GREEN for every behavior change; run focused tests during fix cycles and one final gate at final SHA.

## Review Focus

- A legacy alias (`sleep`, `achieve`, `forage`, garden helpers) must return a turn without invoking its old loop;
  Task 1 pins this with dependency-spy tests on every registered gameplay alias.
- A waypoint that moves away from the goal, does not move, or produces irrelevant evidence must create a surprise;
  Task 1 tests all three outcomes and prohibits a second input.
- A graph/vector correction made from model vision must update only the named node/kind and remain replay-idempotent;
  Task 1 tests provenance, wrong-node refusal, and duplicate correction replay.
- Suspending garden for sleep/shop and restarting the daemon must preserve parent interaction, subgoal phase, and
  pending intent without repeating input; Task 1 tests every interruption boundary.
- A successful purchase must verify both inventory increase and money decrease before resolving blocked beds; Task 2
  pins this in a captured replay and the bounded live gate.

---

### Task 1: Hard-cut every gameplay command to one universal model-owned turn loop

**Files:**
- Create: `tools/game/play.py`
- Create: `.claude/skills/wylde-play/actions/INDEX.md`
- Create: `.claude/skills/wylde-play/actions/navigation.md`
- Create: `.claude/skills/wylde-play/actions/regions.md`
- Create: `.claude/skills/wylde-play/actions/sleep.md`
- Create: `.claude/skills/wylde-play/actions/shop.md`
- Create: `.claude/skills/wylde-play/actions/garden.md`
- Modify: `tools/game/task_state.py`
- Modify: `tools/game/turn.py`
- Modify: `tools/game/primitives.py`
- Modify: `tools/game/integrate.py`
- Modify: `tools/game/engine.py`
- Modify: `tools/game/sleep.py`
- Modify: `tools/game/garden.py`
- Modify: `tools/game/forage.py`
- Modify: `tools/game/nav.py`
- Modify: `tools/wf.py`
- Modify: `tools/wfc.py`
- Modify: `.claude/skills/wylde-play/SKILL.md`
- Modify: `docs/actions.md`
- Modify: `docs/mechanics/interaction-laws.md`
- Test: `tools/test_play.py`
- Test: `tools/test_turn.py`
- Test: `tools/test_engine.py`

**Interfaces:**
- Consumes: existing `TurnLoop`, `TurnContext`, `Decision`, `Recommendation`, `TaskStore`, `GameAdapter`, and
  `integrate.correct` contracts from commits through `f8fdf85`.
- Produces: `play.turn(goal: str | dict = None, params: dict = None, answer: object = None,
  store: TaskStore = None, adapter: GameAdapter = None) -> TurnContext`; `TaskState.stack: list[Subgoal]`;
  `Subgoal(goal, params, phase, status, parent_interaction, evidence_refs, result)`; domain aliases that call only
  `play.turn`; correction kinds `graph`, `appearance`, `transition`, `revise_decision`, `blocked_target`, `gap`, and
  `human` through the universal turn boundary.

- [ ] **Step 1: Preserve the live baseline**

  Pause/state-check the game; record current run/task IDs and `git status`; commit the approved revised design plus
  live graph/vector/action artifacts in one named baseline commit. Do not modify ignored run evidence.

- [ ] **Step 2: Write the universal-cutover RED tests**

  In `tools/test_play.py`, add tests named:
  `test_every_public_gameplay_alias_returns_before_input`,
  `test_aliases_never_call_legacy_workflow_drivers`,
  `test_one_decision_performs_at_most_one_input`, and
  `test_domain_alias_and_play_resume_the_same_task_id`.
  Enumerate the actual registered gameplay aliases from `tools/wf.py`; spy on `sleep.do`, `engine.achieve`,
  `nav.reach/search`, garden schedulers, and forage loops; assert zero calls.

- [ ] **Step 3: Run the cutover tests and verify RED**

  Run: `PYTHONPATH=tools .venv/bin/python -m unittest tools.test_play`
  Expected: FAIL because `game.play`, task stack, and hard-cut aliases do not exist.

- [ ] **Step 4: Add durable nested subgoals and universal entry point**

  Implement `Subgoal` and backward-compatible `TaskState.stack` serialization in `task_state.py`. Implement
  `play.turn(...)` as a thin constructor/resumer around the existing `TurnLoop`; it may select a pure domain clue/
  policy adapter from the goal, but it must not execute or select a next gameplay action. A parent interaction is
  frozen while a subgoal is active and restored only by an explicit model decision after verified subgoal completion.

- [ ] **Step 5: Hard-cut all public gameplay aliases**

  Route every gameplay alias registered by `tools/wf.py` through `play.turn`; keep observation-only commands unchanged.
  Convert legacy `sleep.py`, `garden.py`, `forage.py`, `engine.achieve`, and navigation entry points into private clue/
  atomic helpers or compatibility shims that return a turn. Add a dependency guard test that fails if a public alias
  invokes any legacy multi-input driver.

- [ ] **Step 6: Write RED tests for universal surprises and corrections**

  Add tests:
  `test_no_move_blocks_next_input_until_model_correction`,
  `test_movement_away_from_goal_is_not_progress`,
  `test_irrelevant_movement_is_not_progress`,
  `test_vision_graph_correction_updates_only_named_edge_with_provenance`,
  `test_vision_appearance_correction_reembeds_only_named_kind`, and
  `test_correction_replay_is_idempotent`.
  Assert the second input count remains zero while surprise is unresolved.

- [ ] **Step 7: Run the surprise/correction tests and verify RED**

  Run the six exact tests from Step 6.
  Expected: FAIL because movement relevance and universal graph/vector corrections are not yet enforced.

- [ ] **Step 8: Implement the universal outcome and correction boundary**

  Extend `TurnLoop`/`integrate.correct` so every primitive compares evidence with the active subgoal and emits a
  surprise for no progress, wrong region/object/modal, stale route/vector clue, missing evidence, or unexpected
  evidence. Implement graph/appearance correction validation and provenance; never mutate another node/kind and never
  perform input while correcting.

- [ ] **Step 9: Write RED tests for subgoal interruption and purchase authorization**

  Add tests:
  `test_garden_sleep_shop_return_survives_restart_at_every_boundary`,
  `test_pending_subgoal_intent_reconciles_without_repeat`,
  `test_shop_quantity_and_spend_require_task_authorization`, and
  `test_blocked_bed_reopens_only_after_verified_seed_acquisition`.

- [ ] **Step 10: Run the subgoal tests and verify RED**

  Run the four exact tests from Step 9.
  Expected: FAIL because parent suspension/resumption and evidence-backed unblock do not exist.

- [ ] **Step 11: Implement subgoal suspension, verification, and unblock**

  Add explicit push/suspend/complete/resume decisions to `play.turn`. Purchase completion requires inventory delta and
  money delta evidence. Only that verified result may remove matching seed-shortage constraints and return those beds
  to remaining coverage; it must not mark them planted, watered, or covered.

- [ ] **Step 12: Move every workflow into skill/action docs**

  Make `wylde-play/SKILL.md` route progressively to `actions/INDEX.md`. Document each workflow's recognition clues,
  prerequisites, atomic decisions, expected evidence, surprise/correction choices, and completion proof. Include the
  verified house rules: outside click the visible entrance/porch; after entering, the bed is west; exiting uses the
  interior opening then exterior stairs. State explicitly that docs choose sequences and Python never does.

- [ ] **Step 13: Run the focused Task 1 gate**

  Run:
  `PYTHONPATH=tools .venv/bin/python -m unittest tools.test_play tools.test_turn tools.test_garden_turn tools.test_screen tools.test_experience`
  and `git diff --check`.
  Expected: all pass; no warnings newly introduced; dependency guard proves no public legacy driver.

- [ ] **Step 14: Commit and task-review**

  Commit the complete hard cutover as one integrated change and obtain one task-scoped spec/quality review. Fix all
  blocking findings in one wave before Task 2.

### Task 2: Prove sleep, seed purchase, and garden return from captured and live evidence

**Files:**
- Create: `tools/fixtures/play/enter-house-sleep.json`
- Create: `tools/fixtures/play/sell-grown-buy-seeds.json`
- Create: `tools/fixtures/play/garden-shop-return.json`
- Modify: `tools/test_play.py`
- Modify: `.claude/skills/wylde-play/actions/INDEX.md`
- Modify: `.claude/skills/wylde-play/actions/navigation.md`
- Modify: `.claude/skills/wylde-play/actions/regions.md`
- Modify: `.claude/skills/wylde-play/actions/sleep.md`
- Modify: `.claude/skills/wylde-play/actions/shop.md`
- Modify: `.claude/skills/wylde-play/actions/garden.md`
- Modify: `docs/progress.md`
- Modify: `docs/learnings.md`
- Modify: `retros/stuck-ledger.md`
- Modify: current run report/retro artifacts

**Interfaces:**
- Consumes: Task 1 `play.turn`, durable `Subgoal` stack, universal surprise/correction boundary, atomic primitives,
  alias cutover, and action-skill docs.
- Produces: deterministic captured replays for sleep/sale/catalogue-purchase/return; final live evidence that the
  model alone drives garden → sleep → shop → garden; final verified branch ready for broad review/integration.

- [ ] **Step 1: Capture honest RED fixtures from the current run**

  Preserve the exact failed sleep sequence: house entry, incorrect waypoint answers, `moved=false`, overlay/card modes,
  frames, graph state, absent Bed vectors, and missing surprise. Capture the real shop sequence that sells grown
  Tulips and honey, enumerates every currently available seed type, and buys exactly 10 of each without inventing
  future evidence. Until the live run supplies it, keep the trade fixture explicitly incomplete and never assert
  success from synthetic outcomes.

- [ ] **Step 2: Write and verify replay RED tests**

  Add:
  `test_enter_house_wrong_bed_route_requires_vision_then_graph_or_vector_correction`,
  `test_sleep_replay_reaches_west_bed_and_proves_sleep_transition`,
  `test_sell_tulip_honey_and_buy_ten_each_available_seed_verifies_signed_inventory_and_money`, and
  `test_garden_shop_return_reopens_constrained_beds_without_false_completion`.
  Run each test before its fixture/behavior is complete and record the expected failure.

- [ ] **Step 3: Complete the smallest replay-backed fixes**

  Fix only gaps reproduced by the captured tests. Update the relevant action doc in the same change. Do not add a
  domain scheduler or encode screen coordinates as workflow policy.

- [ ] **Step 4: Run one bounded Luna-low live gate**

  Resume from preserved evidence in a fresh acceptance run. Required path: correct/remap the House→Bed clue after
  model vision; sleep; verify merchant capabilities during open hours (offline references point to Violet for Tulip/honey
  sales); sell grown Tulips and honey within observed stock; enumerate complete seed catalogues at both Violet and
  Dahl/Lina with merchant/type/availability source frames; deduplicate exact item IDs and buy a total of exactly 10
  of every unique available seed type
  subject to the verified sale proceeds/available-money guard; verify every signed inventory/money delta; return to
  GardenSouth; explicitly constrain/report insufficient funds without overspending or lowering quantities; reopen constrained beds; plant and water; continue remaining coverage. Parent watches `log.jsonl` and
  uses issue → pause → fixture → focused RED/GREEN → same-turn resume for any new gap.

- [ ] **Step 5: Verify pass criteria from the canonical log**

  Assert: one intent/experience per selected action; zero/one physical input; no legacy driver calls; every mismatch
  has look/correction/gap/human handling; Bed graph/vector correction has provenance; `sleep_transition` is observed;
  Tulip/honey sales and all ten-per-available-type purchases have matching signed inventory/money deltas; parent
  task/subgoal IDs survive; reopened beds are actually planted and watered; all garden targets end covered or
  explicitly constrained for a still-valid reason.

- [ ] **Step 6: Run the final offline gate once at final SHA**

  Run the compact architectural/replay suites plus the repository's basic CLI/engine suite, `git diff --check`, and
  report every known baseline failure by name. Do not restore scheduler-overfit tests.

- [ ] **Step 7: Update verified docs and commit**

  Update only facts proven by replay/live evidence, including action docs, progress, learnings, and stuck retro.
  Commit all requested tracked graph/vector/docs/code artifacts; keep ignored run evidence referenced by absolute path.

- [ ] **Step 8: Final review and integration**

  Use `superpowers:verification-before-completion`; dispatch one broad whole-branch review on the most capable model;
  fix blocking findings in one wave; rerun affected tests; then use `superpowers:finishing-a-development-branch` and
  integrate onto local `main` as previously authorized.

## Completion Criteria

- Every public gameplay command returns control to the model after zero or one input.
- All gameplay sequencing is discoverable in skills/docs; no Python function owns a multi-step player workflow.
- Navigation, sleep, shops, gardening, and subgoal transitions share one durable task/turn/surprise contract.
- Wrong route/vector/graph assumptions cannot lead to another input before model vision/correction.
- The captured and live garden → sleep → buy seeds → garden path succeeds with one canonical timeline.
