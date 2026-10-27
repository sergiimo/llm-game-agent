# Screen: journal

> **Summary:** Quest log: active quests list, description, hint.

## Recognise
Mode `overlay`; OCR title **To-Do** (≈(696,266)); open book graphic.

## Elements
- Left page: quest rows with questline icon (sprout = Gardening …).
- Right page: quest title, description, button **Show Hint** (Show hint ≈(1294,820)).
- The description may show a later/flavour line; **the hint is the actionable step** (learnings L12).

## Actions
- `./wf key j` opens; `./wf click-text "Show Hint"` → hint popup with **OK** (`./wf click-text OK --exact`).

## Exit
`J` toggles it closed (Esc sometimes doesn't right after a popup, L20).
