# SQLite Runtime Store Design

## Intent

Replace file-coordinated gameplay state with one local SQLite authority. Every gameplay task is pinned to one coherent
save profile for its lifetime, normal slot-file rotation inside that profile is allowed, and no vectors, graph clues,
recommendations, or input may use evidence from another profile or a contradictory game timeline.

SQLite also replaces structured run-local `*.json` and `*.jsonl` files. Human Markdown remains file-based: `plan.md`
is authored input; `progress.md` and `decisions.md` are readable projections that cite SQLite row IDs; retros remain
documents. Screenshots, video, and other large artifacts remain files whose paths and digests are recorded in SQLite.

## Authority boundary

### SQLite is canonical for local structured state

- active run and run lifecycle;
- current durable task/subgoal/transaction state;
- chronological run events and turn phases;
- write-ahead intents, immutable experiences, integration results, applied-update keys, and gap bundles;
- save profiles, rotating slot files, log epochs, task profile pins, and coherent observation snapshots;
- profile-scoped dynamic world facts, local discoveries, learned edges, and their provenance.

The database lives at `runs/wf.sqlite3`, is git-ignored with `runs/`, and uses schema migrations. Connections enable
`foreign_keys`, WAL journal mode, `synchronous=FULL`, and a bounded busy timeout.

### Version-controlled files remain canonical for shared declarations

- goals, kinds, actions, and other executable/configuration JSON;
- the stable world-map seed: fixed regions, identities, containment, landmarks, stable geometry, and reviewed
  navigation relations;
- documentation, plans, retros, and user-authored run plans.

Runtime code never saves an in-memory world projection back into the map seed. A reviewed `wf graph promote` command
is the only path from a proven local discovery to version-controlled map JSON.

### Generated human views are not replay inputs

`progress.md` and `decisions.md` are regenerated from SQLite. They use references such as `event #1842`,
`observation #317`, and `experience 64e995862d57cc01`. Failure to render either file cannot roll back or invalidate a
committed gameplay record. No runtime recovery or model decision reads Markdown as structured state.

## Core schema

The initial migration creates these logical tables. JSON columns hold bounded domain payloads where normalization
would only reproduce the dataclass tree; identity, ordering, lineage, validation, and transaction state are relational.

| Table | Purpose and key constraints |
|---|---|
| `schema_migrations` | Applied schema versions and checksums. |
| `save_profiles` | Stable lineage identity: canonical profile directory plus first/last-seen metadata. |
| `save_slots` | Rotating `.local` files for a profile: canonical path, file identity, digest, save count, game time, scene, and observation timestamps. |
| `log_epochs` | Player-log inode/session identity, first/last game stamp, and continuity with a preceding epoch. |
| `runs` | Stable run ID, task slug, directory, goal, status, timestamps, and nullable pinned profile until task creation. |
| `active_run` | Singleton pointer to the current run, replacing `.shots/run.current`. |
| `task_state` | One current payload and monotonic revision per run; compare-and-swap update. |
| `run_events` | `INTEGER PRIMARY KEY AUTOINCREMENT`; total local ordering, run/turn/type/phase, timestamp, and bounded payload. |
| `observations` | Immutable save/log/frame snapshot, validation status, mismatch details, and pinned profile/slot/log-epoch references. |
| `intents` | One write-ahead intent per run/turn with lifecycle `prepared`, `performed`, `captured`, or `settled`. |
| `experiences` | Immutable content-hash ID, run/turn/observation references, and complete payload. |
| `applied_updates` | Idempotency key per experience/consumer/op/args hash plus result and timestamp. |
| `gap_bundles` / `gap_experiences` | Structured escalation data and its source experiences. |
| `world_nodes` | Profile-scoped local objects/regions not present in the shared seed, with provenance. |
| `world_facts` | Append-only node-key-value observations with game time, source, confidence, run/turn/observation/experience references. |
| `world_edges` | Profile-scoped learned/local relations and provenance. |
| `legacy_imports` | Reserved schema slot; unused after the decision to discard historic records. |

Run IDs are stable text IDs; chronological rows use never-reused integer IDs. Foreign keys prevent an event,
experience, or dynamic world fact from pointing at another run/profile accidentally.

## Save-lineage invariant

### Profile identity and slot rotation

A profile is the canonical parent directory below the game save root, not a numbered `.local` slot filename. Slot
creation, deletion, and rotation are legal only inside the pinned profile. A different parent directory is a different
lineage even if its modification time is newer.

### Task creation

`run start` creates an unbound administrative run. The first gameplay task observation performs one immediate
transaction:

1. Read the live Player log identity and timestamped timeline.
2. Enumerate and decode candidate save slots across profiles without choosing by modification time alone.
3. Retain candidates whose save game time and scene can be reconciled with the live log timeline.
4. Require one winning profile. A newer mtime on an inconsistent profile is ignored. Zero or multiple coherent
   profiles produce `save_lineage_mismatch` and no task input capability.
