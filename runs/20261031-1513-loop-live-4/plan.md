# Plan: loop-live-4 (rerun: raw thresholds + any-bubble arrival)

- **Goal:** `goto_bed()` reaches a bed with that bed's bubble, from two starts (house front, road west of the garden).
  Asks answered by labelling (beds missed → `label(n, 'GardenBed', …)`; false bed boxes → `label(n, 'Grass'|'Flower', …)`).
- **Done when:** steps 1–3 done; table in progress.md (call · output · image · clicks · asks · ok/wrong).
- **Brief:** AGENTS.md rules 0–8 · docs/mechanics/basic-actions.md (Approach a target: the loop, answering asks)
- **Review:** supervisor 2026-10-31. D151 ~10:45 am. No planting/watering/buying/sleeping, never press Space.
  One game command per call. **Hard budget 25 calls — count them.** Look scale: game = look px / 0.4 (ask pngs are full
  size: use their coords directly).
  **Answering an ask:** Read the ask png. A visible bed not boxed → `./wf py "label(<n>, 'GardenBed', x0, y0, x1, y1)"`
  (one whole bed frame, tight). A box on something that is not a bed → `./wf py "label(<n>, 'Grass', …)"` (or
  'Flower'/'Fence'). Then re-run the call. No bed visible → `./wf py "answer(<n>, X, Y)"` with a walkable point toward the
  garden. Two unhelpful answers → the call fails: stop, report.

## Step 1: Orient
- **Do:** `./wf resume`, `./wf look` (Read), `./wf graph where`
- **Budget:** 3 calls

## Step 2: goto_bed() from where she stands / the house front
- **Do:** if she is not outside the garden, one click onto the dirt path south of the house's gate arch. Then
  `./wf py "goto_bed()"`; Read the look: at the named bed with its bubble?
- **Budget:** 10 calls

## Step 3: goto_bed() from the road west of the garden
- **Do:** one click onto the road west of the garden fence (look first), then `./wf py "goto_bed()"`; score.
- **Done when:** scored; `./wf pause`; `./wf run end done|partial`
- **Budget:** 10 calls
