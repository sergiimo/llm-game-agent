# Objects: DINOv2 patch detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (user: "use subagents").
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** replace region proposals + grid search in `tools/objects/detect.py` with DINOv2 patch heatmaps: one model
pass per frame, then a cheap comparison per sought kind; per-kind thresholds and rival kinds decide presence.

**Architecture:** `tools/objects/dino.py` wraps DINOv2-small (torch hub `facebookresearch/dinov2`, `dinov2_vits14`, MPS
when available): `frame_features(img)` → patch grid, `crop_vectors(crop)` → foreground patch vectors. `detect.py`
builds per-kind example vectors from the store's crops (cached, refreshed when the store changes), scores each patch
per kind (max cosine), normalises per frame (z-score), assigns patches to the best-scoring kind among all stored kinds
(rivals), and returns peaks above the kind's threshold as `Detection`s. `./wf objects` keeps its commands.

**Tech Stack:** Python 3.12, torch + torchvision (installed in .venv), DINOv2-small (~90 MB, torch hub cache), numpy,
PIL; unittest on `tools/fixtures/frames/*.jpg` + `labels.json`.

**Spec:** `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` §3.2, §4 (perception), §5 (click point).
Spike evidence (2026-10-31): top-1 Tara 5/5, BeeHive 5/5, GardenBed 4/5, Mailbox 2/2, HouseDoor 2/4 (windows), Well
1/4 (only zoomed examples), Gate 0/2 (bad example); frame pass ~230 ms, ~15 ms per kind.

## Global Constraints
- Detection works on the current frame only; no coordinates/calibration; only the kinds the step needs are scored
  (rivals: all stored kinds take part in the per-patch competition, cheap after the frame pass).
- The model is loaded once per process (the daemon) and reused; first load may download weights (network).
- Model input: the frame resized to 1344×756 (96×54 patches of 14 px); a crop is resized by the same factor (0.7).
- Example vectors: a crop's inner patches minus those whose max cosine to the crop's border patches ≥ `FG_CUT = 0.6`.
- Presence: a peak's z-score (score − frame median) / frame std ≥ the kind's threshold (`Z_MIN = 4.5` default;
  per-kind values in `tools/objects/db/thresholds.json`, written by `objects calibrate`).
- Click point = the centroid of the peak's connected patches above threshold (main body), in game coords.
- Commits only on the user's request; never git stash/checkout/reset.

## Review Focus
- A kind absent from the frame (labels `absent`) → no detection.
- Two hives in a row → several detections (peak suppression radius 4 patches), not one merged blob.
- Store changes (add/remove) → kind vectors refreshed without a daemon restart.
- A kind with no examples → "unknown kind", no scoring.
- Thresholds file missing → defaults; malformed → defaults + a warning.

---

### Task 1: `dino.py` + new `detect` backend

**Files:** Create `tools/objects/dino.py`; rewrite the internals of `tools/objects/detect.py` (keep `Detection`,
`detect(img, store, kinds=None, light=None)`; drop `proposals`, `grid_find`, Vision instance masks; keep `embed` only if
the store still needs a vector — see below); `pyproject.toml` (+ `torch`, `torchvision`, `uv lock`); Test:
`tools/test_objects.py` (replace proposal/grid tests; keep store tests).

**Interfaces — Produces:**
- `dino.frame_features(img) -> np.ndarray (54, 96, 384)` L2-normalised; `dino.crop_vectors(crop) -> np.ndarray (n, 384)`;
  `dino.mean_vector(crop) -> np.ndarray (384,)` (normalised mean of crop_vectors; the store's `vec` from now on).
- `detect(img, store, kinds=None, light=None) -> list[Detection]` sorted by z desc; `Detection.dist` = z-score (field
  kept for the CLI; document it), `box` = bounding box of the peak's patches above threshold, `point` = their centroid.
- `thresholds(store) -> dict[kind, float]`.

- [ ] **Step 1:** tests on fixtures (labels.json): for each frame and each kind in its labels with ≥1 example in a test
  store built from the real `tools/objects/db` crops (copy to a temp dir): `test_tara_found` (normal-1, normal-2,
  zoom-1, zoom-2: top Tara detection's point inside the Tara box); `test_beehive_found` (all 5 frames);
  `test_absent_not_detected` (zoom-3: no Tara; zoom-1: no Well/Gate/Mailbox); `test_several_hives` (zoom-3 ≥ 3 BeeHive
  detections); `test_unknown_kind`; `test_vectors_refresh_after_add`; `test_speed` (one frame + 3 kinds < 1.5 s after
  the model is loaded). Mark kinds known to fail before relabelling (Well, Gate, HouseDoor, GardenBed normal-1) with
  `expectedFailure` and a comment pointing at Task 3.
- [ ] **Step 2–4:** FAIL → implement → OK; also re-embed the existing store (`objects reembed`, Task 2) is NOT needed
  for tests (they build vectors from crops).

### Task 2: CLI + calibration + store migration

**Files:** `tools/wf.py` `objects_cmd`; `tools/objects/store.py` (DUP for DINO mean vectors: measure and set); Test:
`tools/test_objects.py`.

- `./wf objects detect [kinds…]` → `<kind> z 5.8 box … point x,y` lines; `find <kind>` = `detect <kind>` (alias kept).
- `./wf objects reembed` → recompute every example's `vec` with `dino.mean_vector` (crops are on disk).
- `./wf objects eval [frames_dir]` (default `tools/fixtures/frames`) → per kind: hits / misses / false detections vs
  `labels.json`, and the z of true vs false peaks.
- `./wf objects calibrate [frames_dir]` → per kind the threshold halfway between the lowest true-peak z and the highest
  false-peak z (default when no data), written to `thresholds.json`; prints the table.
- [ ] tests: eval on fixtures prints a row per kind; calibrate writes the file; reembed keeps counts.

### Task 3: Relabel run (live, supervised)

Plan run `objects-relabel`: label in the **normal view** GardenBed, Well, HouseDoor, Gate (tight on the arch); rival
kinds `Window` (house windows), `Tree`; replace the bad Gate example (`objects remove`); then `objects eval` +
`objects calibrate` on the fixtures, and `objects detect` live in two places, scored against the image. Then remove
the `expectedFailure` marks that now pass.