5. Insert the profile, slot, log epoch, root observation, task state, and run profile pin atomically.

The profile column may remain null while the root task is in this pre-input mismatch state. The first coherent read
sets it exactly once; after that the task's pinned profile never changes. Starting gameplay on another profile requires
a new run.

### Every observation

For a pinned task, the observation boundary selects only slots within the pinned profile. It permits slot rotation
when save count and game time are monotonic and the live log is continuous. Log-file rotation is permitted only when
the new epoch can be linked without moving the game timeline backward.

One immutable observation row contains the exact save slot/digest/count/time/scene, log epoch and range, frame/view
identity, and validation result. The decoded save and log slice used in memory are the values represented by that row;
consumers do not call `read_save()` or `today_log()` again.

Validation occurs before world refresh, vector scope/detection, graph projection, recommendations, or input. A
contradiction inserts a zero-input observation with status `save_lineage_mismatch`, records both sides of the conflict,
and exposes only `look`, `read`, or `stop`. A later coherent `read` may clear the interrupt; correction cannot rebind a
task to another profile.

Immediately before a primitive input, the guard verifies that the chosen observation still belongs to the pinned
profile and that no contradictory save/log epoch has appeared. A refusal records an unsafe zero-input experience and
does not reuse or replay the action.

## Turn and crash semantics

SQLite transactions replace the current choreography among `task.json`, `log.jsonl`, `experiences.jsonl`, and
`applied.txt`:

1. Creating a turn commits its coherent observation, task revision, clues event, and recommendation event together.
2. Accepting a decision atomically inserts the decision and prepared intent and updates durable task state before
   physical input.
3. Physical input occurs outside the database transaction.
4. Capture atomically inserts the immutable experience and outcome event and advances the intent to `captured`.
5. Integration inserts idempotent applied updates, integration/gap events, world facts, and settled task state in a
   transaction. A crash resumes from the recorded intent state and never repeats input merely because an outcome is
   incomplete.

Short transactions and one writer per action avoid holding database locks while OCR, vision, input, or model work is
running. `wfc`, the daemon, and `runwatch` may use separate connections; WAL permits watcher/report readers while the
daemon commits.

## World seed and local overlay

Loading the world creates an in-memory graph from:

1. the version-controlled static seed;
2. profile-scoped local nodes and learned edges from SQLite;
3. the latest valid dynamic facts as of the task's coherent observation.

The static seed no longer contains crop/watering state, Tara position/region, refresh conflicts, experience lists,
temporary paths, appearance samples, or run-specific interaction hints. Stable discoveries live locally with
provenance until explicitly promoted. Promotion writes only reviewed structural fields and never writes dynamic facts
or local artifact paths.

## Human reports

- `plan.md`: supervisor-authored and still reviewed by `wf run plan`.
- `progress.md`: regenerated status/timing narrative from run and plan-step event IDs.
- `decisions.md`: regenerated per-turn narrative linking observation, decision, intent, experience, and integration
  row IDs plus artifact links.
- `wf run report`: queries SQLite directly; Markdown is presentation only.
- `wf run export --jsonl`: optional diagnostic export, never read by runtime code.
- `runwatch.py --follow`: polls `run_events.id > last_seen_id`; no file tailing.

## Cutover

There is no dual-write period and no legacy importer. At the user's direction, historic file-backed run records were
discarded rather than trusted after the captured D4/D219 lineage contradiction. Production readers and writers for
the replaced filenames are removed, and a source guard prevents their return. The reviewed static graph structure is
retained; contradictory historic dynamic graph values are not assigned to any profile.

## Acceptance criteria

- The captured D4 Town / D219 Farm sequence first pins the uniquely log-consistent D4 profile even when D219 has newer
  mtime. A later observation that supplies or requires D219 instead of the pinned D4 lineage creates one
  `save_lineage_mismatch`, zero Farm vector candidates, zero graph/world writes, zero Farm recommendations, and zero
  input.
- A numbered slot rotation inside the pinned D4 profile remains valid and advances the observation timeline.
- A newer save from another profile never wins through modification time.
- Every vector result, graph clue, recommendation, intent, outcome, experience, and world fact is traceable to one
  coherent observation ID and pinned profile.
- Pending-intent crash recovery issues no duplicate physical input.
- SQLite is the only structured runtime authority; production code does not write run-local JSON/JSONL or dynamic map
  state to the shared graph seed.
- `progress.md` and `decisions.md` remain useful if opened alone and cite the database IDs behind their claims.
- Historic structured files are neither produced nor consumed by runtime code.

## Non-goals

- Storing screenshots or videos as SQLite blobs.
- Moving version-controlled configuration JSON into SQLite.
- Automatically publishing local learned facts into the shared map.
- Redesigning perception, navigation policy, or model decision semantics beyond requiring a coherent observation.
- Recovering discarded legacy run files into the runtime store.
