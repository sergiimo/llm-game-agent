# AGENTS.md — playing Wylde Flowers on this Mac

**Goal:** minimal, sufficient docs so agents can pass the quests. Current phase: testing; **filling gaps beats winning**.

This repo is a toolkit for an AI agent to **play Wylde Flowers** (Apple Arcade macOS build, running full-screen,
UI language **English** since D4 (L48); older docs quote Russian UI strings, see `docs/ui/glossary.md`) and a **world model** of the game.

## Layout: progressive loading
Read **`wiki/INDEX.md`** for game knowledge or **`docs/INDEX.md`** for app operations (a short router), then only the index and the one file the current step needs.
Every detail file starts with a `> **Summary:**` line, so `head -8` is often enough.

| Path | What |
|---|---|
| `requirements.md` | Canonical persistent product requirements; dated specs/plans may reference but not redefine them |
| `docs/INDEX.md` | Router: need → which index to open |
| `wiki/quests/INDEX.md` → `quests/<line>/<quest>.md` | All 131 quests by questline with status ▶️/✅/·; each file = wiki requirements (generated) + **verified steps** (written while playing) |
| `wiki/mechanics/INDEX.md` → `mechanics/<topic>.md` | Game systems (time, energy, farming, fishing, shops, …); "(wiki)" vs "Verified in-game" sections |
| `docs/ui/INDEX.md` → `controls.md`, `hud.md`, `screens/<screen>.md`, `glossary.md` | What's on screen, how to recognise it (`wf state` mode), actions, exit; RU↔EN |
| `wiki/INDEX.md` → topical mechanics, quests, characters, places, businesses, items, story, and tips | Reference knowledge (generated from the wiki) |
| `docs/operations/actions.md` | **Actions DB:** each action → recipe, **expected** hits/drops/energy, verify signal, fix. `./wf actions <tags>` prints a job's rows |
| `runs/wf.sqlite3`, `runs/<YYYYMMDD-HHMM>-<task>/` | **SQLite is the sole structured authority** for runs, observations, tasks, intents, experiences, and local world facts. Each task dir keeps human artifacts: `plan.md`, generated `decisions.md`/`progress.md` (with SQLite row IDs), screenshots, and retros. `./wf run status` / `report` / `export --jsonl <run>`. |
| `tools/game/` | **Universal model-owned engine:** `./wf play <goal> k=v` returns one durable `NEXT`; the gameplay agent reads its evidence/full-scale frame and selects exactly one guarded primitive. Public aliases resume the same turn boundary; legacy `achieve`/`do`/`py`/`call`/routes are not workflow executors. `turn.py` persists task/transaction state, `primitives.py` performs zero or one input, and `integrate.py` records immutable evidence/corrections/gaps. `./wf gaps` is the offline code-factory queue. |
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
| `.claude/agents/wylde-quest.md` | Primary gameplay agent (cheapest model): owns one goal's complete model-owned turn/vision/correction loop |
| `.claude/agents/wylde-runner.md` | Optional exact-command helper only; never owns, interprets, or stops a gameplay turn |
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

## Playing = supervisor → one primary gameplay agent
Always have **one current goal** in the current task's `runs/<task>/plan.md`. The main conversation supervises (`wylde-supervise`):
choose the goal, dispatch `wylde-quest`, review, ask the user for decisions. The quest agent loads only the relevant
docs and owns every observe → model vision → decide → one primitive → verify/correct turn itself. Do not insert a
text-only runner between the returned `NEXT` receipt and the model that must inspect its frame. `wylde-runner` is an
optional exact-command helper after a decision is already complete; normal gameplay does not spawn it.
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
   **At 18:00 or later, stop ordinary gameplay and either return home/sleep immediately or explicitly hand control
   to the human. Before every new gameplay task, check the exact clock and sleep/advance first if needed**
   (user standing rule, updated 2026-11-08; this sleep is pre-approved).
1. **One model-owned decision per step:** `./wf play <goal> [k=v]` observes and returns `NEXT`; continue with the exact
   `turn_id` and one explicit decision. Each continuation performs zero or one input, settles, integrates one immutable
   experience, and returns control to the same gameplay agent.
   Observe with the game files first: `./wf log` (live events: quests, dialogue, scenes, pickups; input commands
   print new lines as `log: …`) and `./wf save` (exact money/time/quests/inventory as of the last autosave), see
   `docs/ui/game-files.md`. Then `./wf state` (text) → `./wf look` (full-scale JPEG, then Read it; **every screenshot and vision image is full scale**, user D188: small copies made the map unreadable).
   **Move only by a selected click primitive:** choose a target only when its complete visible road is clear; otherwise
   choose one short visible-ground waypoint. There is no keyboard fallback or hidden route executor.
2. **Small steps, no blind loops.** Never spam keys through cutscenes, dialogue or menus. `./wf advance` stops at
   anything unexpected.
