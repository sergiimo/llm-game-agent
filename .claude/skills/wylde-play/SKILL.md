---
name: wylde-play
description: Play Wylde Flowers through the universal model-owned one-turn boundary; read clues, choose one atomic input, verify evidence and record docs.
---

# Playing Wylde Flowers

Session start: read `AGENTS.md`, `docs/INDEX.md`, `active run plan`; then load only the relevant index/detail.
The supervisor owns one current goal and a reviewed run plan; gameplay children use the user's cheapest-model rule.
Check permissions, exact clock and current save/log before starting. A new task after 19:00 requires pre-approved
sleep first. Focus mode is front: pause before coding, documentation or long thinking.

For **every gameplay domain**, load [actions/INDEX.md](actions/INDEX.md), then the one workflow file it routes to.
Docs choose sequences; Python never does. `./wf play <goal> [k=v]` and bare domain aliases return `NEXT` without input.
Continue with the exact `turn_id` and one explicit model decision. Accept an obvious saved recommendation, choose one
primitive, inspect the full-scale source frame, correct data, push/suspend/complete/resume a subgoal, or stop. Read the
outcome before deciding again. Never use legacy `py`, `call`, batched commands or routes to run a hidden workflow.
Every `NEXT` prints `vector_detections` from the same captured frame and a compact `model_workflow` trace:
observe → decide → optional/required vision → act → verify → learn → repeat. Read it on every turn; it exposes
evidence/status and never substitutes hidden reasoning.

Game files first: `./wf log` for live events; `./wf save` for exact but potentially stale autosave facts; `./wf state`
for screen/HUD text. A `look` decision returns the saved 1920×1080 frame without input; read it for uncertainty.
Tara is at frame centre. A target needs its entire visible walkable road; otherwise choose one short visible-ground
waypoint. Move only by clicking. Current modal and guard rules apply to each primitive; no blind key loops.

A surprise blocks gameplay until `look`, `correct` or `stop` resolves it. Preserve the active crop/phase/node and
parent interaction. Pending input reconciles from recorded evidence without repetition. Corrections update named
graph/vector/transition data with provenance, revise a decision, mark a constraint, record a gap, or report ambiguity
to the human; never patch runtime code while playing. Purchases require explicit root-task quantity/spend bounds and
matching inventory/money proof. Do not change settings, sell valuables or choose major story actions without scope.

The canonical chronological timeline is `runs/<run>/log.jsonl`; `experiences.jsonl` is machine replay evidence.
After milestones update verified quest steps/status, run `python3 -I tools/gen_quests.py`, and update
`active run plan`. Record surprises in `docs/troubleshooting/INDEX.md` and fix their one canonical doc/tool/skill in the same pass.
Completion is evidence-backed coverage/proof; constrained work is reported as constrained. Filling doc gaps beats winning.
