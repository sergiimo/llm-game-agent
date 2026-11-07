# Receipt-First Observer Design

> **Summary:** one settled post-action frame is simultaneously the immutable outcome receipt, the next model view,
> and the source for corrections. Vectors remain the primary current-frame navigation evidence; graph, save and log
> data are incrementally projected as task-relevant context rather than rebuilt and dumped on every turn.

## Intent

Make the model the driver of the whole game while reducing latency, stale-coordinate errors and repeated reasoning.
The runtime supplies coherent perception, guarded single-input primitives, durable evidence and relevant memory. It
never chooses a target or schedules a workflow.

## Goals

- One full observation per completed action, not pre-action + post-action + next-turn observations.
- One immutable `view_id` joins frame, OCR controls, bubbles, vector candidates and model decisions.
- A cheap preflight refuses stale screen-relative decisions with zero input.
- The final settled frame becomes the next `NEXT` view without another capture.
- Vectors identify visible navigation/object candidates; graph state scopes and contextualizes them.
- Detector outcomes distinguish `searched`, `disabled`, `untrained`, `no_match` and `error`.
- Save, log, graph and vector-store work is revision-cached and projected to the active task.
- Surprise handling identifies wrong decisions, bad learned data, uncertain observation and code failures separately.
- Preserve durable intents, unknown-input recovery, event-owned identity, transaction phase/crop and financial bounds.

## Non-goals

- No background observer or continuous GPU loop.
- No automatic workflow scheduler in Python.
- No replacement of learned vectors with model vision.
- No claim that pixel change proves progress or arrival.
- No compatibility promise for private legacy multi-input drivers after public cutover.

## Normal loop

```text
compact current view
→ model selects one primitive bound to view_id and candidate/control ID
→ cheap scene/modal/camera preflight
→ durable intent
→ exactly one input
→ settle while retaining final frame
→ evidence + perception + integration
→ the same receipt becomes the compact next view
```

Cached reads perform no capture. Explicit `read` captures once. Modal turns skip world-vector inference. A surprise
branches to preserved-frame inspection and one explicit correction before any further world input.

## View contract

`ViewSnapshot` contains an immutable ID/path/time, mode, clock, scene provenance, captured controls and bubbles,
effective vector scope and stable candidates. `WorldSnapshot` contains revisioned task-relevant resources and graph
clues. `TurnContext` exposes the active interaction, coverage, latest result, optional `need`, and allowed operations.
Full graph/history remains available through explicit read-only queries.

Screen-relative actions carry both `turn_id` and `view_id`. Target/control actions reference captured IDs; free-ground
waypoints retain an explicit point plus the same `view_id`. If preflight detects a changed scene, blocking modal or
camera registration outside tolerance, it returns `stale_view`, records `input=not_issued`, and supplies a fresh view.

## Observation rules

Every visual reader receives the caller-owned image. No observation helper may call `WF.grab()` internally. OCR,
HUD clock, screen mode, bubbles, controls, vectors and model vision all refer to the same frame. `wait_settle()` returns
its final full frame rather than discarding it. Frame features are cached by `(view_id, model_revision)`; store/sample
metadata is cached by data revision. Existing all-kind competition semantics remain until detector evaluation proves a
safe smaller competitor set.

## World projection

The runtime tracks save revision, log cursor, graph revision and vector-store revision. It parses only new log bytes
and only decodes a save when its revision changes. The model receives current region ancestry, visible candidate graph
hints, relevant exits/routes, active resources, changed facts and contradictions—not every node and edge.

## Surprise and vision

`need.kind=vision` is operational: allowed decisions become `inspect`, `correct`, `read`, `stop`. Reasons distinguish
wrong model choice, learned-data conflict, insufficient observation and runtime/code failure. Corrections reuse the
preserved source frame and cached features. Detector failure is never represented as a successful empty result.

## Safety and durability

Canonical intent is durably journaled before input. Canonical outcome/integration evidence must be durable before the
task clears its WAL. Restart never repeats uncertain input. Movement, progress and arrival are separate fields. Event
identity outranks projection; financial and destructive choices retain their existing authorization gates.

## Approaches considered

1. Optimize current `TurnContext`: smallest change but retains duplicated concepts and oversized observations.
2. **Receipt-first loop:** selected; coherent evidence, compact decisions and one expensive pass per action.
3. Persistent background observer: rejected for continuous GPU work, snapshot races and invalidation complexity.

## Acceptance

- A normal action's final frame ID equals the next turn's view ID; no extra full observation occurs.
- Production clues introduce no hidden capture.
- Controls, bubbles and vectors share one view ID.
- Stale view preflight refuses input.
- Modal actions skip DINO.
- Effective detector scope reports disabled/untrained/error/no-match distinctly.
- Hot appearance corrections reuse cached frame features.
- Journal failures cannot mark evidence applied or clear pending intent.
- Context size remains bounded as graph/history grow.
- Recorded garden, house/bed/map and shop traces retain identity, authorization and completion proof.
