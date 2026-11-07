# SQLite Runtime Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SQLite the sole structured authority for runs, coherent save-profile observations, experiences, and
profile-local world state while retaining human Markdown reports and a version-controlled static map seed.

**Architecture:** `runs/wf.sqlite3` provides schema-versioned transactional storage. A task pins one save profile at
its first gameplay observation; every derivation and input references a validated immutable observation. Static JSON
loads first, then profile-scoped SQLite world facts overlay it. Historic file-backed runs are dropped at cutover.

**Tech Stack:** Python 3.12 standard-library `sqlite3`, SQLite WAL/foreign keys, `unittest`, existing dataclasses and
Markdown renderers.

**Spec:** `docs/superpowers/specs/2026-11-07-sqlite-runtime-store-design.md`

## Global Constraints

- SQLite is canonical after cutover; never dual-write SQLite and run-local JSON/JSONL.
- `plan.md`, retros, screenshots, and videos remain files; Markdown projections are never machine recovery inputs.
- Every gameplay derivation and input must reference one validated observation from the run's pinned profile.
- `save_lineage_mismatch` is zero-input and permits only `look`, `read`, or `stop`.
- Normal `.local` slot rotation is allowed only within the pinned profile and a monotonic game timeline.
- Runtime never writes dynamic state or local artifact paths into version-controlled graph JSON.
- Use short transactions; never hold a SQLite write transaction across OCR, capture, model reasoning, or input.
- One game command per tool call; live acceptance follows the repository supervisor rules.
- Preserve unrelated dirty-worktree changes. Commit only when the user asks.

## Review Focus

- Two profiles have plausible saves at task creation: fail closed instead of choosing newest mtime.
- Save and log rotate between observation and input: revalidate and issue zero input on contradiction.
- Process dies after physical input but before outcome commit: recovery captures/reconciles and never repeats input.
- Watcher reads while daemon commits: WAL readers remain responsive and event IDs are neither skipped nor duplicated.
- Historic file-backed records are not runtime inputs and must not regain compatibility readers.

---

### Task 1: SQLite foundation and schema

