# Objects Step 3: The Loop, Member Identity, Interaction Implementation Plan

**Status (2026-11-02):** implemented (`loop.py`, `identity.py`, `bubbles.py`). Next: spec §10 step 4 (survey run) and step 5 (removals).

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (user: "use subagents").
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** a goal-driven click loop on detected objects (no coordinates): click the target as soon as it is visible,
otherwise the next region step; know which group member is which; take the target's bubble from the frame; prove the
action from the log and update the graph; ask model vision when stuck.

**Architecture:** `tools/objects/identity.py` (dedupe a group's detections, assign pattern indices; log line → member),
`tools/objects/loop.py` (`goto(q)` frame loop, active object set `{(node, region)…}`, no-progress check, ASK),
`tools/objects/bubbles.py` (bubble owner = the detected object right below the bubble, in frame px).
Skills: `game/well.fill_can` and a new `game/garden.goto_bed(**state)` run on the loop.

**Tech Stack:** Python 3.12; existing `wf.find_bubbles/bubble_kind/bubble_highlighted`, `run_action`, `wait_settle`,
`log_mark`, `game.core` (`@action`, `prove`, `Failed`); objects graph/query/regions/detect/views.

**Spec:** `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` §5 (loop), §6 (interaction), §7
(questions), §3.1b (regions; inside = ≥ 85 % of a group detected).

## Global Constraints
- Every action is a click at a frame point: a detection's `point`, a bubble's point, or a model-answered point.
- **Click the target as soon as it is visible** (user rule): every frame also detects the target kind with the
  target region's thresholds, even from outside that region; visible → click it, skip the region steps.
- Never click within `BUBBLE_KEEP = 60` px of a bubble that isn't the wanted one (a bubble click is its action).
- No progress = frame vector (views.frame_vector) distance < `STILL = 0.01` between frames over 3 clicks, or the
  interaction didn't start after reaching → one ASK → after 2 unhelpful answers `Failed` (escalation).
- Identity evidence from the log (a `> action … target=X at (x, y, z)` line) maps to a member through the save's
  bed numbering once; positions are not stored in the graph.
- Commits only on the user's request; never git stash/checkout/reset.

## Review Focus
- Two detections on one hive (zoom-3 had 14 for 8) → one member after dedupe.
- Target visible from outside its region → clicked directly (no `enter` step).
- A bubble of another object between Tara and the target → the click point avoids it.
- The loop stops (no endless clicking) when the frame doesn't change.
- An action proved by the log updates the right member's state with game time and source `log`.

---

### Task 1: `identity.py` + `bubbles.py`

**Files:** Create `tools/objects/identity.py`, `tools/objects/bubbles.py`; Test: `tools/test_loop.py`.

**Interfaces — Produces:**
- `dedupe(dets, min_frac=0.5) -> list[Detection]`: merge same-kind detections closer than `min_frac` × the median
  nearest-neighbour spacing (keep the higher z).
- `assign(group: Node, members: list[Node], dets) -> dict[member_id, Detection]` and `uncertain: bool`: rows by
  clustering y (gap > 0.5 × median row spacing), columns by x; pattern rows×cols (`order` north row first = smallest
  y first, west → east = smallest x first). All rows and columns seen → absolute indices; fewer → indices only when
  anchored (beds: the row nearest the hive row is the north row) else `uncertain=True` with relative indices.
- `member_from_log(line, beds) -> member_id|None`: `> <action> … target=GardenBed… at (x, y, z)` → the save bed whose
  (x, z) is within 0.6 of the line's → `GardenBed#<its id>` (beds = `game.garden.beds()` list; numbering is already
  north row first, west → east).
- `bubbles.owner(bubble_pt, dets, dx=90, up=(20, 260)) -> Detection|None`: the detection whose point is below the
  bubble (0 < det.y − bubble.y in `up`, |dx| ≤ `dx`), nearest.
