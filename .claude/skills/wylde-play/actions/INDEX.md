# Model-owned actions

> **Summary:** docs choose sequences; Python supplies clues, guarded atomic inputs and evidence. Every gameplay
> domain uses `./wf play`. Load this index, then the one workflow needed now.

| Need | Read |
|---|---|
| Move to an object/place, or forage | [navigation.md](navigation.md) |
| Enter/exit the farmhouse or another region | [regions.md](regions.md) |
| Reach Tara's bed and sleep | [sleep.md](sleep.md) |
| Open a merchant UI, sell authorized items and buy discovered types | [shop.md](shop.md) |
| Maintain every bed/hive in a named region | [garden.md](garden.md) |
| Talk, advance a quest, use inventory or craft | Read the relevant `docs/ui/INDEX.md` screen and `docs/operations/actions.md` row; apply the same atomic loop below. |

Start a reviewed run, check exact game time, and observe `./wf play <goal> [k=v ...]`. Bare domain aliases also
return `NEXT` without input. All aliases share the active run's SQLite task row in `runs/wf.sqlite3`; `./wf play`
resumes it. A different domain does not silently start another task: push a subgoal explicitly.
`read` and `look` are continuations, not root goals: use `./wf play turn_id=N answer=read` or
`./wf play turn_id=N answer=look`. Never run `./wf play read ...` / `./wf play look ...`, which requests a different
root task and is correctly refused while navigation is active.
Legacy `do`, `py`, `call`, `goto`, `advance`, routes and batching requests are task descriptions; they execute no
old Python workflow. Continue all tasks through `play` with the exact saved turn ID.
The same vision-capable gameplay agent owns this entire loop. Do not delegate `NEXT` to a text-only executor or wait
for Python to call a model. An optional exact-command helper returns its receipt immediately to the owner.

Every fresh gameplay `NEXT` is one coherent receipt. `view` names the exact settled full-scale frame and contains
its captured candidates, controls, bubbles and vector status. Treat those candidates as the primary current-frame
appearance/navigation clues. `result` is the preceding immutable outcome, `need` requests vision when required,
`memory` is the bounded current-region graph projection, and `resources` carries relevant save/log facts. Detailed
observe, decide, act, verify and learn rows stay in SQLite and project to `decisions.md`; they are not repeated as
workflow prose in `NEXT`.

For navigation, read `NEXT.navigation.localization` before any image. Stage `vectors` supplies usable current-frame
landmarks plus the bounded graph slice and means **do not run model vision**. Stage `vision` means there are no
vectors: inspect the full-scale frame once, identify a unique graph object, create its appearance vector, and refresh
with a zero-input `read`. At or after 18:00, existing vectors may be read but an evening/dark frame may never create, update,
calibrate, or retain a vector; defer the exemplar until daylight. For the sleep interrupt only, current-frame model
vision may localize and choose one visible-road step without persisting a vector. Only
`map_if_still_unresolved` permits the outdoor map as stage 3. A wrong returned vector
is repaired as a vector-system defect; it is never silently bypassed with vision. The model updates one task-local
semantic location, derives the next objective from the graph route, and owns every map open/read/close and route
decision. Python supplies no hidden route schedule. See `navigation.md`.

After inspecting a map, bind its gross direction before closing it with a task-local correction:
`{"kind":"correct","correction":{"kind":"route","data":{"target":"Well","origin_point":[620,430],"target_point":[715,490],"region":"Farm","frame_path":"<current-map-frame>","expires_after_turns":6}},"rationale":"map_pin_to_exact_goal","evidence_refs":["<current-map-frame>"]}`.
`origin_point` is Tara's current pin and `target_point` is the exact current navigation goal, not its broad parent
region or a remembered earlier landmark. The engine derives compass/range from these points; never copy a compass
from an earlier map view. Map compass is world/map space, not screen-click space. It remains evidence for the next
model belief; it does not veto a visible-road action or independently classify semantic progress.
If a fresh full frame proves that the labelled map target was semantically wrong, stop movement and submit a
`route_clear` correction with `reason`, the current `frame_path`, and that frame as evidence. Never wait for a known
bad hint to expire or silently fall back while it remains active.
The hint overrides the broad scene edge only for its bounded lifetime; when it expires, refresh from a map or newly
proved landmark. Never view a map, narrate its direction, then continue under the old edge.

