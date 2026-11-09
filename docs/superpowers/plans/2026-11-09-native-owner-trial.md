# Native Gameplay Owner Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking. The gameplay owner remains the selected native agent.

**Goal:** Determine whether a native Computer Use owner using compact engine tools can navigate reliably with
routine cycles around four seconds, while retaining graph localization and learning.

**Architecture:** The native agent calls observation/action tools and owns every decision. A thin host adapter
forwards data to the existing warm daemon, which executes at most one primitive and returns an image plus bounded
world context. SQLite remains the only structured run/state authority.

**Tech Stack:** Existing Python/macOS daemon, native host's supported tool transport, image/text tool results,
existing SQLite runtime and live evaluation. Choose a transport dependency only after Task 1 proves host support.

**Spec:** `docs/superpowers/specs/2026-11-09-native-owner-trial-design.md`

## Global Constraints

- The native agent calls the engine; the engine never calls the native agent.
- One owner, one Mac controller, one input at most per action tool, one canonical full-scale observation.
- Coordinates are canonical 1920×1080 pixels. Current-frame evidence controls the next action; history is a hint.
- Preserve pending-intent recovery, save-profile pinning, source-specific clocks and the Bed-before-18:00 limit.
- Native control and a four-second benchmark are trial exceptions; keep reporting the current three-second R3 limit.
- Live gameplay is acceptance. Offline checks cover only the bridge's input/recording contracts.
- Keep the current branch and dirty changes. No historical imports, broad refactor, Jev integration or model change
  during this comparison. Do not restart the daemon for documentation or learned-data changes.

## Review Focus

1. The actual native owner can call the engine; a renamed Codex/Luna wrapper is not a substitute (Task 1).
2. A refocus/modal or resized window cannot misdirect a world click; zero-input failures remain zero-input (Task 2).
3. Compact state changes do not make an old location fresh or credit an uncertain input as movement (Tasks 2/4).
4. Disconnect after delivery cannot duplicate input; stop terminates both owner and controller (Tasks 2/4).
5. Four-second results include decision, execution and observation, rather than only engine time or successful turns
   (Tasks 3/4). Graph progress must also match visible/event evidence (Task 4).

## Files and responsibilities

| File | Planned responsibility |
|---|---|
| `tools/game/native_bridge.py` (new) | Compact model tool request → existing turn decision; bounded receipt projection |
| `tools/native_tools.py` (new) | Host transport registration and image/text result packaging; no game controller |
| `tools/wf.py`, `tools/wfc.py` | `native` daemon RPC routing, physical-input receipt and existing focus/stop handling |
| `tools/game/play.py`, `tools/game/turn.py` | Only the smallest necessary support for optional semantic deltas; retain existing loop |
| `tools/owner_timing.py` | Match actual native tool events when exposed; retain explicitly unmeasured host boundaries |
| `tools/runtime/live_eval.py`, `tools/test_live_eval.py` | Add reverse Well → Bed scenario and reuse endpoint validation |
| `tools/test_native_bridge.py` (new) | Focused bridge behavior: one input, frame identity, stale/unknown delivery |
| `docs/testing/INDEX.md`, play/supervise skills | Final tested launch, owner, recovery and measurement instructions |
| `runs/<task>/plan.md`, `retro-N.md`, `comparison.md` | Live task plan, ten-turn review, experiment verdict |

## Task 1: Prove the native-host connection before refactoring

**Interfaces:** consumes the selected ChatGPT/Dot native owner and its actual supported tool registration; produces
a documented host/transport and one read-only observation shown to that owner.

- [ ] Inspect the selected host's supported custom-tool connection. Record owner identity, model if exposed,
  transport, image-result support and timing visibility in the initiating run's plan. Reuse the existing daemon.
- [ ] Expose only a read-only `wf_observe()` probe using that supported transport. It must return a rendered image
  and the same frame's goal/graph/current-location hint to the native owner. No click yet, no second capture helper.
- [ ] Ask the native owner to identify the visible scene, likely graph position and next route edge from this result.
  Inspect the exact preserved frame and event/source IDs. Record any disagreement as evidence.
