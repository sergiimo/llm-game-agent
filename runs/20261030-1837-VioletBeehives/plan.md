# Plan: VioletBeehives (Meant To Bee)

- **Goal:** hand 1 Honey to Violet → quest VioletBeehives done (130 coins + 3 tulip seeds).
- **Done when:** `./wf save` lists VioletBeehives under done.
- **Brief:** docs/quests/town/meant-to-bee.md (read its `Read:` list once before step 1)
- **Review:** rev 6 (D149 10:10, retro-3: clicks were landing on hive sprites; a STUCK inside a function now asks NEED_VISION step; answer it before escalating). rev 5 (D149 9:22, retro-2: on-screen beds are clicked directly and the game pathfinds around the hives, L81; step 4 = the same one-bed test again). rev 4 (D149 9:07: game functions walk through the graph, objects such as hives are walls, the stuck rule runs inside calls; step 4 starts with a one-bed test). rev 3 (D149 7:00, after L77–L78: bed work through game functions, `./wf py`; the well is a learned place; 6 wilted beds left: 1, 3, 4, 5, 9, 10; beds 7, 8 not watered). rev 2 (2026-10-30, after retro-1: wilted beds can't be watered; user approved digging up the 11 wilted tulips and replanting from the 26 bulbs). rev 1: supervisor 2026-10-30 18:40. `./wf run plan` OK. Feasibility: D148 Mon 19:10 now; watering 11 beds ≈ 2 game
  hours (rusty can: 1 fill per bed), bed by 23:00. Honey needs a hive at 12/12 pollen (now 2–7, +0–1 a night), so
  several nights: step 6 repeats each day. Unverified (❓, find out and write down): where the hives stand, what a
  hive shows on click, how honey is collected, where Violet's shop is, how the hand-in works. Violet: Tue–Sat 9–17.
  Sleeping approved; no spending or selling.

## Step 1: Orient
- **Do:** `./wf resume`, then `./wf state`, then `./wf look` (Read the image). Tara should be outside near the farmhouse.
- **Signal:** `gameplay` mode, clock ≈ 7:10 pm, Tara on the farm.
- **Done when:** you know where she is relative to the farmhouse and the garden.
- **Budget:** 4 calls, 10 min
- **If stuck:** a menu is open → `./wf state` names it; close it per docs/ui/ (never blind Escape).

## Step 2: Test digging up ONE wilted bed (scout)
- **Do:** stand on a wilted bed (tulip + drop bubble; `./wf look`), `./wf do key:space` → the card "This plant has
  wilted…" → `./wf do key:space` once more. Then `./wf log --tail 10` and `./wf look`.
- **Signal:** a second `> unplant` log line / the plant gone; the bed now shows an empty-bed (sprout) bubble.
- **Done when:** you know what the second Space did (bed empty or not). Write it in the quest file.
- **Budget:** 6 calls, 15 min
- **If stuck:** nothing changes → escalate with a look image (don't try other keys on the card).

## Step 3: Plant a tulip bulb in that bed and water it
- **Do:** docs/actions.md A9 (empty bed sprout bubble → Space → planting panel → the Tulip Bulbs card → Select), then
  A7 (well: `./wf do act:fill_can`) and A8 (back on the bed: `./wf do act:water`).
- **Signal:** `TulipSeed` −1 in `./wf save`; a `> water me=Player target=GardenBed` log line.
- **Done when:** the bed is planted and watered (`./wf save` isWatered via `./wf routines` count).
- **Budget:** 14 calls, 30 min
- **If stuck:** the panel doesn't show tulips → escalate with a look image.

## Step 4: Replant the remaining wilted beds with game functions
- **Do:** `./wf py "beds()"` (check), then ONE bed as a test: `./wf py "replant(1)"` (walks via the graph around the
  hive row: an on-screen bed is clicked directly and the game pathfinds, L81). If it prints ✓ for every action:
  `./wf py "for b in beds(wilted=True): replant(b)"` (dig up → Tulip → water,
  each proven from the log), then `./wf py "for b in beds(dry=True): water(b)"`. Read the action tree it prints.
- **Signal:** `✓ garden.replant(bed N)` per bed; `FAILED: …` names the missing proof.
- **Done when:** `./wf py "beds(wilted=True)"` and `./wf py "beds(dry=True)"` print nothing (after the next autosave;
  the save may lag a few minutes) and the action tree shows every bed ✓.
- **Budget:** 15 calls, 120 min
- **If stuck:** a FAILED/STUCK output with `NEED_VISION step` → Read the image it names, answer `./wf teach step X:Y`
  (a click near her on open ground toward the goal, never a hive), then re-run the same `./wf py` line. Escalate after
  2 answers that didn't get her moving toward the bed.

## Step 5: Leave the ripe bed (no harvest during this quest)
- **Do:** `./wf run step 5 skip grown flowers feed the bees` (the ripe bed is most likely grown tulips; the hives
  need fully grown flowers nearby, docs/routines.md / reference/wiki/Bee Hive.md).
- **Signal:** progress.md shows step 5 ⏭
- **Done when:** skipped.
- **Budget:** 1 calls
- **If stuck:** nothing to do

## Step 6: Go to bed (before 23:00)
- **Do:** `./wf goto House:in` → docs/actions.md A11 (pink bed in the front-left room; click the bed, zzz bubble,
  `./wf do key:space`, `text:Yes`).
- **Signal:** log `Spawning player at Farm/Bed`, `OnDayStarted`.
- **Done when:** next day 7:00, ⚡ full.
- **Budget:** 10 calls, 40 min
- **If stuck:** wrong bed (no prompt) = the purple bed (L69); stuck rule → ask-step.

## Step 7: Each morning until a hive is full (repeat: `./wf run step 7 start` again every day, max 7 days)
- **Do:** `./wf log --tail 400` and note each hive's `current pollen is N/12` (written ~1–2 AM) in the quest file;
  `./wf py "for b in beds(wilted=True): replant(b)"`, `./wf py "for b in beds(dry=True): water(b)"`; no harvesting
  (step 5); then back to bed (step 6). Tulips grow in 4 days; the bees need grown flowers.
  ❓ The bed may refuse daytime sleep: then note it and escalate (don't idle for hours).
- **Signal:** pollen lines; R1/R2 DONE.
- **Done when:** a hive is at 12/12 (go to step 8), or the day's routines are done and she is back in bed.
- **Budget:** 80 calls, 240 min
- **If stuck:** after 7 days no hive above 10/12 → escalate with the pollen trend.

## Step 8: Collect the honey (❓)
- **Do:** the hives stand in a row north of the garden beds (bubble = honey jar, card "Bee Hive" with a progress bar).
  `./wf do go:<x>:<y>` onto the full hive, then `./wf do key:space` once.
- **Signal:** `grab_item` / `Honey` in the log.
- **Done when:** `./wf save` inventory shows `Honey x1` or more.
- **Budget:** 10 calls, 20 min
- **If stuck:** no prompt on the full hive → escalate with a look image.

## Step 9: Give the honey to Violet (Tue–Sat 9–17)
- **Do:** `./wf goto fountain-square` (Town), then find Violet's Violets (docs/world/locations.md Town Center; not a nav
  place yet: `./wf key m` map, look for the flower shop) and `./wf pos --learn violets` at her door. Talk to Violet
  (docs/actions.md A12; docs/ui/screens/interaction-menu.md) and pick the "!" quest topic.
- **Signal:** `[QUEST] Complete quest VioletBeehives` in the log.
- **Done when:** `./wf save` lists VioletBeehives under done.
- **Budget:** 40 calls, 120 min
- **If stuck:** only a sell/shop menu offered → stop, return decision-needed (no selling). Shop closed → wait/next day.

## Step 10: Record and close
- **Do:** write the verified steps in docs/quests/town/meant-to-bee.md (`### Attempt 1`), set `status: done`, run
  `python3 -I tools/gen_quests.py`, then `./wf run end done`.
- **Signal:** gen_quests prints the update.
- **Done when:** the quest file shows status done and the run is closed.
- **Budget:** 5 calls
- **If stuck:** report it in GAPS.
