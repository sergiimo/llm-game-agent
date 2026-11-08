# Model-Localized Graph Navigation

> **Summary:** Before choosing a navigation input, the gameplay model localizes Tara semantically from the current
> full-scale frame and a bounded graph slice, replaces its short-lived location belief, and derives the next visible
> road from that belief plus the graph route.

## Intent

Prevent visually plausible landmarks from replacing a known route. In the failed Farm-to-Town run, every receipt
contained `Farm -> Farm/LinkTown: SE, far`, but the model guessed that a bridge to the north led to town. The graph
was correct; the turn prompt did not require the model to localize Tara relative to visible graph landmarks before
choosing a road.

## Chosen approach

At task start and on every fresh navigation turn, give the model:

- the goal and the smallest relevant graph route/slice;
- the last semantic location as an explicitly weak hint, or `unknown` after restart;
- current-frame landmark vectors;
- the preceding action outcome.

The model must first replace a compact turn-local belief such as:

`Tara is west of Farmhouse and south-east of Mine; the Town link is south-east through Farm.`

It then derives the next objective from the graph route and selects one visible road or target that serves that
objective. The atomic decision persists the new belief and binds the one input to it. Screen coordinates remain
single-frame data and are never durable location state.

Localization follows a strict three-stage cascade:

1. If current-frame vectors are present, localize from those vectors and graph relations. Do not call model vision.
2. Only when no vectors are present, inspect the full-scale screenshot with model vision. If an identifiable unique
   graph object is visible, create its appearance vector with frame/crop provenance, rerun vector detection, and
   localize from that vector.
3. Only if localization remains unresolved after stage 2, request the outdoor map, use it to update the same semantic
   belief, close the map, and then move.

A returned localization vector is usable evidence. A wrong vector is a defect in vector labelling, detection, or
calibration and must be investigated there; navigation must not silently bypass it with model vision. The model must
not invent a landmark-to-destination relationship from appearance alone.

## Evidence precedence

The model reconciles all evidence; no semantic engine guard chooses the route. Stable graph connectivity defines
what nodes and edges exist. Current-frame vectors establish visible landmarks relative to Tara. Model vision fills a
missing vector before navigation. The map is the third-stage outdoor fallback. The last location is only a hint. A
current outcome proves whether the selected input moved Tara and whether the resulting frame supports the intended
semantic progress.

## Alternatives considered

- **Make graph compass a hard click guard:** rejected because world compass and screen projection differ and the
  engine would own semantic navigation again.
- **Always run model vision or open the map:** rejected because current-frame vectors are the fast primary evidence;
  vision is only for creating missing vector coverage, and the map is only the third-stage fallback.
- **Model-localized graph navigation (chosen):** keeps route reasoning model-owned while requiring an explicit
  localization result before each action and escalating only real ambiguity to the map.

## State and prompt boundary

The prompt carries only a bounded route slice, current-frame vector evidence, prior outcome, and one compact belief.
It does not carry the full graph, accumulated screenshots, recursive outcomes, or historical coordinates. A restart
begins with `current = unknown`; the prior location may be shown only as a labelled hint. The full screenshot enters
the model prompt only at cascade stage 2, when the current frame has no vectors.

## Success criteria

- A fresh Farm-to-Town task cannot describe a north/bridge objective while its own localization and graph route say
  the Town link is elsewhere.
- Each movement decision records screenshot-derived semantic location, graph-derived next edge, and the selected
  current-frame road.
- No-vector localization produces model vision and vector creation before any map observation.
- The map is used only as cascade stage 3 when vector-backed localization remains unresolved.
- Live verification reaches `Farm/LinkTown`; timing and every wrong/no-move action remain recorded in SQLite.
