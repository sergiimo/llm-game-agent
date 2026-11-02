# Retro 5: routing continued despite a visible due-bed bubble

## Outcome
The reviewed west-gap teaching click moved Tara 2.5 units to `(-3.6,-21.7)`. The retry made no watering action and
asked for another route point. R1 remains 10/12, the can remains full, and the game is paused.

## Cause hypothesis and live result
The direct-object correction removed bubble use completely after one stale/misclassified case. The new frame appeared
to show blue water-drop bubbles nearby, so the fix required kind **and owner** to match a due bed. On live retry the
filter found only `beehive_progress`; the apparent water bubbles were the hive bubbles the user had corrected earlier.
The filter held and no wrong click occurred; navigation, not arrival, remained the blocker.

## Earlier fixes
- The taught gap point was safe and produced real movement, so retro-4's visual answer held.
- The exact stop held. The visual assumption that the bubble was a due bed did not; ownership evidence corrected it.

## Fix
Before routing, `water_next()` may click a water bubble only when its projected owner matches an exact bed in
`beds_due()`. A stale bubble owned by an already-watered bed is rejected; the action log still decides success.
