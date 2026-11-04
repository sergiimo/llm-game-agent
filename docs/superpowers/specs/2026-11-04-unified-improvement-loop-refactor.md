# Unified improvement loop: code refactor suggestion

> **Summary:** represent every attempted action as one immutable experience, then route its verified discrepancy to
> the smallest sufficient correction: world state, learned memory, transition knowledge or an offline code-change
> bundle. Unify the evidence protocol and lifecycle, not all responsibilities in one module.

**Status:** proposal, 2026-11-04. This document suggests a refactor; it does not change runtime behavior.

## Why refactor

The runtime already behaves like one improvement loop, but knowledge updates are spread across its layers:

- `act.py` captures a click and immediately learns bubble labels, vision answers and crop-card state;
- `steps.py` checks predictions and appends transition observations;
- `engine.py` applies event evidence to the world, creates unknown transitions and consolidates observations;
- `nav.py` updates appearance vectors and graph directions;
- `world.py` interprets proven events as object and agent state.

These are all valid reactions to the same interaction. The problem is that the interaction has no single durable
identity or integration point. It is therefore harder to replay, make idempotent, test update ordering, prevent two
layers from learning the same fact, or escalate an exact runtime discrepancy into the code factory.

The refactor should make this causal chain explicit:

    goal -> prediction -> action -> evidence -> verdict -> correction

It should not merge `act`, `world`, `learn`, `evals` and the code factory into a giant class.

## Shared experience record

Introduce one immutable record, tentatively in `tools/game/experience.py`:

```python
@dataclass(frozen=True)
class Experience:
    id: str
    goal: GoalRef
    before: Observation
    prediction: Prediction
    action: Action
    evidence: Evidence
    verdict: Verdict
    discrepancy: Discrepancy | None
    artifacts: Artifacts
```

The fields should contain structured data, not formatted explanations:

- `goal`: goal name, parameters, target node and transition row;
- `before`: relevant world state, visible affordances and screen mode;
- `prediction`: expected events, screen state, movement and state delta;
- `action`: the exact click, key or UI primitive that ran;
- `evidence`: log lines, events, positions, screen text, before/after affordances and frame references;
- `verdict`: hit, miss, unknown or unsafe;
- `discrepancy`: which prediction field differed and whether the system can currently represent the correction;
- `artifacts`: stable paths and hashes for frames, run logs and save excerpts.

`Experience.id` must be stable for a recorded attempt. Every consumer records that ID so replay cannot apply the same
state, vector or transition update twice.

## One integration boundary

After a primitive action settles, the engine should pass the resulting experience through one boundary:

```python
outcome = steps.run(decision)
experience = verifier.build(goal, decision, outcome)
correction = integrator.propose(experience)
integrator.apply(correction)
```

`integrator.propose` selects the smallest sufficient correction:

1. **Proven fact:** produce a `WorldDelta` for graph state or position.
2. **Recognition gap:** produce a labelled appearance example or graph relation.
3. **Behavior gap:** produce a transition observation, addition or revision candidate.
4. **Capability gap:** produce a `GapBundle` for the offline code factory.

A correction may contain more than one compatible update—for example, an event can both update a bed's state and
label the bubble that caused it—but those updates share an experience ID and are committed in a deterministic order.

Suggested order:

1. persist the immutable experience;
2. apply proven world facts;
3. record evaluation results;
4. apply or queue learned-memory updates;
5. emit an escalation bundle if the discrepancy remains unrepresentable;
6. persist the graph and transition journal.

If a later step fails, replay from the experience journal can complete the remaining idempotent updates.

## Module responsibilities after the refactor

### `act.py`: capture, never interpret

Keep input guards, the physical action, settling, burst frames and raw evidence capture. Move calls such as
`learn_bubble`, `learn_answer` and `observe_card` out of `act.click`. The actuator should not decide what an image or
event teaches.

### `steps.py`: execute and compare

Keep transition-step execution and expectation checking. Return structured checked fields instead of directly making
an append-only learning decision. During migration it may continue writing the current observation journal through an
adapter.

### `engine.py`: own the lifecycle

Keep goal selection, planning, subgoals and the main loop. Replace its current `_learn` helper with the integration
boundary. The engine should invoke learning but should not contain vector-store or transition-confidence policy.

### `world.py`: apply proven facts

Keep the rules that translate application events, save fields and cards into graph state. Accept a `WorldDelta` or
the evidence needed to derive one. World updates should remain deterministic and explainable by source.

### `learn.py`: propose knowledge changes

Consume experiences and return proposed vector, relation or transition updates. Keep agreement and contradiction
thresholds here. Where practical, make proposal generation pure and keep filesystem writes in the integrator.

### `evals`: score the same prediction

Record the experience ID, prediction fields and verdict rather than reconstructing another version of the attempt.
This lets evaluation, learning and code evolution agree on what was predicted and what happened.

### Code factory: consume unresolved experiences

The runtime must never patch live code. For an unrepresentable or repeatedly unresolved discrepancy, emit a
`GapBundle` containing:

- one or more experience IDs;
- the smallest recorded evidence needed to reproduce the failure;
- the expected invariant that was violated;
- the owning component inferred by the integrator;
- the current toolkit revision and relevant data-table versions.

The supervised coding process turns this bundle into a failing offline fixture, makes the smallest patch, runs the
offline suite, performs a bounded live smoke test and compares the benchmark. Only then does the patch become the
next runtime in the same loop.

## Confidence and safety remain different by correction depth

Unifying the loop must not give every correction the same authority:

| Correction | Gate |
|---|---|
| Proven current state | One authoritative event/save fact |
| New visual example | Application-labelled result; optional distance/quality checks |
| New graph relation | Successful observed traversal; confidence retained |
| New transition | Repeated agreement before general trust |
| Revised expectation | Repeated consistent contradictions |
| Code change | Failing fixture, offline tests, live gate, benchmark and supervisor review |

The shared protocol makes escalation continuous; the gates keep its consequences proportional.

## Migration plan

1. Add `Experience`, `Evidence`, `Verdict`, `Correction` and serialization tests without changing call sites.
2. Build an adapter from the existing `steps.run` result dictionary and click record to `Experience`.
3. Add an integrator that initially delegates to the current `_learn`, `learn.py`, `world.py` and `evals` functions.
4. Give every persisted observation and learned update an experience ID; make replay idempotent.
5. Move semantic learning calls out of `act.click` and navigation primitives into integrator consumers.
6. Replace direct `observed-steps.jsonl` writes with experience-backed transition observations.
7. Emit `GapBundle` artifacts for unresolved or repeated discrepancies and connect them to run retrospectives.
8. Remove adapters only after existing engine, law and object tests pass and a one-object live gate succeeds.

Each migration step should preserve behavior. This is an ownership and evidence-flow refactor before it becomes a
learning-policy change.

## Verification

The refactor is complete when:

- one action produces one experience ID referenced by graph, learning and eval records;
- replaying an experience produces the same proposals and no duplicate mutations;
- low-level actuators have no semantic-learning imports;
- expected, observed and learned values can be traced from one record;
- an unresolved experience can generate an offline fixture without manually reconstructing the failure;
- runtime code cannot invoke the patch/apply path of the code factory;
- existing offline suites and a bounded live smoke test retain their baseline behavior.

This yields one improvement loop in both the architecture and the implementation while preserving small modules,
different confidence policies and the safety boundary around executable code.
