# Entering and leaving regions

> **Summary:** follow fresh doorway geometry one click at a time and prove the region transition from the game log.
> These verified house rules are workflow knowledge; Python never chooses the sequence.

For a long trip between regions or to a remote entrance/merchant, first use and learn the map as specified in
`navigation.md`. The doorway steps below are local approach, not a substitute for map-based route planning.

Outside the farmhouse, click the visible entrance/porch and inspect the result. Do not click a bed through the wall
as a route to the house. After entering, Tara's bed is west. Recognize `OnEnterBuilding House`/the interior view,
then inspect the bed/road in a fresh frame. `OnEnterFarmHouseArea` or `OnEnterFarmPorch` alone does not prove indoors.

To exit, first use the interior opening between two white posts with no railing across it. The lower wall and porch
railings are solid. The opening's screen column changes as the camera follows Tara: use a fresh frame, not old cells.
Once on porch boards, choose the exterior stairs, then inspect outside and the exit/scene evidence. Each opening,
stair and onward waypoint is a separate model decision.

Prerequisites: current region/modal, visible walkable road, preserved parent interaction if returning. A blocked
entrance, no move, unexpected interior, wrong building, or unknown modal is a surprise. Read the outcome frame and
correct the named region/edge or your decision; never auto-close a useful panel or repeat an old route.

For other buildings the same recognition/evidence rules apply; load the relevant screen/location doc for the actual
entrance and merchant. A navigation/enter/exit subgoal with `params:{"region":"House"}` completes only after captured
matching region evidence. Complete then explicitly resume the parent; a camera change alone is insufficient.

D209 failure evidence includes `[D209 6:38:02 PM] [TRIGGER] OnEnterBuilding House`. Subsequent guessed eastward
waypoints did not establish bed arrival. Entry evidence and bed approach proof are separate.

Named nested areas need no scene change: a fresh positioned interaction with a known member records its graph
region ancestry in the immutable outcome. Navigation completion accepts that captured proof for any named
ancestor region; stale graph location alone or an unknown/conflicting latest object event cannot complete arrival.

Scene scope is applied before kind/position matching. A same-coordinate object in another scene cannot mask
the current scene’s member; multiple compatible current-scene candidates remain ambiguous and require a gap or
correction. The event update, canonical interaction identity and card attribution use the same scoped match.

Production observations keep physical `scene` separate from the current building/region. Each positioned event
retains its own source scene/scope across scene changes, snapshot refresh and immutable replay. A newer save
anchors later events; older scene-log entries cannot override its physical scene. If `graph_clues` contains a
`world_conflict`, inspect the source frame and correct the named identity/placement or record a gap. Ambiguous
or unknown source context does not update an arbitrary candidate.

An explicitly unknown before-scene stays unknown for events preceding a scene transition. The final scene
reading cannot retroactively label those events. A transition before a later positioned event can establish
that later event’s source. Compatibility applies only to legacy adapters declaring no location context.
