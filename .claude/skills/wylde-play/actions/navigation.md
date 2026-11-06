# Navigation and foraging

> **Summary:** use graph/vector results as dated clues; the model chooses every visible target or short waypoint.
> Every click returns to `play`; no route, search, forage or retry loop runs inside Python.

Prerequisites: read the active goal/transaction, exact clock, current modal and full-scale frame. Tara stays at the
frame centre. Graph edges/detector matches are hypotheses with provenance, never permission to click off-screen.

Choose a target click only when both the target and its entire walkable road from the centre are visible. Otherwise
choose one short visible-ground waypoint, then inspect the returned frame. On a map, close it explicitly before world
input. To open a map use one `key:m` decision; reading the map never implies an automatic open/close sequence.

For measurable travel, state `destination_position:[x,z]` and compare captured before/after positions; a smaller
distance is progress. A matching expected event, card or region can also provide relevant observation. No move,
movement away, unrelated movement, wrong region/object/modal, stale route or failed vector match is a surprise.
Read the captured frame; revise the click, correct the exact named edge/location/kind, record a gap, or ask the human.
Never retry a stale direction silently. Completion needs captured matching `region` evidence; unsupported or stale
placement stays unresolved. Use a navigation subgoal when travel interrupts another interaction.

Foraging (`./wf forage rock|chop|pickup|forage`) uses vision, never graph nodes. Inspect one target, click its visible
road/bubble, choose a single highlighted tool/pickup action, and read damage/destroy/grab-item evidence. The historical
expected hit counts in `docs/actions.md` are estimates, not an instruction to repeat N inputs. Inspect drops and choose
each pickup separately. Wrong tool/target or absent damage/pickup proof requires correction. Completion means all
model-counted drops/targets have their event proof or explicit unresolved constraints, with no unproved claims.
