# Interaction laws

> **Summary:** the gameplay model owns each garden turn: read clues, accept or override one recommendation,
> execute at most one input, then read its evidence. A durable transaction retains crop, phase and event-owned
> identity across calls. The graph supplies coverage and dated clues; the positioned game event owns identity.

## Garden turn contract (offline verified; full live pass pending)

An active `./wf run start <task> <goal>` is required. The supervisor writes and reviews its `plan.md` before play.
`./wf garden region=GardenSouth [crops=Tulip]` observes without input and prints `NEXT` plus a JSON TurnContext.
The model reads screen/card, visible affordances, graph clues with their source/time, active transaction, coverage,
last outcome, surprise, interrupts, recommendation and allowed decisions. Accept obvious recommendations promptly.

Continue with the exact returned turn ID; each command is its own tool call:

```sh
./wf garden turn_id=7 answer=accept
./wf garden turn_id=8 answer=look
./wf garden turn_id=8 answer='{"kind":"act","action":{"kind":"bubble","cell":"K8","visible_road":true},"rationale":"visible_target_and_road","evidence_refs":["<frame_path>"]}'
./wf garden turn_id=9 answer='{"kind":"correct","correction":{"kind":"gap","data":{"invariant":"<missing behavior>"}},"rationale":"capability_gap","evidence_refs":["<experience-id>"]}'
```

`accept` consumes the exact saved recommendation. `act` selects one primitive: target/cell/bubble, waypoint, press
label, space, close, wait or read. `look` returns the saved full-scale frame path without input or a new turn; Read
that image. `correct` applies the model's smallest correction; `stop` ends safely. Stale IDs refuse input. Use
Decision JSON for concise rationale categories and evidence references; no separate `run think` row is needed for
the same decision. Shell-safe alternatives include `answer=walk:F7`, `answer=target:K8`, `answer=press:Collect`.

The model selects the next target only when the active transaction has completed. A target click needs the target
and its full walkable road visible from Tara at the frame centre. Otherwise choose one short visible-ground
waypoint (`{"kind":"waypoint","cell":"F7","walkable":true}`). Never infer actual node ownership from projection.

## Evidence and garden rules

1. **Tara stays at the centre.** Describe targets relative to the centre; use fresh full-scale frames (1920×1080).
2. **Record before deciding again.** Each selected action persists its intent, captures evidence, integrates one
   immutable Experience and saves the transaction. A pending intent after interruption reconciles from evidence;
   it never repeats an uncertain input. A read/guard refusal can record an experience with zero physical inputs.
3. **Identity needs a positioned game event.** Trust event > card > bubble > text > vision for state. Projection
   is a provisional clue. Vision can classify a crop/state but cannot manufacture an actual graph node.
4. **Finish the same interaction.** Inspect → collect/remove when allowed → plant → water → verify. Carry the
   observed crop across calls; an explicitly requested crop controls planting and flower authorization, not identity.
   General garden maintenance plants pre-existing empty beds using an available seed. Narrow water/harvest jobs do
   not. Collect ready non-flower crops and ready honey; preserve flowers unless authorized. Water after planting
   unless raining. A plant plus drop icon needs interaction evidence to distinguish dry from wilted.
5. **The model handles surprises.** Read the preserved frame before diagnosing uncertain evidence. Choose a world,
   appearance, transition, gap, unresolved or stop correction (`integrate.correct`); code never patches itself.
   Preserve the active crop/card/transaction while fixing the smallest issue. Do not close a useful card or start
   the whole task again as generic recovery.
6. **Check interrupts each turn.** Rain/darkness or a new task after 19:00 calls for sleep/resume; the standing task
   start sleep gate is pre-approved. After 23:00 stop optional work. Empty can calls for refill then this transaction.
   Dialogue, pause, cutscene, map and unknown menus block world input. Pause before coding or long off-game work;
   front focus mode means the clock runs between calls. Do not change user settings.
7. **Coverage proves completion.** Every bed/hive in the named region must be in `coverage.covered`, backed by the
   actual event-owned interaction. A final zero-input verification turn marks coverage. `task.status=complete`
   plus no missing/unresolved targets closes the task; a constrained/unresolved result needs supervisor review.

## One timeline and hot learning

`runs/<run>/log.jsonl` contains chronological `type=turn` rows joined by `task_id` and `turn_id`: clues,
recommendation, decision, optional vision, intent, outcome, integration and correction. Calls/game events share
this log. `experiences.jsonl` is a machine replay journal only; follow its IDs for raw evidence, not a second
reasoning history. `.venv/bin/python tools/runwatch.py <run> --follow` watches every phase and alerts on surprises;
`--report` writes coverage, timing and trace to `watch.md`. Legacy `event=turn` captures remain readable.

Learning `actions.json`, graph JSON, observation journals and image/vector data does not restart the daemon.
Transitions/graph/stores are reopened at their command boundaries; image feature caches refresh on PNG revisions.
Python source and import-time vocabulary/configuration (`goals.json`, `kinds.json`, `forage.json`) still restart it.
After a live issue: pause, preserve task/log/experience/frames, add the real replay, make the smallest fix, run the
exact failing test, then resume the same task/transaction. Full discovery is a final gate, never the live fix loop.

## Code boundaries

| Module | Responsibility |
|---|---|
| `garden.py`, `turn.py`, `task_state.py` | Public one-turn API, immutable context/decisions, durable transaction and write-ahead recovery |
| `garden_policy.py` | Pure recommendations, evidence reduction and coverage; no inputs, model calls or target scheduler |
| `primitives.py` | Guard and execute zero or one selected input, capture evidence |
| `observe.py`, `screen.py`, `brief.py` | Fresh frame/screen/affordance readings and graph clues |
| `world.py`, `objects/graph.py` | Dated facts, event-owned nodes, coverage clues |
| `integrate.py`, `experience.py` | Immutable evidence, idempotent world/memory/transition corrections and gap bundles |
| `plan.py`, `steps.py` | Transition data and pure next-step recommendation; generic legacy goals still use row execution |

Offline proof: `tools/test_turn.py`, `test_garden_turn.py` (captured tulip Collect → Seeds → plant → water trace),
`test_experience.py`, `test_runtime_data.py`, `test_runwatch.py`. A full live south-garden pass remains required.
