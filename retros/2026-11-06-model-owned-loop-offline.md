# Model-owned loop: offline runtime preparation

> **Summary:** offline tests exposed restart/cache and timeline visibility gaps. The fixes preserve model-owned
> turns and the existing task state. No live game commands were issued; full south-garden proof remains pending.

The source watcher included learned `actions.json`, while crop/badge/bubble references cached images for the
process lifetime. Transition and graph files already reopen at command boundaries; image feature caches now use
disk revisions, including replaced crops with the same example ID. Only Python and import-time vocabulary/config
(`goals.json`, `kinds.json`, `forage.json`) trigger restart.

TurnLoop wrote `event=turn`; runwatch consumed `type`, so the new model loop was absent from supervision and
coverage reports. Turn rows now use the shared envelope and retain concise model rationale/evidence references,
intent, outcome/experience, integration and corrections. The watcher handles historical envelopes, alerts on
surprises, and derives final coverage from the context. Call completion timestamps and partial append handling
also have regression coverage. `experiences.jsonl` remains the raw machine replay journal.

The initial runtime/timeline selection failed six of seven tests for the intended boundaries. Two additional
image-cache tests and two chronology/partial-write tests also failed before their respective fixes. Focused
green runs and the compact architectural/CLI gate are recorded in the task report. Existing file-resource
warnings in experience tests are recorded there; no live evidence is claimed from offline tests.

No further hidden garden scheduler tests remained: the old streaming assertions had already been removed in
Task 2. Generic engine/navigation tests still cover active legacy goals and were retained. No movement-stuck
episode occurred, so the stuck ledger has no new entry.

The next proof is one bounded `gpt-6-luna` low garden run. The supervisor watches `log.jsonl`, pauses on an issue,
preserves the exact experience/frame/task, adds that evidence to replay, applies the smallest fix and immediately
resumes the same transaction after focused tests. Full discovery/final broad review belong after live evidence.
