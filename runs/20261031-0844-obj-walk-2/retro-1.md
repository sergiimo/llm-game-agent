# Retro 1: obj-walk-2 step 1 escalated (D150 10:51–11:04)
Evidence: `walk.walk(Well#13)` ✓ in 9.6 s while she stayed at (2.9, -22.5); the bubble list matched hive honey bubbles
("unknown") to Well#13, whose position had moved to (0.17, -21.41).
Causes (both mine, reproduced by tests): (1) walk counted an unknown-kind bubble matched by position as the target's
bubble → false arrival; (2) the world replays the session log at daemon start; this morning's `full_watering_can
target=Well` became a pending use, and the next reading (far from the well) became a use point.
Fixes: unknown bubbles never prove arrival; replay ends with no pending use; the Well repaired to its D148 use point.
Not explained yet: `./wf state` read "overlay" while the screen showed gameplay (rain?) — watch in the next run.
