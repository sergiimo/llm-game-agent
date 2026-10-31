# Plan: frames-dino (frames for the DINOv2 detection spike)

- **Goal:** 6 full-size gameplay frames of the Farm (no menu, no dialogue): 3 in the normal camera view, 3 in the
  zoomed garden view, each showing several known objects (Tara, BeeHive, GardenBed, Well, HouseDoor, Gate, Mailbox).
- **Done when:** 6 frames copied into `runs/20261031-1021-frames-dino/frames/` as `normal-1.png … zoom-3.png`, and a
  `progress.md` line per frame: where Tara stands + which objects are visible.
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Camera zoom)
- **Review:** supervisor 2026-10-31. D150 ~1 pm, raining. Only walking by click (`./wf do go:X:Y`) and `./wf shot`.
  No planting/watering/buying/sleeping, no menus. One game command per tool call. Look images: game = look px / 0.4.

## Step 1: Resume and orient
- **Do:** `./wf resume`, `./wf state`, `./wf look` (Read it)
- **Signal:** gameplay
- **Done when:** gameplay and you know where the garden/house are on screen
- **Budget:** 4 calls, 5 min

## Step 2: Normal view frames (3)
- **Do:** at 3 different spots on the roads around the house/garden (not inside the garden): `./wf shot` → copy the
  printed png to `frames/normal-N.png` (`cp <path> runs/20261031-1021-frames-dino/frames/normal-N.png`). Before each
  shot `./wf state` must say gameplay (no bubble menu, no dialogue). Move 1–2 clicks between shots.
- **Signal:** shot path printed
- **Done when:** 3 files
- **Budget:** 12 calls, 10 min

## Step 3: Zoomed garden frames (3)
- **Do:** click into the garden (between the beds, or on the well's roof); the camera zooms in. Take 3 shots at
  different spots (beds + hives in view; the well in view in at least one) → `frames/zoom-N.png`.
- **Signal:** Tara visibly bigger in the look (zoomed)
- **Done when:** 3 files
- **Budget:** 12 calls, 10 min
- **If stuck:** position unchanged over 3 clicks → `./wf look`, describe, escalate

## Step 4: Finish
- **Do:** `./wf pause`, write progress.md lines, `./wf run end done`
- **Budget:** 3 calls
