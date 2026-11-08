# Navigation and foraging

> **Summary:** navigation follows nested graph edges expressed as compass plus near/mid/far; screen points identify one current-frame click only.
> Every click returns to `play`; no route, search, forage or retry loop runs inside Python.

Prerequisites: read the active goal/transaction, exact clock, current modal and
`NEXT.navigation.localization`. Tara stays at the frame centre. The localization packet carries `stage`, `current`,
`prior_hint`, current-frame `landmarks`, and `graph_slice`. Each landmark supplies `landmark_from_tara` and the
inverse `tara_from_landmark`; the route is in `graph_slice.route_edges`.

Use the localization cascade exactly:

1. At stage `vectors`, localize Tara from the returned vector landmarks plus graph relations and **do not run a
   separate model-vision localization escalation**. The acting model still reads the current full-scale screenshot
   on every turn to verify the target/entire walkable road and choose the one current-frame click; vectors replace
   visual semantic localization, not road-safety inspection.
   A returned localization vector is usable evidence. A wrong returned vector is a vector-system defect: stop route
   continuation and fix its label/detection/calibration rather than silently bypassing it with vision.
2. At stage `vision`, and only because the current frame has no vectors, read the full-scale image at `view.path`.
   **At or after 18:00, stop before vector creation:** evening/darkness is not valid appearance-training evidence. Existing
   vectors may still localize, but do not create, update, calibrate, or keep any vector from the dark frame. Defer the
   missing exemplar until daylight. For the return-home/sleep interrupt only, use current-frame model vision as
   ephemeral localization and choose one visible-road step without persisting a vector. Stop safely only when the
   dark frame does not show enough road/landmark evidence for that one step.
   If an identifiable unique graph landmark is visible, prefer a stable crop. Gameplay zoom is stable per scene, so
   calibrate each crop once in source-frame pixels for that scene; do not enlarge it merely to simulate arbitrary
   zoom invariance. An ordinary patch vector should be object-dominant, normally 100–300 px and at least about 80×80
   source pixels (four DINO patches per side). For a whole structure or contextual landmark, use a separate matching
   landmark kind and `state=structure`; normally crop 300–900 px with about 0.5–1 object width of recognisable context
   per side. A mailbox crop includes the full box, post and adjacent fence/road (roughly 250–400 px in the calibrated
   Farm view), not an unconditional 300 px margin on every side. Scale is stable but viewing angle can vary: keep a
   few clean angle exemplars at the same scene-calibrated scale rather than expanding one crop indefinitely.
   Different scene zooms or stable visual states get separate scene/state templates. Do not label a large contextual crop as a tight sub-object kind. If Tara occludes
   the identifying shape, the frame clips it, or the requested context is unavailable, skip that landmark for now
   instead of storing a partial vector. Create an ordinary vector with
   `./wf objects add <kind> x0 y0 x1 y1`, or a spatial-context template with
   `./wf objects add <kind> x0 y0 x1 y1 structure`, preserving frame/crop
   provenance, then submit a zero-input `read` on the saved turn so detection reruns. The receipt names this step
   `identify_unique_object_and_create_vector`. Keep it only when that immediate reread returns the correct landmark
   and no stronger false peak; otherwise remove or region-disable it.
3. Only when stage 2 leaves localization unresolved, use the outdoor map. The receipt names this fallback
   `map_if_still_unresolved`; it is stage 3, never the first localization step.

Before any movement, replace belief `current` with a semantic relation justified by the packet, for example
`west of Farmhouse`, then derive `next_objective` from that localized position and `graph_slice.route_edges`.
Do not infer that a visually plausible bridge or road leads to the goal without that graph derivation.

Push a generic `navigate` child before any waypoint, including from garden work. Read its localization packet and
`navigation.next_edge`; then choose a target or visible-road waypoint that serves the localized graph objective.
A point/cell binds the atomic click to that view and is discarded afterward. Do
not derive, persist, or compare world coordinates, calibrated distances, or dead-reckoned positions. Garden,
interiors, and outdoors all use the same nested graph path.

The map workflow is outdoors only and is localization stage 3 after a no-vector vision pass could not create usable
unique-landmark coverage. A canonical guarded
`action:{kind:"key",label:"m",expects:{mode:"map"}}` produces another source frame for model interpretation; it
does not become a coordinate system or automatic route. Record landmarks/road connectivity as qualitative graph
evidence. An indoor `m` request is a guard refusal and issues no input.

Close a recognized map in its own turn with `action:{kind:"close",expects:{mode:"gameplay"}}` before any world
input. The dedicated `close` primitive issues the guarded Escape. Do **not** encode this as `key:m` or `key:esc`:
`key` is only for opening `j`/`m`/`i` from gameplay, so those map-screen attempts are guard refusals that issue no
input. Read `verdict.checks` and `artifacts.frames` before interpreting a no-change result. Then choose one visible-road step along the
model-selected map route and reassess. Reopen/compare the map when localization or the next long segment needs it.
Visible-road-only navigation is for local approach, or a fallback **after** a correctly issued map request/result
proves it unavailable or insufficient; record that limitation. Invalid/refused map requests prove neither. Do not
replace map learning with a long chain of guessed waypoints.

