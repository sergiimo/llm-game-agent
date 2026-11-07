# Wylde Flowers — world model overview

**Genre:** cozy farm/life sim + witchcraft story, fully voiced, by Studio Drydock (Australia).
**This install:** Apple Arcade macOS build, bundle `com.studiodrydock.mayflower`, v1.7.2, full-screen 1920×1080.

## Premise
Tara Wylde leaves the city for the seaside town of **Fairhaven** to help her aging grandmother
**Hazel ("Gramma")** run the family **farm**. She soon discovers she is a **witch**, joins the secret
**Fairhaven Coven**, and gets drawn into a conflict with the anti-witch **League of the Conscious Mind**
and, later, a mysterious enemy (the "Raven"). The story is split by **seasons**; each season is a chapter.

## Story structure (one in-game year + epilogue)
| Chapter | How it ends / what triggers the next | Headline content |
|---|---|---|
| Spring (Year 1) | Craft a **Spirit Flame** potion → Summer ritual | Meet the town, learn farming, discover magic, join coven as Novice |
| Summer | **Fall Ritual Incantation** + Spirit Flame | Drought (Summon Rain), coven identities, mine depths, Summer Festival |
| Fall | Winter Ritual incantation | Election, Gloaming keystones, Ravenwood Hollow |
| Winter | Spring ritual / finale | Wraiths, Winter Feast, final confrontation with Vanessa |
| Spring (Year 2, epilogue) | open-ended | Epilogue quests, Spring Fling |

**Seasons never change on their own.** You trigger the change when you complete the ritual quest, so
you can stay in a season as long as you want. Out-of-season crops **vanish** at the change, so harvest first.

## Core systems (details in docs/mechanics/)
- **Time:** clock advances in 10-minute ticks; game speed is configurable (Relaxed/Normal/Challenging).
  Days have weekdays, and **shops have fixed hours and closed days** (docs/world/businesses.md).
- **Energy (stamina):** tool use, foraging, spells all cost energy. Eat food/coffee to restore. Running out
  makes Tara collapse. Sleeping restores it. Max energy grows via coven rewards (Increase Energy spell).
- **Magic meter:** spells/wand use magic; restore with alcohol drinks or Restore Magic potions.
- **Farming:** garden beds (4 seeds each), watering daily, compost bins (weeds→soil+worms), beehives near flowers.
- **Crafting:** Tool Shed (mundane stations), **Basement/Sanctum** (magic: cauldron, desk, distillery…), kitchen stove (cooking).
- **Fishing, Foraging, Mining** (20-level mine next to the farm), **Animals** (coop, barn, pet cat Cleocatra).
- **Relationships:** one daily chat per villager + gifts; heart events; romance and marriage (8 romanceable).
- **Shops level up** when you sell to them, which unlocks more stock (stars, top-right of the shop window).
- **Quests:** To-Do quests in the Journal (story questlines) + Bulletin Board quests outside Town Hall.
- **Inventory is unlimited**, so hoard materials rather than selling them.

## Map (docs/world/locations.md)
Farm (home) ↔ Town Center (hub of shops) ↔ Woods (coven meeting place, Silver Willow, Bramble Gate) ;
Farm ↔ Beach (Thomas's farm, Hayseed Homestead) ; Farm ↔ Mountain (after bridge repair) ; Farm ↔ Mine ;
Ravenwood Hollow and the Gloaming (magical areas, later).

## Where to look things up
- Hand-written guides: `docs/` (start with AGENTS.md)
- Generated tables: `docs/world/characters.md`, `businesses.md`, `items/*.md`
- Full offline fan wiki (1190 pages): `reference/wiki/` → search with `./wf wiki "<term>"`
- Story quest list with requirements and rewards: `reference/wiki/To-Do Quests.md`
- Town board requests: `reference/wiki/Bulletin Board Quests.md`
- Sources: wylde-flowers.fandom.com (CC BY-SA), wyldeflowersgame.com/help.html, commonsensegamer.com guides.