- [ ] **Gate:** native owner successfully invoked the custom tool and could inspect both its image and context.
  A local pathname, inaccessible image, `noWindowsAvailable`, manual copy/paste, or generic Codex agent using the
  Computer Use library does not pass. Resolve safe in-scope integration problems; if the host cannot expose the
  interface, record the precise limitation and return that architecture choice to the user before Task 2.

**Expected:** one genuine native-to-engine observation round trip, zero inputs, verified native-visible context.
This probe decides the transport; do not install an MCP server or change host configuration speculatively.

## Task 2: Add compact observation/action tools through the existing daemon

**Interfaces:** implement `observe() -> Receipt`, `act(turn_id, action, objective=None, location=None) -> Receipt`,
and `note(turn_id, finding, evidence_ids) -> NoteResult` in `game/native_bridge.py`. The host exposes these as
`wf_observe`, `wf_act`, `wf_note`. `Receipt` carries image content plus turn/frame IDs, route, location evidence/hint,
current landmarks, prior result and relevant constraints. The note result does not consume or invalidate a turn.

- [ ] Add focused failing checks for the contracts not already covered by existing turn tests:
  `observe` issues no input; `act` issues exactly one primitive and reuses its outcome image; stale IDs and uncertain
  delivery issue no repeated input; an omitted location remains a hint rather than new localization evidence.
  Use real SQLite/turn components and substitute only Mac input/capture boundaries.
- [ ] Run `.venv/bin/python -m unittest discover -s tools -p test_native_bridge.py -v` and confirm the missing
  behavior is the cause of failure.
- [ ] Implement mechanical decision defaults: current-frame references, active goal, waypoint movement expectation,
  and semantic changes only when supplied. No required prose arrays or duplicated objectives. Let the native owner
  replace a short location/objective and recover from a navigation no-move atomically in the same action call.
- [ ] Add `wf native observe|act|note` daemon RPC routing as data-only requests; the host adapter calls it with an
  argv request over the existing socket, never generated/evaluated code. Apply existing issuance reporting,
  cancellation/stop and focus handling to this command family. The transport process never captures or actuates.
- [ ] Package the saved full-size frame as an image tool result with its context text. Register the compact schema
  directly so the owner emits a short tool call. Preserve map/modal primitives for open-ended recovery.
- [ ] Re-run the focused contract checks. Inspect test assertions for real input counts/frame provenance, rather
  than source-text or message-wording checks. Record unrelated existing failures separately.
- [ ] **Live boundary:** from a fresh known-screen receipt, native owner chooses one visible safe ground waypoint;
  verify actual input, movement evidence and that the returned image/context reach the same owner together. A
  refusal/loading frame does not count as the successful action boundary; recover safely and rerun it.

**Expected:** one compact native call → one tracked physical input → one usable next receipt. No shell/JS wrapper
generated by the gameplay model, no engine-to-model call, no standalone correction required for routine navigation.

## Task 3: Make the comparison measurable

**Interfaces:** existing `run_events` stores bridge timing events keyed by run/task/turn/experience; existing
`LiveEvalStore` gains scenario `well-to-bed` with start Farm/Well and destination House/Bed.

- [ ] Add the reverse scenario to `tools/runtime/live_eval.py`; reuse shared start/destination evidence rules.
  Extend `tools/test_live_eval.py` only for the new direction: static House/Bed graph knowledge cannot prove
  arrival; a fresh matching endpoint proof can. Keep the outbound evaluator unchanged.
- [ ] Persist `bridge.receipt_ready`, `bridge.call_received`, packaging duration and existing action/capture phase
  timings in SQLite. Link the native owner/transport identifier to the run. All records remain outside recursive
  model context. Don't add a second machine trace file.
- [ ] Extend `owner_timing.py` to recognize actual `wf_act`/`wf_observe` tool names and structured `turn_id`
  arguments where native host traces exist. If they do not, retain whole-cycle timing and mark model subdivisions
  unavailable. Never manufacture model-request or first-token timestamps from bridge receipt times.
- [ ] Report consecutive bridge receipt-ready intervals, engine phases, optional host intervals, action output size,
  p50/p95/max and counts exceeding 3/4 seconds. Include reads, misses, refusals and correction calls; partition only
  explicit startup, loading, sleep, retro and human pauses, also retaining unfiltered route wall time.
