# Actions DB (what to do → what must happen)

> **Summary:** every in-game action as one row: the exact command recipe, the **expected outcome** (hits, drops, energy,
> game time) and the **verify** signal. Agents get only the rows for their job: `./wf actions <tag> [tag…]` (`--all` =
> every tag must match). A quest brief lists the tags under **Actions:**.
> **Rule:** after each action, compare the result with **Expect**. If they differ (fewer drops picked, more hits, no
> log line), apply **If not** before the next target, and report the difference as a `[docs]` gap so the row gets fixed.

**Waiting:** `still[:max_s]` waits until Tara's own action/walk ends (tracker, L52), so it can replace fixed `wait:` after a
swing (`key:space still`), ❓ not yet measured on swings. `go:` already returns when she stops.
Approach any target first: `go:` onto its base point → `bubble@` appears ([mechanics/basic-actions.md](mechanics/basic-actions.md#approach-a-target-any-object)).
Energy % = share of the bar (200 stamina on the D144 save). Hits assume **copper** tools (30 damage); rusty = 10 damage →
3× the hits. HP comes from the log line `[DAMAGE] … (damage = N), … destroying`.

Tags: `chop` `rock` `pickup` `forage` `farming` `water` `eat` `sleep` `talk` `shop` `buy` `sell` `smelt` `build` `inventory` `fish`

| ID | Action | Tags | Do | Expect | Verify | If not | Status |
|---|---|---|---|---|---|---|---|
| A1 | Chop tree (pine/oak) | chop | `go:` trunk base → axe bubble → `key:space wait:1` ×4 | HP 100 → **4 hits** (copper). **5–8 Wood** scattered around. ~16% ⚡, ~1 game h incl. pickup | log `TreePine … destroying` + `totalDestroyed.TreePine` | no `destroying` after 4 hits: look (missed swings during animation, or the bubble was another object) | ✅ D144 |
| A2 | Chop branch / fallen log | chop | `go:` onto it → axe bubble → `key:space wait:1` ×N | branch HP 30 → 1 hit (copper), 3 hits (rusty) → 1 Wood. Log ~3–4 hits (rusty) → several Wood + sticks | log `WoodBranch … destroying` | — | ✅ D3/D144 |
| A3 | Break small rock | rock | `go:` rock base → pickaxe bubble → `key:space wait:1.5` ×2 | HP 45 → **2 hits** → **1–2 Stone**. ~10% ⚡ | log `StoneRock … destroying` | no bubble = decoration rock (by the house/hedge, cliffs): skip it | ✅ D144 |
| A4 | Break boulder | rock | `go:` boulder base → pickaxe bubble → `key:space wait:1.5` ×8 | HP 240 → **8 hits** → **~10 Stone** (+ sometimes a recipe popup: `./wf advance`). ~50% ⚡ | log `StoneBoulder … destroying` | — | ✅ D144 |
| A5 | Pick up drops (after A1–A4) | pickup, chop, rock, forage | **look, count the drops** (= expected gain) → for each: `go:` onto it → **only if the bubble is the bag/"+"**: `key:space` | tracker/inventory **+1 per drop**; all counted drops gone from the ground. Free (0 ⚡) | log `grab_item … Stone(Clone)` / `#1705624119` (Wood) per pickup; tracker toast "N / 50 Stone" | Space fires the **nearest** bubble: next to a tree/rock it swings the tool (wastes ⚡, can faint you). `go:` onto the drop from the side away from the tree/rock until the bag bubble shows. **Don't leave while counted drops remain** (retro 2026-10-27: ~7 Stone left by the ranch) | ✅ D144 |
| A6 | Forage plant (mushroom, thistle…) | forage, pickup | `go:` onto it → bag/"+" bubble → `key:space` | +1 item; free | log `grab_item` + toast/tracker ("Mushroom: 2/2") | a "+" bubble can be **another plant**: check the log before counting | ✅ D2 |
| A7 | Fill watering can | water, farming | the well (can bubble) → `key:space` | can filled | log / can icon | — | ✅ D1 |
| A8 | Water a bed | water, farming | planted bed (potato + drop bubble) → `key:space` | 1 fill waters a bed; ⚡ small | bed turns dark | refill at the well (A7) | ✅ D2 |
| A9 | Plant seeds | farming | empty bed (sprout bubble) → Space → planting panel → seed card → **Select (EN ❓)** | seed −1, bed planted | bed shows the seed | — | ✅ D1 |
| A10 | Eat / drink (food) | eat, inventory | `key:i wait:1` → Food card (first card: `click:225:262`) `wait:1` → `text:Drink` / `text:Eat` `wait:1` → `key:escape wait:1 key:escape` | item −1. **Restorative Tea +~43% ⚡**; Cream of Mushroom Soup: part of the bar | log `totalConsumed.<Item>`; ⚡ in `./wf state` | the first card changes when an item runs out: look before repeating blindly. Eat only per `./wf tips food` | ✅ D3/D144 |
| A11 | Sleep | sleep | bed (zzz bubble) → `key:space` → `text:Yes` | next day 7:00, full ⚡ | log `Spawning player at Farm/Bed`, `OnDayStarted` | needs approval (ask the user) | ✅ D3/D144 |
| A12 | Talk / give / quest hand-in | talk | NPC standing still with bubble → `key:space` → interaction menu → the "!" topic (highlighted) → `key:space` → `./wf advance` → **one** `key:escape`, then check state | first talk: `[STATS] game.CharactersMet = N+1`, `[REL] <Name> friendship = 1` | `./wf log` | 2nd Escape opens the pause menu. `advance` may pick a dialogue choice (tools/TODO.md): on choices, choose yourself | ✅ D3/D4 |
| A13 | Buy in a shop | shop, buy | shopkeeper → coin icon → Space → click the item card → Space ("Buy (1)") → `key:escape` ×2 ([ui/screens/shop.md](ui/screens/shop.md)) | money −price, item +1 | `./wf save` money/inventory | needs approval | ✅ D3 |
| A14 | Sell in a shop | shop, sell | shopkeeper bubble → `key:space` → icon menu (talk, gift, coin) → `key:right key:right key:space` → shop opens on the BUY tab → click the 2nd left tab (sack, `click:70:237`) = SELL → click the item card → popup "Sell 1": ▶ (+1) ▶▶ (+10) ▶\| (max) → click **Sell N** → `key:escape` ×2 | money + N × price (Mushroom Risotto 20c at Sophia) | log `<Shop> sell Nx <Item> for $X`, `[STATS] totalSold.<Item>` | needs approval. A 3rd Escape opens the pause menu | ✅ D145 (Sophia) |
| A16 | Smelt ore at Natalia (Blacksmith) | shop, smelt | Natalia's bubble → `key:space` → icons (talk, gift, coin) → `key:right key:right key:space` → "Blacksmith" window (hammer tab) → ingot card (Iron = 1st, `click:217:237`) → popup: ▶ +1, ▶▶ +10 → **Craft N** → `key:escape` ×2 | per ingot: 2 ore + 5c (iron); instant | log `craft Nx Iron`, toast "N Iron Ingot" | Natalia closed Thu, Sun | ✅ D145 |
| A17 | Build at Parker (Nailed It!) = quest hand-in for building quests | shop, build | Parker standing still (he walks while sweeping; Emmi/Finn nearby have their own talk bubbles) → his bubble → `key:space` → icons (talk, gift, **blueprint**) → the 3rd icon → blueprint list → item (e.g. Ranch) → **Build** | coins + materials taken; Parker: "Should only take a day or so!"; popup "<Quest> / Wait for Parker to finish building …" | log `craft 1x <Thing>`, `[QUEST] Advance quest <Id> to goal 1` | the talk icon is only banter, there's no "!" topic. Needs approval (spends) | ✅ D145 |
| A15 | Fish | fish | fishing spot (sign with a fish; ripples) | ❓ | ❓ | rod from Bruno + bait | ❓ |
