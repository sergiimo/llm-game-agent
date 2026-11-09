# Testing

> **Summary:** Evals, benchmarks, run logs, and verification live under `tools/evals`, `tools/bench`, and task-local `runs/` directories.

- Run offline tests with `.venv/bin/python tools/test_<area>.py`.
- Partial native-owner experiment:
  [native owner trial](../superpowers/plans/2026-11-09-native-owner-trial.md). `./wf native observe` returns fresh
  bounded context plus the exact full-size frame; `./wf native act turn_id=N action=<JSON>` performs at most one
  primitive and returns its next receipt; `./wf native note` records a finding without input. The live trial proved
  the transport and movement boundary but did not leave the House, so this is not the production gameplay default.
  A navigation waypoint that only moves the camera/player is reported as `moved` with
  `semantic_progress: unverified`, not as route success.
- Report native receipt-to-receipt latency with
  `.venv/bin/python tools/owner_timing.py --bridge --db runs/wf.sqlite3`. Host/model subdivisions remain explicitly
  unmeasured unless an actual host trace is supplied.
- Run task reports with `./wf run status` and `./wf run report`.
- Run the persisted bed-to-well navigation evaluation inside an active gameplay run:
  `./wf live-eval start bed-to-well`, play normally, then
  `./wf live-eval finish` and `./wf live-eval report <id>`. The start gate requires a fresh, coherent House
  observation with current visual Bed evidence; success requires newer current visual Garden+Well evidence or a
  positioned Well interaction. Static graph membership never proves visibility or arrival.
- Compare completed evaluations across toolkit revisions with
  `./wf live-eval compare bed-to-well`. Checkpoints and metrics live in SQLite; they do not
  depend on historical JSON/JSONL files. Finalization is immutable; inputs count only issued physical actions, while
  observations, no-moves, wrong transitions, surprises, and available real/game elapsed time stay evaluation-bounded.
- The reverse evaluator is `well-to-bed`; it requires a fresh Farm/Well start and fresh House/Bed destination proof.
