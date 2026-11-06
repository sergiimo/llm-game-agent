# Model-Owned Gameplay Loop Design

> **Summary:** invert gameplay control: the model owns the repeated observe → decide → act loop, while code supplies
> evidence, graph clues, safe atomic actions, deterministic recommendations, integration, and durable task state.

**Status:** approved in conversation, 2026-11-06. This supersedes the orchestration portions of
`2026-11-04-model-decides-next-move.md` and `2026-11-05-streaming-garden-design.md`. Their state brief, interaction
laws, immutable experiences, and integration boundary remain valid.

## Problem

The current engine lets `tend_garden()` own the workflow. It selects a target, chooses and runs transition rows,
keeps local `remaining` and `replanting` state, and asks the model only at selected gaps. The model can correctly see
and click a ready tulip, but the function that resumes later may have lost the active target, crop, phase, or card
state. It then closes the right card, navigates away, repeats an action, or reconstructs stale graph state.

This is not mainly a perception problem. It is a control-ownership problem: functions consult the model, instead of
the model running functions and consulting the graph. The first implementation corrected this only for gardening.
Legacy public commands such as `./wf sleep` still own multi-step navigation in Python, accept model-supplied waypoint
cells, and retry their private workflow without producing model-owned surprises or corrections. That split is not an
acceptable steady state: the model must drive the whole game, not selected domains.

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
finish several hidden steps. A cheap gameplay agent repeats calls until the returned task status is terminal. This
contract applies to every gameplay domain: navigation, entering/exiting regions, sleep, shops, dialogue, quests,
foraging, routines, gardening, inventory use, and future actions.

Public gameplay commands are a hard cutover to the universal turn interface. Existing implementations may remain
temporarily only as observation helpers or atomic adapters; no legacy public entry point may retain control of a
multi-input workflow.

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

A **model-invoked primitive** is coded Python, not prose. It accepts a structured model decision, performs at most one
input, and returns evidence. It never retries, navigates to another object, resolves a modal, or chooses a follow-up.
Examples are `click(point)`, `press(label)`, `space`, `close`, `select_card(name)`, `read`, and `wait`.

### Skills and action documentation

Every player-visible action and workflow is defined in text under the game skills/docs. The text states recognition
clues, prerequisites, legal primitives, expected evidence, surprise conditions, corrections, and completion proof.
Examples include enter house, exit house, reach bed, sleep, open shop, buy an item, talk to a character, and tend a
garden target. Skills may refer to graph/vector queries and primitives, but never hide a Python scheduler.

Code may implement reusable mechanics that are not gameplay decisions: parsing logs/saves, detecting affordances,
querying vectors, computing a route clue, validating a visible road, persisting state, applying a correction, and
issuing one guarded input. If code decides *what gameplay action comes next*, it violates this boundary and must be
converted into skill knowledge plus a model decision.

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

`./wf play <goal> ...` is the universal entry point. Domain aliases such as `./wf garden`, `./wf sleep`, and shop or
quest commands construct/resume the same durable task and return a `NEXT` turn without input. A continuation supplies
a decision and executes at most one primitive. The exact surface may remain compatible with `answer=`, but the data
contract is:

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

Subgoals do not escape the loop. For example, garden → no seeds → sleep → shop → buy seeds → return to garden is one
durable task stack. The active parent interaction and every subgoal phase survive calls and restarts. A subgoal may be
suspended or completed explicitly; it is never implemented by calling a hidden multi-step helper.

## Universal surprise contract

Every primitive outcome is compared with its intent. No movement, unexpected movement, wrong region, wrong modal,
wrong object, stale graph direction, failed vector match, missing expected event, or unexpected event produces a
model-visible surprise before another gameplay input. Movement alone is not progress unless it reduces the stated
goal or yields a relevant observation.

The next decision is restricted to `look`, `correct`, or `stop`. After optional full-scale vision, `correct` must
select one explicit result:

- revise the model decision without changing learned facts;
- update graph position/direction/region data;
- add/relabel/re-embed appearance evidence;
- update a learned transition expectation;
- mark a target or subgoal temporarily constrained with evidence;
- create a code/skill gap bundle;
- report an unresolved application ambiguity to the human.

Graph and vector correction are first-class task operations. A vision-confirmed object location can update its
appearance sample and relative direction/region edge while preserving the source frame and model rationale. A failed
route cannot silently keep its old graph edge. A failed detector cannot silently reuse its old embedding.

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

## Other domain behavior

Navigation code supplies candidate routes, directions, distances, detections, and visible-road validation. The model
chooses each target or waypoint. A waypoint result returns to the universal loop; route helpers never consume another
waypoint internally.

Sleep is a documented workflow: reach/enter the house, locate the bed from graph/vector/vision clues, interact once,
and verify `sleep_transition`. The Bed must have either current graph placement or appearance evidence. If neither is
usable, the model looks and records the missing graph/vector evidence before moving again. The old `sleep.py` loop and
`nav.reach()` ownership are removed from the public path.

Shopping is a documented workflow with a durable purchase subgoal: confirm shop hours, reach and enter the shop,
open the correct merchant UI, choose an explicitly authorized item and bounded quantity, confirm price, perform one
purchase input, and verify money/inventory change. Spending authorization and quantity remain in task parameters.

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
- captured whole-game replays for enter-house → locate-bed → sleep and shop → select item → buy, in addition to the
  garden replay;
- dependency tests proving public gameplay aliases cannot call legacy multi-input workflow drivers;
- one bounded live garden → sleep → shop → garden pass driven by a Luna-low child, with the parent watching
  `log.jsonl`.

Once the replay and live gate pass, remove tests whose only purpose is preserving the old hidden scheduler's internal
rungs, local dictionaries, or exact mock call ordering.

## Non-goals

- Removing stable graph nodes or replacing the world model with vision-only state.
- Inferring water need from crop appearance.
- Letting runtime code edit executable source.
- Building a fully autonomous non-model garden bot.
- Keeping compatibility with internal `tend_garden()` scheduler behavior; only the user-facing task command remains
  compatible.
- Encoding complete workflows as Python functions merely because their individual inputs are already guarded.
- Treating model vision as an occasional error callback owned by a legacy workflow.

