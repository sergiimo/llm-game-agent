# D209 legacy Bed-route failure

> **Summary:** House entry is proven; Bed arrival and sleep are not. The universal outcome comparison stops after the captured no-move. Fresh model vision must supply the missing clue.

Source (preserved byte-for-byte):
`/Users/serg/w/.worktrees/llm-game-agent-model-owned-loop/runs/20261106-2027-model-owned-south-garden/`.
`tools/fixtures/play/enter-house-sleep.json` retains the exact source rows/experiences/frame paths. It excludes the four later offline bookkeeping rows documented by Task 1.

The game emitted `OnEnterBuilding House` at D209 18:38. Subsequent legacy navigation went east; the Bed search reported `map: no direction`. Answers `walk:E9`, `walk:B15`, `walk:H12` had no game events and `moved=false` on an overlay. Their legacy path emitted no universal surprise. The captured card immediately before the sleep attempt was a growing Tulip card, not a Bed card. No sleep event exists in this evidence.

Task 2 preflight reads the committed graph: Bed belongs to House, with no House→Bed directional edge. `tools/objects/db/Bed` is absent at preflight; this does not prove its historical state at every failed click. Exact position deltas are unavailable, so the three failed clicks are not claimed to meet the numerical L75 threshold.

The offline public-boundary replay normalizes the legacy textless overlay with the real screen classifier, then feeds the captured click and raw no-move evidence through `play.turn`. It emits one physical-boundary test input, returns `no_progress`, blocks a second action, records a model `look`, then accepts an explicit gap correction. No production change is justified: Task 1 already supplies that behavior.

The legacy JPEG paths listed by the three experiences are missing on disk. The last surviving `.shots/ask_frame.png` was copied at full scale to `tools/fixtures/play/legacy-bed-last-ask.png` before live work can overwrite it. Model vision sees Tara beside Gramma’s purple bed, with the pink west bed off-frame. Its HUD is 18:50; exact association with earlier click frames is unavailable. Thus the legacy `overlay` label is retained as raw data, not claimed as proof of a visible modal.

Live closure remains pending: read a fresh full-scale frame, identify Tara’s pink west bed and its road, sample its appearance or correct an actual named graph relation with provenance, then prove `sleep_transition`. Do not treat a gap correction as the missing successful mapping. The fresh acceptance run, not this legacy trace, must prove that path.
