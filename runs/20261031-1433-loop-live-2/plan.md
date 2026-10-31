# Plan: loop-live-2 (rerun on the fixed loop)

- **Goal:** `fill_can()` and `goto_bed()` from the house front on the fixed loop (enter a region = click a member;
  label answers). Score each call: output, image, clicks, asks.
- **Done when:** steps 1–4 done; table in progress.md (call · output · image · clicks · asks · ok/wrong).
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Approach a target: the loop, answering asks)
- **Review:** supervisor 2026-10-31. D150 ~6:45 pm (dusk soon), rain. No planting/watering/buying/sleeping. One game
  command per call. **Hard budget 25 calls — count them.** Look scale: game = look px / 0.4.
  **Answering an ask** (an `ask-<n>.png` path printed): Read it. The target visible but not boxed → `./wf py
  "label(<n>, '<Kind>', x0, y0, x1, y1)"` (tight box around the target in game coords; use the ask png, it is full size)
  then re-run the call. Not visible → `./wf py "answer(<n>, X, Y)"` (a walkable ground point toward it — not a fence,
  not a wall), then re-run. Two unhelpful answers → the call fails: stop, report.

## Step 1: Orient
- **Do:** `./wf resume`, `./wf look` (Read). Tara starts at the well inside the garden.
- **Budget:** 2 calls

## Step 2: To the house front, one click
- **Do:** one `./wf do go:X:Y --look` on the dirt path just south of the gate arch below the house porch (from the
  garden: the arch is right of the garden, the house behind it). Tara jumps fences. If not there yet, one more click.
- **Budget:** 3 calls

## Step 3: fill_can()
- **Do:** `./wf py "fill_can()"` (answer asks as above). Read the look after it.
- **Signal:** ✓ well.fill_can; log `target=Well` or `My watering can is already full!`
- **Budget:** 8 calls

## Step 4: back to the house front, goto_bed()
- **Do:** one click back to the path south of the arch (as step 2), then `./wf py "goto_bed()"`. Read the look: is Tara
  at the bed it names, with that bed's bubble? Don't press anything.
- **Done when:** scored; `./wf pause`; `./wf run end done|partial`
- **Budget:** 10 calls
