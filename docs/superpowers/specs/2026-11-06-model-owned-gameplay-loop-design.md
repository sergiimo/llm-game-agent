# Model-Owned Gameplay Loop Design

> **Summary:** invert gameplay control: the model owns the repeated observe → decide → act loop, while code supplies
> evidence, graph clues, safe atomic actions, deterministic recommendations, integration, and durable task state.

**Status:** selected in conversation, 2026-11-06. This supersedes the orchestration portions of
`2026-11-04-model-decides-next-move.md` and `2026-11-05-streaming-garden-design.md`. Their state brief, interaction
laws, immutable experiences, and integration boundary remain valid.

## Problem

The current engine lets `tend_garden()` own the workflow. It selects a target, chooses and runs transition rows,
keeps local `remaining` and `replanting` state, and asks the model only at selected gaps. The model can correctly see
and click a ready tulip, but the function that resumes later may have lost the active target, crop, phase, or card
state. It then closes the right card, navigates away, repeats an action, or reconstructs stale graph state.

This is not mainly a perception problem. It is a control-ownership problem: functions consult the model, instead of
the model running functions and consulting the graph.

## Selected architecture

The gameplay model owns the loop. Code executes one turn at a time:

```text
model
  ├─ asks code for a fresh TurnContext
  ├─ optionally inspects the full-scale frame
  ├─ chooses one atomic action (or accepts the recommendation)
  └─ calls code once
       ├─ persist intent
       ├─ perform one input
       ├─ capture evidence
       ├─ create and integrate one Experience
       └─ persist the resulting task/transaction state
```

There is no code-owned `while remaining` workflow. A CLI call may observe or execute one input, never select and
finish several hidden steps. A cheap gameplay agent repeats calls until the returned task status is terminal.

## Responsibilities

### Model

- Owns the sequence of turns and the final choice of every action.
- Reads non-model clues first: current screen/card, visible bubbles, graph hypotheses with source/freshness, active
  transaction, last experience, policy recommendation, and global interrupts.
- Accepts an obvious recommendation with minimal reasoning, overrides it, requests full-scale model vision, or stops.
- On a surprise, classifies the smallest correction: current world fact, visual/embedding label, transition data,
  capability/code gap, or an unresolved application ambiguity for the human.

The model records a short structured rationale category and evidence references, not hidden chain-of-thought.

### Atomic functions

- Observe only, or perform exactly one input and capture its complete result.
- Never choose the next object, invoke model vision, advance a workflow phase by policy, or loop across targets.
- Return an immutable `Experience` and exact outcome (events, card, texts, bubbles, movement, frames).
- Retain existing guards: visible-road target clicks, walkable waypoint checks, HUD avoidance, red flags, menu guard.

Initial primitives are: click target/cell/bubble, press named button, press Space, select a card, close the current
card, and wait for settling. `steps.run()` is split so its rows can recommend the next primitive without executing the
rest of the row.

### Graph and detectors

- Supply clues and the coverage set, never the next action or a click gate.
- Every reading exposes provenance and freshness.
- Screen projection may create a provisional target hint. Only a positioned game event binds an actual graph node.
- Event/card evidence overrides graph hypotheses. Vision may settle a visible state but cannot invent node identity.
- Water need comes from bubbles/cards/events, not crop appearance.

### Deterministic policy

- Is pure and input-free: it returns `recommended_action`, confidence, reasons, and expected evidence.
- Encodes known game rules so the model can accept obvious choices quickly.
- Does not execute, ask vision, select a different target while a transaction is active, or mark coverage.
- For an unrequested empty bed, planting recommends any available seed. Every planted bed recommends watering unless
  it is raining. Ready `!` means collectible; flower policy still respects explicit crop authorization. A plant plus
  water-drop icon means dry or wilted and must be disambiguated by interaction evidence.

## Durable task and interaction state

One JSON-serializable task state survives CLI calls, daemon restarts, pauses, and vision:

```text
TaskState
  task_id, revision, goal, params, status
  targets, covered, unresolved
  active: Interaction | null
  last_experience, last_surprise, global_interrupt

Interaction
  transaction_id
  phase: approach | inspect | collect | remove | plant | water | verify
  provisional: {frame, point/cell, projected_node?}
  actual_node: null until a positioned event proves it
  crop, evidence_ids, completed_actions
  pending_intent: {turn_id, action, log_mark, written_at} | null
```

