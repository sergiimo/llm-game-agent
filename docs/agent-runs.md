# Agent runs

> **Summary:** Gameplay-agent outcomes and gaps promoted from per-run evidence.

| Date | Run | Result | Cost | Gaps → fix |
|---|---|---|---|---|
| 2026-11-07 | `runs/20261107-1628-go-home/` | stopped; Tara stayed outside Kim's in Town | 14 calls; 0 clicks; 0 movement; 4 alerts | `[tool]` 25 s RPC deadline → 60 s + regression; `[brief]` legacy `do` plan → universal `play`/`turn_id`; `[tool]` cross-save D4→D219 clue contamination → save-lineage pinning required before retry; `[agent]` idle diagnosis advanced clock → unfocus immediately on alert |
