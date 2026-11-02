# M3: Walk and Skills on the World Model Implementation Plan

**Status (2026-11-02):** implemented; `game/walk.py` geometry is **superseded** by the object-graph spec (§10 step 5: removal). Skills structure (`@action`, proofs) stays.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Skills and walking act through the world model: `walk(goal)` picks a mode by evidence (in reach / on
screen / same area / other area), readings only when the belief needs a fix, no hidden trips inside skills; then the
benchmark (A, B) is re-run against the targets and the M3 rows of the removal ledger are closed where the gate passes.

**Architecture:** `tools/game/walk.py` (new) uses `wf.world()` (belief, entities, costmap route, view) and `runtime.act`;
`move.goto` delegates to `walk`; garden skills lose their hidden well trip; the stuck rule checks distance to the goal.
Between areas `walk` still uses the old graph route (`wf.goto`) — porting it to `world.graph` is the next step after
the gate (ledgered ruling).

**Tech Stack:** Python 3.12, existing `world/`, `runtime/`, `game/` packages; unittest with fakes.

**Spec:** `docs/superpowers/specs/2026-10-30-agent-system-refactor-design.md` (§5, §7.2 targets, §10 ledger)

## Global Constraints
- Gate first: a clean shadow re-run must show `world_belief` ≥ old `belief` on the same readings before `walk` is used live.
- Save readings only when `world.needs_fix()` (u > 3.0) or at the end of an off-screen walk without a fix on the way.
- A skill does one thing: `plant` does not water; `water` does not walk to the well unless the log says the can is
  empty (`out_of_water`), and then says so in its result.
- Stuck = < 2 units over 3 moves **and** farther than reach from the goal.
- Supervision: the first live use is a small plan step for the quest agent; one game command per call.

## Review Focus
- The target is on screen but covered (hive in front): `walk` clicks the uncovered point `view.click_point` returns.
- The belief is unknown (u = 99) at the start: `walk` takes one reading first, never clicks blind.
- A click refused because a menu is open: `walk` stops with MENU OPEN, no stuck alarm.
- She arrives within reach but the reading lags: no false STUCK (goal-distance check).
- `water` with an empty can: one `out_of_water` line → fill at the well → back → water, reported as two actions.

### Task 1: `game/walk.py`
- `walk(target, reach=REACH) -> str` (`'ARRIVED …'` / `'NEAR …'` / raises Failed): target = Entity/Bed (x, z, area) or a
  place name (other area → `wf.goto`). Order: `needs_fix()` → one reading; in reach → done; on screen →
  `act.click(view.click_point(...))`, `world.clicked`, sync; else `world.route_status` waypoints → one click per
  on-screen waypoint; after the walk: in reach by evidence or `needs_fix()` → reading → arrived if within reach.
- Tests (fake world/act): in reach → 0 clicks; on screen → 1 click at the click point; covered target → the click is
  not inside the hive; unknown belief → 1 reading first; MENU OPEN → Failed('MENU OPEN …').
### Task 2: skills without hidden trips + stuck goal check
- `garden.plant` no longer calls `water`; `garden.water` detects `out_of_water` in the log → `well.fill_can()` →
  back → water; `move.goto` → `walk`; `track_point(scene, x, z, goal=None, reach=REACH)`: no alarm within reach.
- Tests: `test_plant_does_not_water`, `test_water_refills_on_out_of_water`, `test_no_stuck_within_reach`.
### Task 3: live gate + benchmark (supervised)
- world-shadow re-run (as runs/20261030-2102-world-shadow plan) → gate; then `./wf bench start A`, `bench start B`
  with the new `walk`; `./wf bench compare` vs baseline and targets; stuck retros as usual.
### Task 4: removals
- Close the ledger rows whose gate passed (A and B at target): straight hops/side-steps/detour, `map_walk`, readings
  after every walk, `objects.json`, road masks/`to_road`/`fill_pin`/coverage/`improve`, `track_point` stuck tracker
  → world belief; rows whose gate failed stay open with the reason.