Choose a target click only when both the target and its entire walkable road from the centre are visible. On a long,
clear road, choose the **farthest safe walkable point** along that road whose entire path remains visible; this avoids
wasting turns on tiny steps. Use a short visible-ground waypoint only at a bend, threshold, occlusion, or uncertainty,
then inspect the returned frame. On a map, close it explicitly before world
input. A menu key uses `label`, for example
`action:{kind:"key",label:"m",expects:{mode:"map"}}` inside one versioned `act` decision. Do not send
`{kind:"key",key:"m"}` or `press` the HUD hotkey letter `M`: those are refused before input. `answer=key:m` is
also accepted as one guarded menu-key input, but carries no automatic prediction; prefer the explicit expected-mode
JSON. Reading the map never implies an automatic open/close sequence. A guard refusal with no after frames proves
no attempt reached the game; it does not prove a missing/unavailable map or focus failure. If a correctly issued
request fails, inspect and record its outcome before choosing the bounded local fallback.

Map mode requires the large paper-framed layout plus either the labelled paper/cloud-header appearance vector or
the map pin. The header vector proves that the modal is open; the pink pin localises Tara when its current palette is
detectable. A HUD `M` icon or pink-coloured world scenery alone is not a map. A genuine map still blocks world
clicks; preserve uncertainty rather than click through it.

`HouseExit` is a structural appearance vector for the complete unrailed wall opening. A valid candidate point lies
inside that gap between its boundary posts; individual wall, railing, or porch-board patches do not prove the exit.

For measurable travel, state the expected compass/range edge and relevant destination region/transition. A matching
expected event, card, scene, region, or positioned-object ancestry provides progress proof. No move,
movement away, unrelated movement, wrong region/object/modal, stale route or failed vector match is a surprise.
Read the captured frame; revise the click, correct the exact named edge/location/kind, record a gap, or ask the human.
Never retry a stale direction silently. Completion needs captured matching `region` evidence or fresh positioned-object graph ancestry; unsupported or stale
placement stays unresolved. Use a navigation subgoal when travel interrupts another interaction.

Foraging (`./wf forage rock|chop|pickup|forage`) uses vision, never graph nodes. Inspect one target, click its visible
road/bubble, choose a single highlighted tool/pickup action, and read damage/destroy/grab-item evidence. The historical
expected hit counts in `docs/operations/actions.md` are estimates, not an instruction to repeat N inputs. Inspect drops and choose
each pickup separately. Wrong tool/target or absent damage/pickup proof requires correction. Completion means all
model-counted drops/targets have their event proof or explicit unresolved constraints, with no unproved claims.

Captured D209 failure: the legacy Bed search said `map: no direction`, then accepted three waypoint answers on an
overlay with no events and `moved=false`. This is not a route. The legacy overlay label alone does not establish a modal: current textless-overlay classification is gameplay.
The universal no-move boundary blocks another input; inspect the captured frame and correct the decision/clue or record a gap before continuing.

For a named nested region, an interaction event from the selected input can prove arrival at a known member.
The immutable outcome records `regions` and `region_provenance` from that object’s graph ancestry, agreeing with
the current scene/building. Use `expects:{region:"<nested region>"}`, then complete the navigation child after
that proof. A stored Tara location, nearest-object guess or no-event waypoint never supplies nested arrival.

One highlighted named affordance may also prove arrival when the current-region graph has exactly one unique provider
for it (for example `sleep` offered only by `Bed`). Complete the navigation child from that fresh zero-input receipt,
resume its parent, and interact under the parent workflow; do not click the affordance through an active navigation
child merely to manufacture object proof.

For a model-selected visible-road waypoint, declare the atomic movement expectation explicitly, for example
`action:{kind:"waypoint",cell:"F7",walkable:true,expects:{moved:true}}`. Matching `expects.moved=true` and captured `moved=true` is relevant step evidence. A stationary
waypoint still reports no progress when `expects.moved=false` matches `moved=false`. Absent or mismatched expectations still require the usual conservative
progress checks. Complete navigation only after captured matching region/ancestry proof; a movement check
does not complete the region handoff. Read the returned frame before selecting another point.
Explicit virtual coordinates may be supplied as either `point:[x,y]` or equivalent numeric `x` and `y` fields; the
boundary normalizes both to the canonical point before frame/HUD checks.

If the capture is unknown or black, use the versioned zero-input `answer='{"kind":"read"}'` to refresh it while
retaining the task/stack. OCR, affordances and the saved frame now come from the same capture. Black pixels never
prove movement or gameplay. A later authoritative snapshot may establish changed position/scene only with matching
save lineage and advancing count/time at/after the input clock, without another domain input sharing the stale
baseline, including completed/resumed child history; the original incomplete experience remains immutable.
Fresh evidence must satisfy every original expectation through the normal check/outcome rules. Movement within
the old region cannot resolve a promised arrival elsewhere; absent node/event/card/log/modal proof stays unresolved.
Older outcomes recover full expectations only from their exact canonical intent, never a partial Prediction.
If the source outcome says `unsafe` / `world input blocked by unknown`, the guard issued no click: fresh known-screen
observation can resolve that refusal, but movement from an earlier action cannot credit it. Inspect the fresh full-size
frame before choosing any next input; keep the vision need/surprise when proof remains missing. Do not replay the refused
or uncertain point automatically.
