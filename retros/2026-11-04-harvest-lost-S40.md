# Stuck retro S40: engine harvest lost on the farm, D188 12:31

> **Summary:** the retry after S39 walked from the garden's west fence to the river and bridge, following bed
> detections in the grass, for 15+ clicks. The watcher only raised ALERTs and the supervisor waited. The user: "it's
> absolutely lost and we didn't notice it's multiple clicks for no progress. 2 - it didn't try a map a single time".

## Ledger first
- S39 (10 min earlier): the vision start question fires only when bed bubbles are in view: the far case was not covered.
- S37/S38: target identity by vision: not the issue here; this was navigation.

## Causes
1. The first two clicks were the new bed-to-bed walk from an *old* event position: in the garden every click reads a
   textless `overlay`, and `act.click` set the walk mark only in `gameplay`, so the stale event looked exact.
2. Nav's search order puts the target kind's detections before the map. Out in the wild the detector "saw" beds in
   grass and mushrooms on every frame; each walk to one was an arrival miss, and a new one always came. The map step
   (after detections) ran once, at the start.
3. Nothing measured progress: the stuck rule counts clicks that don't move her; these all moved her.
4. Map calibration is unusable (5 pairs disagree > 2 units): nothing could say she was far.
5. Supervision: ALERTs only; the supervisor read the frame after ~10 misses.

## Fixes (L160; tests: test_engine `Lost`, test_runwatch)
- Walk mark under a textless overlay (`act.on_card`).
- `nav.MISS_MAX` = 2 arrival misses in a row → detections off for the call, the map leads (explore too).
- `nav.BLIND_MAX` = 6 walks without an event or a bubble of the target kind = LOST → stop, one question.
- Map-led walks are measured on the map: the pin closer to the goal = progress; `MAP_FLAT` = 3 flat readings = LOST.
- Watcher: 4 arrival misses in a row or a LOST trace = **STOP** (the supervisor stops the child at once).
- Supervisor skill: two ALERTs of the same kind in a row → Read the newest frame at once.
- The engine reports an unusable map calibration in its notes.

## Open
- Recalibrate the map (5 disagreeing pairs): needs live positioned events + pins; a later live task.
