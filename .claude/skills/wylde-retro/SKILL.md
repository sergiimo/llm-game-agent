---
name: wylde-retro
description: Use when reviewing or writing a retrospective for a Wylde Flowers run that was slow, stopped, over budget, unsafe, inconsistent, or formally stuck.
---

# Wylde Flowers run retro

## Core principle

A retro is an evidence audit, not a confident story. Separate facts, inferences, unknowns, and containment; recommend
the smallest change supported by the run.

Every human-readable retro belongs to exactly one task and is written as `runs/<task>/retro-N.md`. Never create or
update a top-level `retros/` directory or a repository-wide Markdown ledger. Cross-run recurrence is queried from
`runs/wf.sqlite3` and compared with prior run-local retros; SQLite remains the canonical structured history.

## Before analysis

- If the user stopped the run, first follow `wylde-supervise`'s terminal stop protocol. Do not start the daemon again.
- Otherwise let the game lose focus before off-game work so diagnosis does not consume game time.
- Work from the run directory without gameplay input. Do not use `./wf run report` for a stopped run because its
  wrapper may restart stale automation.

## Gather the evidence

Read the run's rows from `runs/wf.sqlite3`, then `plan.md`, `progress.md`, `decisions.md`, `watch.md`, prior
`retro-*.md`, and the relevant preserved full-size frames. Retired run-local JSON/JSONL files are not evidence
sources for new retros. If `watch.md` is missing or stale, generate it without the daemon:

```sh
.venv/bin/python tools/runwatch.py runs/<task>/ --report
```

Use ordered SQLite `run_events`, intents, observations, and experiences as the canonical timeline; Markdown artifacts
are projections or human claims to check against it. Report HUD/OCR, game-log, and save time separately. A
disagreement is a tracing gap, not a value to average.

For a Codex gameplay owner with an available local session trace, split external decision gaps using
`.venv/bin/python tools/owner_timing.py --session <owner-rollout.jsonl> --turns <first> <last> --write`.
It joins explicit tool call/result timestamps to SQLite and stores `model.owner_breakdown` timing events.
Report receipt-to-host-result, result-to-first-observable-model-output, first-output-to-tool-call, and call-to-command
separately. The middle two form an estimated model cycle including host/queue overhead; first observable output
is not a first-token timestamp. Request queue, image prefill, reasoning and generation cannot be separately timed
without additional host telemetry. Keep those fields unmeasured. Inspect metadata/timestamps only, not private
reasoning content, and avoid inferring pure API latency from the gap.
Optional `--call-parts` reports emitted text sizes and proportional generation-time estimates in separate
`model.call_generation_estimate` rows. These are not measured field-level timings; state the uniform-character-rate
assumption and validate any proposed savings with actual before/after owner-cycle timings.

## Classify before writing

Choose every applicable type: safety, budget, performance, docs/manifest, user-stop, or stuck. Call it **stuck** only
when the trace contains the canonical stuck event or proves the configured no-progress threshold. Zero moves, zero
clicks, a timeout, or a budget overrun is not stuck. Record a formal stuck episode in the current run's retro and
canonical SQLite events; compare recurrence by querying prior runs, never by maintaining a separate Markdown ledger.

## Build the explanation

Write the causal chain as:

```text
trigger -> failure mechanism -> propagated damage -> detection -> containment
```

Label every link **Observed**, **Inferred**, or **Unknown**. Distinguish:

- the trigger from the mechanism;
- containment from a root-cause fix;
- engine, runner, supervisor, plan/docs, and user actions;
- input status as **issued**, **refused before issuance**, or **unknown after delivery**.

Apply the same evidence discipline outside the chain: cite every metric and causal claim; label any claim that is not
directly observed. Do not leave confident prose elsewhere to contradict the labeled analysis.

Credit a user correction or stop to the user, not agent safety. Inspect test assertions before saying what they prove.

## Required retro shape

1. **Outcome:** goal, result, physical-input status, and who initiated the stop.
2. **Cost and clocks:** wall time, calls by available class, thinking gaps, game-time readings by source, and conflicts.
3. **Evidence:** compact timeline with event/experience/frame references; account for every vision request.
4. **Failure chain:** labeled facts, inferences, unknowns, and the earliest point the run should have stopped.
5. **What held / failed:** separate engine, runner, supervisor, plan/docs, and user behavior.
6. **Fixes:** one row per independent invariant with priority, smallest implementation, reason, acceptance test, and
   order. Do not split one invariant into several P0 architecture proposals.
7. **Retry gate:** the exact evidence required before repeating the gameplay task.
8. **Record updates:** current run's `retro-N.md`, canonical SQLite events, and shared docs/TODO for durable gaps.

Include system improvement suggestions for the user. Defer broader redesigns unless evidence shows the minimal
boundary cannot work.

## Red flags

- Calling a save timestamp the visible clock
- Calling a zero-move incident stuck
- Calling a user-forced stop an agent safety success
- Inferring a root trigger from a demonstrated failure mechanism
- Describing a test by its name rather than its assertions
- Recommending overlapping P0 fixes for one invariant

When any red flag appears, return to the canonical trace and narrow the claim.
