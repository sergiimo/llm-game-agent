# Objects Steps 0–1: Frame Mapping, Detection and Vector Store Implementation Plan

**Status (2026-11-02):** implemented (frame mapping in `wf.py`, detection + vector store in `tools/objects/`). Checkboxes were not ticked during execution.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (user chose native/auto). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Grab frames and send clicks correctly for any window size/display (step 0), and detect objects in a frame by
appearance — Apple Vision region proposals + feature-print embeddings matched against a per-kind vector store with many
examples (step 1) — with no coordinates or calibration.

**Architecture:** `content_box` fits the 16:9 picture after removing the title bar. A new package `tools/objects/`
holds `store.py` (examples per kind, persisted) and `detect.py` (proposals → embeddings → matches, grid fallback for a
sought kind, main-body click point). `./wf objects` exposes add/list/detect for the agent (labelling = adding examples).

**Tech Stack:** Python 3.12, pyobjc Vision (feature prints, foreground instance masks, objectness saliency), numpy, PIL;
unittest offline on fixture images.

**Spec:** `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` (§2, §3.2, §4, §10 steps 0–1)

## Global Constraints
- No coordinates, no calibration, no zoom factors: detection works on the current frame only (spec §2).
- Embeddings must not care about zoom: an example matches the same object at 1.0× and ~1.8× (spec §3.2).
- Examples carry kind, state, light (day/dusk/night), weather, source; cap per kind, near-duplicates skipped (spec §3.2).
- Grid fallback only for the sought kind (spec §4). Click point = the object's main body (spec §5).
- Offline tests first; live = a small supervised plan step for the quest agent; one game command per call; commits only
  on the user's request.

## Review Focus
- A frame with nothing known: `detect` returns [] (no false kind above the distance cut).
- Two objects of the same kind in one frame: both returned, not merged.
- A 1600×928 window (the old setup) keeps its exact old mapping (x0 0, y0 28, scale 0.8333).
- Fullscreen (window at y 0, 1920×1080): no title bar removed.
- A store with one example per kind still matches; the cap keeps the newest/most varied, never deletes a kind's last one.

---

### Task 0: Frame ↔ window mapping for any window

**Files:** Modify `tools/wf.py` `content_box` (~line 470); Test: `tools/test_wf_safety.py`

**Interfaces — Produces:** `content_box(w: dict) -> (x0: float, y0: float, scale: float)`; `TITLE_BAR = 28` (points);
the title bar is removed only for windowed windows (`w['y'] > 0`), then 16:9 is fitted into the rest with bars on the
sides or top/bottom, centred.

- [ ] **Step 1:** tests `class Mapping`: `content_box({'x':1958,'y':65,'w':1920,'h':978})` → x0 ≈ 115.6, y0 = 28.0,
  scale ≈ 0.8796 (±0.001); `{'x':0,'y':38,'w':1600,'h':928}` → (0.0, 28.0, 0.8333); `{'x':0,'y':0,'w':1920,'h':1080}` →
  (0.0, 0.0, 1.0); a tall window `{'y':40,'w':1600,'h':1100}` → x0 0, y0 = 28 + (1072 − 900)/2 = 114.0.
- [ ] **Step 2:** run `.venv/bin/python tools/test_wf_safety.py` → FAIL (1920×978 gives y0 0).
- [ ] **Step 3:** implement in `content_box`.
- [ ] **Step 4:** run → OK; `./wf stop`; `./wf state` (sandbox off) shows no "Wylde Flowers" title text.

### Task 1: `objects/store.py` — examples per kind

**Files:** Create `tools/objects/__init__.py`, `tools/objects/store.py`; Test: `tools/test_objects.py`

