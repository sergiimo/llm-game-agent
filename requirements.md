# Requirements

> **Summary:** canonical, persistent product requirements for the Wylde Flowers gameplay agent. Update this file when
> the user adds, changes, or removes a requirement; dated specs and plans must reference it and may not silently
> redefine it.

## R1. One gameplay owner

- One long-lived gameplay agent owns observe → reconcile → decide → act → verify for the complete task block.
- The same agent handles recoverable refusals, stale observations, no-moves, wrong directions, modal changes,
  delayed evidence, and replanning.
- The supervisor dispatches the goal, authority, and limits once. It receives control only when the task is done or
  the gameplay agent reaches a genuine full block that cannot be resolved with its tools or evidence.
- There is no per-turn, per-refusal, or per-correction supervisor handoff.

## R2. Minimal model-owned state and consistency

- Each turn gives the gameplay agent the current full-scale screenshot, a small state payload with source provenance,
  and the preceding action result.
- The gameplay agent—not a growing collection of engine guards—decides whether those inputs are mutually consistent
  enough for the next action.
- If reconciliation is needed, the gameplay agent replaces or corrects state before issuing the action in the same
  owned block. A routine correction does not escape to the supervisor.
- Durable state contains only stable facts needed across turns. Transient observations, screen coordinates, route
  hypotheses, clock readings, camera-relative beliefs, and other short-lived data remain turn-local evidence or hints.
- Updating durable state is exceptional. A fact is persisted only when its expected useful lifetime justifies the
  cost of validating and maintaining it.
- Engine checks are limited to irreducible mechanical safety and authorization invariants. Semantic consistency,
  route quality, evidence sufficiency, and recoverable variation belong to the gameplay agent.
- Graph, map, vectors, saves, logs, and prior state are evidence sources. None independently vetoes a model-owned
  decision merely because another source differs.

## R3. Turn latency

- Every live gameplay turn completes in at most 3 seconds end to end.
- Every sub-action and tool call within a turn is measured separately.
- Timing measurements are persisted in the canonical SQLite run data and exposed in the run logs, with enough
  attribution to identify which sub-action or tool consumed the budget.
- A turn exceeding 3 seconds is a requirement violation even if the gameplay action ultimately succeeds.
- Full-history report generation, graph rebuilds, broad vector scans, and other projections are not on the critical
  path. They run incrementally, asynchronously, or only when the gameplay agent requests them.
- Latency does not grow with run history.

## R4. Terminal supervisor retro

- The gameplay agent returns control to the supervisor only for a genuine `BLOCKED` result or a finished task.
- After either terminal handoff, the supervisor runs the retro skill.
- The retro reviews the canonical SQLite run history and the run's Markdown files.
- The retro checks the completed block for violations of every requirement in this file, including ownership,
  unnecessary refusals/escalations, state growth, and per-turn/per-tool latency.
- The retro reports evidence-backed violations and suggested system fixes to the human. It does not silently turn
  suggestions into implementation work.

## R5. Live-first verification

- Live gameplay is the primary behavioral verification and final acceptance gate.
- Every implementation round must exercise the exact behavior and acceptance boundary it claims to verify. Nearby
  observations, partial prerequisites, unit tests, or evidence that the new code loaded do not count as a passed round.
- Gameplay-model formatting, reasoning, orchestration, or tool-use mistakes are system failures to repair or absorb;
  they are never an excuse for an incomplete acceptance test and are not reported as the user's problem.
- A round remains incomplete until its acceptance test passes. If the attempt is invalidated before reaching the
  boundary, fix the test driver or interface and rerun a clean attempt.
- A failed live attempt is not kept alive as a supervisor-driven debugging session. The gameplay owner diagnoses and
  recovers within its block when safe; a contaminated acceptance attempt is ended and restarted cleanly.

## R6. Model-localized graph navigation

- Every navigation turn gives the gameplay model the goal, the smallest relevant graph route/slice, current-frame
  vector landmarks, the preceding action result, and the last semantic location only as a weak hint.
- Before choosing an input, the model replaces its short-lived semantic location, for example:
  `Tara is west of Farmhouse`, based on current-frame vector landmarks and their graph relations.
- The model derives the next objective from that current semantic location plus graph connectivity, then selects one
  current-frame visible road or target that serves the objective.
- A task restart begins with unknown current location. Historical location is never silently promoted from hint to
  fact, and screen coordinates are never durable location state.
- Localization uses this strict cascade: (1) existing vectors plus graph; (2) only when no vectors are present, model
  vision on the current full-scale screenshot, creating a vector for an identifiable unique graph object and then
  localizing from it; (3) only if localization remains unresolved, observe the outdoor map, update the same semantic
  belief, close the map, and then move.
- At or after 18:00, ordinary gameplay stops: immediately begin the return-home/sleep workflow or explicitly hand
  control to the human. Existing vectors remain readable but no vector may be created, updated, calibrated, or retained
  from the dark frame. Defer that learning until daylight. When existing vectors do not localize the dark scene,
  current-frame model vision may localize and choose one visible-road step, but only for the active return-home/sleep
  objective and without persisting the observation as a vector.
- A returned localization vector is usable evidence. If it is wrong, that is a vector-system defect to investigate
  and fix; the navigation loop must not silently bypass it with model vision.
- Gameplay zoom is stable within each scene, so localization-vector crop geometry is calibrated per scene in
  source-frame pixels; it does not need zoom-invariant margins. Prefer the whole landmark or the complete object with
  enough fixed surrounding context to disambiguate it (often about 0.5–1 object width, measured for that scene).
  If Tara occludes the identifying shape, the frame clips it, or that scene's required context is unavailable,
  skip/disable the vector for now instead of storing or returning a partial match. Different scene zooms or stable
  visual states or viewing angles use separate clean scene/state/angle exemplars rather than one scale-agnostic crop.
  Do not keep enlarging one crop to cover angle variation; retain the same scene-calibrated scale and collect a few
  unobstructed views whose surrounding geometry represents the angles actually seen in that scene.
- Several patch hits for one graph-unique landmark are one landmark observation; expose only the strongest usable hit
  so context patches cannot masquerade as several independent localization facts.
- A visually plausible landmark must not be treated as the destination route merely from appearance. The failed
  Farm-to-Town pattern—graph says south-east while the model invents `north toward the bridge`—is a requirement
  violation, not a valid visible detour.

## Conflicts and precedence

These requirements supersede conflicting historical specs and plans, including guard-heavy semantic refusal,
restricted post-surprise decisions, large durable interaction state, and supervisor-mediated or CLI-call-per-turn
orchestration. Historical documents remain evidence of prior decisions, not current requirements.

## Requirements still to settle

- The minimal stable state schema.
- The small, explicit list of irreducible engine checks.
- The definition of a genuine full block.

