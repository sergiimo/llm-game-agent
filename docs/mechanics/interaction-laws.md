# Interaction laws

> **Summary:** the gameplay model owns every gameplay turn: read clues, accept or override one recommendation,
> execute at most one input, then read its evidence. A durable transaction retains crop, phase and event-owned
> identity across calls. The graph supplies coverage and dated clues; the positioned game event owns identity.

## Universal turn contract (offline verified; full live pass pending)

An active `./wf run start <task> <goal>` is required. The supervisor writes and reviews its `plan.md` before play.
`./wf play <goal> [k=v ...]` (or `./wf garden region=GardenSouth [crops=Tulip]`) observes without input and prints `NEXT` plus a JSON TurnContext.
All domains share the active run task file, including existing `garden-task.json`; `./wf play` resumes it.
Load `.claude/skills/wylde-play/actions/INDEX.md` then the one workflow file. **Docs choose sequences; Python never does.**
Legacy `do`, `py`, `call`, `sleep`, `goto`, `advance`, and route aliases return turns rather than run private workflows.
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
label, space, select_card, guarded menu key (j/m/i), close, wait or read. `look` returns the saved full-scale frame path without input or a new turn; Read
that image. `correct` applies the model's smallest correction; `stop` ends safely. Stale IDs refuse input. Use
Decision JSON for concise rationale categories and evidence references; no separate `run think` row is needed for
the same decision. Shell-safe alternatives include `answer=walk:F7`, `answer=target:K8`, `answer=press:Collect`.

Administrative controls (for example Resume Game) keep a task-level pending intent, separate from the bed/hive
transaction. They do not create or mutate the active garden interaction. Resume succeeds when evidence returns
to gameplay; it needs no world event. Interrupted menu input reconciles from its recorded intent without repetition.

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
5. **The model handles surprises.** Read the preserved frame before diagnosing uncertain evidence. Choose a graph,
   appearance, transition, gap, human or stop correction (`integrate.correct`); code never patches itself.
   If the model chose the wrong primitive (for example a world bubble while Collect is already open), choose
   `correct` with `{"kind":"revise_decision","data":{"reason":"<mistaken choice>"}}`. This records the decision
   revision and clears the surprise without learning, a gap, an input or a task/transaction reset. The next normal
   turn may explicitly press `Collect` with observed `crop` metadata, preserving that same interaction.
   If this actual target cannot be finished (for example its Seeds picker is empty and purchases are not authorized),
   choose `correct` with `{"kind":"blocked_target","data":{"node":"<actual_node>","reason":"<constraint>"}}`
   and evidence references. It records that event-owned node, interrupted phase, crop, transaction and evidence in
   `unresolved`, releases only this interaction and leaves remaining work active. It teaches no data and performs
   no input. The model may then accept a separate close-card recommendation before selecting the next target.
   Preserve the active crop/card/transaction while fixing the smallest issue. Do not close a useful card or start
   the whole task again as generic recovery.
6. **Check interrupts each turn.** Rain/darkness or a new task after 19:00 calls for sleep/resume; the standing task
   start sleep gate is pre-approved. After 23:00 stop optional work. Empty can calls for refill then this transaction.
   Dialogue, pause, cutscene, map and unknown menus block world input. Pause before coding or long off-game work;
   front focus mode means the clock runs between calls. Do not change user settings.
   Arbitrary OCR text does not establish a card: controls/detail/hint semantics distinguish cards, recognized
   world affordances support gameplay, and unmatched overlay text with no such signal stays unknown for inspection.
7. **Account for every target.** Each bed/hive must be in `coverage.covered` with actual event-owned proof, or have
   an explicit per-target `unresolved` entry with event-owned identity, interrupted phase, reason and evidence.
   A final zero-input verification turn marks successful coverage. `task.status=complete` means accounting is
   finished: the watcher reports `COMPLETE` only with no unresolved targets, otherwise `CONSTRAINED` for supervisor
   review. A blocked replant is never counted as planted, watered or covered; the whole task stays active while
   other targets remain unaccounted for.

## Explicit nested subgoals and corrections

`push` with `action:{goal,params}` freezes the parent interaction. `suspend` holds a subgoal; `complete` verifies its
captured domain evidence without restoring the parent. A separate `resume` restores it. Pending intents reconcile
without repeat at any nesting depth. Sleep requires `sleep_transition`; region travel requires matching captured
region evidence. Unsupported proof becomes a gap/human resolution, never a model assertion of completion.

A shop task/subgoal names item, bounded quantity and max_spend; the root task supplies
`authorization:{purchases:[{item,quantity,max_spend}]}`. A purchasing action supplies `purchase:{item,quantity,price}`
(total price). Root authorization is reserved durably before input, so a restart or ambiguous outcome cannot spend
it twice. Completion requires matching inventory AND money deltas. Save-derived evidence retains save count/time
and can lag. Only verified acquisition clears matching `reason:seed_shortage,item:<seed ID>` constraints; those beds
return to remaining coverage and are never marked planted, watered or covered by buying seeds.

Every primitive compares evidence with its active goal: no move, irrelevant/away movement, wrong object/region/modal,
stale route/vector, missing or unexpected evidence is a surprise. While unresolved, only look/correct/stop is allowed.
Public `graph` corrections name one existing node (state/placement) or exact `edge:{a,b,rel}` plus bounded values;
legacy `world` remains a compatible node/state spelling. `appearance` can sample a bounded crop or reembed one named
kind. Vision corrections retain captured frame, rationale, evidence refs and experience ID, apply idempotently, and
perform no gameplay input. Never invent object identity or overwrite current positioned-event facts.

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
| `play.py`, `garden.py`, `turn.py`, `task_state.py` | Public one-turn API, immutable context/decisions, durable transaction and write-ahead recovery |
| `garden_policy.py` | Pure recommendations, evidence reduction and coverage; no inputs, model calls or target scheduler |
| `primitives.py` | Guard and execute zero or one selected input, capture evidence |
| `observe.py`, `screen.py`, `brief.py` | Fresh frame/screen/affordance readings and graph clues |
| `world.py`, `objects/graph.py` | Dated facts, event-owned nodes, coverage clues |
| `integrate.py`, `experience.py` | Immutable evidence, idempotent world/memory/transition corrections and gap bundles |
| `plan.py`, `steps.py` | Transition data and pure next-step recommendation; no public gameplay alias executes a row workflow |

Offline proof: `tools/test_play.py`, `tools/test_turn.py`, `test_garden_turn.py` (captured tulip Collect → Seeds → plant → water trace),
`test_experience.py`, `test_runtime_data.py`, `test_runwatch.py`. A full live south-garden pass remains required.
