# Plan: objects-seed (spec 2026-10-31 step 1, live)

- **Goal:** seed the object store (`tools/objects/db`) with labelled examples of Farm objects, then check that
  `./wf objects detect` finds them from other places and zooms. Report hits and misses per kind, with images.
- **Done when:** steps 1–5 done; the report table (kind · examples added · detect hits/misses · notes) is in `progress.md`.
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Interaction bubbles, Camera zoom) ·
  `./wf objects` (help: `./wf objects bogus` prints usage)
- **Review:** supervisor 2026-10-31. Daytime D150 (it rains). No planting/watering/buying/sleeping. Movement only by
  clicking (`./wf do go:X:Y`) — few moves are needed; this run is about labelling, not walking. Image first on any problem.

## How labelling works (read once)
- `./wf look` writes a JPEG at **0.4 scale** (768×432). **Game coords = look pixel / 0.4** (the `look:` line prints it; this plan first said ×2 — wrong). Read the image, then for each
  object give a box `x0 y0 x1 y1` in game coords that tightly covers its **whole visible body** (not its shadow, not a
  bubble, not Tara).
- `./wf objects add <Kind> x0 y0 x1 y1 [state]` crops the *current* frame — so add right after the look, before Tara or
  the camera moves. Prints `added …` or `duplicate (skipped)` (both fine).
- Kinds (exact spelling): `Tara`, `Well`, `BeeHive`, `GardenBed`, `HouseDoor`, plus any other clear object you see
  (`Mailbox`, `Tree`, `Fence`, `Barrel`…) — CamelCase, singular. GardenBed state: `empty`, `planted`, `wilted`, `watered`
  (what you see; omit if unsure).
- `./wf objects detect` prints `<kind> box … dist … point x,y` per detection (dist < 0.6 is a match; lower = surer).
  Check each against the image: right kind, box on the object? That is the hit/miss.

## Step 1: Orient
- **Do:** `./wf resume`, `./wf state`, `./wf look` (Read it)
- **Signal:** gameplay; image shows the Farm
- **Done when:** you can name which of the kinds are visible
- **Budget:** 4 calls, 10 min
- **If stuck:** pause menu still open → `./wf resume` once more

## Step 2: Label what is visible here
- **Do:** for each visible kind (Tara always): `./wf objects add …` (one call each, right after the look; re-look if
  she moved). Then `./wf objects list`.
- **Signal:** `added …` lines; list shows the kinds
- **Done when:** ≥ 3 kinds have an example
- **Budget:** 10 calls, 15 min
- **If stuck:** a box crop looks wrong → `./wf look` again and redo that one

## Step 3: Go to the garden/well and label there (zoomed camera)
- **Do:** click toward the well/garden (`./wf do go:X:Y` on the well's roof if visible, else on the road toward it),
  `./wf look`, then add `Well`, `BeeHive` (2 different hives), `GardenBed` (3–4 beds in different states), `Tara`
  (zoomed: she looks bigger).
- **Signal:** `added …` for each
- **Done when:** Well, BeeHive, GardenBed have ≥ 2 examples each (`./wf objects list`)
- **Budget:** 16 calls, 25 min
- **If stuck:** position unchanged over 3 moves (stuck rule) → `./wf look`, describe it, escalate

## Step 4: Label by the house
- **Do:** click toward the house front door, `./wf look`, add `HouseDoor`, `Tara`, and any new clear objects.
- **Signal:** `added …`
- **Done when:** HouseDoor ≥ 1 example
- **Budget:** 10 calls, 20 min
- **If stuck:** as step 3

## Step 5: Detection check in two other places
- **Do:** at two places where you did NOT label (e.g. halfway between house and garden, and the far side of the
  garden): `./wf look` (Read it), `./wf objects detect`, and for one expected-but-missed kind `./wf objects find <Kind>`.
  Score each detection hit/miss against the image; note missed visible objects.
- **Signal:** detect lines
- **Done when:** a table in progress.md: kind · examples · hits · misses (wrong kind, box off, missed) · notes;
  `./wf pause` at the end
- **Budget:** 10 calls, 20 min
- **If stuck:** detect errors → copy the error, escalate
