# Energy

> **Summary:** stamina spent by tool use and some actions. **Sleep is the main restore.** Food restores little and costs
> money (tips T1–T3). Shown as the orange ⚡ arc
> on the clock; `./wf state` reports `⚡N%`.

## Rules (wiki, partly verified)
- Spent by chopping, mining, watering, digging, foraging and some spells. At 0, tool use stops.
- Restored by sleeping (full), food/coffee/potions (partial), the Mountain Onsen (paid, 1×/day).
- Max energy grows through story rewards (Increase Energy spell at the end of Spring).

## Strategy
`./wf tips energy` (all energy/food/sleep strategy lives in [../tips.md](../tips.md): T1–T5, T8).

## How to see
Orange arc on the right of the clock widget, starting at a ⚡ icon, filling clockwise over a pale track:
[../ui/hud.md](../ui/hud.md) (Clock widget row).

## How to read
`./wf state` → `⚡N%` (`read_energy` in tools/wf.py: share of orange along the ring at r=96 around (116,116),
82°→205°). Appears whenever the HUD is visible.

## Verified in-game
- ✅ Out of energy (Wed d3 ~11:10, after ~1.5 logs + morning chores): "Тара: У меня больше нет сил!" (I have no strength
  left); tool use stopped. Eating 1 Грибной крем-суп restored part of the bar.
- ✅ The ⚡ arc is the energy meter (Wed d3 13:00 ≈ 47% after a soup and the morning's chopping).
