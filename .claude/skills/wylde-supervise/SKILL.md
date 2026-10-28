---
name: wylde-supervise
description: Supervise playing Wylde Flowers — keep a current goal, pick the next quest/goal, dispatch one wylde-quest agent per goal (which uses wylde-runner for steps), review results, handle decisions with the user, and keep docs/progress.md current. Use when asked to play, continue the game, or progress quests.
---

# Supervisor loop

You are the supervisor (main conversation). You don't press keys yourself except for quick checks (`./wf state`).
The hierarchy:
```
supervisor (you)  ──spawns──▶  wylde-quest (Sonnet): one goal, loads relevant docs, plans, records
                                   └──spawns──▶  wylde-runner (Haiku): one concrete step via ./wf, text-only
```

## 0. Purpose
We are **testing the docs**: the goal is minimal docs sufficient for an agent to pass quests. **Filling gaps beats
winning.** Prefer goals that exercise undocumented actions/places/screens. When a gap blocks a run, stop it and fix the
docs, then re-test. Judge runs by gaps found and fixed.

## 1. Orient (cheap)
- Read `docs/progress.md` (state + **Current goal** + goal queue) and `docs/quests/INDEX.md` → "Active now".
- `./wf save` + `./wf log --tail 20` (sandbox disabled): exact day/time, money, scene, quest goals, inventory, and
  recent events (`docs/ui/game-files.md`). Then `./wf state`; add one `./wf look` only if the exact spot matters.
  Fix progress.md first if reality differs, and put the observed location in the brief.

## 2. Choose the current goal
Before choosing, check the docs cover the goal's verbs and places (`mechanics/basic-actions.md`, `world/locations.md`).
Missing how-to/location → either make the goal "scout/learn X" first, or brief the agent to fill the gap.
Plan with the tips: `./wf tips planning energy time` (+ the goal's tags). Approve eating only where the tips say so.
**Energy feasibility:** for gathering/tool goals, add up the costs from `docs/mechanics/energy.md` (Cost table). If the total is over
100% of the bar, split the goal by day (retro 2026-10-27: 240% in one day → 2 faints, 6 teas used, stone still short).
Pick ONE goal that is small, verifiable, unblocked **now**, and **tests something not yet verified** (a ❓ row in
basic-actions, an unknown place, a new screen) (time of day, weekday shop hours in
`docs/world/businesses.md`, energy, money). Priority:
1. Time-critical dailies (e.g. watering planted crops).
2. Main-story active quests whose next step is doable now.
3. Cheap side progress on the way (foraging, meeting villagers).
Write it to `docs/progress.md` → **Current goal** (goal, quest file, done-signal, constraints) before dispatching.

## 3. Dispatch: give the child EVERYTHING it needs (the manifest)
The child should finish the quest from the manifest alone. Before dispatching, complete the quest file:
- `## Quest brief` fields: Why · Steps (▶️ current) · How-to · Where · Progress signal · Done when · Next · Tips ·
  **Actions** (tags for `./wf actions`: the DB rows with expected outcomes the agent checks each step against) · Gotchas.
  An action missing from `docs/actions.md`, or one with ❓ Expect → add the row first, or make verifying it part of the goal.
- **`Read:`** field = the manifest: exact files + sections + commands the step needs, e.g.
  `docs/mechanics/basic-actions.md (Talk, Eat rows)`, `docs/world/locations.md (Farm → interior)`,
  `docs/ui/screens/interaction-menu.md`, `./wf tips shops money`,
  `reference/wiki/Rice and Shine.md`. If you can't list a source for something the step needs, it's a docs gap: fill it
  first, or make the goal "scout/learn it".

Dispatch message (short; the quest file carries the content):
```
MANIFEST: docs/quests/<line>/<quest>.md + every item in its `Read:` field
GOAL: its ▶️ step(s) up to <stop point>
START STATE: <state line + location from your look>
CONSTRAINTS: <approved decisions; forbidden; time limit; call budget = HARD stop>
ON GAPS: stop safely and return RESULT: need-help with NEED/TRIED/WOULD HELP/STATE. I'll fix the docs and resume you.
REPORT: standard report with COST + GAPS (incl. every user message you received).
```
Before dispatching a "get/use X here" goal, **check the target yourself with one `./wf look`** and put its on-screen
direction from Tara in START STATE (e.g. "mushroom ~190 px left of Tara, a rock in between"). Don't pass on target
positions from old attempt notes without checking them (run #11 chased a wrong position for 25 calls).
One quest agent at a time. **Never send game input (keys, look-with-escape, pause) while an agent runs**, even after
its `run end`: wait for its task notification (retro 2026-10-28: my Escapes fought the agent's inputs).
**Hand-in mechanics:** read the wiki quest page's completion text; if how the hand-in works isn't verified in
`docs/actions.md`, mark that step ❓ in the brief instead of guessing (retro 2026-10-28: "!" topic vs Build button).

## 3b. When the child pings (`RESULT: need-help`)
1. Fix the source **for now and the future**: the shared doc (basic-actions / locations / ui / mechanics), `docs/tips.md`,
   the quest brief, and its `Read:` list (add the file that would have answered it). Research with `./wf wiki`, a quick
   `./wf look`, or ask the user if it's their decision/knowledge.
2. Resume the **same** child: `SendMessage(to: <agent id>, "Fixed: <what>. Re-read <files>. Continue from <state>.")`.
3. Log the ping in `docs/agent-runs.md` (Gap → fix). Many pings on one quest means the manifest template needs a new field.

## 4. Review
- `./wf run report [runs/<file>]`: timeline (attempts, issues, walks, game events) + time split (in calls / agent
  thinking / Tara active). Retros start from run logs, not from video.
- Read the report; verify with `./wf state`. Spot-check that the quest file's Verified steps were written.
- RESULT=done → mark the goal done in progress.md and pick the next one.
- partial/blocked → decide: re-brief with a narrower goal, fix a tool/doc (log in learnings), or ask the user.
- decision-needed → **ask the user** (purchases, choices, sleeping/ending the day, romance), then re-dispatch.

## 5. Debrief: you own the shared docs (mandatory, before the next goal)
Agents only write raw attempt notes in the quest file and report GAPS. **You** turn them into docs.
First `./wf learn` (docs/self-improvement.md): check new bubble kinds (delete bad samples in `tools/bubbles/`), and
copy observed hits/pickups into `docs/actions.md` Expect where they differ.
| GAP kind | Your action |
|---|---|
| `[docs]` | update `mechanics/basic-actions.md`, `world/locations.md`, `ui/…`, `mechanics/<topic>` (flip ❓→✅, add gotchas) |
| `[brief]` | fix that quest file's `## Quest brief` (and the field list above if a field type was missing) |
| `[tool]` | `docs/learnings.md` row + `tools/TODO.md`; fix now if cheap and blocking |
| `[agent]` | edit `.claude/agents/wylde-quest.md` / `wylde-runner.md` |
| `[user]` | each user correction is a gap in brief/docs/agent → apply the matching fix above |
Also clean the quest file's attempt log if it has stale/wrong values. Log the run in `docs/agent-runs.md`.
Every ~5 goals, or when costs trend up, run `/retro` over `docs/agent-runs.md`.

## 6. Keep records (you own these)
- `docs/progress.md`: state summary, Current goal, Goal queue, one session-log row per finished goal.
- After a slow or messy stretch, run `/retro`.
- The game stays in the background between goals (time frozen, learnings L28).
