---
name: wylde-play
description: Play Wylde Flowers on this Mac through ./wf — the observe→decide→act loop, cheap screen checks, advancing quests, and recording playbook notes and learnings. Use whenever asked to play, progress a quest, or do something in the game.
---

# Playing Wylde Flowers

Session start: read `AGENTS.md`, `docs/INDEX.md`, `docs/progress.md`. Then load progressively, only what the step
needs (index → one file; `head -8` gives the summary). The game UI is **Russian**; see `docs/ui/glossary.md`.

## 0. Preflight
```
./wf status          # running, permissions both true. Run outside the sandbox
```
If permissions are false, stop and ask the user to enable Warp in Screen Recording and Accessibility.

## 1. Loop: observe → decide → act → verify
**Golden rules:** **one `./wf do` call per step** (batch several actions in one `do` when you're confident: each
call pays a ~3–4 s focus switch) · the game stays **in the background** between calls, paused with time frozen.
`./wf` focuses it only while acting (L28).

**Observe (cheapest first)**
- **Game files (exact, no screenshot; `docs/ui/game-files.md`):** `./wf log` = new event-log lines (quest
  start/advance/complete, every dialogue line, building/scene changes, pickups, purchases, friendship). Input commands
  print them automatically as `log: …`. `./wf save` = day/time, money, stamina, scene, quest goal counters, inventory
  from the last autosave (may be minutes old). Read both at goal start; read the log after every action.
- `./wf state` → one line `mode | clock | money | bubble@x,y | text`. Modes: `gameplay` (HUD visible),
  `dialogue` (subtitle "Name: …"), `popup` (quest card with Confirm), `cutscene` (letterbox), `overlay`
  (journal/map/menu/shop/inventory). `--json` for full detail.
- Need to see the scene (positions, icon bubbles, obstacles)? `./wf look` (960×540 JPEG) or
  `./wf look --crop X Y W H --scale 1` to zoom. Image→game coords: `game = offset + img / scale`.
- Full-res `./wf shot` only for fine detail.

**Decide**
- What is the current quest? `./wf key j`, then `./wf state` reads it. Get the actionable step with
  `./wf click-text "Show Hint"`, read it, then `./wf click-text OK --exact` and `./wf key escape`.
- Look up anything unknown: skill `wylde-lookup` (wiki, items, characters, shop hours).
- Open `docs/quests/INDEX.md` → the active quest's file. If it has **Verified steps**, follow them. Unknown screen?
  `docs/ui/INDEX.md` → the screen file. Unknown system? `docs/mechanics/INDEX.md` → the topic file.

**Act (one call per step)**
- `./wf do <actions…> [--look]`: actions `go:<x>:<y>` (click-to-move: the **only** way to move, L54),
  `key:space` (Space = **interact**/confirm), `text:<label>`, `click:x:y`, `wait:<s>`, `still`. It prints the settled
  state, and the look path with `--look`.
- Interaction pattern: `./wf do go:<object x>:<y>` → see `bubble@x,y` → `./wf do key:space`.
- Dialogue/cutscene/quest popups: `./wf advance`. It presses Space only in dialogue/popup/cutscene and stops on
  anything else.
- Mechanical text-only loops (long dialogue, routes, repeated interactions): delegate to the **wylde-runner** agent
  (Haiku) with a goal + stop conditions; keep decisions here.

**Verify**: the `log:` lines first (`[QUEST]`, `[STATS]`, `grab_item`, …), then the state line. Did mode/text/money change as expected? If not, note it as a surprise (step 3).

## 2. Guardrails
- No blind loops: every scripted loop must check state and stop on anything unexpected.
- Ask the user before: changing settings/language, selling rare items, big purchases, sleeping/ending the day
  (unless told to play autonomously), romance or other irreversible story choices.
- Focus mode is the user's choice (`./wf focus-mode`). **front** (current): the game stays focused and game time runs
  between calls, so batch actions, keep thinking short, and watch the clock. **background**: time is frozen between calls.

## 3. Record progress (mandatory)
- **Quest step done:** append to the quest file's `## Verified steps` (start state → exact commands → what appears
  (exact on-screen text) → done-signal → gotchas). New quest seen: set front-matter `id:` (internal name from `./wf log`) and `status: active`; finished: `status: done`.
  Then `python3 -I tools/gen_quests.py` (rebuilds the index, keeps your text).
- **New screen / HUD element / key:** add or extend `docs/ui/screens/<screen>.md` (Recognise · Elements · Actions ·
  Exit), `ui/hud.md`, `ui/controls.md` (✅/❓) and the index table; new strings go to `ui/glossary.md`.
- **Mechanic confirmed or contradicted:** edit its "Verified in-game" section in `docs/mechanics/<topic>.md`.
- **Session end:** update `docs/progress.md` (current state + one log row).
- **Surprise** (doc/wiki/assumption was wrong, tool misbehaved, unexpected UI): add a row to `docs/learnings.md`
  (expected → actual → now → updated), then fix the doc/tool/skill it affects.
- A way that worked (landmarks + `go:` hops): add it to `docs/world/locations.md`.
