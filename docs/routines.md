# Routines (daily chores, L61)

> **Summary:** things to do every day **before** quest work. `./wf routines` prints today's status from the save (what
> exists: beds, ripe/wilted crops) and today's engine log (what was done). The supervisor runs it every morning and
> dispatches DUE routines first.

| ID | Routine | When / skip | Steps | Done when | Cost |
|---|---|---|---|---|---|
| R1 | **Water the garden** (12 beds, 4×3 grid left of the farmhouse) | every day; **skip if** today's log says `Forecast is Rain/Storm` (rain waters everything). Wilted beds first | `Bed` → `House-door` (edges) → the **well** (left side of the garden): `act:fill_can` → each dry bed: `go:` onto it → `act:water`. Rusty can: **1 fill waters 1 bed** (refill between beds) | `./wf routines` R1 = DONE (`> water me=Player target=GardenBed` lines today ≥ beds not ripe) | small ⚡ per pour; ~10 game min per bed |
| R2 | **Harvest ripe crops** | when the save shows `plantState ##produced` in a bed | `go:` onto the ripe bed → bag bubble → `act:pickup` (harvest = pickup ❓ verify) | R2 = DONE | free |
| R3 | Bee hives (8) | ❓ (log shows pollen levels per hive overnight) | ❓ | ❓ | ❓ |

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
