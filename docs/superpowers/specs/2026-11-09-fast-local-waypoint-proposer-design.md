# Fast local waypoint proposer

## Intent

Reduce navigation deliberation from 16–23 seconds to a few seconds by avoiding a separate full-frame model-vision
round trip on routine, visually familiar roads and floors. Luna remains the gameplay decision-maker. The local code
proposes bounded current-frame primitives; it never selects or executes one.

## Goals

- Add at most six ephemeral waypoint proposals to the same compact `NEXT` receipt.
- Produce proposals in well under 300 ms from the already captured full-scale frame and existing SQLite evidence.
- Let Luna choose a proposal using current graph location, route, landmarks, and the preceding outcome.
- Fall back to full model vision when the local evidence is missing, contradictory, or low confidence.
- Keep coordinates turn-local. Persist only immutable experiences and reusable scene-level appearance evidence.

## Non-goals and anti-goals

- No hidden route schedule, calibrated coordinate route, keyboard movement, or automatic click.
- No conversion of graph compass into screen direction without current visual evidence.
- No claim that a smooth patch is a road merely because it points toward the destination.
- No proposals from dark frames or recognized modals.
- No weakening of HUD, frame-boundary, lineage, trade, or modal safety checks.

## Chosen approach

Use successful historical waypoint experiences as positive appearance examples. Each `hit` experience with
`moved=true` already owns a source frame, click point, scene, and immutable provenance. Build a small cached scene
profile from color/texture descriptors around those proved points. On a current frame:

1. Sample a coarse grid outside HUD and object/interaction exclusion zones.
2. Compare each patch with the current scene's proved waypoint descriptors.
3. Reject high-edge/obstacle-like patches and candidates without a continuous chain of similar patches toward Tara's
   centre area.
4. Cluster nearby survivors and expose the best candidate per screen compass/range sector, capped at six.
5. Include confidence, screen compass/range, point, conservative patch bounds, profile experience IDs, and current
   frame/view IDs.

The graph route remains separate evidence. The proposer does not filter by graph compass because graph/world compass
and screen compass are not generally interchangeable. Luna receives both and chooses a candidate or requests vision.

## Alternatives considered

- A local vision-language model would preserve open-ended visual reasoning but adds installation/model lifecycle cost
  and is unlikely to guarantee three seconds on this Mac.
- Fixed radial/grid clicks are cheap but cannot distinguish road, grass, walls, water, or furniture and would recreate
  wrong-direction/no-move failures.
- Remote full-frame vision on every turn is the current behavior and is the measured 16–23 second bottleneck.

## Interface

Navigation `NEXT` gains:

```json
"waypoint_proposals": [
  {
    "id": "waypoint-0",
    "point": [820, 760],
    "box": [760, 710, 880, 810],
    "screen_compass": "SW",
    "range": "near",
    "surface": "road",
    "confidence": 0.91,
    "view_id": "view-...",
    "evidence_refs": ["experience-id"]
  }
]
```

An action may choose `candidate:"waypoint-0"` with `kind:"waypoint"`. Existing view binding resolves its point only
for the matching `view_id`. The action remains one explicit model decision and passes ordinary mechanical guards.

When proposals are empty, the receipt states a bounded reason such as `no_scene_profile`, `low_confidence`,
`disconnected_surface`, `dark`, or `modal`; the model follows the existing vector → vision → map cascade.

## Data and lifetime

- Training source: canonical SQLite experiences only; no JSON/JSONL state.
- Reusable state: a derived, rebuildable per-scene descriptor cache keyed by contributing experience IDs and image
  revisions. It is not authoritative world state.
- Current proposals: turn-local only and never copied into graph nodes or durable semantic location.
- A miss/no-move does not become a positive example. It is logged against the proposal for later calibration.

## Safety and ambiguity

The proposer runs only on coherent daylight gameplay frames. Candidate patches must be on-frame, outside HUD, clear
of current object/control/bubble exclusion zones, and connected to Tara's local surface by similar sampled patches.
Confidence below the calibrated threshold yields no proposal. A proposal is advisory appearance evidence; Luna can
reject it. A selected proposal that misses is a system failure signal and is excluded from future positive profiles.

## Verification

1. Unit fixtures: learned road/floor surfaces produce bounded proposals; grass/wall/HUD/object zones do not.
2. Provenance: every proposal references successful source experiences and the current view.
3. Stale view: a proposal cannot resolve on another frame/view.
4. Latency: proposal generation is measured and remains below 300 ms.
5. Live acceptance: from the current House porch context, Luna chooses from `NEXT` without opening the frame through a
   separate vision tool; model deliberation and the physical action call are logged separately. Continue gameplay only
   after the end-to-end turn improves materially, then re-run the Bed → Well acceptance route.

## Resolution spike (2026-11-09)

The same uncropped porch frame was tested through Luna at three resolutions with the identical waypoint question:

| Resolution | Luna elapsed | Answer | Confidence |
|---|---:|---|---|
| 1920×1080 | ~15 s | `(0.50, 0.84)` | high |
| 960×540 | ~13 s | `(0.50, 0.84)` | high |
| 640×360 | ~13 s | `(0.50, 0.84)` | medium-high |

Downsampling preserved the routine navigation decision but saved only about two seconds; remote model/tool latency is
the dominant cost. Use an uncropped 960×540 whole-frame preview for fallback navigation vision. Retain the canonical
1920×1080 source for maps, text, ambiguity resolution, vector creation, and evidence. Resolution reduction complements
the local proposer but cannot replace it as the three-second latency fix.
