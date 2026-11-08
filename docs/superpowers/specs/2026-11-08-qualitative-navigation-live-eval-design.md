# Qualitative Navigation and Live Evaluation Design

## Intent

Navigation should reason over the world the same way at every scale: a persistent topology of regions, exits, and
landmarks, plus qualitative guidance from the current observation. Coordinates are measurement evidence, not route
authority. Garden travel is ordinary nested-region navigation, identical in structure to leaving a house or entering a
shop.

## Goals

- Plan routes through one object graph using nodes and directed `nav` edges.
- Give each edge qualitative guidance: compass plus `near`, `mid`, or `far` range.
- Keep pixel/world coordinates only in observation and SQLite evidence for diagnostics and evaluation.
- Require an explicit `navigate` subgoal for every waypoint, regardless of the parent gameplay goal.
- Keep save, log, and HUD clocks separate inside an observation; never promote save time to the live action clock.
- Add a SQLite-backed live evaluation scenario for `bed-to-well` with comparable results across commits.

## Non-goals

- Reconstructing a metric world map.
- Automatically choosing screen points or issuing movement.
- Replacing model vision for deciding whether a road or target is actually visible.
- Migrating historical JSONL benchmark results.

## Anti-goals

- Goal-specific navigation modes such as “garden navigation.”
- Persistent route decisions derived from world coordinates, map pixels, homographies, or dead reckoning.
- Treating a waypoint movement as proof that a graph node was reached.
- A single mutable `game_time` that conflates multiple evidence sources.

## Architecture

### Persistent topology

The static object graph owns route topology. A `nav` edge is always walkable and may carry:

- `compass`: one of `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`, `NW`;
- `range`: `near`, `mid`, or `far`;
- `transition`: the scene/region signal expected after crossing an exit;
- `source`: provenance for the edge.

Route search is breadth-first over these edges. The current node comes from the coherent observed scene/region or a
transition-proven durable node, never nearest-coordinate matching. A route receipt exposes the next edge and qualitative
guidance only.

Screen coordinates remain local to a single captured view. The guard converts the model-selected point into an observed
screen compass and range relative to Tara, then compares those qualitative values with the edge. It does not project the
point into world coordinates.

### Generic nested navigation

Every movement waypoint requires the current goal to be `navigate`. A garden, sleep, shop, or quest goal that is not in
its target region must push a normal navigation child, complete it from region/transition evidence, and resume. Direct
target clicks remain legal when the target and its entire walkable road are visible.

### Clock evidence

Every coherent observation may contain separate values for:

- `hud_hour`: the visible clock reading;
- `log_time`: the current log timeline stamp used as action time;
- `save_time`: the selected save snapshot stamp, carried only with save-derived resource/position provenance.

Refresh these values at observation boundaries: task creation, before input, after input, scene transition, relevant game
event, autosave-dependent operation, and contradiction. No clock value is advanced locally.

### Live evaluations

SQLite stores evaluation definitions/runs and immutable checkpoints. `bed-to-well` begins from a coherent House/Bed
observation and succeeds only when a fresh observation or positioned interaction proves the Well/Garden destination.
Reports include inputs, observations, no-moves, wrong transitions, surprises, elapsed real/game time when available, and
the final verdict. Reports compare by scenario and git revision without tracked JSONL output.

## Approaches considered

1. **Metric graph cleanup.** Keep world coordinates and improve filtering/calibration. Rejected because it preserves the
   wrong planning authority and repeats the current stale-anchor failure.
2. **Pure model vision without topology.** Ask the model for every next click. Rejected because it forgets stable world
   structure and cannot evaluate route predictions.
3. **Qualitative topology with observation-local geometry.** Selected because it preserves stable knowledge, lets model
   vision own visibility, works for nested indoor/outdoor regions, and produces testable predictions without pretending
   coordinates are durable truth.

## Constraints

- One input per turn and no automatic movement loops.
- Any contradiction or stale lineage remains zero-input.
- Persistent runtime/evaluation state is SQLite; tracked JSONL files receive no new live records.
- Existing coordinate fields may remain as historical or object-identity evidence, but navigation code must not read them.