Navigation-only graph nodes have no object candidate/event. A successful aligned waypoint advances them
task-locally. If upgrading code after such a step, use a `route_step` correction naming the exact current edge target;
it is valid only when the immutable outcome proves a moved waypoint and the target is navigation-only.

```sh
./wf play turn_id=7 answer='{"kind":"act","belief_update":{"goal":"Well","assessment":"initial","current":"outside house","confirmed":["pale road is visible"],"blocked":[],"rejected":[],"unknown":["garden entrance"],"next_objective":"follow visible road to the next landmark"},"action":{"kind":"waypoint","cell":"F7","walkable":true,"objective":"follow visible road to the next landmark","expects":{"moved":true}},"rationale":"visible_road","evidence_refs":["<frame>"]}'
./wf play turn_id=8 answer=accept
./wf play turn_id=9 answer='{"kind":"push","action":{"goal":"sleep","params":{}},"rationale":"late_task_gate"}'
```

The decision envelope accepts only `kind`, `action`, `correction`, `belief_update`, `rationale`, and `evidence_refs`. Primitive fields
such as `primitive`, `target`, `cell`, `point`, and `walkable` belong inside `action`; never place them at the top
level and never invent a `data` wrapper for an act decision.
`resume` always operates on the top completed/suspended child and accepts no goal selector: submit
`{"kind":"resume"}` only (plus optional rationale/evidence_refs). Never add `goal`, `action`, or child params.
Every navigation `act` replaces the complete short-lived belief with exactly `goal`, `assessment` (`initial`,
`progress`, `no_progress`, `contradiction`, or `arrived`), `current`, the bounded lists `confirmed`, `blocked`,
`rejected`, `unknown`, and `next_objective`. Put the current full-scale frame in `evidence_refs`; set
`action.objective` exactly to `next_objective`. A task restart deliberately removes this belief. On a semantic
navigation surprise, `no_progress` or `contradiction` may atomically replan and act only with a changed objective.
Use `contradiction` when the preserved outcome/frame disproves the engine's semantic surprise—for example movement
reached the intended visible detour even though an advisory graph compass called it irrelevant. A proved moved input
bound to the current belief is thereafter accepted as model-owned movement; the next fresh belief, not the graph,
classifies whether it was progress.
The engine normalizes the belief's `goal` to the active task destination; do not spend a turn trying to reproduce an
internal node spelling when a natural goal statement is clearer.
If `resources.hour` is null, add optional numeric `observed_hour` from the same current full-scale HUD frame. The
engine uses that evidence-backed value for the 18:00 cutoff and refuses ordinary navigation when both clock sources
are unknown.
Current-frame provenance belongs in top-level `Decision.evidence_refs`. A duplicated `belief_update.frame_path` or
`belief_update.evidence_refs` is tolerated only when it exactly matches/subsets that canonical top-level evidence;
the runtime discards the duplicate when persisting belief.

