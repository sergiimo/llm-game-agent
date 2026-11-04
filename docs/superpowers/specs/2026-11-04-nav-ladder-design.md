# Navigation ladder: one decision per step, distance tiers in the graph

> **Summary:** user D188 (after five lost live runs): replace the search cascade with one ladder per step - target
> visible by vectors -> walk to it; else the graph says close and knows the direction -> step that way (around
> obstacles); else the map -> long steps that way. After each step Tara's place in the graph is updated (tier, pin,
> nearest node). Any failure -> model vision, log reading, gap bundle. Distance is tracked from far to near:
> map-far, screen-far, steps-far.

## Why
The cascade (graph -> heading -> soil -> detections -> explore -> map) let any one noisy source drive clicks:
phantom bed detections far from the garden, a misread map pin (598,461 -> 1320,419 in one minute), the map read once
and then forgotten. Each fix patched one branch; the next run hit another.

## The ladder (`nav.seek`, one round)
1. **Tier** (`nav.tier`), cheapest evidence first:
   - **steps-far**: a bubble of the target kind in view (the search's fit check acts on it);
   - she is inside the target's region (graph), or her exact position is near the target -> **near**;
   - else ONE map reading: pin -> target's map point distance > `NEAR_MAP_PX` (60) -> **map-far**, else **near**;
   - no map reading possible -> **unknown** (the near rungs are tried, nothing is trusted more).
2. **map-far**: the map rung only (`map_walk`: long steps, dead ends, the vision way question). Detections are
   never used here (they are phantoms far from the target).
3. **near / unknown**:
   a. the target kind **visible by vectors** = embeddings (`observe.see`: DINOv2 patch embeddings against the
      labelled crops of `tools/objects/db/<kind>`) -> walk to free ground beside it (**screen-far**);
   b. the **graph's direction** from the node she is at (`toward`) -> a step that way; a blocked step turns
      (obstacles);
   c. inside the region without a direction -> explore free ground;
   d. else the map rung.
4. **After each step** (`nav.update_tara`): the graph's Tara node keeps `tier`, `pin` (last good map pin), `near`
   (the node she is at), `pos` (exact, from an event), `t`.

## Distance is a graph edge (user D188: "so a new distance edge?" - "yes")
- **Tara -> target** `distance` edge, rewritten after each step (`nav.update_tara`, `objects.graph.set_edge`):
  `tier` (map-far / near / screen-far / steps-far), `map_px` (straight, pin to the target's map point), `route_px`
  (along the map's roads), `source`, `t`. A step without a map reading keeps the last distances.
- Progress is judged against it: this call's best, else a fresh edge (< 10 min) from the last call.
- The map rung's target point comes from map embeddings (`map_vectors.locate`: DINO features of `map_db` crops).

## Ways between nodes keep a compass point
Every `toward` edge (seeded, learned, or from a vision way answer) stores `compass` (N..NW) next to `dir`
(user D188: "graph as before should store compass direction for nodes connections"); an edge known only by its
compass point gives the direction too. A learned way also keeps its distance (`route_px` from where it started).

## Readings are checked
- A map pin more than `PIN_JUMP` (150 map px) from the last good pin within the call is rejected (no step), logged,
  and vision is asked (the way question with the last good pin).
- Arrival misses, LOST, STUCK and rejected readings write a gap bundle (owner `nav`) with the experiences involved.

## Tests (tools/test_engine.py `NavLadder`)
map-far skips detections; near uses detections; the graph direction is used when nothing is visible; a pin jump is
rejected with a question and a gap bundle; Tara's tier and pin are in the graph after each step.
