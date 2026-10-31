# Plan: objects-relabel (DINOv2 detection, plan 2026-10-31-objects-dino-detection Task 3)

- **Goal:** add examples taken in the **normal (unzoomed) camera view** and rival kinds, recalibrate, then check
  `./wf objects detect` live. Report hits/misses per kind with images.
- **Done when:** steps 1–5 done; eval + calibrate tables and the live check table in `progress.md`.
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Camera zoom) · `./wf objects` (usage: `./wf objects bogus`)
- **Review:** supervisor 2026-10-31. D150 ~2 pm, rain. No planting/watering/buying/sleeping, no menus. Move only with
  `./wf do go:X:Y`. **One game command per tool call — never chain with `;`.** `./wf state` says "overlay" in rain:
  check gameplay with `./wf look` instead. Image first on any problem.

## How labelling works
- `./wf look` is at **0.4 scale**: game coords = look px / 0.4. Read the image; give a box `x0 y0 x1 y1` in game coords
  tightly around **one object's visible body** (one hive, one bed, the door only, the gate arch only).
- `./wf objects add <Kind> x0 y0 x1 y1 [state]` right after the look (crops the current frame). Prints `added …` or
  `duplicate of <id> …` (both fine). Bad label → `./wf objects list <Kind>` → `./wf objects remove <Kind> <id>`.
- `./wf objects detect [Kind…]` prints `<kind> z <score> box … point x,y`; check each against the image.
- Kinds: `BeeHive`, `GardenBed` (state empty/planted/wilted), `Well`, `HouseDoor`, `Gate`, `Mailbox`, `Tara`, and the
  rivals `Window` (house windows), `Tree` (pines/bushes), `Fence`.

## Step 1: Orient, drop the bad Gate example
- **Do:** `./wf resume`, `./wf look` (Read), `./wf objects remove Gate 1793433787273-23`
- **Signal:** gameplay in the look; `removed Gate …`
- **Budget:** 4 calls, 5 min

## Step 2: Normal-view labels from the road east of the gate (not where the saved frames were taken)
- **Do:** click onto the road east of the gate/mailbox (Tara well outside the garden, camera unzoomed: Tara small).
  `./wf look`, then add: 2 single `BeeHive`, 2 single `GardenBed`, `Well` (its roof if that is all you see),
  `HouseDoor` (door only), `Gate` (arch only), 2 `Window`, 1 `Tree`, `Mailbox`, `Tara`.
- **Signal:** `added`/`duplicate` lines
- **Done when:** each listed kind has a new example (`./wf objects list`)
- **Budget:** 16 calls, 15 min
- **If stuck:** moved < 2 units over 3 clicks → `./wf look`, describe, escalate

## Step 3: One more normal-view spot (west road, by the pine)
- **Do:** click onto the west road; `./wf look`; add 1 `GardenBed`, 1 `BeeHive`, `Well`, 1 `Tree`, `Tara`.
- **Budget:** 10 calls, 10 min

## Step 4: Recalibrate (offline, no game input)
- **Do:** `./wf objects calibrate`, then `./wf objects eval`; copy both tables into progress.md.
- **Budget:** 2 calls

## Step 5: Live check in two places
- **Do:** at two places (one normal view on the north road, one zoomed in the garden): `./wf look` (Read),
  `./wf objects detect BeeHive GardenBed Well HouseDoor Gate Mailbox Tara`. Score each line hit/miss against the image;
  list visible objects that were missed.
- **Done when:** table in progress.md (place · kind · z · hit/miss/false · note); `./wf pause`
- **Budget:** 8 calls, 10 min
