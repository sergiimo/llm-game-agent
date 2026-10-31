# Plan: graph-garden (step 2 live check: nested regions)

- **Goal:** check the region loop live: from outside, `./wf graph where` says Farm and `./wf graph path GardenBed`
  gives a click on the Garden; clicking it gets Tara inside (camera zooms); `where` then says Garden and lists garden
  members. Score every claim against the look image.
- **Done when:** steps 1–4 done; table in progress.md: step · command output (short) · what the image shows · ok/wrong.
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Camera zoom; fences: Tara jumps them) · `./wf graph`
- **Review:** supervisor 2026-10-31. D150 ~5 pm, rain. Only clicks (`./wf do go:X:Y`) and read-only `./wf graph`/`objects`
  calls. No planting/watering/buying/sleeping/menus. One game command per call. **Hard budget 25 calls**: at 25,
  `./wf pause` and report partial. Look scale: game = look px / 0.4. Image first on any problem.

## Step 1: Orient outside the garden
- **Do:** `./wf resume`, `./wf look` (Read). If Tara is inside the garden (camera zoomed, beds big), click a road point
  well outside it first and look again.
- **Done when:** Tara outside the garden, unzoomed (Tara small)
- **Budget:** 4 calls

## Step 2: where + path from outside
- **Do:** `./wf graph where`, `./wf graph path GardenBed`. Compare with the look: is the region right? Is the `click`
  point on the garden (hives/beds/well), not on grass/fence/house?
- **Done when:** both outputs scored
- **Budget:** 3 calls

## Step 3: Enter the garden
- **Do:** `./wf do go:<click from path> --look` (if the click point is wrong, use a point on the bed grid from your look
  and note it). Read the image: zoomed in? Then `./wf graph where`.
- **Signal:** `region Garden`; seen list with BeeHive/GardenBed/Well
- **If** the image shows her inside (zoomed) but `where` says Farm: `./wf graph view-add Garden`, then `where` again.
- **Done when:** where scored against the image
- **Budget:** 6 calls

## Step 4: Out and back once (second sample)
- **Do:** click a road point outside the garden → `./wf graph where` (expect Farm; if wrong and the image is clearly
  outside: `./wf graph view-add Farm`) → `./wf graph path GardenBed` → click its point → `./wf graph where`.
- **Done when:** table complete; `./wf pause`; `./wf run end done|partial`
- **Budget:** 10 calls
