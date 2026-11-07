# Navigation and foraging

> **Summary:** long-distance navigation uses and learns the map first; visible-road steps serve local approach or a proved map limitation.
> Every click returns to `play`; no route, search, forage or retry loop runs inside Python.

Prerequisites: read the active goal/transaction, exact clock, current modal and full-scale frame. Tara stays at the
frame centre. Graph edges/detector matches are hypotheses with provenance, never permission to click off-screen.
Read `NEXT.vector_detections` first: these learned appearance vectors are the primary current-frame landmark/object
evidence and are computed from the same frame as bubbles/OCR. Use the graph to scope and interpret them. If an
expected learned kind is absent or contradicts the graph, inspect the frame with model vision and correct the vector,
graph or decision explicitly; never silently fall back to a stale route.

The map workflow is outdoors only. When `region=House`, first click the visible interior exit/opening, then the porch
stairs, then one more outside waypoint until the house interior is gone and the exterior is fully rendered. Only
then open the map. An indoor `m` request is a guard refusal and issues no input.

**User rule:** before a long-distance trip or searching for an off-screen destination, issue one canonical guarded
`action:{kind:"key",label:"m",expects:{mode:"map"}}` from proved gameplay. Inspect the full-scale result, locate
the pin, destination/landmark candidates and road connections, and learn from it before choosing a route. Record
these observations and their uncertainties in the next versioned decision's rationale/evidence_refs (canonical run
timeline); retain the map frame. Correct an existing graph edge/location or appearance label only with supported
source-frame proof, and consolidate verified route knowledge after milestones. Map pixels are not world coordinates
without calibration. Python does not select routes, decide when a trip is long, schedule map calls or move for you.

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

Map mode requires the large paper-framed map layout plus its pin. A HUD `M` icon or pink-colored world scenery
alone is not a map. A genuine map still blocks world clicks; preserve uncertainty rather than click through it.

For measurable travel, state `destination_position:[x,z]` and compare captured before/after positions; a smaller
distance is progress. A matching expected event, card or region can also provide relevant observation. No move,
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

For a model-selected visible-road waypoint, declare the atomic movement expectation explicitly, for example
`action:{kind:"waypoint",point:[<x>,<y>],walkable:true,expects:{moved:true}}`. Matching `expects.moved=true` and captured `moved=true` is relevant step evidence. A stationary
waypoint still reports no progress when `expects.moved=false` matches `moved=false`. Absent or mismatched expectations still require the usual conservative
progress checks. Complete navigation only after captured matching region/ancestry proof; a movement check
does not complete the region handoff. Read the returned frame before selecting another point.

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
frame before choosing any next input; keep NEED_VISION/surprise when proof remains missing. Do not replay the refused
or uncertain point automatically.