- [ ] tests: dedupe on zoom-3 real detections (BeeHive, Garden thresholds) → ≤ 8; assign on a synthetic 3×4 grid
  (full → #1..#12 right; one column missing → uncertain unless anchored by a hive row above); member_from_log with a
  recorded line (tools/fixtures/game_log.txt has `> plant … GardenBed(Clone) at (…)` lines; use the save bed list
  from a small fixture you write: 12 beds at x ∈ {-1.66, 0.84, 3.34, 5.84}, z ∈ {-25.34, -28.47?, -31.59} — take the
  real rows from the fixture log lines); owner picks the right one of two detections under two bubbles.

### Task 2: `loop.py` — goto(q)

**Files:** Create `tools/objects/loop.py`; Test: `tools/test_loop.py` (fake game: a scripted sequence of frames
from the fixtures and the live run images, fake clicks recorded).

**Interfaces — Produces:** `goto(q: Q, wf, max_clicks=8) -> Arrival(node, region, point, frames)`, raising
`NeedVision(question_path)` or `Failed`. Each frame: `img = wf.grab()`; region via `regions.current_region` (scene from
`wf.current_scene()`, detections per candidate region); detect `scope(region)` + the target kind (target region's
thresholds); bubbles via `wf.find_bubbles(img)` + `bubble_kind`.
- Every compatible owned bubble writes transient `bubble={kind, point}` state on its graph node. Any active node that
  matches q is an `Arrival`; otherwise the first visible candidate is clicked (avoiding all bubbles). Ownership sees
  all current-region object candidates before q is applied, so stacked neighbour bubbles keep their real owner kind.
- After a target click, a game-log action whose `target` kind matches that selected node is fallback arrival proof
  (`out_of_water target=GardenBed` counts; `beehive_progress target=BeeHive` cannot prove a bed arrival).
- Else first `path()` step: `enter R` → click R's detection point; `exit R` → click R's exit node detection; not
  detected → ASK.
- `ASK`: write `runs/<current>/ask-<n>.png` (frame with detections drawn) + `.json` (goal, step, detections) and raise
  `NeedVision`; the agent answers `./wf teach click X:Y` (existing teach command) — the loop reads the stored answer
  the next call (`wf.teach_answer()` or a json file `ask-<n>.answer.json`; choose the simplest that fits existing
  teach code) and clicks it once.
- No progress (Global Constraints) → ASK once; a second time → `Failed('stuck: …')`.
- Active objects: each frame, `loop.ACTIVE = frozenset({(node_id, region_id), ...})`; selecting one for arrival or an
  action does not deactivate its neighbours. A transient Tara node has `near` edges to them with screen-relative
  direction; active nodes carry transient `bubble={kind, point}` state.
- [ ] tests (fake wf): target visible from outside → one click on it, no region click; not visible → click Garden,
  then (next frame inside) click bed; frames identical 3× → NeedVision; bubble of another object near the target →
  click point moved away (≥ 60 px from it).

### Task 3: skills on the loop + log → graph state + live

**Files:** Modify `tools/game/well.py` (`fill_can` on the loop; old path removed), `tools/game/garden.py` (add
`goto_bed(**state)`: Q GardenBed where(**state) → loop.goto); `tools/objects/graph.py` (`apply_log(lines, beds)`:
`> full_watering_can … target=Well` → Well `can=full`; `> plant … GardenBed at` → member `crop=<seed>`; `> water` →
`watered=<day>`); `./wf graph sync` (apply the log since the last sync, save the graph). Docs: L92, AGENTS.md row,
`docs/mechanics/basic-actions.md` (Approach a target: "the loop clicks the target as soon as it's visible").
- [ ] tests: fill_can with a fake wf (can bubble visible → one click, proof line); apply_log on fixture log lines.
- [ ] Live (quest agent): plan run `loop-live`: from the house front `./wf py "fill_can()"`; then `./wf py
  "goto_bed(crop=None)"`; score with images; eval components detect / hop / interact / ask.
