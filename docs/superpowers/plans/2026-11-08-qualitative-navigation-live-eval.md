# Qualitative Navigation and Live Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace coordinate-authoritative routing with qualitative graph navigation and add a SQLite-backed `bed-to-well` live evaluation.

**Architecture:** Static `nav` edges provide topology, compass, and qualitative range. Observation-local screen geometry is guarded against that guidance; clocks and coordinate evidence remain source-specific. A live-eval store derives comparable results from ordinary run observations, intents, and experiences.

**Tech Stack:** Python 3, SQLite, unittest, existing object graph and `./wf` CLI.

**Spec:** `docs/superpowers/specs/2026-11-08-qualitative-navigation-live-eval-design.md`

## Global Constraints

- Navigation planning never reads world coordinates, map pixels, homographies, or dead-reckoned positions.
- Coordinates may exist only in observation/SQLite diagnostic evidence.
- Every waypoint requires an active `navigate` goal; parent goals use nested navigation children.
- Save, log, and HUD clocks remain distinct and are refreshed, never locally advanced.
- Live evaluation results are SQLite-only and ordinary gameplay still uses one model-owned input per turn.

## Review Focus

- A dirty legacy scene fact must not alter a planned route or static anchor.
- A save timestamp older than the action must never become the action timestamp.
- A waypoint under garden/shop/sleep must issue zero input and request a navigate child.
- A missing compass/range hint must remain observable and must not invent numeric guidance.
- Re-reporting one live evaluation must be idempotent and must not duplicate checkpoints.

---

### Task 1: Separate observation clocks and remove live JSONL pollution

**Files:**
- Modify: `tools/game/play.py`
- Modify: `tools/game/primitives.py`
- Modify: `tools/nav/events.jsonl`
- Modify: `tools/nav/facts.jsonl`
- Test: `tools/test_play.py`
- Test: `tools/test_turn.py`

**Interfaces:**
- Produces: observation fields `hud_hour`, `log_time`, and `save_time`; top-level `game_time` remains a compatibility alias for `log_time` only.
- Consumes: coherent save/log snapshot and frame HUD clock.

- [ ] Write failing tests proving save time does not replace live log time and fresh reads refresh all clock sources.
- [ ] Run the focused tests and confirm the clock assertions fail.
- [ ] Implement source-separated clock fields without local advancement.
- [ ] Remove the two branch-added live JSONL rows.
- [ ] Run focused tests and confirm they pass.
- [ ] Commit `fix: separate gameplay observation clocks`.

### Task 2: Qualitative graph navigation and universal waypoint boundary

**Files:**
- Modify: `tools/objects/graph.py`
- Modify: `tools/objects/graph/Farm.json`
- Modify: `tools/game/navigation.py`
- Modify: `tools/game/play.py`
- Test: `tools/test_graph.py`
- Test: `tools/test_play.py`

**Interfaces:**
- Produces: `navigation.receipt(task, observation, graph=None)` with `next_edge.compass` and `next_edge.range`, and `navigation.assess(action, receipt)` using only screen-local qualitative geometry.
- Consumes: observed scene/region, static `nav` topology, current captured point.

- [ ] Write failing tests for `House -> HouseExit -> Farm -> Garden -> Well`, coordinate independence, qualitative range guarding, and refusal of a garden waypoint outside a navigate child.
- [ ] Run the focused tests and confirm each behavior fails for the intended reason.
- [ ] Add qualitative edge validation and the Farm/House/Garden/Well topology.
- [ ] Rewrite route receipts and assessment to remove coordinate/calibration/dead-reckoning authority.
- [ ] Enforce the universal navigate-child waypoint boundary.
- [ ] Run focused tests and confirm they pass.
- [ ] Commit `refactor: use qualitative topology for navigation`.

### Task 3: SQLite live evaluation for bed-to-well

**Files:**
- Modify: `tools/runtime/schema.py`
- Create: `tools/runtime/live_eval.py`
- Modify: `tools/wf.py`
- Create: `tools/test_live_eval.py`
- Modify: `tools/test_runtime_db.py`
- Modify: `docs/testing/INDEX.md`

**Interfaces:**
- Produces: `LiveEvalStore.start(scenario, run_id, revision)`, `checkpoint(eval_id)`, `finish(eval_id)`, `report(eval_id)`, and CLI `./wf live-eval start|status|finish|report|compare bed-to-well`.
- Consumes: `runs`, `run_events`, `observations`, `intents`, and `experiences` rows.

- [ ] Write failing schema/store tests for immutable checkpoints, idempotent reporting, and success only from fresh Well/Garden proof.
- [ ] Run the focused tests and confirm missing schema/store behavior fails.
- [ ] Add the SQLite migration and live-eval store.
- [ ] Write failing CLI tests for scenario validation and report/compare rendering.
- [ ] Run CLI tests and confirm the command is missing.
- [ ] Add the `live-eval` CLI and `bed-to-well` definition.
- [ ] Run focused tests and confirm they pass.
- [ ] Commit `feat: add sqlite live navigation evaluations`.

### Task 4: Integrate guidance, verify, and live-test safely

**Files:**
- Modify: `.claude/skills/wylde-play/SKILL.md`
- Modify: `.claude/skills/wylde-navigate/SKILL.md`
- Modify: `wiki/mechanics/interaction-laws.md`
- Modify: `docs/troubleshooting/INDEX.md`

**Interfaces:**
- Consumes: qualitative receipt and live-eval CLI from Tasks 2–3.
- Produces: one documented generic navigation workflow and a recorded live evaluation when the game state satisfies the start gate.

- [ ] Update instructions to require nested navigate children and prohibit coordinate-authoritative route decisions.
- [ ] Run focused navigation, graph, clock, runtime DB, and live-eval tests.
- [ ] Run the full unittest suite and inspect all failures/warnings.
- [ ] If the exact game clock is at or before 19:00 and Tara is coherently at home, run one `bed-to-well` live evaluation; otherwise record the unmet gate without gameplay input.
- [ ] Commit `docs: adopt qualitative navigation workflow`.
- [ ] Run final whole-branch review and address Critical/Important findings with RED→GREEN tests.

