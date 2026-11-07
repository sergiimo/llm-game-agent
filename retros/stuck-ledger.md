# Stuck ledger

> **Summary:** One row per gameplay stuck episode; later retros must score whether earlier prevention fixes held.

| Date | Run | Symptom | Cause | Fix / prevention | Next score |
|---|---|---|---|---|---|
| 2026-11-07 | `runs/20261107-1628-go-home/` | 0 clicks and 0 movement; controller repeatedly described the visible Town Center frame as Farm | Durable alias misuse plus an unpinned save read switched from the active D4 `b-ts…` slot to inactive D219 `AoUVi…`, contaminating scene, inventory, position, vector scope, and graph clues | Keep the safety refusal; pin a run/task to its initial save lineage and reject cross-slot reads; manifest the universal `play` turn contract; freeze focus immediately during diagnosis | First occurrence; verify all three preventions on the next navigation run |
