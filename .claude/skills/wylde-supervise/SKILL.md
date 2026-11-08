---
name: wylde-supervise
description: Use when asked to play, continue, or progress Wylde Flowers and a supervisor must maintain one reviewed task, dispatch one primary gameplay agent that owns every model-owned turn, monitor evidence, handle user decisions, and keep the run plan accurate.
---

# Supervisor loop

You are the supervisor (main conversation). You don't choose or execute gameplay inputs. You perform preflight,
maintain the plan, watch evidence, repair gaps, and handle user decisions.
The hierarchy:
```
supervisor (you)  ──spawns──▶  wylde-quest (cheapest model): one goal; owns observe → vision → decide
                                                → one primitive → verify/correct until terminal or handoff
```

Do not place `wylde-runner` between a `NEXT` receipt and its gameplay owner. The optional runner may execute one
already-selected exact command, but it never reads vision to decide, continues a turn loop, or submits durable stop.

## 0. Purpose
We are **testing the docs**: the goal is minimal docs sufficient for an agent to pass quests. **Filling gaps beats
winning.** Prefer goals that exercise undocumented actions/places/screens. When a gap blocks a run, stop it and fix the
docs, then re-test. Judge runs by gaps found and fixed.

## 1. Orient (cheap)
- **Clock gate before every new gameplay task:** read the exact game time from `./wf save` or `./wf state` before
  planning or dispatching any action. If it is later than **19:00**, make model-owned sleep the first reviewed task/
  subgoal and dispatch the primary gameplay agent to execute it one turn at a time; refresh state next morning before
  ordinary work. This standing user rule pre-approves that sleep; it is not a decision-needed stop.
- **Before every dispatch:** `./wf status` — a locked Mac screen blocks capture and input (loop-live 2026-10-31: the
  agent stopped at its first call). Locked → tell the user, wait; never dispatch.