3. **Don't change the user's settings** (language, game speed) or spend/sell/sleep through big decisions without
   asking, unless the user said so ("pass quest X" = sleeping as many nights as it needs is approved).
4. After each milestone, write the **verified steps** into that quest's file (`wiki/quests/<line>/<quest>.md`), set its
   front-matter `status`/`ru`, re-run `python3 -I tools/gen_quests.py`, and update the current run plan.
5. When something differs from expectations, **log it in `docs/troubleshooting/INDEX.md`** and fix the affected doc/tool/skill
   in the same pass.
6. Prefer the hint button in the journal (**Show Hint**) for the actionable next step (L12).
7. **Every task runs from a plan (L76):** `./wf run start` → `runs/<YYYYMMDD-HHMM>-<task>/plan.md`, written and reviewed
   by the supervisor, shown to the user, followed by the agent step by step (`./wf run step N start|done`, timestamps in
   `runs/<task>/progress.md`). A step over its budget or stuck → `./wf run escalate N` → stuck retro → plan fixed from step N.
   **Stuck = Tara's position changes < 2 units over 3 moves while not at the goal (L75).** Every stuck episode gets a
   **stuck retro**: read `retros/stuck-ledger.md` first (did earlier fixes hold?), add a row, save the retro in
   `retros/`; a cause that repeats gets a tool fix. Every retro must include **System improvement suggestions for the
   user**: prioritized fixes, why each matters, a concrete implementation direction, an acceptance test, and a
   recommended implementation order. Return those suggestions in the final user-facing retro summary. Aim: fewer
   stuck episodes per trip.
8. **One game command per tool call** (never `wf stop; wf resume; wf goto` in one call): a rejected call may already
   have run its first commands. After any rejection: `tail -3 .shots/actions.log`, then inspect the current task/turn;
   let the game lose focus during diagnosis rather than opening the Pause menu.
   wfc refuses an input command chained with another ./wf call.
9. **Uncertainty → the primary agent uses model vision (user, D183).** Every `NEXT` supplies its coherent full-scale
   `view.path`; `need.kind=vision`, a surprise, unknown icon/card, or missing proof tells the same gameplay agent to
   open that image itself before diagnosing or deciding. Low-level code never invokes a model. A `look` decision logs
   optional vision and exposes the saved frame; it is not an engine-owned callback or a handoff to another agent.
10. **Universal model-owned turns (`wiki/mechanics/interaction-laws.md`):** every gameplay domain, including garden,
   navigation, indoors, sleep, shops, dialogue and foraging, uses the same durable `NEXT` contract. The gameplay model
   chooses every continuation with `turn_id=N answer=accept|<Decision JSON>`.
   Each continuation performs at most one input. Keep the active transaction/crop/phase through surprises and fixes;
   only positioned events bind an actual node. Every decision carries a concise rationale category/evidence refs
   in the run's ordered SQLite event stream; immutable experiences live in the SQLite `experiences` table. Learned actions/graph/observations/images
   are hot data, not restart triggers. Every bed/hive needs covered identity proof or an explicit event-owned
   blocked-target entry (phase/reason/evidence); constrained completion needs supervisor review. General
   maintenance plants empty beds and waters after planting unless rain; narrow harvest/water jobs leave empties.
   Read the interaction-laws command contract before play; it supersedes old scheduler/streaming instructions.
11. **Other interaction laws (user, D183/D191):** Tara is always at the frame centre
   (never ask where she is); record every click result and update state from it; click every fitting bubble until none
   is left. A target click is preferred when the target **and its full walkable road from Tara are visible**; otherwise
   click one short visible-ground waypoint and look again. Vision answers `target <cell>` or `walk <cell>`; projected
   ownership is only a hint and the game event decides which node was treated. Garden surprises use rule 10's durable
   correction path; other legacy goals may request close cards + fresh frame.
   Chores, objects and foraging are goals/subgoals on `./wf play`. Foraging remains pure current-frame vision and never
   creates graph nodes, but the agent still selects one atomic target/waypoint/tool action per turn. A missing required
   parameter is answered from explicit task authorization or returned to the user; never default it.
   A surprise or vision request is not a terminal stop. The primary agent inspects/corrects it; if genuinely ambiguous,
   it returns `need-help` while leaving the durable task active. Only an intentional terminal outcome or explicit user
   stop submits the durable `stop` decision.
12. **A user stop stops everything (user, 2026-11-07):** immediately interrupt every live gameplay child/descendant;
   do not wait for a cooperative stop. Make at most one zero-input durable-task stop and run-close attempt, then run
   `./wf stop` to terminate and verify the controller/recording thread and every live `runwatch.py` watcher and remove
   the socket. Unfocus the game. Verify agents with the platform agent list and local automation with `ps`; never use
   `./wf status` for this check because it starts the daemon. Only after both checks may the supervisor report stopped
   or begin a retro. See `.claude/skills/wylde-supervise/SKILL.md` §3d.
