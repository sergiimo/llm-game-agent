# Docs router (load this first, then ONLY what the current step needs)

| Need | Load |
|---|---|
| Where are we in the game right now? | [progress.md](progress.md) (current save state + session log) |
| What should I do next / quest steps | [quests/INDEX.md](quests/INDEX.md) → one quest file |
| How do I do an action / use a tool (chop, water, mine, fish, eat, talk, sleep) | [mechanics/basic-actions.md](mechanics/basic-actions.md) |
| Where is something (area, resource, shop, person) | [world/locations.md](world/locations.md), then quest notes, then map `M` |
| How does a system work (time, energy, farming, fishing, shops…) | [mechanics/INDEX.md](mechanics/INDEX.md) → one mechanic |
| What is on screen / which key / how to exit a screen | [ui/INDEX.md](ui/INDEX.md) → controls, hud, one screen, glossary |
| Who/what/where (characters, shops+hours, items, recipes, story) | [world/INDEX.md](world/INDEX.md) → one table, or `./wf wiki "<term>"` |
| How did past agent runs go / what to tune | [agent-runs.md](agent-runs.md), `tools/TODO.md`, `retros/` |
| What's the smart way to do X (eat vs sleep, when to chop/mine, money…) | [tips.md](tips.md) → `./wf tips <tag>` |
| Something behaved unexpectedly | [learnings.md](learnings.md) (search it first, then add a row) |

Every detail file starts with a `> **Summary:**` line; read the top first (`head -8 <file>`) and go deeper only if needed.

## Conventions (keep docs minimal, one home per fact)
- **A game concept (energy, money, time, magic, hearts, season…) has ONE home: `mechanics/<concept>.md`**, with sections:
  `Summary` · `Rules` (wiki, unverified) · `Strategy` (only a pointer: `./wf tips <concept>`) · `How to see` (link to its
  `ui/hud.md` row) · `How to read` (the `./wf state` field, or "not readable yet") · `Verified in-game`.
- **All strategy/tips live in ONE table, [tips.md](tips.md)** (ID · tip · tags · source user/verified/wiki ❓ · links).
  Find them with `./wf tips <tag…>`. Quest briefs list the tags to load. Trust: user > verified > wiki.
- `ui/hud.md` holds only the **visual** (position, look) plus a link to the concept file. No rules there.
- Measurable concepts get a `./wf state` field (`clock`, `money`, `energy ⚡N%`, …).
- Facts are linked, not copied. A quest brief links to concept/action/location files instead of repeating them.
- Unverified = ❓; verified = ✅ with the day it was seen; wrong = ✏️ crossed out with the correction.