- [ ] On the live single-action probe, compare the reported interval with the original timestamps and check input
  counts against intents/experiences. A quick click without the model gap is not a passed timing test.

**Expected:** one reproducible end-to-end row per consumed turn, no double-counted nested phases or hidden delays.

## Task 4: Live flexibility, reliability and speed trial

**Interfaces:** same native owner, compact tools, ordinary task/run lifecycle and two route evaluation scenarios.

- [ ] Verify permissions/unlocked screen and user control; obtain a current clock. Start from confirmed Bed/sleep
  spawn, not a stale graph node. Create the reviewed run plan before input. Freeze the game during setup.
- [ ] Give the native owner one manifest: goal Well, return Bed, relevant graph/interaction docs, tool definitions,
  bedtime limit and ten-consumed-turn checkpoint. Keep engineering history and full docs out of repeated context.
- [ ] Run Bed → Well using ordinary model-chosen moves. Capture positioned/unique-affordance endpoint proof
  supported by the existing evaluator; seeing a Well somewhere in the graph is not arrival.
- [ ] Close the completed outbound root/run and start the return leg under the same native owner, linked by a
  shared experiment ID in SQLite. Run Well → Bed with fresh Bed proof. Do not push a new objective under a completed
  root; preserve the current run/task invariants.
- [ ] Freeze after each ten consumed turns, task completion/full block, or the formal three-issued-no-move stuck
  threshold. Reads/corrections do not reset that physical streak. Run retro, fix the smallest demonstrated cause,
  then rerun a clean affected acceptance round. A task restart starts with fresh unknown state.
- [ ] Exercise a naturally occurring detour/no-move and owner-led recovery; if absent, perform a separate bounded
  detour/localization task and mark the original run's recovery coverage accurately. No deliberate blind bad click.
- [ ] Restart the observer/bridge between attempts. Verify an experience-linked note remains queryable, the task
  gets a fresh observation, and an old location is only a hint. Exercise stop at a checkpoint and verify both the
  managed owner and local controller cease automation before continuing a separate trial.
- [ ] Complete a second independently started round trip, with at least 20 ordinary cycles across trials. If the
  route needs fewer turns, repeat the real task rather than adding filler. Start fresh after confirmed sleep.

**Expected:** complete endpoint proofs, no human route decisions, no duplicate/unknown inputs, no unhandled modal or
wrong-direction loop; recovery and persisted learning tested. At/after 18:00 hand control to the human and label
the attempt incomplete. No late autonomous recovery to force a benchmark pass.

## Task 5: Verdict and next architecture decision

- [ ] Write `runs/<initiating-task>/comparison.md`: actual owner/host, model if exposed, code revision plus dirty-diff
  identity, linked leg/eval IDs, route completion, inputs/no-moves/wrong moves, recovery steps, human interventions,
  context/output sizes and timing distributions. Include every failed attempt and unknown measurement.
- [ ] Compare with existing Luna-owner evidence as a historical baseline, clearly labelled non-matched. A causal
  speedup claim needs comparable fresh-start route attempts; don't compare one native screenshot with a full old
  action cycle. Do not restart the old controller merely to create another baseline when existing evidence suffices.
- [ ] **Promote only if:** both round trips and recovery/learning checks pass and routine-cycle empirical p95 is at
  most 4.0 seconds. Show the existing 3-second violations too. Treat a functionality-only or speed-only pass as
  partial; a small sample cannot establish a production reliability guarantee.
- [ ] If integration or model time fails: identify the exact limiting phase, then propose the dedicated API runner
  using this same bridge. If perception fails: preserve the failed images/evidence and fix that issue; consider Jev
  separately in shadow mode. Avoid stacking a second remote model before the native decision in this trial.
- [ ] Update `docs/testing/INDEX.md` and play/supervise skills with only the tested launch and recovery recipe.
  Record any proposed changes to R3/R7 explicitly. Keep the current production defaults until a verdict supports
  replacing them. Commit only this trial's completed changes if requested; never sweep the dirty branch into it.

**Current status:** plan only. No native host connection, engine code change, gameplay input or benchmark run has
been performed by writing this plan.
