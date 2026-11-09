# Native gameplay owner trial

> **Summary:** Test a native Computer Use agent calling our engine for observation and single actions. Preserve world
> knowledge and learning while removing generated shell/JavaScript wrappers and mandatory full belief rewrites.
> Status: planned; no native integration or four-second performance has been demonstrated by this document.

## Intent and chosen approach

The user selected the direction: **native agent calls the engine; the engine never calls the native agent**.
The native owner observes, reconciles location, chooses actions, handles recoverable surprises, and owns the task.
The engine supplies a small world context, an image, atomic input, outcome verification and SQLite learning records.
The experiment must balance flexibility, reliability and speed on actual gameplay.

Approaches considered:

- **Selected for this trial:** native ChatGPT/Dot Computer Use owner plus compact engine tools. Tests whether the
  previously useful native interaction loop can benefit from the project's world memory without its verbose loop.
- Dedicated API controller with the same tools: a later comparison if native host integration or latency is limiting.
- Jev routine decisions plus general-model recovery: a later experiment; image accuracy and latency remain unmeasured.

Using Computer Use's screenshot/input library from the existing Luna owner does **not** establish that the native
ChatGPT/Dot owner was tested. Record the actual host, owner/model where exposed, and tool transport. Do not label
an ordinary Codex child or engine-to-model API runner as the selected architecture.

## Scope

Build only the bridge needed for a live comparison. Reuse the existing daemon, graph, pinned-save lineage, task
store, intent/experience/integration boundary, and live evaluation. No alternate world database, generic route
policy, new perception backend, learning redesign, or concurrent gameplay owners.

This is an explicitly authorized native-controller experiment despite R7's current default excluding a native
dependency. The trial target is about four seconds despite R3's existing three-second requirement. Report both
thresholds; neither default is silently changed or declared satisfied by this experiment.

## Native-facing interface

The selected host must expose these as actual named tools, rather than asking the model to write a wrapper:

- `wf_observe()` returns one fresh canonical frame plus the current context, without input. Use it at task start
  or when the current observation is unusable; ordinary actions already return the next observation.
- `wf_act(turn_id, action, objective?, location?)` accepts one primitive and optional short semantic changes. It
  returns the next canonical image, updated context and immutable outcome in the **same tool result**.
- `wf_note(turn_id, finding, evidence_ids)` records a bounded learning/gap observation without input. Existing
  integration still owns automatic learning; this tool makes unusual findings recordable without a new workflow.

The bridge is mechanical translation into the existing model-owned boundary. For example:

```text
wf_act(turn_id=7,
       action={kind:"waypoint", point:[1070,835]},
       objective="bypass counter south")
```

The waypoint primitive asserts that the owner has inspected its visible continuous walkable path. It adds
`walkable:true` and `expects:{moved:true}` mechanically. Target primitives similarly assert full visible approach.
The bridge supplies the source frame/evidence IDs, active goal and standard envelope fields. It must not infer a
semantic route or promote omitted location text to a newly confirmed fact. Keep existing pending-intent recovery;
stale IDs or uncertain delivered inputs must never be replayed. Non-navigation expectations remain domain-specific.

The initial trial supports the current navigation/modal primitives: waypoint, target, bubble, named press, space,
close and allowed menu keys. Coordinates are canonical 1920×1080 pixels. The native owner may inspect a map, choose
a new visible waypoint, or refresh observation when needed. It is not restricted to prerecorded coordinates.

Each result includes only: turn/frame IDs and the image; goal and relevant graph route/compass edges; likely
semantic location explicitly labelled as a hint or fresh evidence; usable current landmarks; preceding action
result; relevant modal, clock and constraints. Retain source-specific clock provenance. Never return the whole
run history or require the owner to rewrite unchanged state.

Keep the canonical full-resolution frame. The native host must display image content, not a base64 text blob or a
local pathname it cannot open. Metadata, detections and model input refer to that exact frame. Only the existing
daemon captures/actuates; the transport adapter must not create a second permission-bearing controller.

## Timing and acceptance

A cycle runs from receipt N being ready at the tool bridge to receipt N+1 being ready. This includes model/host
delay, any extra tool operations, input, settling and the next image/context. Where host delivery timestamps are
available, also publish the host-observed interval. Never equate a quick click or screenshot with a quick cycle.

Record per-cycle: observation readiness, call receipt, intent commit, physical input, settle/capture, context/image
packaging, next receipt readiness, input issuance and experience ID. Capture model request/first-output/tool-call
timestamps if the host exposes them; explicitly mark unavailable subdivisions unmeasured. Whole-cycle timing
remains mandatory even if the native host exposes no model internals.

Proposed promotion criteria (engineering targets, not existing results):

- Two complete Bed → Well → Bed trips from independent fresh task starts, with real endpoint proof and no human
  navigation instructions. At least 20 ordinary cycles total; repeat the actual task if necessary, not filler moves.
- Routine-cycle p95 at most **4.0 s**; publish p50, p95, maximum and count over both 3 and 4 seconds. This is an
  empirical small-sample gate, not a guarantee. Include no-moves, reads, recovery and correction turns in statistics.
- Also publish all-cycle timing and complete route wall time, with startup, sleep, loading, retro and user pauses
  attributed separately. Longer cycles remain visible; physical travel must not be hidden by returning early.
- One naturally occurring no-move/detour is recognized and corrected by the owner, without repeating the same
  blocked point or handing recovery to the supervisor. If none occurs, mark recovery untested and perform a separate
  bounded live detour/localization task; do not manufacture a known wrong click to collect a failure.
- One cold task restart begins at unknown location except a fresh confirmed sleep spawn; old location stays a hint.
- Every issued input has exactly one attributable intent/outcome; no unknown delivery, duplicate input, fabricated
  arrival, wrong-direction loop, unhandled modal, or autonomous movement at/after 18:00.
- One recorded finding survives observer/bridge restart without becoming an unverified static graph fact.

The trial can pass functionality and fail latency, or vice versa. Full promotion requires all three dimensions;
report partial results as such. A full block triggers retro; recoverable surprises stay with the owner. Freeze and
retro after each ten consumed turns, or earlier at the configured three-issued-no-move stuck threshold.

## Operational limits and artifacts

Keep branch `fix/gameplay-lineage-sleep-guards`; preserve existing dirty changes. No gameplay during plan writing.
Implementation uses one active gameplay owner and one existing Mac controller. Stop covers both ownership
boundaries. Never change user game settings. Plan return time so Tara is at Bed before 18:00; hand control to the
human if already late. Confirmed sleep starts a new fresh gameplay task.

Canonical structured records stay in `runs/wf.sqlite3`. Each task gets `runs/<task>/plan.md`, ordinary reports and
`retro-N.md`; the experiment's comparison report belongs under its initiating run and references both leg run IDs.
Keep full-size frames. Notes/decisions describe results and evidence IDs; no new JSON/JSONL trace or top-level retro
folder. The current Bed-to-Well eval already exists; add the reverse endpoint scenario rather than duplicate it.

## References

- `requirements.md` and `docs/architecture/runtime-store.md`
- Current measurements: `runs/20261109-0832-bed-to-well-reverse-live/retro-5.md`
- [OpenAI custom UI tools: image and text results](https://developers.openai.com/api/docs/guides/tools-computer-use-integration)
- [OpenAI latency guidance](https://developers.openai.com/api/docs/guides/latency-optimization)
