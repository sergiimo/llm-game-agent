# AGENTS.md — playing Wylde Flowers on this Mac

**Goal:** minimal, sufficient docs so agents can pass the quests. Current phase: testing; **filling gaps beats winning**.

This repo is a toolkit for an AI agent to **play Wylde Flowers** (Apple Arcade macOS build, running full-screen,
UI language **English** since D4 (L48); older docs quote Russian UI strings, see `docs/ui/glossary.md`) and a **world model** of the game.

## Layout: progressive loading
Read **`wiki/INDEX.md`** for game knowledge or **`docs/INDEX.md`** for app operations (a short router), then only the index and the one file the current step needs.
Every detail file starts with a `> **Summary:**` line, so `head -8` is often enough.

| Path | What |
|---|---|
| `docs/INDEX.md` | Router: need → which index to open |
| `wiki/quests/INDEX.md` → `quests/<line>/<quest>.md` | All 131 quests by questline with status ▶️/✅/·; each file = wiki requirements (generated) + **verified steps** (written while playing) |
| `wiki/mechanics/INDEX.md` → `mechanics/<topic>.md` | Game systems (time, energy, farming, fishing, shops, …); "(wiki)" vs "Verified in-game" sections |
| `docs/ui/INDEX.md` → `controls.md`, `hud.md`, `screens/<screen>.md`, `glossary.md` | What's on screen, how to recognise it (`wf state` mode), actions, exit; RU↔EN |
| `wiki/INDEX.md` → topical mechanics, quests, characters, places, businesses, items, story, and tips | Reference knowledge (generated from the wiki) |
| `docs/operations/actions.md` | **Actions DB:** each action → recipe, **expected** hits/drops/energy, verify signal, fix. `./wf actions <tags>` prints a job's rows |
| `runs/<YYYYMMDD-HHMM>-<task>/` | **One dir per task (L76), local and git-ignored:** `plan.md` (supervisor's step plan for the agent), `log.jsonl` (auto: calls, walks, game events; `./wf run step/attempt/issue/escalate/end`), `progress.md` (step timestamps + budget use), `retro-N.md`. `./wf run status` / `report`. Older runs: `runs/*.jsonl` |
| `tools/game/` | **Generic engine (L138): `./wf achieve <goal> k=v [answer=X]` (goals in `goals.json`, or a raw `{kind, where, make}` query); world graph from save + log (`world.py`, areas by distance; `./wf world kinds\|nodes\|status <Kind>` = readings with source + game time, CHECK = not read today), learned transition table (`actions.json`), one vision question (`ask.py`); framework `observe` → `act` → `learn` → `nav`.** **Proven primitives (L147)**: `smoke.plant_one/plant_visible/plant_garden/morning`, `smoke.fill_can`, `screen.py` (screen rules), `where.py` (position); `garden.water_all/replant_all/harvest_all/plant_all` = one-line goals; `ui.press/close`. Each proves itself from the game log and logs an action tree. `./wf py "<code>"`, `./wf call <module.fn> args`, `./wf run waits`. **Improvement loop (spec 2026-11-04, L161):** every action = one immutable experience (`experience.py`) through one boundary (`integrate.py`: world facts → evals → memory → transitions → gap bundles; idempotent replay); `./wf gaps` = escalations for the offline code factory |
| `tools/runtime/`, `tools/world/` | **Runtime evidence + world model (M1–M2, shadow)**: one game-log parser (`runtime/log.py`), actuators with a menu guard (`act.py`), the save (`save.py`); the world = entities (from log lines with positions), scene graph (networkx), costmap + A*, Tara's belief (Kalman), view. `./wf world [entities\|tara\|route X Z\|explain ID]`. **`tools/world/` coordinate model is superseded** by the object graph (spec 2026-10-31 §10 step 5: remove; don't extend). Identify targets from game-log `at (x, y, z)` lines instead (§13) |
| `tools/objects/` | **Objects by appearance (spec 2026-10-31)**: per-kind vector store of labelled crops (`db/<kind>/`) + detection (DINOv2 patch heatmaps, one pass per frame, per-kind calibrated z thresholds, zoom-invariant). `./wf objects list\|add <kind> x0 y0 x1 y1 [state]\|detect [kinds]\|find <kind>\|eval\|calibrate\|reembed`; reads the frame only, no input. **Object graph with nested regions** (`graph.py`, `query.py`, `regions.py`, `views.py`, `graph/Farm.json`): Farm ⊃ House, Garden ⊃ beds/hives/well; `./wf graph show\|where\|path <Kind> [k=v]\|view-add <region>` (frame only, no input). `./wf graph sync` applies the game log to node states (the old object loop was removed; objects and their state live in the engine's world graph, `game/world.py`) |
| `tools/evals/`, `tools/bench/` | **Eval + benchmark (M0, spec 2026-10-30)**: every prediction's hit/miss per component (`./wf eval`, `./wf eval mark <id> hit\|miss`); fixed benchmark tasks A garden day, B trips, C NPC (`./wf bench start\|report\|compare`) |
| `docs/architecture/self-improvement.md` | **Self-improvement loop**: act → capture → label from the game log → store disagreements → verify (`./wf learn`) → use. Bubble kinds learn automatically |
| `docs/operations/routines.md` | **Daily chores** (water garden, harvest…): `./wf routines` = today's status from save + log; do DUE ones before quests |
| `docs/troubleshooting/INDEX.md` | Current setup and recovery guidance; integrate surprises into their canonical Wiki or Docs page |
| `wiki/` | Joint topical game Wiki: imported fan-wiki facts plus verified mechanics and tips (CC BY-SA attribution retained). Search: `./wf wiki "<term>"` |
| `./wf` → `tools/wfc.py` → daemon `tools/wf.py serve` | CLI to observe/control the game. **`./wf stop` after editing wf.py** |
| `routes/*.txt` | Old keyboard routes (disabled, L54); landmarks in them still describe the way |
| `.claude/skills/` | `wylde-play` (main loop), `wylde-navigate`, `wylde-lookup`; generic `game-onboarding` (method for onboarding any game, with template scripts) |
| `.claude/skills/wylde-supervise/` | **How to play:** supervisor loop (main conversation) → one `wylde-quest` per goal |
| `.claude/agents/wylde-quest.md` | Quest agent (cheapest model): one goal, loads relevant docs, plans, records verified steps |
| `.claude/agents/wylde-runner.md` | Action agent (cheapest model): executes one concrete step via `./wf`, text-only |
| `retros/` | Retrospectives (`/retro`) |
| `tools/gen_quests.py`, `gen_world_tables.py`, `build_reference.py`, `wikiclean.py` | Regenerate quests/world/reference (verified steps are preserved) |

## Setup facts (see docs/troubleshooting/INDEX.md L1–L5)
- Warp needs **Screen & System Audio Recording** and **Accessibility** (System Settings → Privacy & Security).
  `./wf status` must show both `true`. If it shows `false` or capture fails: `./wf stop` and retry first (stale daemon, L42).
- Run `./wf` commands that touch the game **outside the sandbox** (window server access).
- Python deps live in `.venv` (pyobjc Quartz/Vision/Cocoa, Pillow); `./wf` uses it automatically.
- The game runs **windowed 1600×900** (user's choice, L46). `wf` coordinates are always a virtual **1920×1080** frame
  (captures scaled, clicks mapped), whatever the window size. Input commands focus the game for the action only
  (~0.2 s), then return focus; a `do` ≈ 2.3 s.

## Playing = supervisor → quest agent → action agent
Always have **one current goal** in the active run plan. The main conversation supervises (`wylde-supervise`):
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
   **For off-game work (coding, docs, long thinking), let the game lose focus; unfocus freezes game time. Do not issue
   `./wf pause` merely for thinking**, because it creates a gameplay modal that later needs a model-owned Resume action.
   **After 23:00 game time: no optional work**
   (exploring, `wf improve`); finish the step and ask about bed (`improve` stops by itself).
   **Before every new gameplay task, check the exact game clock. If it is later than 19:00, sleep and advance to the
   next day before starting the task** (user standing rule, 2026-11-06; this sleep is pre-approved).
1. **One call per step:** `./wf do <actions> [--look]` acts, waits for the screen to settle and prints a one-line state.
   Observe with the game files first: `./wf log` (live events: quests, dialogue, scenes, pickups; input commands
   print new lines as `log: …`) and `./wf save` (exact money/time/quests/inventory as of the last autosave), see
   `docs/ui/game-files.md`. Then `./wf state` (text) → `./wf look` (full-scale JPEG, then Read it; **every screenshot and vision image is full scale**, user D188: small copies made the map unreadable).
   **Move only by clicking (L54, user rule):** `./wf do go:<x>:<y>` (click-to-move; the game pathfinds, L49) to a
   spot/object from a look. There is no keyboard fallback: `walk:`/`path:`/`route:`/`bubble:` are disabled. `NO MOVE`
   → click a nearer ground point; `ALREADY THERE` → act (Space).
2. **Small steps, no blind loops.** Never spam keys through cutscenes, dialogue or menus. `./wf advance` stops at
   anything unexpected.
3. **Don't change the user's settings** (language, game speed) or spend/sell/sleep through big decisions without
   asking, unless the user said so ("pass quest X" = sleeping as many nights as it needs is approved).
4. After each milestone, write the **verified steps** into that quest's file (`wiki/quests/<line>/<quest>.md`), set its
   front-matter `status`/`ru`, re-run `python3 -I tools/gen_quests.py`, and update the active run plan.
5. When something differs from expectations, **log it in `docs/troubleshooting/INDEX.md`** and fix the affected doc/tool/skill
   in the same pass.
6. Prefer the hint button in the journal (**Show Hint**) for the actionable next step (L12).
7. **Every task runs from a plan (L76):** `./wf run start` → `runs/<YYYYMMDD-HHMM>-<task>/plan.md`, written and reviewed
   by the supervisor, shown to the user, followed by the agent step by step (`./wf run step N start|done`, timestamps in
   `progress.md`). A step over its budget or stuck → `./wf run escalate N` → stuck retro → plan fixed from step N.
   **Stuck = Tara's position changes < 2 units over 3 moves while not at the goal (L75).** Every stuck episode gets a
   **stuck retro**: read `retros/stuck-ledger.md` first (did earlier fixes hold?), add a row, save the retro in
   `retros/`; a cause that repeats gets a tool fix. Aim: fewer stuck episodes per trip.
8. **One game command per tool call** (never `wf stop; wf resume; wf goto` in one call): a rejected call may already
   have run its first commands. After any rejection: `tail -3 .shots/actions.log`, then inspect the current task/turn;
   let the game lose focus during diagnosis rather than opening the Pause menu.
   wfc refuses an input command chained with another ./wf call.
9. **Uncertainty → model vision, always (user, D183).** Game functions never fail blind: any `Failed` carries
   `NEED_VISION: look at <png>: <question>` (`core.ask_vision`, frame taken at the innermost failure, before menus
   close). Agents Read it before reporting a cause or deciding; code that can't tell (unknown icon, unread card, no
   proof) asks vision, it doesn't guess.
10. **Model-owned garden turns (`wiki/mechanics/interaction-laws.md`):** bare `./wf garden region=…` observes and
   prints `NEXT`; the gameplay model chooses every continuation with `turn_id=N answer=accept|<Decision JSON>`.
   Each continuation performs at most one input. Keep the active transaction/crop/phase through surprises and fixes;
   only positioned events bind an actual node. Every decision carries a concise rationale category/evidence refs
   in the single run `log.jsonl`; `experiences.jsonl` is machine replay only. Learned actions/graph/observations/images
   are hot data, not restart triggers. Every bed/hive needs covered identity proof or an explicit event-owned
   blocked-target entry (phase/reason/evidence); constrained completion needs supervisor review. General
   maintenance plants empty beds and waters after planting unless rain; narrow harvest/water jobs leave empties.
   Read the interaction-laws command contract before garden play; it supersedes old scheduler/streaming instructions.
11. **Other interaction laws (user, D183/D191):** Tara is always at the frame centre
   (never ask where she is); record every click result and update state from it; click every fitting bubble until none
   is left. A target click is preferred when the target **and its full walkable road from Tara are visible**; otherwise
   click one short visible-ground waypoint and look again. Vision answers `target <cell>` or `walk <cell>`; projected
   ownership is only a hint and the game event decides which node was treated. Garden surprises use rule 10's durable
   correction path; other legacy goals may request close cards + fresh frame.
   **Chores and object goals run on the engine (L138):** `./wf achieve <goal> k=v` (`./wf world kinds` = what exists);
   **foraging (rocks, trees, drops, forage plants) is pure vision, never graph nodes (L158, spec §13):** `./wf forage
   chop|rock|pickup|forage` → one `NEED_VISION click` per target → `answer=<cell>|walk:<cell>|none`;
   `NEED_VISION click|button|name` → call again with `answer=…`; `NEED_INPUT <goal>: <param>?` → ask the user or answer from
   the task text (never default it).