Each `act` or `accept` performs at most one input. Its settling loop supplies the exact final frame for the next
receipt without a following grab. Read its immutable outcome before choosing again. Allowed primitives:
`target`/`cell`/`bubble` (model-confirmed visible target and entire road), `waypoint` (short visible walkable ground),
`press` (one exact visible label), `space` (highlighted world affordance or known dialogue/popup/cutscene),
`select_card` (one visible card point, or exact visible nonfinancial item `label`), `key` with `j`/`m`/`i` in gameplay, `close` on a recognized closable panel,
`read` and `wait` (zero input). `look` returns the saved full-scale frame and the same turn. Never use keyboard movement.
When the game must remain frontmost without input so its clock can advance, use canonical `./wf focus`; macOS
`open -a` does not reliably switch to the game's Space. A zero-input `play wait` followed by refocusing Warp keeps
the game frozen and must not be repeated as a time-advance loop.
In `focus-mode front`, settled universal gameplay receipts keep the game focused for a sixty-second action lease.
Reuse the captured final frame and start the next call inside that lease to avoid a Pause/Resume input. When the lease
expires, the persistent controller freezes game time in Warp; never send the stale waypoint—read and resolve the exact Pause modal.
Background mode activates Warp immediately. Never run `./wf focus` as post-call cleanup: it focuses the game and was
the cause of multi-hour HUD jumps during zero-input analysis.
Before selecting a waypoint, compare it with every visible unique-object candidate. Keep at least 96 px away from
their candidate points so a road step cannot enter an object's approach/interaction zone; deliberately interacting
with that object uses a target/bubble action instead. Raw vector candidates are appearance hypotheses: inspect them
against the full frame. A vector-only false positive cannot authoritatively veto model-confirmed obvious walkable
ground; only an interaction-proved or explicitly confirmed candidate owns an approach exclusion in the runtime guard.
Tara is not appearance-vector scanned: those guesses duplicated her body and sometimes matched scenery. The tracker
anchor identifies Tara for the model but does not impose an arbitrary minimum waypoint distance. At a bend or tight
interior, a short model-confirmed centreline step may be closer than 240 px; its visible surface and clearance, not a
fixed radius, determine whether it is usable.
Place a waypoint in the interior centerline of one continuous visible walkable surface, with clearance around the
point. Never label a path edge, fence or bridge rail, waterline, rock, vegetation border or decorative boundary as
walkable. Fireplace/chimney masonry is a vertical obstacle, not a stone path: never click its face, hearth, base, or
shadow. When Tara is occluded by a fireplace or other structure, detour to clearly textured open floor with visible
clearance around the point; do not click the occluder in an attempt to move through it. At a bend or bridge approach,
take a short center-of-road `visible_detour` first, then inspect the fresh
view before selecting the bridge deck.
For an indoor divider wall, a waypoint before the visible wall end must remain on Tara's current side. First move
parallel to the wall until the full opening is visibly below/beyond its end; only a later fresh frame may turn across
the opening. A point on the opposite room floor is not reachable merely because both endpoints look wooden.
If a waypoint supplies `surface` (`road`, `floor`, `porch`, or `bridge`), it must also supply the current frame's
visible `surface_box:[x0,y0,x1,y1]`; never send a surface label without its bounds. The point must be inside that
model-confirmed continuous surface; Python adds no arbitrary inset beyond the model's visible-clearance judgment.
When any road is visible, navigation waypoints stay on its centerline; do not cut across grass because the eventual
map/compass direction points that way. A winding road segment may temporarily point away from the destination and is
an explicit `visible_detour`. Map/compass evidence chooses only among branches that are actually visible.
Every road waypoint includes `surface:"road"` and a conservative `surface_box:[x0,y0,x1,y1]` enclosing only the
continuous visible pale/dirt road patch around that point. Keep the point visibly clear of the boundary; if the
patch is too narrow to judge safely, take a different patch or refresh the view instead of guessing.
At dusk, distinguish the pale/desaturated road texture from darker green grass before drawing the box. Do not draw a
box across a road/grass boundary, under a fence, or through a semi-transparent tree merely to admit the desired point.
Compare the graph edge's qualitative compass with the visible road, but resolve disagreement in `belief_update`.
The graph cannot refuse an otherwise safe visible-road primitive. Use `visible_detour:true` for an intentional short
step around an obstacle or along a winding road and record the obstacle/road evidence in the belief. After movement,
classify semantic progress from the fresh frame and outcome; if the route was wrong, replace the belief and change
`next_objective` atomically with the next action.
Always read the durable guard verdict before diagnosing a zero-input result.
An action on turn N produces its outcome/surprise on successor turn N+1. Submit `correct` with the exact current
`NEXT` turn ID, never the refused action's old ID. If a stale-turn response occurs, request context once and continue
with the returned current turn. The stale rejection itself is zero-input, but it does **not** prove that an earlier
in-flight request failed to consume that turn: inspect the latest durable decision/experience before claiming no
input or retrying. Stale context is not a reason to stop or ask the supervisor.

Every refused or inefficient action is a blocking improvement signal. Freeze game time, identify the exact guard,
decision rationale and source evidence, then fix the responsible policy, primitive or observation boundary before
issuing another gameplay input. A `correct` decision records the evidence but is not by itself a fix. Reload changed
runtime code, resume the same durable task, and verify the fix in that live route. Do not normalize repeated
zero-input refusals, redundant map opens, stale-view churn, no-displacement clicks or wrong-direction movement as
ordinary navigation steps. After every movement compare the source/result frames with the committed belief; movement
that did not advance its semantic `next_objective` must pause input, record `no_progress` or `contradiction`, and
change the objective before continuing.

