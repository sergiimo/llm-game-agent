# Guarded Navigation Receipts Design

## Intent

Simple visible-road turns must stay inside one gameplay model instead of waiting for a supervisor. Every navigation
turn must expose and retain enough compass and graph evidence to detect a waypoint that heads away from the route.

## Evidence

In the 20261107 home-to-supermarket run, observation-to-decision time had a 37.5 s median while input plus outcome
capture had a 4.1 s median and the next observation took under 0.1 s. The child escalated every screenshot to its
parent. At the Town bell, waypoint `[1770,470]` calibrated to world delta `(+15.25,+9.52)` (NE), while the known
fountain-square approach was SE; the turn contained neither a resolved destination nor a graph compass.

## Design

- Resolve a navigation task's requested destination through navigation data aliases to a graph node. Unknown
  destinations remain explicitly unresolved; code never invents a node.
- Project a bounded navigation receipt into every navigate turn: scene, current estimated position and provenance,
  destination, resolved goal node, next graph node/edge, required compass, distance, and calibration confidence.
- Advance the durable position estimate after a proved waypoint using the scene calibration. A scene change replaces
  the estimate with the newly observed scene position.
- Before a waypoint input, derive its calibrated world delta and compass. Refuse it when its compass differs by more
  than one 45-degree sector from an authoritative graph compass. Unknown graph/calibration data is logged but not
  converted into false certainty.
- Add the graph receipt and waypoint compass/alignment to the canonical turn decision and the timestamped
  `decisions.md` projection.
- Gameplay children inspect their own captured frame and continue clear-road hops without asking the supervisor.
  Escalation is reserved for unresolved destinations, absent routes, guard refusals after correction, or surprises.

## Approaches

- **Chosen: model-owned waypoint plus deterministic receipt/guard.** Preserves the model-driver architecture while
  catching compass contradictions before input.
- Logging only was rejected because it makes the same mistake reviewable but does not prevent it.
- A deterministic multi-hop navigator was rejected because it would move target selection out of the model loop.

## Constraints

- One physical input per continuation remains unchanged.
- Route and click directions are calibrated world compass values, not prose inferred from screen layout.
- All estimates name their provenance and uncertainty.
- No per-hop supervisor handoff on ordinary visible-road navigation.

