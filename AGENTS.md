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
| `runs/<YYYYMMDD-HHMM>-<task>/` | **One dir per task (L76), local and git-ignored:** `plan.md` (supervisor's step plan for the agent), `log.jsonl` (auto: calls, walks, game events; `./wf run step/attempt/issue/escalate/end`), `progress.md` (step timestamps + budget use), `retro-N.md`. `./wf run status` / `report`. Older runs: `runs/*.jsonl` |
| `tools/game/` | **Generic engine (L138): `./wf achieve <goal> k=v [answer=X]` (goals in `goals.json`, or a raw `{kind, where, make}` query); world graph from save + log (`world.py`, areas by distance; `./wf world kinds\|nodes\|status <Kind>` = readings with source + game time, CHECK = not read today), learned transition table (`actions.json`), one vision question (`ask.py`); framework `observe` → `act` → `learn` → `nav`.** **Proven primitives (L147)**: `smoke.plant_one/plant_visible/plant_garden/morning`, `smoke.fill_can`, `screen.py` (screen rules), `where.py` (position); `garden.water_all/replant_all/harvest_all/plant_all` = one-line goals; `ui.press/close`. Each proves itself from the game log and logs an action tree. `./wf py "<code>"`, `./wf call <module.fn> args`, `./wf run waits` |
| `tools/runtime/`, `tools/world/` | **Runtime evidence + world model (M1–M2, shadow)**: one game-log parser (`runtime/log.py`), actuators with a menu guard (`act.py`), the save (`save.py`); the world = entities (from log lines with positions), scene graph (networkx), costmap + A*, Tara's belief (Kalman), view. `./wf world [entities\|tara\|route X Z\|explain ID]`. **`tools/world/` coordinate model is superseded** by the object graph (spec 2026-10-31 §10 step 5: remove; don't extend). Identify targets from game-log `at (x, y, z)` lines instead (§13) |
| `tools/objects/` | **Objects by appearance (spec 2026-10-31)**: per-kind vector store of labelled crops (`db/<kind>/`) + detection (DINOv2 patch heatmaps, one pass per frame, per-kind calibrated z thresholds, zoom-invariant). `./wf objects list\|add <kind> x0 y0 x1 y1 [state]\|detect [kinds]\|find <kind>\|eval\|calibrate\|reembed`; reads the frame only, no input. **Object graph with nested regions** (`graph.py`, `query.py`, `regions.py`, `views.py`, `graph/Farm.json`): Farm ⊃ House, Garden ⊃ beds/hives/well; `./wf graph show\|where\|path <Kind> [k=v]\|view-add <region>` (frame only, no input). `./wf graph sync` applies the game log to node states (the old object loop was removed; objects and their state live in the engine's world graph, `game/world.py`) |
| `tools/evals/`, `tools/bench/` | **Eval + benchmark (M0, spec 2026-10-30)**: every prediction's hit/miss per component (`./wf eval`, `./wf eval mark <id> hit\|miss`); fixed benchmark tasks A garden day, B trips, C NPC (`./wf bench start\|report\|compare`) |
| `docs/self-improvement.md` | **Self-improvement loop**: act → capture → label from the game log → store disagreements → verify (`./wf learn`) → use. Bubble kinds learn automatically |
| `docs/routines.md` | **Daily chores** (water garden, harvest…): `./wf routines` = today's status from save + log; do DUE ones before quests |
| `docs/learnings.md` | Surprises: expected vs actual → what changed |
| `reference/wiki/` | Full offline fan-wiki mirror (1190 pages, CC BY-SA). Search: `./wf wiki "<term>"` |
| `./wf` → `tools/wfc.py` → daemon `tools/wf.py serve` | CLI to observe/control the game. **`./wf stop` after editing wf.py** |
| `routes/*.txt` | Old keyboard routes (disabled, L54); landmarks in them still describe the way |
| `.claude/skills/` | `wylde-play` (main loop), `wylde-navigate`, `wylde-lookup`; generic `game-onboarding` (method for onboarding any game, with template scripts) |
| `.claude/skills/wylde-supervise/` | **How to play:** supervisor loop (main conversation) → one `wylde-quest` per goal |
| `.claude/agents/wylde-quest.md` | Quest agent (cheapest model): one goal, loads relevant docs, plans, records verified steps |
| `.claude/agents/wylde-runner.md` | Action agent (cheapest model): executes one concrete step via `./wf`, text-only |
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
**User model preference (2026-11-01): every spawned gameplay agent uses the cheapest available model** unless the user
explicitly requests another one (Codex: `gpt-6-luna` low; Claude: `haiku`). Do not inherit the supervisor model.
**Manifest protocol:** the parent gives the child every file/reference it needs (quest file + its `Read:` list). A child that
hits a gap stops safely and returns `need-help`; the parent fixes the docs/brief for now and the future, then resumes it.

## Rules of play
0. **Focus mode (user's choice, L47): the game stays in front** (`./wf focus-mode front`; check with `./wf focus-mode`).
   Game time RUNS between calls (Relaxed speed), so batch actions, think briefly, and watch the clock: Tara passes out at
   ~02:00 (L27). `./wf focus-mode background` = old mode: focus only during input, time frozen between calls (L28).
   **Before any off-game work (coding, docs, long thinking) `./wf pause`** and `./wf resume` after: 1 real minute ≈ 100
   game minutes, so 10 minutes of coding = a passed-out night (L63). **After 23:00 game time: no optional work**
   (exploring, `wf improve`); finish the step and ask about bed (`improve` stops by itself).
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
   asking, unless the user said so ("pass quest X" = sleeping as many nights as it needs is approved).
4. After each milestone, write the **verified steps** into that quest's file (`docs/quests/<line>/<quest>.md`), set its
   front-matter `status`/`ru`, re-run `python3 -I tools/gen_quests.py`, and update `docs/progress.md`.
5. When something differs from expectations, **log it in `docs/learnings.md`** and fix the affected doc/tool/skill
   in the same pass.
6. Prefer the hint button in the journal (**Show Hint**) for the actionable next step (L12).
7. **Every task runs from a plan (L76):** `./wf run start` → `runs/<YYYYMMDD-HHMM>-<task>/plan.md`, written and reviewed
   by the supervisor, shown to the user, followed by the agent step by step (`./wf run step N start|done`, timestamps in
   `progress.md`). A step over its budget or stuck → `./wf run escalate N` → stuck retro → plan fixed from step N.
   **Stuck = Tara's position changes < 2 units over 3 moves while not at the goal (L75).** Every stuck episode gets a
   **stuck retro**: read `retros/stuck-ledger.md` first (did earlier fixes hold?), add a row, save the retro in
   `retros/`; a cause that repeats gets a tool fix. Aim: fewer stuck episodes per trip.
8. **One game command per tool call** (never `wf stop; wf resume; wf goto` in one call): a rejected call may already
   have run its first commands. After any rejection: `tail -3 .shots/actions.log`, then `./wf pause` if needed.
   wfc refuses an input command chained with another ./wf call.
9. **Uncertainty → model vision, always (user, D183).** Game functions never fail blind: any `Failed` carries
   `NEED_VISION: look at <png>: <question>` (`core.ask_vision`, frame taken at the innermost failure, before menus
   close). Agents Read it before reporting a cause or deciding; code that can't tell (unknown icon, unread card, no
   proof) asks vision, it doesn't guess.
10. **Interaction laws (user, D183; `docs/mechanics/interaction-laws.md`):** Tara is always at the frame centre (never
   ask where she is); a click on a visible object is reliable, so vision's only start question is "click point of the first
   node"; record every click result (log, card, bubbles, short-lived text) and update state from it; click every fitting
   bubble until none is left, then ask again. No layouts or positions carried between steps; failure = close cards + fresh frame.
   **Chores and object goals run on the engine (L138):** `./wf achieve <goal> k=v` (`./wf world kinds` = what exists);
   **foraging (rocks, trees, drops, forage plants) is pure vision, never graph nodes (L158, spec §13):** `./wf forage
   chop|rock|pickup|forage` → one `NEED_VISION click` per target → `answer=<cell>|walk:<cell>|none`;
   `NEED_VISION click|button|name` → call again with `answer=…`; `NEED_INPUT <goal>: <param>?` → ask the user or answer from
   the task text (never default it).
