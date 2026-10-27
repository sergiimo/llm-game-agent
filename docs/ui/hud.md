# HUD

> **Summary:** top-left = pause button (game start), replaced by the **clock widget** (day + time) after the first quest
> popups; top-right = map (M), journal (J), inventory (I) with **coins** below. Prompts = icon bubbles near Tara.

| Element | Where (1920×1080) | Appears | `wf state` field |
|---|---|---|---|
| Pause button (Esc badge) | ≈(108,110) | game start → replaced by the clock | template `hud_pause` |
| Clock widget: analog clock + day/time panel ("Wednesday 1:00 pm") → [time](../mechanics/time-and-calendar.md) | top-left; clock centre ≈(116,116), text ≈(150–500, 25–115) | after the first farm quest popups | `clock` |
| Energy arc: orange arc right of the clock, starting at a ⚡ icon, over a pale track → [energy](../mechanics/energy.md) | ring r≈96 around (116,116), 82°→205° | with the clock | `energy` (⚡N%) |
| Small pause "II" button in the clock panel; a flower icon (season? ❓) | clock panel right edge | with the clock | — |
| Map button (M; orange "!" = quest target) | ≈(1520,110) (≈(1690,110) before inventory existed) | start | — |
| Journal button (J) | ≈(1660,110) (≈(1828,110) early) | start | template `hud_journal3` |
| Inventory button (I) + coin badge → [money](../mechanics/money-and-shops.md) | ≈(1815,110), coins ≈(1815,166) | after farm arrival | `money` (OCR misses it indoors ❓) |
| Prompt bubble | near Tara / target, y > 230 | when standing still next to an interactable | `bubble@x,y` |

Changes over time break templates: recalibrate with `./wf save-template <name>` from a clean gameplay frame (L22).
Day 1 = Monday, starts ~10:00. ~02:00 → pass-out ([screens/pass-out.md](screens/pass-out.md)).
