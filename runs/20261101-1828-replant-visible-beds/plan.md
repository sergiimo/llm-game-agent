# Plan: replant-visible-beds

- **Goal:** At current bed-grid position, OCR-probe GardenBed bubbles one-by-one and replant four wilted flowers
- **Done when:** Four currently owned Tulip seeds replace four wilted flowers; every bed is discovered by GardenBed-owner + OCR probing and proved by exact `unplant_impl` and Tulip planting logs; game paused.
- **Brief:** `docs/actions.md` A18; `docs/self-improvement.md` unknown/highlight/OCR rules; `tools/game/garden.py replant_visible`.
- **Review:** Ready. Tara is already at the beds. No navigation, no highlighted-Space selection, no hive candidates. One `replant_visible('Tulip')` call per bed so each outcome is independently proved. Cheapest agent/runner model only.

## Step 1: Replant four visible wilted beds one-by-one
- **Do:** `./wf resume`, then run `./wf py "replant_visible('Tulip')"` four separate times. Each call probes GardenBed bubbles with OCR and stops after exactly one replacement. Run `./wf pause` after the fourth.
- **Signal:** Per call: `bed_probe` OCR says wilted, exact `unplant`/`unplant_impl`, and `totalPlanted.TulipSeed`; never `beehive_progress`.
- **Done when:** Four calls each prove one newly planted Tulip.
- **Budget:** 6 calls, 70 game min.
- **If stuck:** Pause at the first missing/mismatched proof. Do not navigate, press generic Space, or try the next call.

## Step 2: Recount
- **Do:** Run `./wf routines` and report remaining wilted count; leave paused.
- **Signal:** Expected four wilted remain because only four Tulip seeds were owned.
- **Done when:** Exact remaining count is reported and no uncovered bed was removed.
- **Budget:** 1 call, 0 game min.
- **If stuck:** Report last four exact proofs only; no more input.
