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
- `./wf state` → one line `mode | clock | money | bubble@x,y | text`. Modes: `gameplay` (HUD visible),
  `dialogue` (subtitle "Имя: …"), `popup` (quest card with Подтвердить), `cutscene` (letterbox), `overlay`
  (journal/map/menu/shop/inventory). `--json` for full detail.
- Need to see the scene (positions, icon bubbles, obstacles)? `./wf look` (960×540 JPEG) or
  `./wf look --crop X Y W H --scale 1` to zoom. Image→game coords: `game = offset + img / scale`.
- Full-res `./wf shot` only for fine detail.

**Decide**
- What is the current quest? `./wf key j`, then `./wf state` reads it. Get the actionable step with
  `./wf click-text "Показать подсказку"`, read it, then `./wf click-text OK --exact` and `./wf key escape`.
- Look up anything unknown: skill `wylde-lookup` (wiki, items, characters, shop hours).
- Open `docs/quests/INDEX.md` → the active quest's file. If it has **Verified steps**, follow them. Unknown screen?
  `docs/ui/INDEX.md` → the screen file. Unknown system? `docs/mechanics/INDEX.md` → the topic file.

**Act (one call per step)**
- `./wf do <actions…> [--look]`: actions `key:space` (Space = **interact**/confirm), `walk:<dir>:<s>`,
  `path:up:1,left:2`, `bubble:<dir>[:<max_s>]` (walk until an interaction bubble appears), `text:<label>`,
  `click:x:y`, `route:<name>`, `wait:<s>`. It prints the settled state, and the look path with `--look`.
- Interaction pattern: `./wf do bubble:<dir>` → see `bubble@x,y` → `./wf do key:space`.
- Dialogue/cutscene/quest popups: `./wf advance`. It presses Space only in dialogue/popup/cutscene and stops on
  anything else.
- Mechanical text-only loops (long dialogue, routes, repeated interactions): delegate to the **wylde-runner** agent
  (Haiku) with a goal + stop conditions; keep decisions here.

**Verify**: `./wf state` again. Did mode/text/money change as expected? If not, note it as a surprise (step 3).

## 2. Guardrails
- No blind loops: every scripted loop must check state and stop on anything unexpected.
- Ask the user before: changing settings/language, selling rare items, big purchases, sleeping/ending the day
  (unless told to play autonomously), romance or other irreversible story choices.
- Game time runs only while the game is frontmost (during `./wf` input commands) and stops in menus. Never use
  `WF_KEEP_FRONT=1` for long.

## 3. Record progress (mandatory)
- **Quest step done:** append to the quest file's `## Verified steps` (start state → exact commands → what appears, RU +
  EN → done-signal → gotchas). New quest seen: set front-matter `ru:` and `status: active`; finished: `status: done`.
  Then `python3 -I tools/gen_quests.py` (rebuilds the index, keeps your text).
- **New screen / HUD element / key:** add or extend `docs/ui/screens/<screen>.md` (Recognise · Elements · Actions ·
  Exit), `ui/hud.md`, `ui/controls.md` (✅/❓) and the index table; new strings go to `ui/glossary.md`.
- **Mechanic confirmed or contradicted:** edit its "Verified in-game" section in `docs/mechanics/<topic>.md`.
- **Session end:** update `docs/progress.md` (current state + one log row).
- **Surprise** (doc/wiki/assumption was wrong, tool misbehaved, unexpected UI): add a row to `docs/learnings.md`
  (expected → actual → now → updated), then fix the doc/tool/skill it affects.
- A walk that worked: save it as `routes/<from>-to-<to>.txt`.
