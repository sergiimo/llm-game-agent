# Model Decides the Next Move: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** inside an area, when no direct action is in view, the model (not coded rungs) decides the next move from the
graph and the detection state; code builds that state, executes the move under hard rules, verifies and records it.

**Architecture:** `game/brief.py` builds a state brief (Tara, the area's objects with status/freshness/crop/need and
predicted screen points, bubbles in view mapped to objects, the detection heatmap, recent clicks) and draws it on the
full-scale frame. `engine` raises ONE `decide` vision question with that image + text instead of the near rungs
(explore, detection walks, hops). The answer (`click <object id>`, `walk <cell>`, `settle <ids>: <state>`, `done`) is
parsed and executed by code under the hard rules (never another row's bubble, never her own spot, red flags, stuck,
idle). Map navigation (far) and direct bubble actions (a fitting bubble at the target's point) stay as they are.

**Tech Stack:** Python 3 (`.venv`), PIL, the existing engine (`tools/game/`), unittest fakes (`tools/test_engine.py`).

**Spec:** user D189 in conversation: "an agent should reason on graph and heatmap state, because it's vague logic";
design accepted from the reply "Proposed design" (state brief -> marked frame -> model decides -> code executes);
docs/superpowers/specs/2026-11-04-nav-ladder-design.md (the ladder this replaces inside an area).

## Global Constraints

- Every vision image is full scale (memory `full-scale-screenshots`, L165).
- Vision is the fallback for every case; no stop or loop where vision could decide; every answer settles or teaches
  something (L174).
- A vision question pauses the game on plain gameplay; the next call resumes (L175).
- A walk click is never on her own spot or a bubble (`nav.walkable`, L177); a click on an object is deliberate.
- An event of a known row outside the goal is a red flag that stops the call (L177).
- Tracing is absolute: every decision, click (with game events), thought and answer is a run-log row (L177).
- Gameplay agents use the cheapest model (AGENTS.md); the `decide` question is answered by the agent in the run.

## Review Focus

1. A brief whose predicted screen points are off (position from a stale source): the model must see how sure the
   position is, and an object click on a wrong point must be caught by its result, never repeated.
2. An answer naming an object id not in the brief or a cell on her own spot: rejected with a clear message, no click.
3. `settle` answers must only touch objects the brief showed as in view (no settling beds she can't see).
4. A Collect prompt opened by an object click with the crop still unknown must never be confirmed blind (flowers).
5. The question count per call: one `decide` per round, never a loop of decisions without a click or a settle.

---

### Task 1: The state brief (`game/brief.py`)

**Files:**
- Create: `tools/game/brief.py`
- Test: `tools/test_brief.py`

**Interfaces:**
- Produces: `build(g, kind, targets, res) -> dict` with keys `tara` ({pos, source}), `objects` (list of {id, status,
  fresh, crop, need, screen, dist}), `bubbles` (list of {pt, kind, icon, badge, owner}), `heatmap` (list of {kind, pt}),
  `recent` (last 6 click records: pt, what, events, result); `text(brief) -> str` (one line per object/bubble);
  `draw(img, brief) -> Image` (full scale: object points labelled with a short id and status, Tara ring, bubbles).

- [ ] **Step 1: Write the failing tests** — `test_objects_carry_status_freshness_need_and_screen_points` (two beds:
  one seen today not ready, one ready by the save only -> fresh 'today' vs 'save', need False vs True, screen points
  from `engine.screen_point`), `test_bubbles_are_mapped_to_their_objects` (a bubble within OWN_PX of a bed's point gets
  `owner` = that bed), `test_the_drawing_is_full_scale_with_labels` (size equals the frame; a label pixel at a bed's
  point differs from the plain frame), `test_position_source_is_shown` (`tara.source` in {event, walk, save, unknown}).
- [ ] **Step 2: Run, verify they fail** — `.venv/bin/python tools/test_brief.py` -> ImportError.
- [ ] **Step 3: Implement `build/text/draw`** — status from `world.state_of`; fresh from `world.checked_day` and the
  reading's source (card/bubble/vision/event today = 'today', save = 'save', none = 'unknown'); need = passes the
  goal's `where`; owner by nearest object point within `engine.OWN_PX`; heatmap from `observe.see_all()` (one pass).
- [ ] **Step 4: Run, verify they pass.**
- [ ] **Step 5: Commit** — `git commit -m "brief: the graph + heatmap state for the model's decision"`.

### Task 2: The `decide` question and its answer grammar

**Files:**
- Modify: `tools/game/engine.py` (the near branch of `_loop`: where `_reach` is called after `_visit` returns None)
- Modify: `tools/game/ask.py` (nothing new: `ask('decide', ...)` uses the existing `name` path with an image)
- Test: `tools/test_engine.py` class `ModelDecides`

**Interfaces:**
- Consumes: `brief.build/text/draw`.
- Produces: `engine.decide_q(g, spec, targets, res)` raising NeedVision with pending `{'decide': True, 'brief_ids':
  [...], 'in_view': [...]}`; `engine.parse_decision(answer, pend) -> ('click', id) | ('walk', (x, y)) |
  ('settle', [ids], {state}) | ('done',)`, raising `core.Failed` on an id not in `brief_ids`, a cell on her spot, or
  a settle of an id not in `in_view`.

- [ ] **Step 1: Write the failing tests** — `test_no_direct_action_asks_one_decide_question_with_the_brief`
  (GeoGame: a ready bed out of bubble range, bubbles of known beds near -> NeedVision text lists the bed ids and
  their status; zero clicks), `test_parse_decision_grammar` (the four forms; the three refusals of Review Focus 2-3),
  `test_one_decide_per_round` (an answer that neither clicks nor settles -> the next call asks again at most once,
  then the run stops with a gap).
- [ ] **Step 2: Run, verify they fail.**
- [ ] **Step 3: Implement** — replace the near rungs' use in `_loop` (explore, detection walks, hop) with
  `decide_q` when targets remain and no fitting bubble is at the target's point; keep `_visit`'s direct bubble path and
  the map rung for map-far.
- [ ] **Step 4: Run, verify they pass; run the whole suite** — expected: old tests that asserted explore/hop clicks
  now see a `decide` question; update each to answer it (the behaviour change is the plan's point) and note them in
  the commit.
- [ ] **Step 5: Commit.**

### Task 3: Executing the decision under the hard rules

**Files:** Modify `tools/game/engine.py` (`_answer` for pending `decide`); Test: `ModelDecides`.

**Interfaces:** Consumes `parse_decision`; produces the executed click/settle and its records.

- [ ] **Step 1: Failing tests** — `test_click_object_walks_and_its_collect_is_finished_when_the_crop_is_known`,
  `test_click_object_collect_with_unknown_crop_asks_the_crop_with_the_card_open` (Review Focus 4: the card stays
  open; the answer `Green Bean` -> Space, `Tulip` -> Escape), `test_walk_cell_is_checked_by_walkable`,
  `test_settle_marks_only_in_view_objects_with_source_vision`, `test_a_failed_object_click_is_not_repeated`
  (Review Focus 1: the same object click with the same result is refused the second time; a gap is written).
- [ ] **Step 2: Run, verify they fail.**
- [ ] **Step 3: Implement** — `click <id>`: `A.click(screen point, 'object', wait_event=True)`; a card the target's
  row starts with -> the row's remaining steps when the crop is known and not skipped; crop unknown -> a `name`
  question with the card open (pending `collect_open`), and `achieve` skips its opening `A.gameplay()` for that
  pending kind. `walk <cell>`: refused unless `nav.walkable`. `settle`: `world._set` with source 'vision'.
- [ ] **Step 4: Run, verify they pass; whole suite.**
- [ ] **Step 5: Commit.**

### Task 4: The other three points (from the 4-point list of D189 4:05 PM)

The list was: walk clicks on her spot / bubbles (built: `nav.walkable`), the Collect opened on the way to the target
(open), red-flag events (built), absolute tracing (built). This task closes the open one and verifies the built ones
live.

**Files:** Modify `tools/game/engine.py` (`finish_card`), `tools/runwatch.py`; Test: `tools/test_engine.py`
`CollectOnTheWay`, `tools/test_runwatch.py`.

- [ ] **Step 1: Failing tests** — `test_a_collect_on_the_way_uses_the_targets_crop_from_the_graph` (no bubble by the
  click; the target bed's graph crop is Green Bean -> finished), `test_a_collect_on_the_way_with_no_crop_known_asks_with_
  the_card_open` (shares Task 3's `collect_open` path), `test_the_watcher_flags_a_red_flag_stop` (an engine stop
  starting `RED FLAG` -> STOP line).
- [ ] **Step 2: Run, verify they fail.**
- [ ] **Step 3: Implement** — `finish_card` falls back to `world.state_of(g, res['tid_now'])['crop']`, then to the
  `collect_open` question; runwatch: an `engine` row whose stop starts with `RED FLAG` -> STOP.
- [ ] **Step 4: Run, verify they pass; whole suite.**
- [ ] **Step 5: Commit.**

### Task 5: Fold in the uncommitted click-the-bed work

**Files:** `tools/game/engine.py` (`_click_bed`, the `visit_ran` path), `tools/test_engine.py` (`ClickTheBed`).

- [ ] **Step 1:** Remove `_click_bed`'s crop question (Task 3's `collect_open` replaces it) and keep `_click_bed` as
  the executor `click <id>` uses; the two inherited VisitBeds tests that fail under `ClickTheBed` pass again.
- [ ] **Step 2:** Whole suite green; commit.

### Task 6: Live gate (supervised, one run)

- [ ] **Step 1:** Open the run (`./wf run start`), the watcher on every line (not filtered), the agent with the
  `think` rule; goal `harvest` from the current place (D189 ~4 PM, the far-west bed and the tulip row left).
- [ ] **Step 2:** Pass criteria: every click in the trace has a `decide` or a direct bubble reason; no click on her
  spot or a bubble of another row; no red flag; each `decide` answer settles or moves; the run ends `done` with only
  flowers left; the Time table filled (game minutes, picks).
- [ ] **Step 3:** Retro: the vision answers and what each taught (L174 rule); learnings row; stuck ledger if any.
