# M0: Eval, Benchmark, Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Count hits and misses of every prediction the toolkit makes, run three fixed benchmark tasks as normal
runs, and record today's numbers as the baseline that later migration steps (M1–M5) must beat.

**Architecture:** A small `tools/evals/` package (append-only prediction store + report) with hooks in the existing
code where predictions are already checked (dead reckoning vs reading, click moved vs refused, action proof, vision
answer moved her, stuck alarm). `./wf bench` opens an ordinary run directory from a plan template and scores it from
the run log, the nav events and the eval store. The baseline is recorded by the quest agent under supervision.

**Tech Stack:** Python 3.12 (`.venv`), stdlib `unittest` tests run as `.venv/bin/python tools/test_<x>.py`, JSON lines.

**Spec:** `docs/superpowers/specs/2026-10-30-agent-system-refactor-design.md` (sections 7, 9 M0)

## Global Constraints

- Tools never call an LLM; the agents are the only LLM (spec §1).
- Offline tests before live; the first live use is a plan step for the quest agent under supervision (spec §1).
- Run game commands with the sandbox disabled; one `./wf` game command per tool call (AGENTS.md rule 8).
- `./wf stop` after editing `tools/wf.py` (the daemon caches code).
- Commit only when the user asks (repo rule): "Commit" steps below = stage and list the files; commit on request.
- Package name `tools/evals/` (not `eval`, to avoid confusion with the builtin); the CLI is `./wf eval`.

## Review Focus

- Predictions that never get an outcome (Tara walked away, daemon restarted): the report must show them as pending,
  not as hits or misses.
- A run with no predictions (bench aborted at step 1): `bench report` prints zeros, not a crash.
- The daemon restarts mid-run: pending prediction ids live in the store file, not only in memory.
- Two benches of the same task: `bench compare` shows both rows with dates, newest last.
- Interrupts by the user are not machine-visible: they must be recordable by the supervisor (`./wf run interrupt`).

---

### Task 1: Prediction store and report (`tools/evals/`)

**Files:**
- Create: `tools/evals/__init__.py`, `tools/evals/store.py`
- Test: `tools/test_evals.py`

**Interfaces:**
- Produces:
  - `store.PATH` (default `tools/evals/predictions.jsonl`; tests point it at a temp file)
  - `predict(component: str, what: str, value, ctx: dict | None = None) -> str` (id `p<unix ms>-<n>`, appends
    `{"t", "id", "component", "what", "value", "ctx"}`)
  - `outcome(pid: str, value, hit: bool) -> None` (appends `{"t", "id", "outcome", "hit"}`)
  - `record(component: str, what: str, value, outcome_value, hit: bool, ctx=None) -> str` (prediction + outcome at
    once, for checks that happen in the same call)
  - `report(since: float | None = None) -> dict` → `{component: {"hits": n, "misses": n, "pending": n,
    "rate": float | None, "worst": [ctx of up to 3 latest misses]}}`
  - `format_report(rep: dict) -> str` (one line per component: `belief: 41/45 hits (91%) · 2 pending`)

- [ ] **Step 1: Write the failing tests** in `tools/test_evals.py`:
  - `test_predict_then_outcome_counts`: 3 predictions on `belief`, outcomes hit, hit, miss → `hits 2, misses 1,
    rate 0.667 (round 3)`.
  - `test_pending_is_not_scored`: one prediction without outcome → `pending 1`, `rate None`.
  - `test_record_shortcut`: `record('click', …, hit=False)` → `misses 1`.
  - `test_since_filters`: predictions before `since` are not counted.
  - `test_empty_store`: `report()` on a missing file → `{}`; `format_report({})` → `'no predictions yet'`.
  - `test_survives_reload`: predict, re-import / re-read the file, outcome → counted (ids are in the file).

- [ ] **Step 2: Run** `.venv/bin/python tools/test_evals.py` → FAIL (`ModuleNotFoundError: evals`).
- [ ] **Step 3: Implement** `tools/evals/store.py` (append-only JSONL; `report` joins predictions and outcomes by id;
  `worst` = the ctx of the latest misses). `__init__.py` re-exports the functions.
