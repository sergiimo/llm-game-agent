# Self-improvement loop (L56)

> **Summary:** every iteration follows one traceable loop: **deterministic clues → model decision → optional model
> vision → final action or code-gap decision → action evidence → integration → repeat**. Every primitive still becomes
> one immutable experience; every decision phase shares a cycle id in the task's single `log.jsonl`.

## The decision and learning loop

1. Non-model readers produce clues only: graph state and freshness, live bubbles, event history, heatmap detections,
   screen mode, and the transition rows that currently fit. They do not invent an object identity.
2. The model decides whether the clues are sufficient for one guarded action or whether the current full-scale frame
   needs model vision. A direct fitting transition records `decision=ready_to_act`; uncertainty records
   `decision=need_model_vision` before the vision request.
3. The model makes exactly one final decision: interact with a fitting bubble, click a named visible target, walk to a
   visible free-ground waypoint, settle explicitly visible state, finish, or declare a gap. Runtime guards validate it.
4. The actuator performs one primitive and captures events, cards, movement, before/after bubbles, text, and frames.
5. The integration boundary writes one immutable experience, applies proven world facts and learned memory
   idempotently, records transition checks, and emits a gap bundle when the discrepancy cannot be represented safely.
6. The loop repeats from fresh clues. No stale visual ownership or prior frame layout decides the next interaction.

Each phase emits a structured `reasoning` row with one `cycle`: `clues`, `final_decision`, `outcome`, and, when needed,
`gap`. The row stores concise explicit rationale, whether vision was requested, the action, linked experience id,
verdict, and `code_fix` candidate. `./wf run report` renders these from the same `runs/<task>/log.jsonl`; retros and code
review do not need a second reasoning file.

The release gate is deliberately small: `tools/basic_gate.py` checks seven user-visible contracts in under a second,
then one bounded live bed action and one live hive action validate the real UI. The broad fake-heavy suite remains
available for diagnosis but is not evidence of live reliability and is not run by default.

## The pattern
| Step | Rule |
|---|---|
| Act | The model selects one guarded action from the clues and optional frame; transition primitives record that final decision automatically. |
| Capture | The tool keeps what it predicted and the evidence (bubble crop, Tara's activity, call times). |
| Label | Ground truth comes from the **game log**, never from our own guess: `> <performance> me=Player target=<obj>`, `[DAMAGE] … destroying`, `grab_item`, `[QUEST]`, `[STATS]`. A label the tool has never seen **creates a new class** named after it. |
| Store | Only when the prediction was **wrong or unknown** (that's where the information is). Skip near-duplicates; cap per class. Every addition goes to a log (`.shots/learned.log`). |
| Verify | `./wf learn`: classes, leave-one-out accuracy, recent additions, observed vs expected outcomes. The supervisor checks it in every debrief and deletes bad samples. |
| Use | The next prediction uses the new reference / number immediately (refs reload; the docs row is updated). |

## Where it runs now
| Skill | Prediction | Ground truth | Storage | Status |
|---|---|---|---|---|
| Bubble kind (what a prompt means) | `bubble@x,y:<kind>`, `act:<kind>` | next `> <performance> … target=…` after Space (aliases: grab_item→pickup, hit_rock→pickaxe, PlayerGardening→axe, water, fill_can, plant, sleep, routine_sign→info, *_trade→talk; anything else → its own name) | `tools/bubbles/<kind>/*.png` (auto, cap 30, dup < 0.15) | ✅ automatic |
| Action outcomes (hits, drops) | `docs/operations/actions.md` **Expect** | run logs: `damage = HP … destroying` → hits; `grab_item` after it → pickups | `docs/operations/actions.md` rows (supervisor edits from `./wf learn`) | ✅ reported; edit by hand |
| Movement (did Tara move / stop) | `go:` arrival, `still` | Tara tracker + `OnEnter/ExitBuilding`, `ChangeScene` | thresholds in `tools/wf.py` (`Tara.ACTIVE`) | manual tuning |
| **Navigation (where a click takes her)** | each `go:` → dead-reckoned world position (per-scene calibration) | `pos` reading at **checkpoints** (trip/edge end, scene change, stuck, `wf pos`): exact world position from the autosave (L62) | `tools/nav/facts.jsonl` (one fact per checkpoint, append-only); calibration, places, blocks and edge status are **derived** by `tools/nav.py` (per-area `tools/nav/<area>/calib.json` = cache, L65) | ✅ automatic; `./wf learn nav`; review only `suspect-wall` edges. Phase 2: world graph (anchors/exits/links from scene changes, map places via pin pairs) and place fingerprints (predicted before each reading, used only once proven). 4 layers per area: L4 map (outdoors, coarse) → L3 graph → L2 calib → L1 prints; plan at the finest layer that knows the target. Spec: `docs/superpowers/specs/2026-10-29-nav-learning-loop-design.md` |
| Item icons (which card is which item) | `ui.pick_card(name)` matches card icons to stored prints | the detail card's title after a click | `tools/items/<name>/*.png` (cap 20, dup < 0.15) | ✅ automatic (L78) |
| Briefs, docs | quest brief Steps/Where | run log `issue` / `gap` / `decision` lines | quest files, `wiki/places/locations.md` | supervisor debrief |

Unknown bubble rule: if its owner resolves to the exact requested graph/world object, infer the requested action from
that context, record `bubble_resolve`, click it, then let the resulting game-log performance label and store the crop.
If kind or owner remains unresolved, stop with `UNKNOWN_BUBBLE` before input; model/user vision must resolve it first.
Bubble clicks as well as Space presses capture crops for this learning loop.

The orange highlight ring is excluded from bubble embeddings. It only tells a human which interaction Space would
choose; agents click the selected bubble's coordinates directly. Highlight remains separate diagnostic state and never
affects kind matching or agent selection.

For crop-state ambiguity, bubble ownership narrows candidates to GardenBeds and the tool probes them one-by-one. OCR of
the opened card supplies the immediate state (“plant has wilted”); the exact `> unplant`/`unplant_impl` game log remains
the required destructive-action proof. Other crop cards are closed and the next GardenBed bubble is tried.

## Adding a new skill to the loop
1. Find the game-log line that proves the outcome (search `./wf log --tail 200` right after doing it by hand).
2. Make the tool record its prediction next to it (state line, run log).
3. Store only disagreements, report in `./wf learn`, and review in the debrief.
