# Plan: water-beds-live

- **Goal:** water every remaining dry growing garden bed and verify the daily routine
- **Done when:** `./wf routines` reports `R1 water garden: DONE 12/12 beds watered today`, and the game is paused.
- **Brief:** `docs/routines.md` R1; `docs/actions.md` A7–A8; `tools/game/garden.py` `beds(dry=True)` and `water`.
- **Review:** Ready after retros 1–9. R1 is 11/12; only `(0.84,-29.09)` remains. `1228:856` exactly hit `(5.84,-29.09)`, providing a same-frame anchor. Current zoomed calibration maps the remaining bed's -5 world-x offset to -614 screen-x, so the reviewed target is `614:853`. Require exact coordinate plus R1 DONE.

## Step 1: Finish the first three-bed tranche
- **Do:** `./wf run step 1 start`; `./wf resume`; `./wf py "[water_next() for _ in range(2)]"`; immediately `./wf pause`; inspect the new log lines. One bed from this tranche already succeeded at 11:17.
- **Signal:** Two new exact `> water ... target=GardenBed ... at (x, y, z)` lines at distinct, still-due positions; together with the preserved success, three beds advance.
- **Done when:** The game is paused and `./wf routines` reports at least 8/12 watered.
- **Budget:** 14 calls total, 100 game minutes (includes three stopped attempts, one preserved watering, and this direct-object two-bed retry).
- **If stuck:** Stop input, pause, report the exact exception plus the last log line; do not retry blindly.

## Step 2: Water the next three dry beds
- **Do:** Two waters, refill, and the first west-gap click already succeeded. Restart step 2; resume; `./wf do click:1375:812`; pause immediately; inspect the exact log and R1. If it only moves safely, resume and run `./wf py "water_next()"`, then pause. If it waters a due bed, do not repeat it.
- **Signal:** The goal-dot click moves toward bed 6 or emits an exact `> water` at `(0.84,-29.09)`/`(3.34,-29.09)`. One new water completes this tranche; an unrelated action requires stop.
- **Done when:** The game is paused and `./wf routines` reports at least 11/12 watered.
- **Budget:** 22 calls total, 150 game minutes, including preserved actions, stopped routes, discarded halfway click, one goal-dot click, inspection, and optional one-bed retry.
- **If stuck:** Stop input, pause, report the exact exception and any successful bed positions; never repeat already-proved beds.

## Step 3: Water the final dry bed and verify
- **Do:** Restart step 3; resume; `./wf do click:614:853` on the empirically calibrated remaining bed; pause immediately; run `./wf routines`, `./wf save`, and `./wf log --tail 20`. Do not run generic routing first.
- **Signal:** Exact `> water ... at (0.84, 0.10, -29.09)` and R1 reports DONE 12/12.
- **Done when:** R1 is DONE 12/12, save shows no wilted beds, and the game is paused.
- **Budget:** 12 calls total, 70 game minutes, including stopped attempts, one calibrated bed click, and final verification.
- **If stuck:** Pause and report the remaining `beds(dry=True)` plus the latest log; do not add exploratory movement.