- [ ] **Step 4: Run** `.venv/bin/python tools/test_evals.py` → `OK` (6 tests).
- [ ] **Step 5: Commit** (on request): `tools/evals/*`, `tools/test_evals.py`.

### Task 2: Hooks in today's code + `./wf eval`

**Files:**
- Modify: `tools/wf.py` — `checkpoint()` (pred vs reading, ~line 1602), `note_click()` (moved / refused),
  `teach()` kind `step` (moved ≥ 1 unit), `track_point()` (stuck alarm), argparse + dispatch for `eval`
- Modify: `tools/game/core.py` — `action()` decorator (top-level action ok / failed)
- Test: `tools/test_evals.py` (hook mapping), `tools/test_game.py` (skills hook)

**Interfaces:**
- Consumes: Task 1 `predict`, `outcome`, `record`, `report`, `format_report`.
- Produces (components and their hit rule, exact):

| component | where | hit when |
|---|---|---|
| `belief` | `checkpoint()` when `pred` exists | `dist(pred, reading) <= 1.0` |
| `click` | `note_click()` | `moved` is True (False = miss; None = still moving, not recorded) |
| `skills` | `core.action` at depth 0 | the action returned without `Failed` |
| `ask` | `teach()` kind `step` | she moved ≥ 1.0 unit |
| `stuck` | `track_point()` raising `Stuck` | recorded as a prediction; outcome set by `./wf eval mark <id> hit\|miss` (the agent or supervisor judges whether she really was stuck) |

  - `wf.eval_cmd(args: list[str]) -> None`: `./wf eval` (report since the start of the open run, else all),
    `./wf eval all`, `./wf eval mark <id> hit|miss`, `./wf eval pending`.

- [ ] **Step 1: Write failing tests:**
  - `test_game.py::test_skills_hook_records_hit_and_miss`: with `evals.store.PATH` at a temp file, `game.replant(1)`
    on the fake → `report()['skills']['hits'] == 1`; `game.unplant(2)` (healthy) → `misses == 1`. Nested actions
    don't count (only depth 0).
  - `test_evals.py::test_belief_rule`: a helper `wf_belief_hit(pred, to) -> bool` (put it in `evals/store.py` as
    `belief_hit(pred: list[float], to: list[float], tol: float = 1.0) -> bool`) → `[0,0],[0.6,0.7]` hit,
    `[0,0],[1,1]` miss.
- [ ] **Step 2: Run** both test files → FAIL.
- [ ] **Step 3: Implement** the hooks (each wrapped in `try/except Exception: pass` — scoring must never break play)
  and `eval_cmd`; `./wf eval` prints `format_report(report(since))`.
- [ ] **Step 4: Run** `.venv/bin/python tools/test_evals.py`, `tools/test_game.py`, `tools/test_nav.py`,
  `tools/test_plan.py` → all `OK`. Then `./wf stop` and `./wf eval` (sandbox off) → prints a report (possibly
  `no predictions yet`).
- [ ] **Step 5: Commit** (on request).

### Task 3: `./wf bench` (templates, report, compare) + interrupts

**Files:**
- Create: `tools/bench/A.md`, `tools/bench/B.md`, `tools/bench/C.md` (plan templates in the plan.md format of
  `tools/plan.py`), `tools/bench/__init__.py` (scoring), results file `tools/bench/results.jsonl`
- Modify: `tools/wf.py` — argparse + dispatch `bench`; `RUN_NOTES` += `'interrupt'`
- Test: `tools/test_bench.py`

**Interfaces:**
- Consumes: `wf.run_cmd('start', …)`, `wf.run_events(path)`, `game.track.waits(events)`, `evals.report(since)`,
  nav events file `tools/nav/events.jsonl` (`what == 'pos'` = a save reading).