When full-scale model vision proves ordinary gameplay but the captured screen is `unknown`, submit a bounded screen
correction on that exact frame:
`{"kind":"correct","correction":{"kind":"screen","data":{"kind":"gameplay","region":"House","frame_path":"<current-frame>"}},"rationale":"full_frame_gameplay","evidence_refs":["<current-frame>"]}`.
It authorizes only two same-region turns and never promotes a recognized modal/card or persists across a restart.

The `Out of time` / exhausted modal means the route failed: after 01:00 the game stops and puts Tara in bed.
`Zzzz` only acknowledges that already-failed run; it is never recovery, success, or a valid way to reach Bed. An
active live eval that observes pass-out must finish FAIL even if a later frame shows Bed or the destination.
After `time_fail` or forced passout, a previously issued click may finish late across the transition. Before any task
restart or eval start, take two fresh zero-input reads and require the same coherent scene and save position with no
pending intent or new movement event. A disagreement means the old input is still settling: fail/avoid the eval,
refresh again, and do not treat the first post-passout Bed frame as a stable start state.
If the 18:00 sleep interrupt has not reached the House by 23:00, stop and hand control to the human. Do not spend the
remaining night exploring another road branch: avoiding forced passout outranks autonomous route completion.
For a fresh live eval, order is strict: restart the gameplay task first, obtain fresh House+Bed evidence, then start
the eval. `restart=true` deliberately fails every active eval, so never start an eval and restart its task afterward.
If the eval command is delayed until after the first inputs of that same restarted task, `live-eval start` binds to
the task's immutable coherent House/Bed `sleep_spawn` clue and counts every input after it. Do not backtrack to Bed or
manufacture a new visual Bed candidate. The fallback is valid only while that exact task remains active; an older
task's spawn, static graph membership, cutscene frame, or post-passout state is rejected.
Menu-key JSON uses `action:{kind:"key",label:"m",expects:{mode:"map"}}` (similarly `j`/`i`), not a `key` field
or `press` on a HUD letter. The `key:m` shorthand is one guarded input without an implicit expected-mode claim.
On `verdict=unsafe`, read the exact `guard` check first: it issued zero inputs. Empty after-state/after frames in
that refusal are not a capture failure; `artifacts.img0` is the before frame and the NEXT frame is a later read.
Record the actual refusal reason before correcting the model decision. An intended mode never proves an attempt ran.
An exact fresh `pause` screen with one `Resume Game` control is a recoverable modal owned by the same gameplay agent,
not a supervisor block. Resolve any older movement surprise from its immutable evidence, then press that exact current
control with expected gameplay mode and continue the existing task. Never escalate merely because a focus handoff
materialized the standard pause menu.
For every surprise, authoritative `evidence.mode`, `evidence.events`, and `evidence.texts` outrank a visual narrative:
if they show a dialogue/event, the interaction occurred even when the model expected a different proof shape. Never
write a correction claiming “did not open” or “no input” while those fields prove the opposite.

Expectation fields are typed before any observation/input: `card` is a nonempty expected text substring, or `"?"`
to capture/read an unknown card as a gap; it is never `true`/`false`. `mode`, `region`, `node` are text; `moved` is
boolean; `events` is a list of event alternatives (or `"?"`); `allowed_events` is a list; `log` is a valid regex
(or `"?"`); `destination_position` is two finite numbers. Malformed/unknown fields are rejected before an intent
or input. A bubble still needs `visible_road:true` for the model-verified visible target/road, for example
`action:{kind:"bubble",point:[<fresh x>,<fresh y>],visible_road:true,expects:{card:"?"}}`.
Read its actual text/mode next; a gap prediction grants no sleep/trade completion. Unknown + ready/highlighted
does not identify the action: inspect the icon and owner before selecting it.

