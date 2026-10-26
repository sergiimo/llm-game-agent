# Docs router (load this first, then ONLY what the current step needs)

| Need | Load |
|---|---|
| Where are we in the game right now? | [progress.md](progress.md) (current save state + session log) |
| What should I do next / quest steps | [quests/INDEX.md](quests/INDEX.md) → one quest file |
| How does a system work (time, energy, farming, fishing, shops…) | [mechanics/INDEX.md](mechanics/INDEX.md) → one mechanic |
| What is on screen / which key / how to exit a screen | [ui/INDEX.md](ui/INDEX.md) → controls, hud, one screen, glossary |
| Who/what/where (characters, shops+hours, items, recipes, story) | [world/INDEX.md](world/INDEX.md) → one table, or `./wf wiki "<term>"` |
| Something behaved unexpectedly | [learnings.md](learnings.md) (search it first, then add a row) |

Every detail file starts with a `> **Summary:**` line; read the top first (`head -8 <file>`) and go deeper only if needed.
