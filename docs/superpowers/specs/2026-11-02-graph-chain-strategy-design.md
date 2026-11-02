# Graph-chain strategy: act from graph memory, move node by node, resync by vision

> **Summary:** skills act from a graph memory of every object's state and relations. Model vision anchors the chain
> (which node Tara is at, the states of the visible nodes); then Tara moves node by node along pattern/region relations,
> each step checked against the node's predicted state; anything unexpected triggers vision again. **No positions
> anywhere** (no world coordinates, calibration, belief or projection). Extends `2026-10-31-object-graph-navigation-design.md`
> (object graph, regions, detection, vision) and makes its §10 step 5 (removals) concrete.

Status: design, 2026-11-02 (user-directed: brainstorming D183). Approach B of three (A pure chain, C periodic re-anchor).

## 1. Why
D183 replant: projection of beds to the screen was ~2× off (L116), bubble owners picked neighbours (L114) or nothing
(L112), and every fix added more coordinate patches. The log-based fallback ("click, then read which bed the log names")
works but still keys on positions and can't plan, reach off-screen beds or give agents a readable world state.

## 2. Goals (priority order, user)
1. **Plan before acting**: know which nodes need the task (wilted, dry, ripe, empty) before clicking.
2. **Reach off-screen targets** through region and pattern relations.
3. **Agent memory**: one readable world state the LLM agents plan from, kept across sessions.

Constraint (user): **remove every position usage.** Movement is approximate and relational; pattern detection keeps it
flexible; model vision syncs the graph when needed.

## 3. Graph and states
Reuses `tools/objects/graph.py` / `graph/Farm.json` (regions ⊃ groups ⊃ members), with positions removed.
- **Members** are named by pattern cell: `GardenBed@Garden#r2c1`. Two bed groups: `GardenBed@Garden` (3×4, existing
  pattern) and `GardenBed@FarGarden` (its pattern set by the first vision survey).
- **Relations:** `neighbour(a, b, dir)` generated from the group pattern (E/W/N/S); `in(member, group)`,
  `in(group, region)`; `leads_to(door, region)`; `near(Well, Garden)`; `offers(kind, action)` (existing).
- **Member state** (existing hint shape `{value, game_time, source}` + `conf`): `crop` (name), `phase`
  (`empty | growing | ripe | wilted`), `watered_today` (bool). `source ∈ {vision, step, event, save-count}`.
  Vision sets `conf=1`; a confirmed step keeps or raises it; a day change lowers `watered_today` hints to `false`.
- **Tara node:** `at` (member or region, by chain), `can` (`full | empty | unknown`).
- **Save** is read only as **counts per group** (`wilted`, `dry`, `ripe`, `empty`) to cross-check graph totals.
- **Never stored:** x/z, screen points, indexes derived from coordinates.

## 4. The step
One step = move to a neighbour node, check it, act. Screen- and pattern-relative only.
1. **Choose** the nearest node (in relation hops) whose predicted state needs the task; the path is a list of
   `neighbour` edges, one step each.
2. **Locate on screen by pattern:** one detection pass (`GardenBed`, DINOv2, existing) → fit the visible tiles to the
   group's row/col grid, anchored on `Tara.at` (the tile under/nearest her; the camera follows her). The wanted neighbour
   is the fitted tile in that direction. Approximate on purpose: it only picks among visible tiles.
3. **Move:** click that tile's body away from any bubble (the game pathfinds).
4. **Expect** from the node's predicted state: a bubble appears near that tile within the settle time, and its look
   matches (drop sub-icon when dry/wilted, seedling when empty, pickup when ripe). Match → `Tara.at = node`.
5. **Act** (bubble → card/buttons) and **expect the event type** in the game log (`> unplant`, `> unplant_impl`,
   `> plant`, `totalPlanted`, `> water`, `> out_of_water`, `grab_item`). The position in the line is ignored.
   Update the node's state (`source=event`).
6. **Unexpected** = no bubble; a bubble contradicting the prediction; another event type; a card that doesn't fit;
   the fitted grid doesn't match the pattern; Tara not moving (stuck rule L75). → §5 vision, re-anchor, continue
   from the new `at`.

Off-screen targets: follow `in`/`leads_to`/`near` to the region's entry (map route or the region's view signal,
existing), then anchor (§5) and continue the chain.

## 5. Vision: anchor and resync
One question shape for the first anchor and every unexpected event.
1. The tool detects visible tiles and bubbles, draws a label per tile (`A, B, C…`) and Tara's marker, saves the frame,
   and writes the question with context: task, predicted states near `Tara.at`, and what was unexpected.
2. The answer is a fixed format about labels, never coordinates:
   ```
   group: GardenBed@Garden   at: B=r2c1
   A=r1c1 empty   B=r2c1 wilted(Green Bean)   C=r2c2 growing dry   D=r2c3 ripe   E=?
   ```
   `at` ties one label to one member; others follow from the pattern or are named. States use the graph's words;
   `?` = unknown (the old hint stays).
3. The tool validates the format (a malformed answer is rejected with the expected shape), applies `Tara.at` and the
   states (`source=vision`, `conf=1`), then checks totals against the save counts. A mismatch asks **one** follow-up
   naming it; no further loop.
4. The quest agent Reads the image and answers `./wf anchor "<answer>"` (the `NEED_VISION` path, made structured).

Vision runs only at task start, on entering a region, and on unexpected events.

