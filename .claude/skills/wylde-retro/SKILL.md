---
name: wylde-retro
description: Use when reviewing or writing a retrospective for a Wylde Flowers run that was slow, stopped, over budget, unsafe, inconsistent, or formally stuck.
---

# Wylde Flowers run retro

## Core principle

A retro is an evidence audit, not a confident story. Separate facts, inferences, unknowns, and containment; recommend
the smallest change supported by the run.

## Before analysis

- If the user stopped the run, first follow `wylde-supervise`'s terminal stop protocol. Do not start the daemon again.
- Otherwise let the game lose focus before off-game work so diagnosis does not consume game time.
- Work from the run directory without gameplay input. Do not use `./wf run report` for a stopped run because its
  wrapper may restart stale automation.

## Gather the evidence

Read `plan.md`, `log.jsonl`, `progress.md`, `decisions.md`, `watch.md`, `experiences.jsonl`, and the relevant preserved
full-size frames. If `watch.md` is missing or stale, generate it without the daemon:

```sh
.venv/bin/python tools/runwatch.py runs/<task>/ --report
```

Use `log.jsonl` as the canonical timeline; other artifacts are claims to check against it. Report HUD/OCR, game-log,
and save time separately. A disagreement is a tracing gap, not a value to average.

## Classify before writing

Choose every applicable type: safety, budget, performance, docs/manifest, user-stop, or stuck. Call it **stuck** only
when the trace contains the canonical stuck event or proves the configured no-progress threshold. Zero moves, zero
clicks, a timeout, or a budget overrun is not stuck and does not enter `retros/stuck-ledger.md`.

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
8. **Record updates:** per-run retro, shared docs/TODO for durable gaps, and stuck ledger only for formal stuck.

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
