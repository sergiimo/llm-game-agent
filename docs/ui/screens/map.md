# Screen: map

> **Summary:** Illustrated island map with the quest route.

## Recognise
Mode `map`; large painted island in a pale paper frame with a pink position pin; little or no OCR text.
The ordinary circular HUD map icon/`M` hotkey is gameplay, not the map screen. Pin-colored world scenery alone
does not prove the modal; its large four-sided paper frame must also be present. World clicks remain blocked on it.

## Elements
- Pink pin = Tara. Dotted line = route to the current quest target. Unvisited areas covered by clouds.

## Actions
- Long-distance navigation must use and learn this map first. Inspect the pin, destination/landmark candidates and
  road connections; retain source-frame references and record observations/uncertainties in versioned decision
  rationale. Consolidate verified route knowledge after milestones. Visible-road-only travel is local approach or
  fallback after captured unavailable/insufficient map evidence; refused requests do not prove that limitation.
- Use the active `play` turn with `action:{kind:"key",label:"m",expects:{mode:"map"}}`, for example:

  ```sh
  ./wf play turn_id=7 answer='{"kind":"act","action":{"kind":"key","label":"m","expects":{"mode":"map"}}}'
  ```

  Replace `7` with the current NEXT version. Inspect the full-size returned frame. `key` is the action kind;
  the value goes in `label`. `{kind:"key",key:"m"}` and `press M` in gameplay are guard refusals, not map attempts.
  A refusal performs zero inputs. Map availability remains unproved until a correctly issued action is observed.

## Exit
One versioned `close` action only after the map is recognized; then inspect the next frame.
