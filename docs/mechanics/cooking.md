# Cooking

> **Summary:** cook at the **stove in the farmhouse kitchen** using recipes (Gramma's recipe book is "hidden in the
> stove"). Recipes need ingredients in the inventory. ❓ Exact UI not yet seen.

## Rules (wiki)
- Station: kitchen stove ("Frypan / Stovetop" category in `reference/wiki/Cooking.md`). Other categories need other stations.
- Recipes come from quests, books, mine chests and bottles found while fishing.
- **Mushroom Risotto** = 1 Mushroom (or Shiitake) + 1 Rice; Frypan; sells to Sophia for 20c; restores energy. It's
  Gramma's favourite and the Rice and Shine quest target.
- Cooked food sells to Sophia (Cafe Moretti) and feeds favourite-gift relationships.

## Strategy
`./wf tips crafting food money`

## How to cook ✅ (Wed d3 23:08, run #12)
1. Reach the stove (left room; path in `docs/world/locations.md` → House doorway → kitchen stove) → orange **"?"** bubble → Space.
2. Screen **Cooking (EN ❓)** (`overlay`): tabs on the left = cooking type; sections **Raw / Fried / Boiled / Baked (EN ❓)** with recipe cards.
3. Click the card (Mushroom Risotto = 3rd card under **Fried (EN ❓)**, `click:500:512`) → detail "Mushroom Risotto" with ingredients have/need (Mushroom 2/1, Rice 1/1) and the button **Craft** (EN ❓, was Смастерить), focused.
4. Space → crafted at once (log `[STATS] totalCrafted.MushroomRisotto = 1`) → Esc closes.
- Only recipes you know are cookable: the risotto recipe came from Gramma's quest dialogue ("New recipe! Mushroom Risotto" popup). Before that the stove said `Not yet` (below).

## Verified in-game
- **Stove locked by quest stage:** Space at the stove (orange "?" bubble) → `Tara: Not yet.` ("too early"), log `> not_yet target=Oven`, while Rice and Shine was at goal 0 with its items ready but **not yet reported to Gramma** (Wed d3 22:10).
- The stove is in the left room of the farmhouse (kitchen, next to the sink); seen in screenshots, not used yet.
