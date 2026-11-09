---
name: wylde-navigate
description: Move Tara around Fairhaven in Wylde Flowers by clicking (click-to-move), the map, and recognising arrival. Use when the next step requires going somewhere in the game.
---

# Navigating (mouse only, qualitative graph)

Navigation is the same engine workflow everywhere: outdoors, indoors, and garden. The object graph contains nested
regions and landmarks; `./wf play navigate destination=<Kind>` resolves the observed current region to one coherent
path and returns only the next edge. Each navigation edge is `compass=N|NE|E|SE|S|SW|W|NW` plus
`range=near|mid|far`, with optional scene transition. Numeric world positions and calibrated paths are retired as
route authority. Coordinates in old data are debug/provenance only; do not extend `tools/world/`, `tools/nav/`,
`goto`, `go-world`, `pos`, `calib`, route files, or coordinate facts.

## One turn

1. Push a generic `navigate` child whenever another task needs travel, including garden work. A non-navigation task
   cannot issue a waypoint.
2. Read `NEXT.navigation.next_edge` and the exact full-scale frame. Tara is at frame centre.
3. If the named target and its complete walkable road are visible, click the target. Otherwise choose one visible
   ground cell/point in the requested compass and `near|mid|far` band. A screen point identifies only this frame's
   click; it is not persisted as a route coordinate.
4. Submit exactly one `waypoint` or target decision, with frame evidence and both graph/screen qualitative bearings.
   The guard allows at most one adjacent compass-sector difference and requires the same range band.
5. Read the settled outcome and fresh frame. Waypoint movement alone never advances the graph. Only captured scene,
   region, transition, or positioned-object ancestry can prove the next node or complete the child.

At doors, gaps, bends, occlusion, or an unknown screen, take a shorter visible-road step and observe again. A map is
an optional current-frame observation for an unresolved long outdoor segment, not a coordinate source or hidden
route executor. Close it explicitly before world input. Keyboard movement and blind loops remain prohibited.
When an exact goal has no explicit map marker, bind only `navigation.goal.map_anchor` (the nearest labeled ancestor)
and locate the subobject locally after reaching that ancestor. Map compass is world-space, not screen-space: select a
screen branch only from visible landmark/junction topology, otherwise backtrack to the last proved junction rather
than guessing a same-named screen direction.

## Failure and learning

`unresolved_destination`, `unresolved_graph_position`, or `unresolved_path` means the graph lacks a coherent route;
inspect the current frame and correct the exact node/edge or record a gap. A qualitative mismatch means the proposed
click is in the wrong compass/range sector; select a new point from the same fresh frame. `NO MOVE`, irrelevant/away
movement, a stale vector, wrong region/modal, or an expected exit that is visibly present but produces no transition
is a surprise: preserve the frame and experience, then revise the decision or add the smallest evidence-backed
graph/vector correction. Do not silently retry.

For a gap/threshold crop labelled `state=structure`, the detector must match the aligned whole window and clear both
relative and absolute similarity. Never reinterpret a low-absolute structural hit as an object patch. Tara remains in
every regional vector scope so an OCR-poor world frame can still prove gameplay and visual movement.

The known Farm path is nested like indoors: `House → HouseExit → Farm → Garden → Well`. Garden has no private
navigation algorithm. A garden transaction freezes while its `navigate` child runs, then resumes after captured
Garden/Well proof.

For repeated lack of progress, follow AGENTS.md's stuck rule and write the stuck retro. For the stable regression,
start at a fresh House+Bed clue with `./wf live-eval start bed-to-well`, play through the ordinary navigation turns,
then run `./wf live-eval finish` and `./wf live-eval report <id>`. Fresh start and destination proof require coherent
current visual evidence (or a positioned Well interaction at the destination); static graph membership is not proof.
Finalization is immutable. The SQLite report compares issued physical inputs, observations, no-moves, wrong transitions,
surprises, elapsed time when available, and start/finish toolkit revisions.
When bookkeeping starts late, the command may bind to the immutable coherent `sleep_spawn` Bed clue of the same still-
active restarted task and include its already-issued inputs. Never walk backward to recreate a Bed candidate; task ID
and spawn provenance are the boundary, and evidence from any older task remains invalid.
