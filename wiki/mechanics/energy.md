# Energy

> **Summary:** stamina spent by tool use and some actions. **Sleep is the main restore.** Food restores little and costs
> money (tips T1–T3). Shown as the orange ⚡ arc
> on the clock; `./wf state` reports `⚡N%`.

## Rules (wiki, partly verified)
- Spent by chopping, mining, watering, digging, foraging and some spells. At 0, tool use stops.
- Restored by sleeping (full), food/coffee/potions (partial), the Mountain Onsen (paid, 1×/day).
- Max energy grows through story rewards (Increase Energy spell at the end of Spring).

## Cost table (✅ day-144 save, copper tools, Give a Ranch Hand run)
| Action | Energy | Yield |
|---|---|---|
| Tree (pine/oak), 4 hits | ~16% (~4–5% per hit) | 5–8 Wood |
| Small rock `StoneRock`, 2 hits | ~10% | 1–2 Stone |
| Boulder `StoneBoulder`, ~8 hits | ~50% | ~10 Stone (+ sometimes a recipe) |
| Restorative Tea | **+~43%** | — |
**Before a gathering goal, add up the costs.** If the total is over 100% of the bar, split the goal by day; don't plan on food.
(49 wood + 26 stone ≈ 240% → ran out twice and used 6 teas; retro 2026-10-27.)

## Strategy
`./wf tips energy` (all energy/food/sleep strategy lives in [../tips.md](../tips.md): T1–T5, T8).

## How to see
Orange arc on the right of the clock widget, starting at a ⚡ icon, filling clockwise over a pale track:
[../ui/hud.md](../ui/hud.md) (Clock widget row).

## How to read
`./wf state` → `⚡N%` (`read_energy` in tools/wf.py: share of orange along the ring at r=96 around (116,116),
82°→205°). Appears whenever the HUD is visible.

## Verified in-game
- ✅ Out of energy (Wed d3 ~11:10, after ~1.5 logs + morning chores): "Tara: I have no strength left! (EN ❓)" (I have no strength
  left); tool use stopped. Eating 1 Cream of Mushroom Soup restored part of the bar.
- ✅ The ⚡ arc is the energy meter (Wed d3 13:00 ≈ 47% after a soup and the morning's chopping).