**Interfaces — Produces:**
- `Example(id: str, kind: str, vec: np.ndarray, state: str|None, light: str|None, weather: str|None, source: str)`
- `class Store(root=tools/objects/db)`: `add(kind, crop: PIL.Image, vec, state=None, light=None, weather=None,
  source='model') -> Example|None` (None = near duplicate, distance < `DUP = 0.15` to an example of the kind);
  `match(vec, kinds=None, light=None) -> (kind, dist, Example) | None` (nearest example; distance + `LIGHT_PENALTY =
  0.05` when the example's light differs; None above `MAX_DIST = 0.6`); `kinds() -> list[str]`; `count(kind) -> int`.
  Cap `CAP = 40` per kind (drop the example closest to the others, never the last one). Persistence: crops as PNG under
  `db/<kind>/<id>.png`, vectors + metadata in `db/<kind>/index.npz`.
- [ ] **Step 1:** tests: add/match round trip; `test_duplicate_skipped`; `test_light_preference` (two examples of
  different kinds at equal distance, the one with the current light wins); `test_cap_keeps_last_example`;
  `test_reload_from_disk`; `test_nothing_close_is_none` (random vector → None). Use synthetic unit vectors.
- [ ] **Step 2–4:** FAIL → implement → OK.

### Task 2: `objects/detect.py` — proposals, embeddings, matches, grid fallback

**Files:** Create `tools/objects/detect.py`; fixtures: `tools/fixtures/tara_open_crop.png` (exists); Test:
`tools/test_objects.py`

**Interfaces — Consumes:** Task 1 `Store`. **Produces:**
- `embed(img: PIL.Image) -> np.ndarray` (Vision feature print, L2-normalised; same as `wf._featureprint`)
- `proposals(img) -> list[(x0, y0, x1, y1)]` (foreground instance boxes + objectness saliency boxes, deduplicated by
  IoU > 0.6, boxes < 24 px dropped)
- `Detection(kind, box, dist, example_id, point)`; `detect(img, store, kinds=None, light=None) -> list[Detection]`
  (embed each proposal crop, `store.match`, keep matches; two detections of the same kind with IoU < 0.3 are both kept)
- `grid_find(img, kind, store, light=None, scales=(0.08, 0.14, 0.24), stride=0.5) -> list[Detection]` (square crops
  sized as fractions of the frame width, `stride` × size steps, matched against `kind` only; non-max suppression)
- `main_point(img, box) -> (x, y)` (the centroid of the largest foreground-mask component inside the box; the box centre
  if the mask is empty)
- [ ] **Step 1:** tests on the real crop: `test_proposals_find_tara` (a box with height 178 ± 8 around the centre);
  `test_detect_tara_after_adding_one_example` (store with Tara's crop as kind 'Tara' → detect finds 'Tara');
  `test_zoom_invariance` (the crop resized ×1.8 still matches 'Tara' under `MAX_DIST`); `test_grid_find` (Tara's crop
  pasted at ×1.5 onto a plain grass-coloured 1920×1080 canvas at a known place → grid_find('Tara') returns a box
  containing that place); `test_empty_store_detects_nothing`; `test_main_point_on_body` (inside Tara's box, not on
  the background).
- [ ] **Step 2–4:** FAIL → implement → OK (all suites: objects, wf_safety, game, walk, affordances, runtime, evals,
  bench, plan).

### Task 3: `./wf objects` + live seeding (supervised)

**Files:** Modify `tools/wf.py` (early dispatch, no game input except grabbing the frame): `./wf objects list`,
`./wf objects add <kind> <x0> <y0> <x1> <y1> [state]` (crop from the current frame, light from the HUD clock period,
source 'model'), `./wf objects detect [kind…]` (prints detections with boxes, distances, main points),
`./wf objects find <kind>` (grid fallback); AGENTS.md layout row; learnings L87.

- [ ] **Step 1:** CLI on a saved frame via an env var `WF_FRAME=<png>` (tests can run it without the game): test that
  `add` then `detect` on the same frame finds the kind.
- [ ] **Step 2:** run → OK.
- [ ] **Step 3 (live, quest agent, supervised):** a plan run `objects-seed`: at the garden and by the house, `./wf look`
  + Read it, then `./wf objects add` boxes (game coords from the look) for Well, BeeHive, GardenBed (several states),
  House door, Tara; then `./wf objects detect` in two other places/zooms; report hits and misses per kind with images.
- [ ] **Step 4:** docs (AGENTS.md row, L87, spec status); ledger.
