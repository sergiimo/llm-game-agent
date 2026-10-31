# Plan: loop-live (step 3 live: skills on the object loop)

- **Goal:** first live use of the object loop: `graph sync`, `fill_can()` and `goto_bed()` from the house front.
  Score each call: what it printed, what the image shows, clicks used, asks.
- **Done when:** steps 1–4 done; table in progress.md (call · output · image · clicks · asks · ok/wrong).
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Approach a target: the loop, asks; fences)
- **Review:** supervisor 2026-10-31. D150 ~5:30 pm, rain. No planting/watering/buying/sleeping. One game command per
  call (wfc now refuses chained input commands). **Hard budget 25 calls.** Look scale: game = look px / 0.4.
  On `NeedVision` (an `ask-<n>.png` path printed): Read that image, decide the click, answer with
  `./wf py "loop.answer(<n>, X, Y)"`, then re-run the same call. Two unhelpful answers → the call fails: stop, report.

## Step 1: Orient + sync
- **Do:** `./wf resume`, `./wf look` (Read), `./wf graph sync` (prints state changes), `./wf graph show Garden`
- **Done when:** gameplay; sync printed
- **Budget:** 4 calls

## Step 2: To the house front (not into the house)
- **Do:** click the ground on the path in front of the porch, a little below the door (not the door: that enters the
  house). `./wf look`; `./wf graph where` (expect Farm).
- **Budget:** 4 calls

## Step 3: fill_can() on the loop
- **Do:** `./wf py "fill_can()"`. Read the look after it. Expect ✓ with a `target=Well` or "already full" line.
- **Signal:** ✓ well.fill_can; log `full_watering_can … target=Well` or `My watering can is already full!`
- **Budget:** 8 calls (incl. asks)

## Step 4: goto_bed() (any bed)
- **Do:** click back to the house front first (as step 2), then `./wf py "goto_bed()"`. Expect an Arrival with a bed
  member (GardenBed#n) and its bubble. Read the look: is Tara at that bed with its bubble? Don't press anything.
- **Done when:** scored; `./wf pause`; `./wf run end done|partial`
- **Budget:** 9 calls