- Produces:
  - `bench.score(events: list[dict], nav_events: list[dict], evals_rep: dict) -> dict` with exact keys:
    `calls, real_min, game_min, thinking_s, readings, stuck, interrupts, escalations, steps_done, steps_total,
    eval` (`eval` = `{component: rate}`); `game_min` from the first/last `plan_step` `hour`; `stuck` = count of
    `type == 'stuck'` events; `interrupts` = `type == 'interrupt'`; `escalations` = `plan_step` with
    `state == 'escalate'`.
  - CLI: `./wf bench start A|B|C` (= `run start bench-<X>` + copies `tools/bench/<X>.md` to the run's `plan.md`),
    `./wf bench report [run dir]` (scores, writes `<run>/bench.json`, appends a row to `results.jsonl`),
    `./wf bench compare [A|B|C]` (table of rows: date, task, toolkit `git rev-parse --short HEAD`, the score keys).
  - Templates (steps with Do / Signal / Done when / Budget / If stuck, `./wf run plan` must pass):
    - **A. Garden day:** wake in the house → `./wf py "for b in beds(wilted=True): replant(b)"` →
      `./wf py "for b in beds(dry=True): water(b)"` → back to bed (A11). One step per line.
    - **B. Trips:** house → `farm-garden` → `well` → `ruined-ranch` (RuralBeach) → `fountain-square` (Town) →
      `farmhouse`; one step per leg with `./wf goto <place>`.
    - **C. NPC + menus:** go to Town, find Violet's Violets (`./wf key m`, look), `./wf pos --learn violets`, talk to
      Violet (A12), leave the menu. Tue–Sat 9–17 only.

- [ ] **Step 1: Write failing tests** in `tools/test_bench.py`:
  - `test_score_counts`: a synthetic run log (2 calls 1 s apart then 5 s gap, two `plan_step` with hours 7.0 and
    7.5, one `stuck`, one `interrupt`, one escalate) + nav events with 2 `pos` → `calls 2, game_min 30, readings 2,
    stuck 1, interrupts 1, escalations 1, thinking_s 5.0`.
  - `test_score_empty_run`: `[]` → all zeros, `steps_total 0`, no exception.
  - `test_templates_pass_review`: for X in A, B, C: `plan.review(open('tools/bench/X.md').read()) == []`.
- [ ] **Step 2: Run** `.venv/bin/python tools/test_bench.py` → FAIL.
- [ ] **Step 3: Implement** `bench.score`, the templates and the CLI; `./wf run interrupt <text>` works via
  `RUN_NOTES` (the supervisor logs each user interrupt with it).
- [ ] **Step 4: Run** all test files → `OK`; `./wf stop`; `./wf bench compare` → prints `no bench results yet`.
- [ ] **Step 5: Docs + commit** (on request): AGENTS.md layout rows for `tools/evals/` and `tools/bench/`;
  `wylde-supervise` §4 Review: "`./wf eval` and, for bench runs, `./wf bench report`; log each user interrupt with
  `./wf run interrupt <text>`"; learnings row L83 (eval + bench, baseline pending).

### Task 4: Baseline (supervised live runs, today's toolkit)

**Files:**
- Create: the run directories `runs/<ts>-bench-A/`, `runs/<ts>-bench-B/` (by the tool)
- Modify: `docs/superpowers/specs/2026-10-30-agent-system-refactor-design.md` §7.2 (baseline numbers + targets),
  `docs/progress.md` (session row)

**Interfaces:**
- Consumes: Task 3 CLI, Task 2 `./wf eval`, the supervisor flow (wylde-supervise §3/3a).

- [ ] **Step 1:** Supervisor: `./wf bench start A` → review `plan.md` (`./wf run plan` OK), show it to the user,
  dispatch the quest agent with the run's plan (game state: morning in the house; sleeping approved; no spending).
- [ ] **Step 2:** On escalations: stuck retro as usual (ledger), but **no tool changes during the baseline** (it
  measures today's toolkit); note the cause and continue or end the step. Log every user interrupt
  (`./wf run interrupt`).
- [ ] **Step 3:** `./wf bench report` → `bench.json` + a results row. Expected: a filled score dict (numbers, not
  zeros).
- [ ] **Step 4:** Same for B (`./wf bench start B`).
- [ ] **Step 5:** `./wf bench compare` → two baseline rows. Write them into spec §7.2 with the targets for M3
  (proposal: calls per bed ≤ ½ baseline, readings per trip ≤ ⅓, stuck 0, interrupts 0) and ask the user to confirm
  the targets.
- [ ] **Step 6: Commit** (on request): spec, progress, results.

C is run after M4 (it needs the `ask` protocol to be meaningful); its template exists from Task 3.
