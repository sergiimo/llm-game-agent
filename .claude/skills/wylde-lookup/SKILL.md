---
name: wylde-lookup
description: Answer Wylde Flowers knowledge questions offline — items, recipes, crops, fish, characters, favorite gifts, shop hours, quests, locations — from docs/ and the mirrored fan wiki. Use before buying, crafting, gifting, or when a quest names something unfamiliar.
---

# Looking things up

Load progressively: `docs/INDEX.md` → the area index → one file (read the `> **Summary:**` first).
The game is in Russian and the wiki is in English. Translate names with `docs/ui/glossary.md`; if a term is missing, translate it yourself and add it there once confirmed in-game.

| Question | Where |
|---|---|
| Who is X, where/when, favorite gifts | `docs/world/characters.md`, then `reference/wiki/<Name>.md`, `<Name>__Schedule.md`, `__Events.md` |
| Is shop X open now / what it sells | `docs/world/businesses.md`, then `reference/wiki/<Business>.md` (inventory + unlock levels) |
| Recipe / station / sell price | `docs/world/items/*.md` (food-and-drink, potions-and-incantations, crafting-ingredients, workstations …) |
| Crop season / grow time / profit | `docs/mechanics/farming.md`, `reference/wiki/Farming.md` |
| Fish by area & bait | `docs/world/items/fish.md`, `reference/wiki/Fishing.md`, area pages |
| Quest requirements, rewards, status, verified steps | `docs/quests/INDEX.md` → `docs/quests/<line>/<quest>.md`; board: `reference/wiki/Bulletin Board Quests.md` |
| How a system works | `docs/mechanics/INDEX.md` → `docs/mechanics/<topic>.md` |
| What a screen is / how to exit / which key | `docs/ui/INDEX.md` → `docs/ui/screens/<screen>.md`, `controls.md`, `hud.md` |
| Anything else | `./wf wiki "<term>"` (title + content matches); `./wf wiki "<Title>" --show` prints a page |

Wiki data is community-written and may be out of date (the game is v1.7.2). When the game disagrees, trust the
game and log it in `docs/learnings.md`.