State is written atomically before and after every input. If a process dies with `pending_intent`, the next turn
reconciles the game log and current screen; it never blindly repeats the input. `actual_node` may be rebound only by
stronger event-position evidence. Target selection occurs only when `active` is null or verified complete.

## Turn contract

`./wf garden ...` starts or resumes a task and returns a `NEXT` turn without input. A continuation supplies a decision
and executes at most one primitive. The exact surface may remain compatible with `answer=`, but the data contract is:

```text
TurnContext
  turn_id, task, transaction, screen, frame_path
  visible_affordances, graph_clues, coverage
  last_outcome, surprise, interrupts
  recommendation: {action, confidence, reasons, expects}
  allowed_decisions

Decision
  accept | act <primitive and args> | look | correct <kind and data> | stop
```

`look` is intentionally not an input. It exposes/reads the already captured full-scale frame and returns to the same
turn. The model—not an engine helper—decides whether image reasoning is necessary. `accept` executes the exact
versioned recommendation for that `turn_id`; stale turn IDs are rejected without input.

## Garden domain behavior

The garden module supplies a coverage set and pure state rules, not a scheduler. One active transaction is completed
before another target is selected:

1. approach/inspect a visible bed or hive;
2. bind its actual node from the first positioned event, if one occurs;
3. collect ready non-flower crops (or explicitly authorized flowers) and ready honey;
4. remove wilted crops;
5. plant the remembered crop, requested crop, or any available crop when none was requested;
6. water after planting unless rain makes it unnecessary;
7. verify using event/card/bubble evidence, then mark that actual node covered;
8. clear the transaction and let the model select the next visible target or waypoint.

Pre-existing empty beds remain a task-policy choice: general “do the garden” plants them; narrower harvest/water jobs
do not. A target click is allowed only when the target and full visible walkable road are on-screen; otherwise the
recommendation is one short visible-ground waypoint.

Global interrupts are evaluated on every turn. Rain, darkness, or a new task after 19:00 recommends sleep and resume
next day; after 23:00 no optional action is allowed. An empty can recommends the refill subtask. Dialogue, pause,
cutscene, and unknown modal states prevent world input until resolved.

## Surprise and learning loop

Any mismatch between intent and evidence suspends automatic recommendation acceptance:

```text
non-model clues → model chooses whether vision is needed → model decision
→ one action → one Experience → integration → next turn
```

The surprise context contains before state, intended action, expected evidence, actual evidence, and artifact paths.
After optional vision, the model chooses one correction class. Existing `integrate.py` applies representable world,
memory/embedding, and transition updates idempotently. Unrepresentable behavior becomes a gap bundle; runtime never
patches code. A genuinely ambiguous application behavior is reported to the human instead of guessed.

## Logging

`runs/<run>/log.jsonl` is the single chronological action/reasoning log. Each `turn_id` joins concise rows for clues,
policy recommendation, model decision, optional vision, intent, outcome/experience, integration, and correction/gap.
`experiences.jsonl` remains a machine replay journal, not a second reasoning log. Retros use `log.jsonl` as their
timeline and follow experience IDs only for raw evidence.

Mutable learned data (`actions.json`, graph JSON, observations, embeddings) must not count as daemon source changes.
Only executable/configuration schema changes restart the daemon, so learning cannot erase in-memory process context or
add restart latency.

## Verification strategy

Prefer a small architectural suite over state-specific mocks:

- serialization, atomic replacement, stale-turn refusal, and pending-intent reconciliation;
- dependency tests proving atomic functions cannot invoke model/vision and garden policy cannot perform input;
- late event-owned identity binding and graph-source precedence;
- one captured replay of the real failure: target tulip → `!` bubble → Collect card → harvest event → Seeds card →
  Tulip selection → plant confirmation → water → verified coverage;
- one bounded live south-garden pass driven by a Luna-low child, with the parent watching `log.jsonl`.

Once the replay and live gate pass, remove tests whose only purpose is preserving the old hidden scheduler's internal
rungs, local dictionaries, or exact mock call ordering.

## Non-goals

- Removing stable graph nodes or replacing the world model with vision-only state.
- Inferring water need from crop appearance.
- Letting runtime code edit executable source.
- Building a fully autonomous non-model garden bot.
- Keeping compatibility with internal `tend_garden()` scheduler behavior; only the user-facing task command remains
  compatible.

