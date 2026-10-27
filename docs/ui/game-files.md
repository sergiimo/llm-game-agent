# Game files: event log + save (read instead of screenshots)

> **Summary:** The game writes a live event log (`./wf log`) and autosaves zstd-JSON (`./wf save`). Read both at the
> start of a goal and the log after every input action: it's text, exact, and costs no screenshot. `do`/`advance`/input
> commands already print new log lines as `log: …`. The screen is still needed for menus, prompts, bubbles, position.

Both live in the game's sandbox container `~/Library/Containers/com.studiodrydock.mayflower/Data/Library/` (L41).
Run with the sandbox disabled.

## `./wf log`: live event log (`Logs/Studio Drydock/Wylde Flowers/Player.log`)
- `./wf log`: new lines since the last read (the read position is in `.shots/gamelog.pos`). `--tail N` = last N lines
  (use at goal start). `--grep REGEX`, `--raw` (no noise filter/decoding).
- Every line is stamped with **game day + time**: `[D3 2:50:44 PM]`. Ids `#123` are decoded to internal names.
- What it shows (verified D3):

| Line | Meaning |
|---|---|
| `[QUEST] Start quest GrandmaFaveFood day 3` / `Advance quest X to goal 1` / `Complete goal X:…` / `Complete quest X` | Quest progress, exact (internal quest names, see below) |
| `Otto: If you need anything…` / `Player: Hi.` | **Every dialogue line** (speaker + text in the game language), written when the performance starts, so a whole conversation can appear at once |
| `[TRIGGER] OnEnterBuilding GeneralStore` / `OnExitBuilding …` / `OnEnterScene` / `WaypointTrigger LinkFarm` | Location changes (building names = internal ids) |
| `[GAME] OnLoadingSceneLoaded, loading Farm` · `[MODE] Spawning player at Farm/LinkTown` | Scene loaded (Farm, Town, …) and spawn point |
| `> grab_item me=Player target=Thistle(Clone) at (x, y, z)` | Picked something up (+ world position) |
| `[TRIGGER] OnGoalReady GrandmaFaveFood` | All items for the quest's current goal collected. **Next: talk to the quest giver** ("!" over their head) to complete the goal; the save keeps `goal N` and the next step (e.g. the stove) stays locked until then |
| `> grandma_favefood_collect_ready … target=Hazel` → `[QUEST] Complete goal GrandmaFaveFood:collect` → `Advance … to goal 1` | Pattern `<quest>_<goal>_ready target=<NPC>` = a goal handed in to that NPC |
| `[STATS] totalCrafted.MushroomRisotto = 1` | Cooked/crafted an item |
| `> not_yet me=Player target=Oven` + `Tara: Not yet.` | Object locked by quest stage (here: stove before reporting to Gramma) |
| `> grab_item me=Player target=#-1457779501` | Wild-mushroom pickup (this hash = the mushroom pickup, both times) |
| `[STATS] totalPurchased.Rice = 1` · `[TRIGGER] OnBuyItem Rice` | Purchase |
| `[DAMAGE] Damage 10 to WoodBranch … transitioning to final state` · `[STATS] totalDestroyed.… = 3` | Chopping/mining progress |
| `[REL] Otto chat value 1` · `friendship = 1` | Friendship change |
| `[STATS] game.CharactersMet = 4` · `[ACHIEVEMENT] …` | Counters (e.g. Meet Everyone) |
| `> lina_trade` · `> parker_showgeneralstore` · `> routine_sign` | Named interaction/performance started |
| `InventoryMenuViewModel closed without result` | A menu was cancelled |

- Filtered out as noise: focus/pause, iCloud/save chatter, GameCenter, discarded triggers, Unity memory lines.
- The file is recreated when the game restarts (previous run → `Player-prev.log`); `wf log` notices this.

## `./wf save`: exact state from the latest autosave (`Application Support/…/save/<gameId>/<n>.local`)
One summary: year/season/day/**time**, **money**, **stamina**/max, mana, **scene + position**, **active quests with goal
index + goal counters**, completed quests (day), **inventory with counts**, friendship values.
`./wf save --json` dumps the whole decoded save to `.shots/save.json` for `jq`/grep (characters, shops, stats,
notice-board quests, letters, recipes…).
- ⚠️ **Only as fresh as the last autosave.** The game saves when it goes to the background, but not every time
  (seen: 6–9 game-minute gaps, then none for 25 game-minutes). The first line says `(N min ago)`. For "did my
  action work", use the log; use the save for the totals (money, inventory, goal counters).
- Ids are signed CRC32 of internal names; `wf` decodes them with a name list built from the app's asset strings
  (`.shots/hashnames.tsv`, built once in ~25 s). A few stay `#123` (unknown).

## Internal quest names ↔ journal
The log/save use internal names, not the journal titles. Known so far (add to quest files' front matter as `id:` when seen):

| Internal | Quest |
|---|---|
| GrandmaNewGame | (intro, stays active) |
| GrandmaMushroom | The Fungus Among Us (done D3) |
| GrandmaLogging | Wood-n't You Know It? (done D3) |
| GrandmaPotato | From Bud To Spud |
| GrandmaFaveFood | Rice and Shine (2 goal counters: rice, mushrooms; started right after Logging) |
| GrandmaHerblore | Steeped in Mystery ❓ (only remaining active Gramma quest) |
| MayorMeetEveryone | The Most Elaborate Icebreaker |

## Not in the files (still need the screen)
Menus/shops/choices on screen, interaction bubbles, the tracker popup layout, exact position relative to objects,
cutscene vs dialogue mode. Use `./wf state` (cheap OCR) for those, `./wf look` only when position/icons matter.