- **…and check the user isn't playing:** `./wf log --tail 20` + `tail -5 .shots/actions.log`. Game actions in the log
  (`> water`, `> plant`, `grab_item`…) newer than our last command, or a game clock far ahead of where we left it →
  the user is playing: ask before dispatching (loop-live-4 2026-10-31: the agent fought the user's inputs).
- Keep one persistent controller daemon for the live task. Do not switch preflight or diagnosis to
  `WF_NO_DAEMON=1`, and do not launch a second `wf` request while the first has unknown delivery; macOS may prompt
  each helper separately for app-data access. Inspect the SQLite turn first, then restart once with `./wf stop` only
  when the existing controller is genuinely wedged.
- Run `./wf run status` to inspect the current task, if one is open, and read its `runs/<task>/plan.md`; use
  `wiki/quests/INDEX.md` → "Active now" for game-wide quest state. There is no global progress file.
- `./wf save` + `./wf log --tail 20` (sandbox disabled): exact day/time, money, scene, quest goals, inventory, and
  recent events (`docs/ui/game-files.md`). Then `./wf state`; add one `./wf look` only if the exact spot matters.
  If reality differs from the open task, record `./wf run issue <what differs>` and revise that run's `plan.md`;
  `runs/<task>/progress.md` is generated from the run log and must not be hand-edited. Put the observed location in the brief.

## 1b. Every morning: routines first
`./wf routines` (docs/operations/routines.md): DUE routines (watering, harvest) are dispatched before any quest goal; wilted
beds first. A routine is done only when `./wf routines` says DONE.

## 2. Choose the current goal
Before choosing, check the docs cover the goal's verbs and places (`mechanics/basic-actions.md`, `world/locations.md`).
Missing how-to/location → either make the goal "scout/learn X" first, or brief the agent to fill the gap.
Plan with the tips: `./wf tips planning energy time` (+ the goal's tags). Approve eating only where the tips say so.
**Energy feasibility:** for gathering/tool goals, add up the costs from `wiki/mechanics/energy.md` (Cost table). If the total is over
100% of the bar, split the goal by day (retro 2026-10-27: 240% in one day → 2 faints, 6 teas used, stone still short).
Pick ONE goal that is small, verifiable, unblocked **now**, and **tests something not yet verified** (a ❓ row in
basic-actions, an unknown place, a new screen) (time of day, weekday shop hours in
`wiki/businesses/INDEX.md`, energy, money). Priority:
1. Time-critical dailies (e.g. watering planted crops).
2. Main-story active quests whose next step is doable now.
3. Cheap side progress on the way (foraging, meeting villagers).
Carry the chosen goal into the new task's `./wf run start` command and `runs/<task>/plan.md` (goal, quest file,
done-signal, constraints) before dispatching.

## 3. Dispatch: give the child EVERYTHING it needs (the manifest)
**Model rule (user, 2026-11-01): always use the cheapest available model for every spawned gameplay agent**, unless
the user explicitly overrides it. In Codex collaboration this is `gpt-6-luna` with low
reasoning; in Claude agent definitions it is `haiku`. Never inherit the supervisor's more expensive model by default.

**Fast-start rule (user, 2026-11-01): routine navigation must not become an analysis phase.** Start/resume the generic
`./wf play navigate destination=<node-or-kind>` workflow and act from its one next graph edge. The edge is compass plus
`near|mid|far`; the same primary gameplay child inspects the supplied full-scale frame and chooses one matching
visible-road click. Do not
run retired `goto`/calibration/coordinate routes first. The supervisor's fresh preflight is passed in the manifest so
the child does not repeat it.

The child should finish the quest from the manifest alone. Before dispatching, complete the quest file:
- `## Quest brief` fields: Why · Steps (▶️ current) · How-to · Where · Progress signal · Done when · Next · Tips ·
  **Actions** (tags for `./wf actions`: the DB rows with expected outcomes the agent checks each step against) · Gotchas.
  An action missing from `docs/operations/actions.md`, or one with ❓ Expect → add the row first, or make verifying it part of the goal.
- **`Read:`** field = the manifest: exact files + sections + commands the step needs, e.g.
  `wiki/mechanics/basic-actions.md (Talk, Eat rows)`, `wiki/places/locations.md (Farm → interior)`,
  `docs/ui/screens/interaction-menu.md`, `./wf tips shops money`,
  `wiki/quests/gardening-foraging-and-plants/rice-and-shine.md`. If you can't list a source for something the step needs, it's a docs gap: fill it
  first, or make the goal "scout/learn it".

**Every task starts with a plan (user, 2026-10-30, L76):**
1. `./wf run start <task-id> <goal…>` → `runs/<YYYYMMDD-HHMM>-<task>/` with a `plan.md` template. You open the run,
   not the agent.
2. Write `plan.md` for the agent: header (Goal · Done when · Brief = quest file · Review) and one `## Step N: <title>`
   per concrete step with **Do** (goal/workflow and docs sections, never a preselected screen point), **Signal**, **Done when**, **Budget**
   (`<N> calls, <M> min` of game time, from `docs/operations/actions.md` Expect / earlier runs) and **If stuck**. Small steps:
   one place or one action kind each; sleeping/waiting gets its own step.
3. **Review it**: `./wf run plan` (fields complete) + your check: every step's key action is ✅ verified in
   docs/operations/actions.md / routines (an unverified one becomes its own small scout step: try once on one target, report;
   retro S6), every place documented (else a scout step),
   feasible now (shop hours, energy, clock), budgets realistic. For a venue with a closing/last-entry time, compute
   `minutes available = closing time - current game time` and require it to cover **every remaining pre-entry and
   transaction step budget plus 15 game minutes**. If it does not, issue no route input: sleeping/waiting is a separate
   decision step unless already pre-approved. Write the arithmetic and result in **Review**.
4. **Show the plan to the user** (paste plan.md in your reply), then dispatch right away (they see it, no approval
   needed).

Dispatch message (short; the plan carries the content):
```
PLAN: runs/<…>/plan.md (follow it step by step; `./wf run step N start|done`; escalate per your §0)
MANIFEST: wiki/quests/<line>/<quest>.md + every item in its `Read:` field
START STATE: <state line + location from your look>
CONSTRAINTS: <approved decisions; forbidden; total call budget = HARD stop>
ON GAPS: stop safely and return RESULT: need-help with NEED/TRIED/WOULD HELP/STATE. I'll fix the docs and resume you.
REPORT: standard report with COST + GAPS (incl. every user message you received).
```
Before dispatching a "get/use X here" goal, **check the target yourself with one `./wf look`** and put its on-screen
direction from Tara in START STATE (e.g. "mushroom ~190 px left of Tara, a rock in between"). Don't pass on target
positions from old attempt notes without checking them (run #11 chased a wrong position for 25 calls).
**"Record" = video** (user, 2026-10-29): `./wf record start` (sandbox off) right before dispatching,
`./wf record stop` after the agent's notification (prints path + size; `FAILED` = no frames) and give its path in the
report. It runs inside the daemon (L71), so agents must not `./wf stop` during a recorded run. One quest agent at a time. **Never send game input (keys, look-with-escape, pause) while an agent runs**, even after
its `run end`: wait for its task notification (retro 2026-10-28: my Escapes fought the agent's inputs).
**Hand-in mechanics:** read the wiki quest page's completion text; if how the hand-in works isn't verified in
`docs/operations/actions.md`, mark that step ❓ in the brief instead of guessing (retro 2026-10-28: "!" topic vs Build button).

## 3c. Watch every live run (user D186: "the supervisor was meant to control the execution and see a detailed log")
For every gameplay task, first load `wiki/mechanics/interaction-laws.md`. Dispatch one `gpt-6-luna` low primary
gameplay model with that file, the reviewed run plan, clock/authorization/budget and durable task path. It owns one
decision per turn across every domain; do not spawn nested gameplay runners. Watch the ordered SQLite run stream: `type=turn`
joins clues, recommendation, model decision, optional vision, intent, experience, integration and corrections by
turn ID. Do not duplicate structured Decision rationales in another reasoning log. On surprise: stop/pause safely,
preserve experience/frame, update the real replay, make the smallest fix, run only the focused regression, then
resume the same durable transaction. Learned data must not restart the daemon. Run the broad gate once at final SHA.

Never let a child run the game blind. For every dispatch that touches the game:
1. **Start the watcher before the child:** Monitor tool on `.venv/bin/python tools/runwatch.py --follow` (the open run).
   **Keep every line, not only alerts** (user D189: "tracing should be absolute"): the click lines with their game
   events, `decide` (which object and why) and `think` (the child's reasoning). `--report` ends with the full trace.
   It prints one line per click (what, point, walked/still, events, screen, bubbles) and flags rules from the live
   failures: **STOP** = a click or close with the pause menu on screen, the game process gone, 4 arrival misses in a row
   or a `LOST` trace (no progress: live D188 S40, 15+ clicks lost under ALERTs only); **ALERT** = a graph step
   from a look-alike node, a prediction miss, a failed `pick_card`, a junk icon name, an engine stop that isn't done;
   **NOTE** = `> plant` without `totalPlanted`, STUCK, every vision question.
2. **STOP → `TaskStop` the child at once**, then `./wf pause` only if the game is running and not on a menu. **ALERT →**
   An `idle Ns` ALERT (no call or click for 45 s while the game runs) = the child is thinking with the clock running:
   pause the game or nudge the child. After a run, `.venv/bin/python tools/runwatch.py <run> --report` has the Time
   table (wall, in calls, thinking, longest gap, game minutes, clicks, vision, picks) - put it in the review.
   **Vision is the fallback for every case (user D189):** no stop or loop may stand where vision could decide. In the
   retro list each vision answer (`./wf gaps experiences`, run log `vision` rows) and what it settled or taught
   (graph state, a look, a way); one that taught nothing is a gap to fix. Repeated questions = a tool fix.
   Read the click's saved frame (`<run>/clicks/`) yourself and decide (continue / stop / fix). **Two ALERTs of the same
   kind in a row → Read the newest frame at once** (S40: the frame showed her by the river, far from the garden).
   In `focus-mode front`, do not wait for that 45-second alert when the next game call is not ready: activate Codex
   (`open -a Codex`) during off-game reasoning so Unity freezes without changing the saved focus mode. The next `./wf`
   input refocuses the game. Never open the Pause modal merely to buy thinking time.
3. **Vision and surprise turns:** the primary child reads `NEXT.view.path` itself and chooses the next versioned
   decision. A `need.kind=vision` or surprise is not a request for the supervisor to answer and not permission to
   delegate or terminate the task. The child opens the full-scale frame, logs optional `look`, then chooses one
   correction or later one atomic primitive. The supervisor independently spot-checks frames while monitoring, but
   never races the child with another game command. If the child returns `need-help`, the durable task remains active;
   fix the brief/data or ask the user and resume the same child. A durable `stop` here is a defect unless the task is
   intentionally terminal or the user explicitly stopped everything.
4. **After the run:** `.venv/bin/python tools/runwatch.py <run> --report` writes `<run>/watch.md` (a table per attempt:
   clicks, walks, still, predictions hit/miss, alerts, stops); put it in the debrief.

## 3d. User stop is terminal and stops everything

A user `stop`, `stop now`, or equivalent overrides recording preservation, retrospectives, and every active plan step.
The supervisor owns managed agents; `./wf stop` owns local OS automation. Perform this sequence without starting new
diagnosis or gameplay work between steps:

1. Interrupt/TaskStop every live gameplay descendant (quest and runner), then list the agent tree and confirm none is
   running. Do not merely send a stop message and wait for cooperation.
2. If a durable turn and run are active, make at most one zero-input `answer=stop` call and close the run as `stopped`.
   If either call fails or does not return, do not retry it; local shutdown takes precedence.
3. Run `./wf stop`. It terminates and verifies the controller daemon (including its recording thread) and live
   `runwatch.py --follow` processes, then removes the daemon socket. Any `STOP FAILED` result is still a live-stop
   incident: inspect only the named survivor and terminate it before continuing.
4. Let Wylde Flowers lose focus so game time freezes. Verify local state with `ps`, never `./wf status` (which would
   start the daemon again), and verify managed-agent state with the platform's agent list.
5. Only after both verifications may the supervisor say the agent stopped, generate reports, or write the retro.

`./wf stop` cannot control managed Codex/Claude agents, and TaskStop cannot terminate the local controller. A complete
stop always uses and verifies both ownership boundaries.

## 3a. When the child escalates (`RESULT: escalate step N`)
1. `./wf run status` (`runs/<task>/progress.md`: generated step timestamps and budget use) + `./wf run report`.
2. **Stuck retro** (AGENTS.md rule 7): read `retros/stuck-ledger.md` first, score earlier fixes, add the row, write
   `runs/<task>/retro-<k>.md`, apply the fix (tool/doc).
3. Fix `plan.md` from step N (rewrite the steps, keep the done ones), `./wf run plan`, show the user the changed
   steps, then resume the same child: "Plan revised from step N: re-read plan.md, `./wf run step N start`".

## 3b. When the child pings (`RESULT: need-help`)
1. Fix the source **for now and the future**: the shared doc (basic-actions / locations / ui / mechanics), `wiki/tips/INDEX.md`,
   the quest brief, and its `Read:` list (add the file that would have answered it). Research with `./wf wiki`, a quick
   `./wf look`, or ask the user if it's their decision/knowledge.
2. Resume the **same** child: `SendMessage(to: <agent id>, "Fixed: <what>. Re-read <files>. Continue from <state>.")`.
3. Log the ping in `docs/agent-runs.md` (Gap → fix). Many pings on one quest means the manifest template needs a new field.

## 4. Review
- `./wf eval` (hits/misses per component for this run; mark each STUCK alarm `./wf eval mark <id> hit|miss`) and,
  for bench runs, `./wf bench report`. Log every user interrupt as it happens: `./wf run interrupt <text>`.
- `./wf run status` (progress per step) and `./wf run report [runs/<task>/]`: timeline (attempts, issues, walks, game events) + time split (in calls / agent
  thinking / Tara active). Retros start from run logs, not from video.
- Read the report; verify with `./wf state`. Spot-check that the quest file's Verified steps were written.
- RESULT=done → close the task with `./wf run end done`, update the quest's Wiki status/verified steps, then pick the next task.
- partial/blocked → decide: re-brief with a narrower goal, fix a tool/doc (log in learnings), or ask the user.
- decision-needed → **ask the user** (purchases, choices, sleeping/ending the day, romance), then resume the same child.
  Exception (user, 2026-10-30): **"pass quest X" pre-approves sleeping** as many nights as the quest needs (waiting for
  honey, crops); put "sleeping approved" in CONSTRAINTS. Due routines still come first each morning; spending still asks.
  **How to sleep:** the primary gameplay agent pushes/resumes the documented `sleep` workflow and owns each navigation,
  bed interaction, confirmation and morning turn. Completion requires captured `sleep_transition`; there is no hidden
  one-call engine route. Before 02:00: passing out risks sickness.

## 5. Debrief: you own the shared docs (mandatory, before the next goal)
Agents only write raw attempt notes in the quest file and report GAPS. **You** turn them into docs.
First `./wf learn` (docs/architecture/self-improvement.md): check new bubble kinds (delete bad samples in `tools/bubbles/`), and
copy observed hits/pickups into `docs/operations/actions.md` Expect where they differ.
| GAP kind | Your action |
|---|---|
| `[docs]` | update `mechanics/basic-actions.md`, `world/locations.md`, `ui/…`, `mechanics/<topic>` (flip ❓→✅, add gotchas) |
| `[brief]` | fix that quest file's `## Quest brief` (and the field list above if a field type was missing) |
| `[tool]` | `docs/troubleshooting/INDEX.md` row + `tools/TODO.md`; fix now if cheap and blocking |
| `[agent]` | edit `.claude/agents/wylde-quest.md` / `wylde-runner.md` |
| `[user]` | each user correction is a gap in brief/docs/agent → apply the matching fix above |
**Stuck retro (AGENTS.md rule 7):** any `[stuck]` gap or stuck episode you saw → `/retro` scoped to it: read
`retros/stuck-ledger.md` first, score the earlier fixes (held or not), add the row, apply the fix.
Also clean the quest file's attempt log if it has stale/wrong values. Log the run in `docs/agent-runs.md`.
Every ~5 goals, or when costs trend up, run `/retro` over `docs/agent-runs.md`.

## 6. Keep records (you own these)
- Per-task human records only: `runs/<task>/plan.md`, generated `runs/<task>/progress.md` and `decisions.md`, and any task retro. Structured events live only in `runs/wf.sqlite3`. Do not
  create or maintain a repository-wide progress file or cross-task execution log.
- After a slow or messy stretch, run `/retro`.
- The game stays in the background between goals (time frozen, learnings L28).