**Files:**
- Create: `tools/runtime/db.py`
- Create: `tools/runtime/schema.py`
- Create: `tools/test_runtime_db.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `Database(path: str)`, `Database.connect(readonly=False)`,
  `Database.transaction(immediate=False)`, `migrate(connection)`, and `DEFAULT_DB = runs/wf.sqlite3`.
- Produces the tables and constraints defined by the design spec, including schema checksums and foreign keys.

- [x] **Step 1: Write failing schema tests** proving migration from an empty file is idempotent; required tables,
  foreign keys, WAL, `synchronous=FULL`, and busy timeout are enabled; rollback leaves no partial rows; concurrent
  read during a write succeeds.
- [x] **Step 2: Run** `uv run python -m unittest tools.test_runtime_db` and verify RED because the database module and
  schema do not exist.
- [x] **Step 3: Implement** the minimal connection/migration layer with explicit transactions and no game imports.
- [x] **Step 4: Run** `uv run python -m unittest tools.test_runtime_db` and verify GREEN.
- [x] **Step 5: Checkpoint** the foundation; commit only if requested.

### Task 2: Canonical run lifecycle and event store

**Files:**
- Create: `tools/runtime/run_store.py`
- Create: `tools/test_run_store.py`
- Modify: `tools/wf.py:1014-1250`
- Modify: `tools/wfc.py:69-109`
- Modify: `tools/test_runtime_data.py`

**Interfaces:**
- Consumes: `Database` from Task 1.
- Produces: `RunStore.start(slug, goal, run_dir) -> run_id`, `active()`, `end(result, text)`,
  `append_event(type, payload, turn_id=None, phase=None, t=None) -> event_id`, `events(run_id, after_id=0)`, and
  `runs()`.
- Produces stable run IDs plus never-reused chronological event IDs; `active_run` replaces `.shots/run.current`.

- [x] **Step 1: Write failing tests** for start/abandon/end, one active run, event ordering, concurrent appends,
  explicit timestamps, run selection by ID/path, and rollback on a malformed event.
- [x] **Step 2: Run** `uv run python -m unittest tools.test_run_store tools.test_runtime_data` and verify RED.
- [x] **Step 3: Implement** `RunStore` and route `wf run start|step|attempt|issue|gap|decision|note|interrupt|end` plus
  `run_log` through it; keep `plan.md` creation and review unchanged.
- [x] **Step 4: Refactor** `wfc.log_end` to append its call event by active run ID without importing the game or
  starting the daemon.
- [x] **Step 5: Delete production writes** to `.shots/run.current` and run `log.jsonl`; retain no fallback writer.
- [x] **Step 6: Run** the focused tests and verify GREEN.
- [x] **Step 7: Checkpoint** the canonical run/event store; commit only if requested.

### Task 3: SQLite-backed durable task and write-ahead intent

**Files:**
- Modify: `tools/game/task_state.py`
- Modify: `tools/game/turn.py`
- Modify: `tools/game/play.py`
- Modify: `tools/test_turn.py`
- Modify: `tools/test_play.py`
- Modify: `tools/test_garden_turn.py`

**Interfaces:**
- Consumes: `RunStore` and the `task_state`, `intents`, and `run_events` tables.
- Produces: `TaskStore(db: Database, run_id: str)` with `create`, `load`, `compare_and_swap`, `begin_intent`,
  `record_capture`, and `settle`; exposes `run_id` and `run_dir`, not a JSON path.

- [x] **Step 1: Write failing task-store tests** for create/load, monotonic compare-and-swap revision, immutable task
  identity/profile pin, stale writer rejection, and rollback of task+event changes together.
- [x] **Step 2: Write failing crash tests** for death before input, after input/before capture, after capture/before
  integration, and after integration/before response; assert one physical input maximum and idempotent recovery.
- [x] **Step 3: Run** `uv run python -m unittest tools.test_turn tools.test_play tools.test_garden_turn` and verify the
  new tests are RED against file-backed `TaskStore`.
- [x] **Step 4: Implement** SQLite task payload storage and atomic prepared-intent/event creation before input.
- [x] **Step 5: Move** outcome capture and task advancement to transactional store methods; physical input remains
  outside transactions.
- [x] **Step 6: Remove** production creation/compaction of `task.json` and `garden-task.json`.
- [x] **Step 7: Run** the focused suites and verify GREEN.
- [x] **Step 8: Checkpoint** durable task/WAL migration; commit only if requested.

### Task 4: Experiences, history, integration, and gaps in SQLite

**Files:**
- Modify: `tools/game/history.py`
- Modify: `tools/game/integrate.py`
- Modify: `tools/game/turn.py`
- Modify: `tools/game/experience.py`
- Modify: `tools/test_experience.py`
- Modify: `tools/test_turn.py`
- Modify: `tools/test_play.py`

**Interfaces:**
- Consumes: run/turn/task stores from Tasks 2–3.
- Produces: `record_experience(run_id, experience)`, `history.records(store, evidence_refs)`,
  `claim_update(experience_id, consumer, op, args)`, `finish_update(...)`, `journal(run_id)`, `gaps(run_id)` and
  `replay(run_id)` using SQLite rows only.

- [x] **Step 1: Write failing tests** proving immutable experience IDs reject conflicting payloads, exact
  intent/outcome envelopes reconstruct by ID, applied updates are once-only across restart, and gap membership has
  foreign-key integrity.
- [x] **Step 2: Add a concurrency test** where two replay attempts claim the same update and only one consumer runs.
- [x] **Step 3: Run** `uv run python -m unittest tools.test_experience tools.test_turn tools.test_play` and verify RED.
- [x] **Step 4: Replace** `experiences.jsonl`, `applied.txt`, and run-local gap JSON writes with transactional tables.
- [x] **Step 5: Refactor** history and integration callers to pass store/run identity instead of filesystem paths.
- [x] **Step 6: Run** the focused suites and verify GREEN; assert no test fixture relies on production JSON writers.
- [x] **Step 7: Checkpoint** immutable journals and replay; commit only if requested.

### Task 5: Save-profile discovery, pinning, and coherent observations

**Files:**
- Create: `tools/runtime/save_lineage.py`
- Create: `tools/game/observations.py`
- Create: `tools/test_save_lineage.py`
- Create: `tools/fixtures/play/save-lineage-d4-town-vs-d219-farm.json`
- Modify: `tools/wf.py:3809-4020`
- Modify: `tools/game/play.py:38-92,500-570`
- Modify: `tools/game/turn.py`
- Modify: `tools/test_play.py`

**Interfaces:**
- Produces: `SaveCandidate(profile_key, path, file_id, digest, save_count, game_time, scene, decoded)`,
  `LogEpoch(file_id, first_time, last_time, lines)`, `select_profile(candidates, log_epoch)`, and
  `ObservationStore.capture(run_id, frame_context) -> ObservationSnapshot`.
- `ObservationSnapshot` carries `observation_id`, validation status, pinned profile/slot/log epoch, decoded save, exact
  log slice, frame/view identity, and mismatch details.

- [x] **Step 1: Capture the regression fixture** from the stopped go-home evidence: root D4 Town log/frame/save that
  pins D4 despite a newer-looking D219 profile, followed by a later read that supplies/requires D219 and expects a
  zero-input mismatch.
- [x] **Step 2: Write failing pure-selection tests** for unique coherent profile, ambiguous profiles, no coherent
  profile, another-profile newer mtime, same-profile slot rotation, backwards count/time, vanished slot, and continuous
  versus contradictory log rotation.
- [x] **Step 3: Write failing public-loop tests** proving task creation pins one profile; every later observation uses
  it; D4/D219 contradiction permits only `look|read|stop`; and a correction cannot rebind lineage.
- [x] **Step 4: Run** `uv run python -m unittest tools.test_save_lineage tools.test_play` and verify RED.
- [x] **Step 5: Refactor save access** to enumerate/decode candidates and select through `save_lineage`; remove
  latest-mtime selection from gameplay-task observations while keeping explicit-path diagnostic reads.
- [x] **Step 6: Implement** atomic task creation with profile pin plus root observation; insert mismatch observations
  before returning a restricted turn.
- [x] **Step 7: Add the pre-input guard** that revalidates pinned lineage/timeline without deriving clues or issuing
  input when it fails.
- [x] **Step 8: Run** focused tests and verify GREEN.
- [x] **Step 9: Checkpoint** the save-lineage invariant; commit only if requested.

### Task 6: One observation feeds every derivation

**Files:**
- Modify: `tools/game/play.py`
- Modify: `tools/game/snapshot.py`
- Modify: `tools/game/primitives.py`
- Modify: `tools/game/brief.py`
- Modify: `tools/objects/detect.py`
- Modify: `tools/test_play.py`
- Modify: `tools/test_runtime_data.py`

**Interfaces:**
- Consumes: validated `ObservationSnapshot` from Task 5.
- Produces: clue/vector/world APIs that accept the snapshot or `observation_id`; none independently read save/log.

- [x] **Step 1: Write failing dependency tests** that make any second `read_save()`/`today_log()` call raise while
  vector scope, world refresh, graph projection, recommendation, and intent preparation all succeed from one snapshot.
- [x] **Step 2: Write mismatch spies** proving `world.refresh`, vector detection, graph projection, recommendation, and
  adapter input are never called for an invalid observation.
- [x] **Step 3: Run** `uv run python -m unittest tools.test_play tools.test_runtime_data` and verify RED.
- [x] **Step 4: Thread** the immutable snapshot through world, vector, graph, recommendation, and intent paths; persist
  `observation_id` on their events/results.
- [x] **Step 5: Remove** independent live-file reads below the observation boundary.
- [x] **Step 6: Run** focused tests and verify GREEN.
- [x] **Step 7: Checkpoint** coherent derivation boundary; commit only if requested.

### Task 7: Static map seed plus profile-local world overlay

**Files:**
- Create: `tools/game/world_store.py`
- Modify: `tools/objects/graph.py`
- Modify: `tools/game/world.py`
- Modify: `tools/game/learn.py`
- Modify: `tools/game/integrate.py`
- Modify: `tools/wf.py` (`graph` CLI)
- Modify: `tools/objects/graph/Farm.json`
- Modify: `tools/test_graph.py`
- Modify: `tools/test_engine.py`
- Modify: `tools/test_experience.py`

**Interfaces:**
- Consumes: pinned profile and observation IDs plus world tables from Task 1.
- Produces: `WorldStore.load(seed_path, profile_id, observation_id) -> Graph`, `append_fact`, `upsert_local_node`,
  `upsert_edge`, and `promote(candidate_ids, seed_path)`.

- [x] **Step 1: Write failing classification tests** enumerating allowed seed fields and proving crop state, Tara
  position/region, refresh conflicts, experience lists, interaction hints, appearance samples, and temporary paths are
  profile-local rather than serialized into the seed.
- [x] **Step 2: Write failing overlay tests** for seed → local nodes/edges → latest valid facts precedence, profile
  isolation, observation-time cutoff, and provenance retention.
- [x] **Step 3: Write failing promotion tests** proving only explicit reviewed structural candidates reach JSON and
  dynamic/local fields are rejected.
- [x] **Step 4: Run** `uv run python -m unittest tools.test_graph tools.test_engine tools.test_experience` and verify RED.
- [x] **Step 5: Implement** `WorldStore`; make runtime graph save operations append SQLite facts/edges instead of
  rewriting `Farm.json`.
- [x] **Step 6: Clean the seed** through a reviewable migration: classify every removed field and import its local
  value/provenance before changing JSON.
- [x] **Step 7: Add** `wf graph promote <candidate-id>...` with dry-run diff and explicit field allowlist.
- [x] **Step 8: Run** focused tests and verify GREEN.
- [x] **Step 9: Checkpoint** world overlay/promotion; commit only if requested.

### Task 8: Watcher, reports, and human Markdown projections

**Files:**
- Modify: `tools/runwatch.py`
- Modify: `tools/wf.py` (`run status|report|waits|export`)
- Modify: `tools/game/turn.py` (human projection hook)
- Create: `tools/runtime/run_reports.py`
- Modify: `tools/test_runwatch.py`
- Modify: `tools/test_turn.py`
- Modify: `tools/test_plan.py`

**Interfaces:**
- Consumes: ordered SQLite run events and task/observation/experience IDs.
- Produces: `events_after(run_id, event_id)`, `render_progress(run_id, plan)`, `render_decisions(run_id)`,
  `render_report(run_id)`, and diagnostic-only `export_jsonl(run_id, stream)`.

- [x] **Step 1: Write failing watcher tests** for polling by event ID, reconnect without duplicates, events committed
  during a read, terminal run detection, and garden tables from queried rows.
- [x] **Step 2: Write failing projection tests** asserting `progress.md` cites step/event IDs and `decisions.md` cites
  observation/decision/intent/experience/integration IDs while remaining understandable without opening SQLite.
- [x] **Step 3: Write a failure-isolation test** proving Markdown rendering failure does not roll back a canonical event.
- [x] **Step 4: Run** `uv run python -m unittest tools.test_runwatch tools.test_turn tools.test_plan` and verify RED.
- [x] **Step 5: Refactor** watcher and report commands to query SQLite; regenerate Markdown atomically as a best-effort
  projection.
- [x] **Step 6: Add** explicit `wf run export --jsonl <run>`; assert no production reader consumes its output.
- [x] **Step 7: Run** focused tests and verify GREEN.
- [x] **Step 8: Checkpoint** human reporting and watcher migration; commit only if requested.

### Task 9: Drop historic records and finish the no-fallback cutover

**Files:**
- Modify: `tools/game/history.py`
- Modify: `tools/game/integrate.py`
- Modify: `tools/game/play.py`
- Modify: `tools/runwatch.py`
- Modify: `tools/test_runtime_data.py`

**Interfaces:**
- Consumes: the user's explicit decision to discard historic machine records.
- Produces: SQLite-only runtime readers/writers with no legacy structured-file fallback.

- [x] **Step 1: Move the only historic run directory to Trash**; do not import its contradictory D4/D219 state.
- [x] **Step 2: Remove importer work and obsolete file-tail/import tests.**
- [x] **Step 3: Write a source guard test** rejecting production references to `task.json`, `garden-task.json`,
  `log.jsonl`, `experiences.jsonl`, `applied.txt`, and `.shots/run.current`.
- [x] **Step 4: Remove** all runtime fallback readers for replaced structured files.
- [x] **Step 5: Deduplicate inherited gameplay tests that repeated every base contract in 19 subclasses.**
- [x] **Step 6: Run** focused tests and verify GREEN.
- [x] **Step 9: Checkpoint** the no-dual-write cutover; commit only if requested.

### Task 10: Documentation, full verification, and captured acceptance

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/architecture/INDEX.md`
- Create: `docs/architecture/runtime-store.md`
- Modify: `docs/architecture/self-improvement.md`
- Modify: `docs/ui/game-files.md`
- Modify: `docs/troubleshooting/INDEX.md`
- Modify: `.claude/skills/wylde-supervise/SKILL.md`
- Modify: `.claude/agents/wylde-quest.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: operator documentation for database location, backup/integrity checks, lineage mismatch,
  reports, map promotion, and recovery.

- [x] **Step 1: Update docs** so SQLite is the sole structured authority; remove claims that `log.jsonl`,
  `experiences.jsonl`, task JSON, or graph JSON own dynamic runtime data.
- [x] **Step 2: Add operational commands** for `PRAGMA integrity_check`, database backup, run export,
  mismatch diagnosis, and explicit map promotion.
- [x] **Step 3: Run focused suites:**
  `env PYTHONPATH=tools uv run python -m unittest tools.test_runtime_db tools.test_run_store tools.test_save_lineage tools.test_runtime_data tools.test_turn tools.test_play tools.test_experience tools.test_runwatch tools.test_graph`.
- [x] **Step 4: Run** `uv run python -m unittest discover -s tools -p 'test_*.py'` with the game unfocused; report every
  pre-existing failure separately and fix any regression caused by this plan.
- [x] **Step 5: Run captured acceptance** on the D4 Town/D219 Farm fixture: assert root selection pins D4 regardless
  of D219 mtime, then the later cross-lineage read produces one mismatch observation ID, zero
  vector/world/recommendation/input side effects, and `look|read|stop` only.
- [x] **Step 6: Run offline end-to-end acceptance** in a temporary database: start run → pin profile → create turn →
  prepare/capture/settle one fake input → restart → watcher/report/projections → end run → integrity check.
- [x] **Step 7: Run supervised live read-only acceptance** before any navigation retry: start a fresh run, create a
  task from the active game, verify its coherent profile pin or fail-closed mismatch, observation IDs, and human
  projections, then stop without input. The live save was stale relative to the D4 log, so acceptance exercised the
  zero-input `no_coherent_profile` path rather than pinning an incoherent profile.
- [x] **Step 8: Review** the final diff for unrelated graph/data changes and verify no replaced runtime file was newly
  written.
- [x] **Step 9: Checkpoint** the completed migration; commit only if requested.