When resuming after an exception, inspect BOTH `task.pending_intent` and `task.active.pending_intent`. A null
top-level intent does not prove no input. Bare `play` reconciles without replay: an old malformed expectation
is retained in an unsafe outcome with explicit `input_status`. Only durable originating boundary/adapter provenance
that explicitly records preparation refusal permits `not_issued`. The adapter used after restart and a missing
command do not prove what the original adapter did. Legacy/missing/incomplete or prepared provenance remains
`unknown` and requires observation without replay. Do not turn that uncertainty into permission to retry.

The client has a 60-second total RPC delivery deadline. A timeout, partial-send failure, EOF or invalid response
after sending means **outcome unknown**: it prints an explicit error and never automatically resends, restarts to
resend, or executes that request locally. The daemon may finish and advance the task later. Do not repeat an old
decision because stdout was empty; inspect the current task/turn after the outstanding request finishes, then use
the ordinary observation/recovery boundary. Preserve the pending intent and financial reservations.
A bare `./wf play` is a cached-context read: `observation_freshness:"cached"` means its frame is the exact persisted
turn evidence, not a claim about the screen now. Use that version's explicit `read` decision when current-screen proof
is required. A returned `observation_freshness:"fresh"` comes from the current request's coherent observation.
A zero-input `read` uses one fresh coherent snapshot for its outcome and NEXT. It does not wait for an action
that was never issued; an unknown/black snapshot still permits only the existing bounded second observation.
One frame grants no movement comparison (`moved=null`). Restart recovery captures afresh, and every later
physical action takes a new pre-input observation before its guards. This receipt never crosses decisions.
Two fresh rendered before/after frames may prove movement even when the save slot has not autosaved yet. An
unchanged saved position from the same older save count/game time is a stale hint; it cannot negate current visual
movement or be reported as authoritative no-move.
Optional `WF_TIMING_FILE=/tmp/wf-timing.jsonl` records payload-free client/server, capture, clue and persistence
durations when inherited by that process (set it for daemon startup as well as the client). It issues no input.

For a world interaction with a detected bubble, click the bubble first (`bubble` with its fresh point and
`visible_road:true`). Inspect the resulting prompt. When the affirmative confirmation bubble is already highlighted
(for example `Yes`), confirm it with one `space`; do not click it or route it through text/card selection. This is the
general confirmation sequence: **click the interaction bubble, then Space the highlighted confirmation**. For other
dialogue, choose one `space` or one named response, expect the next subtitle/modal or quest event, then reassess.
For a journal hint, open `j`, inspect the quest, press visible `Show Hint`, read it, then close in separate turns.
Inventory use/crafting similarly needs a visible item/control, explicit resource authorization, and its item/event
change as proof. Do not turn a historical action recipe into a batch of keys.

A navigation no-progress or wrong-direction surprise permits one atomic replanned `act` with a replacement belief
and changed objective, as described above. Use the preserved outcome image and explicit `expects:{moved:true}`.
Other surprises use `look`, zero-input `read`, `correct`, or `stop`. Open the preserved `view.path` with model vision
before diagnosing uncertain evidence; opening the saved image directly needs no `look` turn. `stop` is terminal, not a
handoff for vision, exhausted budget, or missing context—return `need-help` with the durable task still active instead.
`answer='{"kind":"read"}'` takes a fresh coherent
frame and authoritative save observation even for a pre-upgrade saved turn; it accepts no action/correction/runtime
state payload. It never repeats pending input. An unknown/black frame stays unsafe for world input. An
outcome gets no automatic credit from its intended mode: if its first capture is unknown, the boundary performs
one bounded settling observation without input, preserves both full frames/screen samples, and verifies the final
observation normally. If it remains unknown or shows the wrong mode, the surprise stays. A UI overlay disappearing
does not prove Tara moved. A fresh read can verify a nonfinancial UI mode transition only when every original
expectation passes; a later safety Pause cannot stand in for promised gameplay. Inspect the preserved post-input
frames and use an explicit `revise_decision` correction when their model-read evidence resolves that historical gap.
The current fresh frame still controls the next input guard. A fresh known
screen can resolve a prior unknown-screen guard refusal (which issued zero inputs), granting no movement credit.
An attempted waypoint with missing movement proof can reconcile from a newer save count AND later game time in
the same save lineage, at/after the attempted input's clock; changed saved position/scene is recorded in a new
immutable read outcome linked to the original. Recovery re-runs the normal checks and outcome rules against ALL
original expectations (including region/node/events/mode/card/log), recovered from the exact canonical intent for
older tasks; partial Predictions are insufficient. The baseline must not also span another domain input, including
completed/resumed child outcomes in the archive. Stale, pre-input, missing, conflicting or ambiguously attributable
evidence retains the surprise. Guard-refusal refresh remains observation-only: no moved credit, and other original
expectations still apply.
Read its source frame before diagnosing uncertainty. Corrections:
`revise_decision`, `route_clear`, `graph`, `appearance`, `transition`, `blocked_target`, `gap`, `human`; legacy `world` remains accepted.
`human` (and legacy `unresolved`) records a terminal unresolved task and leaves only observation/stop; never use it to
request clarification that should resume. For a resumable human question, submit no correction, return `need-help`
with the current turn/evidence, and leave the surprise/task active.
Graph corrections name one existing node (`state` or `placement`) or exact `edge:{a,b,rel}` plus `values`. Appearance
corrections name one kind and `op:sample` with a bounded `box`, or `op:reembed`. Keep the captured `frame_path`, rationale
and evidence references. Public appearance ops are only `sample` and `reembed`; legacy `proven_look`, `relabel` and `badge` model corrections
are rejected instead of discarding provenance. Corrections apply data idempotently and issue no gameplay input. A stale route/vector clue
must be corrected or reported before reuse. Movement needs a satisfied positive `moved=true` expectation or other goal-related proof; region arrival is verified separately.

