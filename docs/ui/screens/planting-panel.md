# Screen: planting-panel

> **Summary:** Seed picker opened by interacting with an empty garden bed.

## Recognise
Camera zooms on the bed; left panel titled **Inventory** with tab **Seeds**.

## Elements
- Seed cards with counts (e.g. Potato Seeds ×1). Opens with the FIRST card highlighted (its name on screen, no Select yet, D183); clicking a card shows details (title, grow days, season) and **Select**. Counts are single digits sometimes: OCR misses them (L117).
- D186 (camera zoomed on the bed): the panel sits at the left edge, partly cut; the highlighted card's name shows in a tooltip ("Tulip Bulbs"). Clicking it opens the card modal with **Select**. Read the card's name from the screen text, not the fixed title band (it read "ılbs", L143). The seed item for Tulip is "Tulip Bulbs" (`TulipSeed` in the save).
- The game logs `> plant … at (x, y, z)` for the bed when the panel is used, also when it is closed without planting ("InventoryMenuViewModel closed without result"); only `[STATS] totalPlanted.<Seed>` proves a planting (L143).
- With no seeds: "Seeds can be bought at Lina's store." (buy seeds at Lina's store).

## Actions
- Click card (≈(110,540) for the first) → `./wf click-text Select` (EN ❓).

## Exit
Esc.
