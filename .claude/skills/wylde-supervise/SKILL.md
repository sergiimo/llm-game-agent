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

## 1. Orient (cheap)
- Read `docs/progress.md` (state + **Current goal** + goal queue) and `docs/quests/INDEX.md` → "Active now".
- `./wf state` (sandbox disabled) to confirm the real state matches progress.md. If not, fix progress.md first.

## 2. Choose the current goal
Pick ONE goal that is small, verifiable, and unblocked **now** (time of day, weekday shop hours in
`docs/world/businesses.md`, energy, money). Priority:
1. Time-critical dailies (e.g. watering planted crops).
2. Main-story active quests whose next step is doable now.
3. Cheap side progress on the way (foraging, meeting villagers).
Write it to `docs/progress.md` → **Current goal** (goal, quest file, done-signal, constraints) before dispatching.

## 3. Dispatch
Spawn `wylde-quest` (fallback until agents reload: `general-purpose` with `model: sonnet`, plus "Follow
.claude/agents/wylde-quest.md"). Brief it with:
- the goal + done-signal, the quest file path, relevant constraints (budget, "don't spend money", "stop before 22:00",
  "no dialogue choices").
- Ask for its standard report.
Run one quest agent at a time (there's one game and one keyboard).

## 4. Review
- Read the report; verify with `./wf state`. Spot-check that the quest file's Verified steps were written.
- RESULT=done → mark the goal done in progress.md and pick the next one.
- partial/blocked → decide: re-brief with a narrower goal, fix a tool/doc (log in learnings), or ask the user.
- decision-needed → **ask the user** (purchases, choices, sleeping/ending the day, romance), then re-dispatch.

## 5. Keep records (you own these)
- `docs/progress.md`: state summary, Current goal, Goal queue, one session-log row per finished goal.
- After a slow or messy stretch, run `/retro`.
- The game stays in the background between goals (time frozen, learnings L28).
