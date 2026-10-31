# Objects Step 2: Object Graph with Nested Regions + Goal Queries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (user: "use subagents").
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** an object graph of nested regions (Farm ⊃ House, Farm ⊃ Garden ⊃ beds/hives/well), persisted as JSON, with
goal queries that return a target and the region path to it, and a per-region detection scope + entry signal.

**Architecture:** `tools/objects/graph.py` (nodes, edges, regions, states with age, JSON per top region),
`tools/objects/query.py` (Q builder, region chain, path steps, candidate ordering), `tools/objects/regions.py`
(scope = kinds to detect in a region; view-region entry signal from detections). Seed graph `tools/objects/graph/Farm.json`
written by hand (supervisor) from what the game shows. CLI `./wf graph show|where|path`.

**Tech Stack:** Python 3.12, networkx (already a dependency), json; unittest offline (fixtures: frames + labels,
recorded log lines).

**Spec:** `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` §3.1, §3.1b, §3.3, §4 (Scope), §5
(region steps), §6 (active object with parent).

## Global Constraints
- No coordinates in the graph: identity by kind, region and pattern index; scene names from the log are the only
  location identity (spec §2). (Save/log positions may order a group's pattern once, at seeding, but are not stored.)
- Regions nest; each has `signal`: `scene` (entered/left by log `ChangeScene`/`OnEnterBuilding`/`OnExitBuilding`;
  `Farm`, `House`) or `view` (no scene change; inside = ≥ `VIEW_MIN = 2` detections of the region's member kinds at
  their thresholds, e.g. `Garden`).
- From outside, a region is one detectable kind (its name, e.g. `Garden`); inside, only its children's kinds + the
  parent's exits are searched (spec §4 Scope).
- States are hints with an age: `{value, game_time, source}`; writers: log action on the active object, model, save.
- Active object = `(node_id, region_id)`.
- Commits only on the user's request; never git stash/checkout/reset.

## Review Focus
- Path from inside the House to a bed: exit House (via its door/exit) → Farm → enter Garden → bed.
- A query with no matching node → empty result, not an exception.
- Group member identity: `GardenBed` members indexed by pattern (4 per row × 3 rows, north row first, west → east).
- Persistence round trip keeps states and ages; unknown keys in the JSON are preserved.
- Current region with no evidence → the top region (`Farm`), flagged `uncertain`.

---

### Task 1: `graph.py` — nodes, edges, regions, persistence, Farm seed

**Files:** Create `tools/objects/graph.py`, `tools/objects/graph/Farm.json` (seed); Test: `tools/test_graph.py`.

**Interfaces — Produces:**
- `Node(id, type, kind, region, state: dict, vec: str|None, seen: dict|None)`; `type` ∈ `region|unique|group|member`.
- `class Graph`: `load(path)`, `save(path)`, `node(id)`, `children(region_id) -> list[Node]`, `parent(id) -> str|None`,
  `chain(id) -> list[str]` (top region … id), `add_edge(a, b, rel, **attrs)`, `edges(a=None, rel=None)`,
  `set_state(id, key, value, game_time, source)`, `members(group_id) -> list[Node]` (in pattern order).
- Seed `Farm.json`: regions `Farm` (scene, top), `House` (scene, parent Farm, exit `HouseDoor` leads_to House),
  `Garden` (view, parent Farm); uniques `Well` (in Garden, offers fill_can), `HouseDoor`, `Mailbox` (in Farm);
  groups `GardenBed` (Garden, pattern `{"rows": 3, "cols": 4, "order": "north row first, west to east"}`, 12 members
  `GardenBed#1..12`, offers plant/water/harvest/unplant), `BeeHive` (Garden, pattern `{"rows": 1, "cols": 8}`, members
  `BeeHive#1..8`, offers honey/beehive_progress); House children `Bed` (offers sleep), `Stove` (offers cook).
- [ ] Step 1 tests: `test_seed_loads` (12 beds, 8 hives, Garden parent Farm); `test_chain` (`GardenBed#7` →
  `[Farm, Garden, GardenBed, GardenBed#7]`); `test_state_age_roundtrip`; `test_unknown_keys_preserved`;
  `test_members_order`.
- [ ] Step 2–4: FAIL → implement → OK.

### Task 2: `query.py` + `regions.py` — goal queries, paths, scope, entry signal

**Files:** Create `tools/objects/query.py`, `tools/objects/regions.py`; Test: `tools/test_graph.py`.

**Interfaces — Consumes:** Task 1 `Graph`; `tools/objects/detect.Detection` (kind, dist = z, box, point).
**Produces:**
- `Q(kind=None, offers=None)` with `.where(**state)` (`state__crop=None` style → `where(crop=None)`), `.run(graph,
  current_region, visible=set()) -> list[Node]` ordered: visible first, then fewest region steps, then pattern index.
- `path(graph, from_region, to_node) -> list[Step]`, `Step(action, node)` with action ∈ `exit|enter|reach`:
  up to the common ancestor (`exit` each region, via its exit node when it has one), then `enter` each region down,
  then `reach` the node.
- `scope(graph, region_id) -> list[str]` kinds to detect: the region's children kinds (groups by member kind, child
  regions by their own name) + the region's exit node if it has one; a region never searches its own name (Farm →
  `Garden, HouseDoor, Mailbox`; Garden → `GardenBed, BeeHive, Well`; House → `Bed, Stove`).
- `inside(graph, region_id, detections) -> bool` for view regions: ≥ `VIEW_MIN = 2` detections of member kinds.
- `current_region(graph, scene, detections) -> (region_id, uncertain: bool)`: scene region from the log (`House` when
  inside the house, else `Farm`), then the deepest view child whose `inside` holds.
- [ ] Step 1 tests: `test_query_bed_for_seed` (state crop=None on beds #3, #9 → both, visible #9 first);
  `test_query_none` (→ []); `test_path_house_to_bed` (`exit House`, `enter Garden`, `reach GardenBed#3`);
  `test_path_inside_garden` (only `reach`); `test_scope_farm`, `test_scope_garden`; `test_inside_garden_from_fixtures`
  (fixtures zoom-1..3 detections via a fake detection list built from labels.json → inside; normal-1/2 → not inside —
  use labels, not the model, so the test is fast); `test_current_region_no_evidence` (→ Farm, uncertain).
- [ ] Step 2–4: FAIL → implement → OK.

### Task 3: CLI + Garden examples + live check

**Files:** Modify `tools/wf.py` (`graph` subcommand: `show [region]`, `where` (scene from `current_scene()` + detect on
the current frame within `scope`), `path <kind> [state=value…]`); docs: AGENTS.md row, learnings L91; Test:
`tools/test_graph.py` (CLI on `WF_FRAME`).
- [ ] Garden examples (supervisor, offline): `objects add Garden` from `runs/20261031-1021-frames-dino/frames/normal-3.png`
  (hive row + bed grid box) and one from `runs/20261031-1039-objects-relabel/look-house-view.jpg` upscaled; add
  `Garden` boxes to `tools/fixtures/frames/labels.json` (normal-1, normal-2); `objects calibrate`.
- [ ] Live (quest agent, supervised): from the road, `./wf graph where` (→ Farm), `./wf graph path GardenBed crop=None`,
  click the Garden's detected point, `./wf graph where` (→ Garden), `./wf objects detect` within the Garden scope;
  report with images.