## 6. Tasks and the runner
Skills become graph tasks run by one runner (`tools/objects/chain.py`):

| task | node needs | at the node | done-signal (event type) |
|---|---|---|---|
| replant | `phase=wilted` | bubble → Remove → plant the same crop → water | `unplant_impl`, `totalPlanted`, `water` |
| water | `growing`, not watered today | drop bubble; `out_of_water` → `fill_can` sub-task | `water` |
| harvest | `phase=ripe` | pickup bubble | `grab_item` |
| fill_can | `Tara.can=empty` | Well (unique, `near` Garden) | `full_watering_can` |

Runner: anchor if `Tara.at` is unknown or stale → loop {choose next node, hops (§4), act, update} → done when no node in
scope needs the task → totals vs save counts. A sub-task (e.g. `fill_can`) pushes and pops; after it the chain
re-anchors at the well and returns by relations. API: `garden.replant_all(seed=None)`, `garden.water_all()`,
`garden.harvest_all()` — one call per task. Reused unchanged: `_finish_unplant`, `ui.pick_card`, `ui.press`, `@action`
proofs, `core.ask_vision` (gains the anchor format).

## 7. Removals
| Remove | Replaced by |
|---|---|
| `tools/world/{belief,costmap,view,zoom}.py`, world entities with x/z, `tools/nav/*/calib.json`, `checkpoint`/`pos` for navigation | graph relations + pattern fit + vision anchor |
| `affordances._owner`, the belief readings in `scan()`/`use()` (L112, L114) | node at the chain; bubble near the clicked tile |
| `identity.member_from_log` by position, `core.log_pos`, `garden._bed_at`, `_WATER_AT` | event type + chain position |
| `garden.plant/water/water_next/unplant/replant(b)` and the `*_visible` variants | `replant_all` / `water_all` / `harvest_all` |

Kept: log parser (event types), menu guard, bubble kinds + drop flag, item icons, evals/bench, plans/runs/retros.

## 8. Testing
- **Offline:** a fake garden (grid of tile states; clicking a tile moves Tara; bubbles follow state; actions fire
  events). Scripted surprises — stale hint, missing bubble, wrong grid fit, can empty — must each produce exactly one
  vision question and a correct re-anchor. Anchor answer parsing/validation (good, malformed, `?`, save-count mismatch).
- **Live:** benchmark A (garden day): vision calls per run, steps, surprises. Target: vision calls ≪ steps; zero
  position reads.

## 9. Open questions
- Pattern fit under strong zoom or when only 2–3 tiles are visible: how often it needs vision.
- The far garden's pattern and its entry signal (first survey).
- Whether hives and the well also need patterns or stay unique nodes reached by `near`.

## 10. Revision B (2026-11-02, after live run 1): vision gives the layout
Live run 1 (L122): the `GardenBed` detector returns border fragments (20–100 px), not one tile per bed (≈560×300 px),
so §4 step 2 (pattern fit of detected tiles) and §5's per-tile labels had nothing to work with. User decision: **vision
gives the layout; no bed detector in the chain.** This section replaces §4 steps 2–4 and §5 items 1–3.

**Layout (screen-relative, not world).** The camera follows Tara, so beds keep fixed screen offsets from the frame
centre while she stands at a bed. A group's `layout` = `{pitch: (px, py), ref_offset: (dx, dy)}` in frame pixels:
the screen point of member m = `CENTRE + ref_offset + ((col(m) − col(at)) · px, (row(m) − row(at)) · py)`.
Stored on the group node (frame pixels only, never world coordinates); invalidated by any failed move proof.

**Anchor image and answer.** The tool saves the full-size frame with a fine labelled grid (columns `A–X`, 80 px;
rows `1–16`, 67.5 px) and the reference marker at CENTRE. Vision names each visible bed by its pattern cell, the grid
cell nearest the **centre of that bed**, and its state:
```
group: GardenBed@Garden   ref: r1c2@L8
r1c1@F8 ripe   r1c2@L8 ripe   r2c1@F12 wilted(Tulip)   r2c2@L12 wilted(Tulip)   r3c1@F15 ?
```
`ref` = the bed nearest the marker (becomes `Tara.at`). Validation: grid cells exist; members exist in the pattern;
at least two beds differing in column and two in row (or a previous layout) to fit the pitch. The tool fits `layout`
by least squares over the named beds (pitch per axis, ref offset) and rejects an answer whose residual exceeds
0.35 × pitch (inconsistent beds) with the expected shape.

**Step (replaces §4.2–4.4).** Locate = the layout's point for the target neighbour. Click it. **Move proof** = the
camera shift measured by phase correlation of the frames before and after the click (numpy FFT, frame pixels):
it must be one pitch opposite to the move direction (±0.4 pitch on that axis, < 0.4 pitch on the other); otherwise
Unexpected (layout dropped → next call re-anchors). After the move the target is at `CENTRE + ref_offset`; its bubble
is `bubble_near` that point and must match the predicted state (§4.4 unchanged). A card or panel on screen before a
step or before asking vision is closed first (`ui.close()`), and one that a click opened is Unexpected (as before).

**Unchanged:** graph (§3), event-type checks (§4.5), tasks and runner (§6), removals (§7), one question per surprise.
**Dropped from the chain:** `detect_fn`, `locate`'s pattern fit, `lines.py` tile clustering (kept only if still used).