`catalogue` records a model-read current shop page without input or a child: `action:{catalogue:[<source-frame entries>],catalogue_complete:false}`. It preserves the parent interaction and advances the versioned turn.

`push` freezes the parent interaction; `suspend` explicitly holds a subgoal. `complete` requires captured domain proof
and leaves the parent frozen. A separate `resume` restores it. Each boundary survives restart; a pending intent is
reconciled without repeating input. `human` terminally records unresolved ambiguity; `gap` preserves evidence for offline repair.
Unsupported completion proof is a gap, never permission to mark success from a model assertion.

Check interrupts every turn. At 18:00 or later, stop ordinary gameplay, push/use the pre-approved sleep workflow,
return home and sleep, or explicitly hand control to the human; runtime refuses ordinary navigation until that workflow owns the route. Rain/darkness also
requires the documented sleep handoff. Empty-can constraints apply only to garden work that needs water: explicitly
push `refill`, navigate to the well, choose its fill action, and complete only after `fill_watering_can`; then resume
the frozen garden interaction. The refill subgoal and unrelated harvest/shop/navigation work do not inherit an
   empty-can prohibition. Clock/weather safety interrupts still apply.
For coding or long off-game work, let the game lose focus; unfocus freezes game time. Do not open the Pause menu merely
for thinking. Use explicit Pause/Resume only when the visible modal itself is part of the model-owned task. Never change
the user's settings.

Captured acceptance evidence lives in `tools/fixtures/play/`. An explicitly incomplete fixture proves no success.
The former `20261106-2027-model-owned-south-garden` run is failure evidence; acceptance uses a fresh run, never a reset
of its task/log. The supervisor supplies the root authorization and bounded run plan before input.

For an accidental child with only administrative/observation work, `answer='{"kind":"cancel","rationale":"<why>"}'` cancels only the current top child without physical input. It restores the parent interaction and reactivates the previous child, retaining cancelled outcomes and a canonical cancellation record. It grants no completion or trade credit. Reservations, financial input/receipts, irreversible or unclassified domain effects, pending input and missing evidence prevent cancellation. Old children with unknown start versions are handled conservatively.

After a code upgrade, a saved turn may not yet advertise `cancel`. Use one `act` / `read` decision with its exact saved turn ID (zero input), then inspect NEXT and choose `cancel` at the returned version. Never edit task files, reset the root, or bypass a refusal. Cancellation does not close menus or resume the physical game.

Cancellation rejects positioned interaction evidence even when its event name is unknown: `at`, canonical
node/region proof, positioned raw log lines, and unproven or changed position state require inspection. An
unchanged save-derived Tara position remains a permitted background hint for administrative Resume evidence.
