# Screen: planting-panel

> **Summary:** Seed picker opened by interacting with an empty garden bed.

## Recognise
Camera zooms on the bed; left panel titled **Inventory** with tab **Seeds**.

## Elements
- Seed cards with counts (e.g. Potato Seeds ×1). Opens with the FIRST card highlighted (its name on screen, no Select yet, D183); clicking a card shows details (title, grow days, season) and **Select**. Counts are single digits sometimes: OCR misses them (L117).
- With no seeds: "Seeds can be bought at Lina's store." (buy seeds at Lina's store).

## Actions
- Click card (≈(110,540) for the first) → `./wf click-text Select` (EN ❓).

## Exit
Esc.
