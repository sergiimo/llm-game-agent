# Routines (daily chores, L61)

> **Summary:** things to do every day **before** quest work. `./wf routines` prints today's status from the save (what
> exists: beds, ripe/wilted crops) and today's engine log (what was done). The supervisor runs it every morning and
> dispatches DUE routines first.

| ID | Routine | When / skip | Steps | Done when | Cost |
|---|---|---|---|---|---|
| R1 | **Water the garden** (12 beds, 4×3 grid left of the farmhouse) | every day; **skip if** today's log says `Forecast is Rain/Storm` (rain waters everything). Wilted beds first | `./wf py "water_all()"`: the chain waters every growing, unwatered bed tile by tile (no positions), and refills at the well only after `out_of_water`. Rusty can: **5 beds per fill** (D156 live) | `./wf routines` R1 = DONE (`> water me=Player target=GardenBed` lines today ≥ beds not ripe) | ~7 ⚡ and ~10 game min per pour |
| R2 | **Harvest ripe crops** | when the save shows `plantState ##produced` in a bed | `go:` onto the ripe bed → bag bubble → `act:pickup` (harvest = pickup ❓ verify) | R2 = DONE | free |
| R3 | Bee hives (8) | daily garden pass; collect only ready honey, otherwise inspect current progress | included in `./wf garden`; visit each hive once by bubble/target proof | all 8 hives have current-pass coverage; ready honey collected | free |

## Rules
- **Morning order:** routines (R1 wilted beds first) → quests.
- **Wilted (save, D148):** a bed with `daysNotWatered` ≥ 2 gets `isWilted: true`; `plantState` stays `##growing`
  (not dead, not growing). ❌ **It can't be watered** (D148 run #15): its bubble is a tulip with a water drop; Space
  shows a card "This plant has wilted. You should remember to water plants every day" and logs `> unplant
  me=Player target=GardenBed(Clone)`, no `> water`, plant unchanged. ❓ A second Space on the card probably digs it up
  (unplant; destructive: ask first). Wilted flowers likely don't feed the bee hives. Wiki: the **Reverse Time Spell** (Westley,
  130 coins) restores wilted plants (spending → ask the user). ❓ How many dry days until a crop dies.
- New bubble kinds on the way (`fill_can`, `water`) are learned by one deliberate Space (docs/self-improvement.md).
- Trips are the same every day: record them as anchored edges (`./wf edge add`), replay them (`./wf edge replay`).
- Status is exact, not remembered: always re-run `./wf routines` instead of counting by hand.

# Fast garden pass

Run `./wf garden` for the default Garden. It keeps one persistent coverage queue containing every graph bed and hive in
the region. For each visible target it immediately completes the applicable rule: harvest non-flowers, remove and
replant wilted crops when the same seed is available, then water; collect ready honey; inspect non-ready hives. Ready
flowers and pre-existing empty beds stay untouched.

With no fitting bubble, answer `target <cell>` only when the target and the full road from Tara are visible; otherwise
use `walk <cell>` for one short visible-ground waypoint. The event position, never projected ownership, decides which
target received coverage. Use `region=GardenSouth` for the south plot.

The supervisor verifies the pass with `./wf run report`: its **Garden coverage** table compares the routine's exact
target IDs with covered and unresolved IDs. `COMPLETE` means every target is covered with a terminal `done` result;
`CONSTRAINED` means every target is accounted for and the terminal result names exact unresolved constraints;
`PENDING` lists the missing target IDs and is never completion.
