# Testing

> **Summary:** Evals, benchmarks, run logs, and verification live under `tools/evals`, `tools/bench`, and task-local `runs/` directories.

- Run offline tests with `.venv/bin/python tools/test_<area>.py`.
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
