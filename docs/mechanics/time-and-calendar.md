# Time And Calendar

> **Summary:** Clock runs in 10-min ticks; weekdays gate shop hours; the day ends by sleeping or by passing out at ~02:00.

## Rules
- Day speed (Settings → Скорость дня): Relaxed 10 game-min = 20 s · Normal 10 game-min = 6 s ≈ 1 h 40 min per real minute · **Relaxed (current since Tue d2) 10 game-min = 20 s ≈ 30 min per real minute** · Challenging 10 game-min = 5 s.
- Weekdays matter: most shops close 1–3 days/week ([../world/businesses.md](../world/businesses.md)).
- Sleeping in bed ends the day. Staying up until ~02:00 → pass-out popup and next morning (possible sickness warning).
- Crafting stations and crops progress with game time (compost → soil 24 h, potato 5 days).
## Verified in-game
- Day 1 = **Monday**, clock appears ~10:00 after the first farm quest popups.
- **Time freezes while the game is not the frontmost app** (L28). It runs only while `./wf` is acting.
- Pass-out at ~02:00 observed (L27); next day Tuesday ~11:40 after the user dismissed it.
- Voluntary sleep at 20:20 (Tuesday) -> woke Среда 07:00 (day 3) with a story cutscene; overnight quest step 2 (soup) became available from Gramma.

## How to see
Clock widget top-left: day name + time ([../ui/hud.md](../ui/hud.md)).

## How to read
`./wf state` → `clock` (e.g. "Среда 13:00").
