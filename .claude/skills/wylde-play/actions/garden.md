# Garden maintenance

> **Summary:** the model accounts for every bed and hive in the named region through one durable interaction at a
> time. Crop, phase and positioned-event identity survive pauses, corrections and nested subgoals.

Prerequisites: current clock/weather/can, reviewed run, `region` and authorized crops/seed. Bare `./wf garden` or
`./wf play garden` observes the same task. Read the coverage set and [interaction laws](../../../../wiki/mechanics/interaction-laws.md).
General maintenance includes empty beds; narrow water/harvest work does not. Preserve flowers unless named crop
permission authorizes collecting them. A ready `!` means collectible. A plant plus drop needs interaction evidence
to distinguish dry from wilted; appearance alone never proves watering need.

Select a visible uncovered bed/hive with its full road, or one short waypoint. Inspect and bind the actual node only
from a positioned game event; projected ownership is provisional. Apply its state rule immediately: collect permitted
ready crops/honey; remove wilted crops; plant the remembered/requested crop (or an available seed when unspecified);
water after planting unless raining; verify. Each control is a separate decision, even when policy recommends it.
The planted-stat line proves planting; water/hive events prove their action. A zero-input verification records only
the actual event-owned node as covered. Never replace an unfinished target with a new one.

On an empty Seeds picker, preserve the crop and choose `blocked_target` with the actual node, exact evidence, and
`data:{"node":"<node>","reason":"seed_shortage","item":"TulipSeed"}` when that is the observed shortage. Other
constraints use an explicit nonempty reason. Blocking releases that interaction without teaching completed work.
Push sleep/refill/shop subgoals as needed; their workflows are text, not schedulers. A verified matching acquisition
reopens only matching shortages. After explicit return/resume, inspect and finish those beds; acquiring seeds is not
planting them. Blocked/covered accounting can finish as constrained, which must be reported honestly.

Wrong identity/card/modal, no progress, unexpected event, stale clue or missing proof requires look/correction before
another input. Rain/darkness/at-or-after-18:00 requires sleep or human handoff; empty can requires refill. Completion accounts for
every bed/hive as covered or explicitly unresolved; successful completion has no remaining constraints.

For a garden task that will sell/buy during shortages, declare its exact sale bounds and category purchase bounds
at root creation; a later shop child cannot expand them. Preserve the root garden task while pushing each bounded
item trade. After all shops, compare the root trade results with the complete combined catalogue separately from
garden coverage: covered beds alone do not prove every requested trade happened.
