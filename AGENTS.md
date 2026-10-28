# AGENTS.md — playing Wylde Flowers on this Mac

**Goal:** minimal, sufficient docs so agents can pass the quests. Current phase: testing; **filling gaps beats winning**.

This repo is a toolkit for an AI agent to **play Wylde Flowers** (Apple Arcade macOS build, running full-screen,
UI language **English** since D4 (L48); older docs quote Russian UI strings, see `docs/ui/glossary.md`) and a **world model** of the game.

## Layout: progressive loading
Read **`docs/INDEX.md`** first (a short router), then only the index and the one file the current step needs.
Every detail file starts with a `> **Summary:**` line, so `head -8` is often enough.

| Path | What |
|---|---|
| `docs/INDEX.md` | Router: need → which index to open |
| `docs/progress.md` | **Current save state** + session log. Read at session start, update at session end |
| `docs/quests/INDEX.md` → `quests/<line>/<quest>.md` | All 131 quests by questline with status ▶️/✅/·; each file = wiki requirements (generated) + **verified steps** (written while playing) |
| `docs/mechanics/INDEX.md` → `mechanics/<topic>.md` | Game systems (time, energy, farming, fishing, shops, …); "(wiki)" vs "Verified in-game" sections |
| `docs/ui/INDEX.md` → `controls.md`, `hud.md`, `screens/<screen>.md`, `glossary.md` | What's on screen, how to recognise it (`wf state` mode), actions, exit; RU↔EN |
| `docs/world/INDEX.md` → `overview.md`, `characters.md`, `businesses.md`, `items/*.md` | Reference knowledge (generated from the wiki) |
| `docs/actions.md` | **Actions DB:** each action → recipe, **expected** hits/drops/energy, verify signal, fix. `./wf actions <tags>` prints a job's rows |
| `runs/*.jsonl` | **Run log per quest/task** (`./wf run start/attempt/issue/end`, auto: calls, Tara walks/actions, game events). `./wf run report` |
| `docs/self-improvement.md` | **Self-improvement loop**: act → capture → label from the game log → store disagreements → verify (`./wf learn`) → use. Bubble kinds learn automatically |
| `docs/learnings.md` | Surprises: expected vs actual → what changed |
| `reference/wiki/` | Full offline fan-wiki mirror (1190 pages, CC BY-SA). Search: `./wf wiki "<term>"` |
| `./wf` → `tools/wfc.py` → daemon `tools/wf.py serve` | CLI to observe/control the game. **`./wf stop` after editing wf.py** |
| `routes/*.txt` | Old keyboard routes (disabled, L54); landmarks in them still describe the way |
| `.claude/skills/` | `wylde-play` (main loop), `wylde-navigate`, `wylde-lookup`; generic `game-onboarding` (method for onboarding any game, with template scripts) |
| `.claude/skills/wylde-supervise/` | **How to play:** supervisor loop (main conversation) → one `wylde-quest` per goal |
| `.claude/agents/wylde-quest.md` | Quest agent (Sonnet): one goal, loads relevant docs, plans, records verified steps |
| `.claude/agents/wylde-runner.md` | Action agent (Haiku): executes one concrete step via `./wf`, text-only |
| `retros/` | Retrospectives (`/retro`) |
| `tools/gen_quests.py`, `gen_world_tables.py`, `build_reference.py`, `wikiclean.py` | Regenerate quests/world/reference (verified steps are preserved) |

## Setup facts (see docs/learnings.md L1–L5)
- Warp needs **Screen & System Audio Recording** and **Accessibility** (System Settings → Privacy & Security).
  `./wf status` must show both `true`. If it shows `false` or capture fails: `./wf stop` and retry first (stale daemon, L42).
- Run `./wf` commands that touch the game **outside the sandbox** (window server access).
- Python deps live in `.venv` (pyobjc Quartz/Vision/Cocoa, Pillow); `./wf` uses it automatically.
- The game runs **windowed 1600×900** (user's choice, L46). `wf` coordinates are always a virtual **1920×1080** frame
  (captures scaled, clicks mapped), whatever the window size. Input commands focus the game for the action only
  (~0.2 s), then return focus; a `do` ≈ 2.3 s.

## Playing = supervisor → quest agent → action agent
Always have **one current goal** (in `docs/progress.md`). The main conversation supervises (`wylde-supervise`):
choose the goal, dispatch `wylde-quest`, review, ask the user for decisions. The quest agent loads only the relevant
docs and drives steps through `wylde-runner`.
**Manifest protocol:** the parent gives the child every file/reference it needs (quest file + its `Read:` list). A child that
hits a gap stops safely and returns `need-help`; the parent fixes the docs/brief for now and the future, then resumes it.

## Rules of play
0. **Focus mode (user's choice, L47): the game stays in front** (`./wf focus-mode front`; check with `./wf focus-mode`).
   Game time RUNS between calls (Relaxed speed), so batch actions, think briefly, and watch the clock: Tara passes out at
   ~02:00 (L27). `./wf focus-mode background` = old mode: focus only during input, time frozen between calls (L28).
1. **One call per step:** `./wf do <actions> [--look]` acts, waits for the screen to settle and prints a one-line state.
   Observe with the game files first: `./wf log` (live events: quests, dialogue, scenes, pickups; input commands
   print new lines as `log: …`) and `./wf save` (exact money/time/quests/inventory as of the last autosave), see
   `docs/ui/game-files.md`. Then `./wf state` (text) → `./wf look` (small JPEG, then Read it) → `./wf shot` (full) only if needed.
   **Move only by clicking (L54, user rule):** `./wf do go:<x>:<y>` (click-to-move; the game pathfinds, L49) to a
   spot/object from a look. There is no keyboard fallback: `walk:`/`path:`/`route:`/`bubble:` are disabled. `NO MOVE`
   → click a nearer ground point; `ALREADY THERE` → act (Space).
2. **Small steps, no blind loops.** Never spam keys through cutscenes, dialogue or menus. `./wf advance` stops at
   anything unexpected.
3. **Don't change the user's settings** (language, game speed) or spend/sell/sleep through big decisions without
   asking, unless the user said so.
4. After each milestone, write the **verified steps** into that quest's file (`docs/quests/<line>/<quest>.md`), set its
   front-matter `status`/`ru`, re-run `python3 -I tools/gen_quests.py`, and update `docs/progress.md`.
5. When something differs from expectations, **log it in `docs/learnings.md`** and fix the affected doc/tool/skill
   in the same pass.
6. Prefer the hint button in the journal (**Show Hint**) for the actionable next step (L12).
