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

For long-distance navigation, the model first opens the map with canonical guarded
`{kind:"key",label:"m",expects:{mode:"map"}}`, inspects and learns pin/landmarks/road connections with frame
provenance, then selects the route. Visible-road-only travel is local approach or fallback after captured
unavailable/insufficient map evidence. A refused request does not establish that limitation. The model owns every
map open/read/close and route decision; Python supplies no hidden route schedule. See `navigation.md`.

```sh
./wf play turn_id=7 answer='{"kind":"act","action":{"kind":"waypoint","cell":"F7","walkable":true},"rationale":"visible_road","evidence_refs":["<frame>"]}'
./wf play turn_id=8 answer=accept
./wf play turn_id=9 answer='{"kind":"push","action":{"goal":"sleep","params":{}},"rationale":"late_task_gate"}'
```

Each `act` or `accept` performs at most one input. Its settling loop supplies the exact final frame for the next
receipt without a following grab. Read its immutable outcome before choosing again. Allowed primitives:
`target`/`cell`/`bubble` (model-confirmed visible target and entire road), `waypoint` (short visible walkable ground),
`press` (one exact visible label), `space` (highlighted world affordance or known dialogue/popup/cutscene),
`select_card` (one visible card point, or exact visible nonfinancial item `label`), `key` with `j`/`m`/`i` in gameplay, `close` on a recognized closable panel,
`read` and `wait` (zero input). `look` returns the saved full-scale frame and the same turn. Never use keyboard movement.
Menu-key JSON uses `action:{kind:"key",label:"m",expects:{mode:"map"}}` (similarly `j`/`i`), not a `key` field
or `press` on a HUD letter. The `key:m` shorthand is one guarded input without an implicit expected-mode claim.
On `verdict=unsafe`, read the exact `guard` check first: it issued zero inputs. Empty after-state/after frames in
that refusal are not a capture failure; `artifacts.img0` is the before frame and the NEXT frame is a later read.
Record the actual refusal reason before correcting the model decision. An intended mode never proves an attempt ran.
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

A surprise permits `look`, zero-input `read`, `correct`, `stop`. Open the preserved `view.path` with model vision
before diagnosing uncertain evidence; `look` records that vision but does not invoke it. `stop` is terminal, not a
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
`revise_decision`, `graph`, `appearance`, `transition`, `blocked_target`, `gap`, `human`; legacy `world` remains accepted.
Graph corrections name one existing node (`state` or `placement`) or exact `edge:{a,b,rel}` plus `values`. Appearance
corrections name one kind and `op:sample` with a bounded `box`, or `op:reembed`. Keep the captured `frame_path`, rationale
and evidence references. Public appearance ops are only `sample` and `reembed`; legacy `proven_look`, `relabel` and `badge` model corrections
are rejected instead of discarding provenance. Corrections apply data idempotently and issue no gameplay input. A stale route/vector clue
must be corrected or reported before reuse. Movement needs a satisfied positive `moved=true` expectation or other goal-related proof; region arrival is verified separately.

`catalogue` records a model-read current shop page without input or a child: `action:{catalogue:[<source-frame entries>],catalogue_complete:false}`. It preserves the parent interaction and advances the versioned turn.

`push` freezes the parent interaction; `suspend` explicitly holds a subgoal. `complete` requires captured domain proof
and leaves the parent frozen. A separate `resume` restores it. Each boundary survives restart; a pending intent is
reconciled without repeating input. `human` records unresolved ambiguity; `gap` preserves evidence for offline repair.
Unsupported completion proof is a gap, never permission to mark success from a model assertion.

Check interrupts every turn. A new task after 19:00 requires the pre-approved sleep subgoal before work; rain/darkness
requires the documented sleep handoff. Empty-can constraints apply only to garden work that needs water: explicitly
push `refill`, navigate to the well, choose its fill action, and complete only after `fill_watering_can`; then resume
the frozen garden interaction. The refill subgoal and unrelated harvest/shop/navigation work do not inherit an
   empty-can prohibition. Clock/weather safety interrupts still apply. After 23:00 finish the immediate safety step and sleep.
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
