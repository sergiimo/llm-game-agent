# Stuck retro: replant selected a hive at the garden boundary

> **Summary:** the direct map route reached the correct garden/bed area, but `garden.unplant()` blindly pressed the
> highlighted interaction after walking; that interaction belonged to a neighbouring hive. No bed changed.

- Earlier fixes S9–S12 correctly made far navigation stop instead of endlessly pushing through the hive row, but did
  not make the final interaction target-specific.
- Evidence: route ended around `(7.78,-25.32)`; replant then moved Tara to `(0.84,-27.34)`, between the bed rows. The
  only action logs were two `beehive_progress` events at `(5.22,-23.46)`; there was no `unplant` or `unplant_impl`.
- Cause: `unplant()` called generic `ui.press_bubble()` after `goto(b)`, so a highlighted neighbouring bubble could win.
- Fix: prefer an exact owned `unplant` bubble, then click the projected bed body. If other bubbles are visible but none
  belongs to the bed, stop. Require exact-position `> unplant` before opening/confirming Remove.
- Verification: `tools.test_game` covers an incompatible highlighted hive bubble; combined focused suite 60/60 passes.

## Follow-up (replant-wilted-3): wrong bed after a successful unplant
- The S-fix above held for the hive (no `beehive_progress`), and OCR probing correctly unplanted bed 7.
- New wrong-target case: `plant(bed 7)` matched bed 8's unknown bubble via a ±1 belief centred on bed 7 → bed 8's Remove
  card opened (closed, nothing removed). Fix: exact reading before target matching (L114), no Space with foreign bubbles,
  wrong-bed `> unplant` detection in `plant()`.
