---
name: wylde-play
description: Use when playing any Wylde Flowers goal through the universal model-owned one-turn boundary, including navigation, vision, atomic inputs, evidence verification, corrections, subgoals, and durable recovery.
---

# Playing Wylde Flowers

Session start: read `AGENTS.md`, the relevant Wiki/Docs router, and `./wf run status`; if a task is open, read its
`runs/<task>/plan.md`. Then load only the relevant index/detail.
The supervisor owns one current goal and a reviewed run plan; gameplay children use the user's cheapest-model rule.
One primary gameplay child owns the complete loop for that goal. It does not delegate returned turns to a text-only
runner; an optional exact-command helper may only return a receipt to this owner.
Check permissions, exact clock and current save/log before starting. A new task after 19:00 requires pre-approved
sleep first. Focus mode is front: pause before coding, documentation or long thinking.

**Daemon discipline:** live gameplay uses one persistent `./wf` controller daemon. Never set `WF_NO_DAEMON=1` or
start parallel diagnostic `wf` helpers while a request is pending; on macOS each helper can independently trigger
the “access data from other apps” prompt and make the outcome unknown. If a request stalls, inspect the existing
client/daemon and SQLite receipt, then `./wf stop` once only when a clean controller restart is actually required.
After restart, route every observation and turn through the one daemon socket.

For **every gameplay domain**, load [actions/INDEX.md](actions/INDEX.md), then the one workflow file it routes to.
Docs choose sequences; Python never does. `./wf play <goal> [k=v]` and bare domain aliases return `NEXT` without input.
Continue with the exact `turn_id` and one explicit model decision. Accept an obvious saved recommendation, choose one
primitive, inspect the full-scale source frame, correct data, push/suspend/complete/resume a subgoal, or stop. Read the
outcome before deciding again. Never use legacy `py`, `call`, batched commands or routes to run a hidden workflow.
Every `NEXT` is receipt-first: `view` identifies the exact settled full-scale frame and its controls, bubbles and
vector candidates; `result` summarizes the preceding immutable experience; `need` makes the request for model vision explicit;
`memory` is the bounded current-region graph projection; `resources` contains relevant save/log facts. Choose the
next primitive from this receipt. Detailed observe/act/verify/learn events remain in the run log for retros.
`complete` proves a root but intentionally leaves its durable record selected. A run owns one immutable root task id:
after its allowed zero-input `stop`, close that run and start a new run for an unrelated root. If several workflows
belong to one planned task, choose their durable parent up front and use explicit children; do not try to replace a
root in place or push a new workflow beneath an already-complete root.

Game files first: `./wf log` for live events; `./wf save` for exact but potentially stale autosave facts; `./wf state`
for screen/HUD text. When vision is requested, the primary gameplay agent opens `view.path` itself. A `look` decision
records vision and returns the saved 1920×1080 frame without input; it never invokes a model or transfers ownership.
Tara is at frame centre. A target needs its entire visible walkable road; otherwise choose one short visible-ground
waypoint. Move only by clicking. Current modal and guard rules apply to each primitive; no blind key loops.

For a navigation turn, read `navigation` before interpreting the frame. It resolves the requested destination to the
current nested object graph and names the next node/edge using only compass plus `near|mid|far`. Inspect the turn's
own full-scale `view.path`; choose a target or visible-road waypoint in the required qualitative sector. The point or
cell exists only to identify that click in this frame—it is never a persistent route coordinate. State the graph and
screen compass/range in the rationale. Any domain, including garden and indoors, must `push` a generic `navigate`
child before issuing waypoints, then complete it from captured transition/region/object-ancestry proof. Escalate only
an unresolved destination/path, a real visual ambiguity, or a repeated qualitative-guard refusal after one fresh
frame correction. Do not extend `tools/world/` coordinates or the retired calibrated route stack.

Keep clocks source-specific. `hud_hour` is refreshed from each captured frame for user-facing gates, `log_time` is
refreshed at the action/outcome boundary and is the canonical action timeline, and `save_time` belongs only to the
latest save snapshot and its provenance. Never merge them into a synthetic “current game time” or advance one source
because another changed; refresh that source at its normal observation trigger.

A surprise blocks gameplay until `look`, `correct` or `stop` resolves it. Preserve the active crop/phase/node and
parent interaction. Pending input reconciles from recorded evidence without repetition. The settle boundary's final
full frame is the next view; do not capture again merely to decide. Corrections update named
graph/vector/transition data with provenance, revise a decision, mark a constraint, record a gap, or report ambiguity
to the human; never patch runtime code while playing. Purchases require explicit root-task quantity/spend bounds and
matching inventory/money proof. Do not change settings, sell valuables or choose major story actions without scope.
`stop` is a terminal durable-task decision, not the spelling of “return to my parent.” A vision request, call-budget
handoff, missing manifest fact, or genuine ambiguity leaves the task active and returns `need-help` with its turn,
frame and experience; resume the same owner after the supervisor resolves it.

The canonical chronological timeline, observations, intents and immutable experiences live in `runs/wf.sqlite3`;
the same loop boundary regenerates timestamped human-readable `decisions.md` and `progress.md` projections. Never
recover gameplay from retired run-local JSON/JSONL files.
For lineage, `[SCENE] Restore SceneController` is only an engine lifecycle message—not physical scene identity.
Only explicit `ChangeScene … to X`, `currentScene=X`, or coherent save/event evidence may constrain the scene.
After milestones update verified quest steps/status, run `python3 -I tools/gen_quests.py`, and update
current `runs/<task>/plan.md` and log. Record surprises in `docs/troubleshooting/INDEX.md` and fix their one canonical doc/tool/skill in the same pass.
Completion is evidence-backed coverage/proof; constrained work is reported as constrained. Filling doc gaps beats winning.
