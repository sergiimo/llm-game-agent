# Entering and leaving regions

> **Summary:** follow fresh doorway geometry one click at a time and prove the region transition from the game log.
> These verified house rules are workflow knowledge; Python never chooses the sequence.

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
