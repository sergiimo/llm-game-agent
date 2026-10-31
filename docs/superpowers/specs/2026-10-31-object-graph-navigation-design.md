# Object-graph navigation: objects, vectors, model vision

> **Summary:** replace the coordinate world model (screen calibration, zoom, position belief, costmap/A*, coordinate
> graph) with **objects**: an object graph (relations, states, groups), a vector store of what objects look like (many
> examples per kind), and the **model (the agent) as vision** for anything new or unclear. Navigation is a chain of
> clicks on detected objects in the current frame; reaching the target means its interaction started. No coordinates,
> no resolution-dependent geometry anywhere.

Status: design, 2026-10-31 (user-directed); steps 0–1 implemented 2026-10-31 (detection: DINOv2); nested regions (§3.1b) added 2026-10-31 (user). Supersedes §3 (world model) and the navigation parts of
`2026-10-30-agent-system-refactor-design.md`; its runtime, eval/bench, process and question protocol stay.

## 1. Why
The coordinate approach failed repeatedly in the garden (stuck ledger S11–S27): screen calibration broke under camera
zoom and a moved window, the position estimate was 6–27 % within 1 unit, clicks computed from geometry landed on hives,
and each fix uncovered another geometric assumption. Evidence of what works: clicking the visible object itself
(the well's roof, D150) made the game pathfind there and offer its bubble.

## 2. Principles
- **No coordinates.** Nothing is computed from world positions or screen calibration. Scene names (from the log) are
  the only location identity.
- **Every action is a click at (x, y) in the current frame**, on a detected object's main body or at a point the model
  answered.
- **Kind by appearance, identity by relations, state in the graph** (refreshed from evidence and the model).
- **The model is the vision fallback**; anything it can't resolve goes to the user (HITL). Every answer is stored.

## 3. Data model

### 3.1 Object graph (networkx, persisted JSON per area)
| Node | Fields |
|---|---|
| `Unique` | kind (Well, Door, Bed, NPC, Shop…), id, area, state, `vec` (link to its current vector record), seen (game time, source) |
| `Group` | kind (GardenBed ×12, BeeHive ×8…), area, **pattern** (layout of members, e.g. a 4×3 grid by rows), members |
| `Member` | group, index in the pattern, state, `vec` (current look), seen |
| `Region` | kind (Farm, House, Garden…), parent region, **entry signal**: `scene` (log `ChangeScene`, e.g. House) or `view` (no scene change; inside = we can detect (nearly) all members of one of its groups, so their states can be updated: ≥ 85 % of a group detected with the region's thresholds (user 2026-10-31; hives 7–8 of 8 inside vs 3–5 outside), e.g. Garden), children (objects, groups, regions) |

| Edge | Meaning (learned from evidence) |
|---|---|
| `in(node, region)` | belongs to the region (regions nest: Farm ⊃ House, Farm ⊃ Garden ⊃ {GardenBed group, BeeHive group, Well}) |
| `visible_from(a, b)` | b was detected in the same frame after reaching a |
| `leads_to(door, area)` | clicking/using it changes the scene (log `ChangeScene`) |
| `blocked_by(a, b, how)` | a hop a → b failed (how: refused click, no progress, wrong object) |
| `offers(node, action)` | the node's bubble offered the action (plant, water, fill_can, talk, sleep…) |

States are **hints with an age**. Writers: log actions on the **active object**, bubbles of the active/detected object,
the morning save (group counts only), model reconciliations, failures.

### 3.1b Regions: a graph inside a graph (user, 2026-10-31)
Each region is a subgraph. **From outside, a region is one object** with its own examples (e.g. `Garden` = the hive row
+ bed grid seen from afar — big and distinct); **inside, only its children are looked for.** Small members are never
searched for from afar (live evidence: beds in the normal view z 3.0–3.5 with false peaks up to 4.0; inside the zoomed
garden they are found every time). Groups and their patterns live in their region.

### 3.2 Vector store (per kind, many examples)
Example = embedding (Apple Vision feature print, scale-tolerant: zoom doesn't matter), crop, kind, state at capture,
light (day/dusk/night), weather, source (detection / model / user). Cap per kind, near-duplicates skipped. Matching
prefers examples of the current light and weather. A node's `vec` points at its latest example (goes stale; refreshed
by detection and model).

### 3.3 Goal queries
`Q(offers='plant')`, `Q(kind='GardenBed').where(state__crop=None)`, `Q(kind='Well')` → candidates ordered **visible
first, then fewest graph hops**. Skills never name a specific object ("any bed that can take a seed").

## 4. Perception
- **Scope:** the kinds searched are the current region's children + the exits of the parent (e.g. on the Farm: Garden,
  HouseDoor, Mailbox…; inside the Garden: GardenBed, BeeHive, Well). Rival competition is within that set.
- **Detect** (per frame, only the kinds the current step needs): DINOv2 patch features (one pass per frame) → per-kind heatmaps from the kind's example crops → peaks above the kind's calibrated z threshold, rival kinds competing per patch (2026-10-31: replaced Apple Vision proposals + grid fallback).
- **Identity:** unique kinds by kind; group members by their place in the group's pattern among the detected members.
- **Reconcile:** when a group's states are stale, one model call on the frame returns each visible member's state and
  which member to click; the graph is updated, member vectors refreshed, later steps run from the graph.
- **Expected but not found:** vector search misses an object the graph says is visible from here → model vision labels
  the frame (new nodes, examples, edges, blocked_by).

## 5. The loop
```
task(goal) → q = query(goal) → target's region chain (e.g. Farm → Garden → bed)
current region = from the log scene + view signal; path = up to the common ancestor, then down
loop on each frame:
  next step is a region → detect it as one object → click its main body → reached = its entry signal (scene / zoom +
                          members detected) → switch the detection scope to its children
  active object set? → it must still be detected / its bubble up; else UNEXPECTED → re-establish (model if needed)
  target candidate visible → reconcile if stale → click its main body → expect its bubble → INTERACTION
                             reached = interaction started
  else graph path to q: next hop visible → click its main body; reached = the hop after it is visible → continue
                        next hop not visible → model vision: "click x,y to get toward <hop>" (stored as an edge hint)
  expected object missing → model vision labels → graph/vectors updated → loop
  no progress (frame embedding + detections unchanged over 3 clicks) or interaction didn't start → model once → HITL
```
- **Click point** = the object's main body (largest part of its mask), away from other objects' masks and bubbles (a
  click on a bubble is that bubble's action).
- **Interruptions** (cutscene, dialogue, sleep, scene change, from the log) pause the loop; it then re-establishes the
  active object.

## 6. Interaction
The clicked node becomes the **active object**, held with its parent region: `(object, region)`. Lost from view → look
in the parent region first; the region's entry signal gone (zoomed out, scene changed) → the region is the target
again. The region changes only on entering/leaving. Its bubble is matched by kind (bubble vectors); menus/cards by OCR and
item vectors (planting picker, Remove/Select); the game log proves the action. The interaction **keeps or changes the
active object** (e.g. `fill_can` ends on the well; `plant` keeps the bed until its seed is set, then the next bed).
The active node's state is updated from the proof line.

## 7. Model vision and HITL (the question protocol)
Questions go to the agent (no API): `ASK <id> <kind>` with the frame and the detections drawn on it. Answer shapes:
`click X:Y` · `label [kind, state, box]…` · `reconcile [member → state]` · `click_target member`. Answers are applied,
checked by the outcome, and stored (examples, edges, rules); the same situation is not asked twice. After two answers
that didn't help, the agent escalates to the supervisor, who asks the user; the user's answer is stored the same way.
A per-trip question budget is tracked by the eval.

## 8. Cold start: survey runs
One survey per area (Farm first): the agent walks the main places (house, garden, well, hives, gate, road), labels what
it sees, and seeds nodes, examples, patterns and edges. After that, questions per trip should fall run by run.

## 9. Eval (replaces belief / click / world_route components)
| Component | Prediction | Outcome |
|---|---|---|
| detect | object expected visible (graph) | detected or not |
| hop | clicking hop a reaches b | b visible next |
| interact | click on target starts its interaction | bubble/menu up, log line |
| ask | answer helps | the outcome after applying it |
| questions / HITL | per trip | counts (should fall) |
Benchmark A (garden day) and B (trips) stay; targets from the 2026-10-30 baseline.

## 10. Migration and removal
Order (each step: plan, offline tests, a small supervised live step, then the benchmark):
0. Frame ↔ window mapping for any window size and display (title bar first, then the 16:9 picture fitted with bars;
   D150: a 1920×978 window put the title bar into captures). The only geometry left, used to grab frames and send clicks.
1. Detection + vector store (proposals, embeddings, kinds, examples by light/weather).
2. Object graph + query builder + persistence.
3. The loop + interaction (active object, reconcile, unexpected events) + question shapes.
4. Survey run (Farm), then benchmark A and B.
5. Removals.

| Remove | Replaced by |
|---|---|
| `tools/world/{belief,costmap,view,zoom,graph}.py`, world entities with coordinates, use/click points | object graph + vectors + model |
| screen calibration (`tools/nav/*/calib.json`, `calibrate`), map compass, `go_world`, `goto_point`, `run_route`, `map_walk`, trail/back links | click chain on detected objects |
| position readings for navigation (`checkpoint`/`pos` in walks), `facts.jsonl` as navigation input | none (scene names from the log only) |
| road masks, coverage, `improve`, fill_pin | survey runs |
| `game/walk.py` geometry, `object_under_her`, `content_box`-dependent click maths in skills | loop + detections (clicks at frame points only) |

Kept: game-log parser (`runtime/log.py`), actuators with the menu guard, affordances/bubbles, bubble and item vectors,
skills' structure (`@action`, proofs), evals/bench, plans/runs/stuck retros, the screen capture itself (`grab`, mapping
the frame to the window only for sending the click).

## 11. Testing
Offline: detection on saved frames (garden day/night, rain, zoomed/unzoomed) with labelled objects; graph queries and
updates from recorded log lines; the loop against a fake game whose frames come from saved screenshots. Live: survey,
then supervised small steps, then the benchmark.

## 12. Open questions
- Proposal quality for flat objects (bed tiles): how often the grid fallback is needed.
- How many examples per kind/condition before model questions drop off.
- Whether "frame unchanged" alone is a reliable no-progress signal in animated scenes (water, rain).
