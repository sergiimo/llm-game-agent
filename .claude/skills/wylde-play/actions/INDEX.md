# Model-owned actions

> **Summary:** docs choose sequences; Python supplies clues, guarded atomic inputs and evidence. Every gameplay
> domain uses `./wf play`. Load this index, then the one workflow needed now.

| Need | Read |
|---|---|
| Move to an object/place, or forage | [navigation.md](navigation.md) |
| Enter/exit the farmhouse or another region | [regions.md](regions.md) |
| Reach Tara's bed and sleep | [sleep.md](sleep.md) |
| Open a merchant UI, sell authorized items and buy discovered types | [shop.md](shop.md) |
| Maintain every bed/hive in a named region | [garden.md](garden.md) |
| Talk, advance a quest, use inventory or craft | Read the relevant `docs/ui/INDEX.md` screen and `docs/actions.md` row; apply the same atomic loop below. |

Start a reviewed run, check exact game time, and observe `./wf play <goal> [k=v ...]`. Bare domain aliases also
return `NEXT` without input. All aliases share the active run's `task.json` (existing `garden-task.json` is adopted
in place). `./wf play` resumes it. A different domain does not silently start another task: push a subgoal explicitly.
Legacy `do`, `py`, `call`, `goto`, `advance`, routes and batching requests are task descriptions; they execute no
old Python workflow. Continue all tasks through `play` with the exact saved turn ID.

```sh
./wf play turn_id=7 answer='{"kind":"act","action":{"kind":"waypoint","cell":"F7","walkable":true},"rationale":"visible_road","evidence_refs":["<frame>"]}'
./wf play turn_id=8 answer=accept
./wf play turn_id=9 answer='{"kind":"push","action":{"goal":"sleep","params":{}},"rationale":"late_task_gate"}'
```

Each `act` or `accept` performs at most one input. Read its immutable outcome before choosing again. Allowed primitives:
`target`/`cell`/`bubble` (model-confirmed visible target and entire road), `waypoint` (short visible walkable ground),
`press` (one exact visible label), `space` (highlighted world affordance or known dialogue/popup/cutscene),
`select_card` (one visible card point), `key` with `j`/`m`/`i` in gameplay, `close` on a recognized closable panel,
`read` and `wait` (zero input). `look` returns the saved full-scale frame and the same turn. Never use keyboard movement.

For dialogue, choose one `space` or one named response, expect the next subtitle/modal or quest event, then reassess.
For a journal hint, open `j`, inspect the quest, press visible `Show Hint`, read it, then close in separate turns.
Inventory use/crafting similarly needs a visible item/control, explicit resource authorization, and its item/event
change as proof. Do not turn a historical action recipe into a batch of keys.

A surprise permits only `look`, `correct`, `stop`. Read its source frame before diagnosing uncertainty. Corrections:
`revise_decision`, `graph`, `appearance`, `transition`, `blocked_target`, `gap`, `human`; legacy `world` remains accepted.
Graph corrections name one existing node (`state` or `placement`) or exact `edge:{a,b,rel}` plus `values`. Appearance
corrections name one kind and `op:sample` with a bounded `box`, or `op:reembed`. Keep the captured `frame_path`, rationale
and evidence references. Public appearance ops are only `sample` and `reembed`; legacy `proven_look`, `relabel` and `badge` model corrections
are rejected instead of discarding provenance. Corrections apply data idempotently and issue no gameplay input. A stale route/vector clue
must be corrected or reported before reuse. Movement alone never proves progress.

`push` freezes the parent interaction; `suspend` explicitly holds a subgoal. `complete` requires captured domain proof
and leaves the parent frozen. A separate `resume` restores it. Each boundary survives restart; a pending intent is
reconciled without repeating input. `human` records unresolved ambiguity; `gap` preserves evidence for offline repair.
Unsupported completion proof is a gap, never permission to mark success from a model assertion.

Check interrupts every turn. A new task after 19:00 requires the pre-approved sleep subgoal before work; rain/darkness
requires the documented sleep handoff. Empty-can constraints apply only to garden work that needs water: explicitly
push `refill`, navigate to the well, choose its fill action, and complete only after `fill_watering_can`; then resume
the frozen garden interaction. The refill subgoal and unrelated harvest/shop/navigation work do not inherit an
empty-can prohibition. Clock/weather safety interrupts still apply. After 23:00 finish the immediate safety step and sleep. Pause before
coding or long off-game work. Never change the user's settings. `./wf pause` remains a single guarded safety input.
