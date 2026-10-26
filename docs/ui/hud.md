# HUD

> **Summary:** top-left = pause button (game start), replaced by the **clock widget** (day + time) after the first quest
> popups; top-right = map (M), journal (J), inventory (I) with **coins** below. Prompts = icon bubbles near Tara.

| Element | Where (1920×1080) | Appears | `wf state` field |
|---|---|---|---|
| Pause button (Esc badge) | ≈(108,110) | game start → replaced by the clock | template `hud_pause` |
| Clock widget: analog clock + orange ring (energy? ❓) + "Понедельник 10:00" | top-left, text ≈(150–500, 25–115) | after the first farm quest popups | `clock` |
| Map button (M; orange "!" = quest target) | ≈(1520,110) (≈(1690,110) before inventory existed) | start | — |
| Journal button (J) | ≈(1660,110) (≈(1828,110) early) | start | template `hud_journal3` |
| Inventory button (I) + coins | ≈(1815,110), coins ≈(1815,166) | after farm arrival | `money` |
| Prompt bubble | near Tara / target, y > 230 | when standing still next to an interactable | `bubble@x,y` |

Changes over time break templates: recalibrate with `./wf save-template <name>` from a clean gameplay frame (L22).
Day 1 = Monday, starts ~10:00. ~02:00 → pass-out ([screens/pass-out.md](screens/pass-out.md)).
