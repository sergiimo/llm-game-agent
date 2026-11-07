> **Summary:** `runs/wf.sqlite3` is the sole structured runtime authority; Markdown is a human projection and graph JSON is a static seed.

# Runtime store

SQLite stores runs, tasks, ordered events, observations, save-profile pins, intents, experiences, applied updates,
gaps, and profile-local world overlays. It uses WAL, foreign keys, `synchronous=FULL`, and schema checksums.
World node and edge revisions are append-only and load as of an observation ID; dynamic facts retain their original
game timestamp. Integration claims use a lease plus an ownership token, and every external consumer uses the
experience ID as an idempotency key so crash recovery can safely finish an update without duplicating its effect.

`plan.md`, `progress.md`, `decisions.md`, retros, screenshots, and video remain files. Runtime recovery never reads
Markdown. `tools/objects/graph/Farm.json` is a reviewed static seed only; crop state, Tara state, experience IDs,
temporary paths, and interaction hints belong in the profile-scoped database overlay.

## Operations

Integrity check:

```sh
sqlite3 runs/wf.sqlite3 'PRAGMA integrity_check;'
```

Consistent backup:

```sh
sqlite3 runs/wf.sqlite3 ".backup 'runs/wf-backup.sqlite3'"
```

`save_lineage_mismatch` is deliberately zero-input. Inspect the observation mismatch, correct the active game/profile,
then issue a fresh read or stop the run. A correction cannot rebind a pinned profile.

Legacy structured run files are intentionally unsupported. Historic records were dropped at cutover; JSONL is
available only as an explicit diagnostic export: `./wf run export --jsonl <run>`.

Static map promotion is explicit and reviewable: `./wf graph promote <candidate-id>` previews a diff;
`./wf graph promote <candidate-id> --apply` writes only allowlisted structural fields.
