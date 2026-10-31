# Plan: loop-live-5 (goto_bed on the loop: inside, then from the house front)

- **Goal:** `goto_bed()` gets Tara to the bed it names with that bed's bubble, from (A) the well inside the garden and
  (B) the house front. Asks answered by labels.
- **Done when:** steps 1–3 done; table in progress.md (call · output · image · clicks · asks · ok/wrong).
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Approach a target: the loop, answering asks, fences)
- **Review:** supervisor 2026-10-31. D156 ~7:30 am. The user just handed the game back; nobody else plays during the
  run. No planting/watering/buying/sleeping, never press Space. One game command per call. **Hard budget 20 calls.**
  After each scored call: `./wf look`, Read it, copy it to the run dir as `look-<step>.jpg`.
  **Asks:** Read the ask png; visible bed not boxed → `./wf py "label(<n>, 'GardenBed', x0, y0, x1, y1)"`; a box on a
  non-bed → `label(<n>, 'Grass'|'Flower'|'Fence', …)`; no bed visible → `./wf py "answer(<n>, X, Y)"`; re-run.

## Step 1: A — from the well
- **Do:** `./wf resume`, `./wf py "goto_bed()"`, `./wf look` (Read): at the named bed with its bubble?
- **Budget:** 6 calls

## Step 2: To the house front
- **Do:** `./wf look` (Read), one click on the dirt path south of the house's gate arch (if a jump fails, click a point
  on her side of the fence toward the arch's opening). Max 3 clicks.
- **Budget:** 5 calls

## Step 3: B — from the house front
- **Do:** `./wf py "goto_bed()"`, `./wf look` (Read): at the named bed with its bubble?
- **Done when:** scored; `./wf pause`; `./wf run end done|partial`
- **Budget:** 8 calls
