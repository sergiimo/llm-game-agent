# Plan: map-vector-heatmaps

- **Goal:** give canonical graph nodes optional map-image representations and locate them with vector heatmaps
- **Done when:** Existing graph nodes can optionally name map examples, descendants inherit their nearest represented ancestor, labelled map points can seed image examples, a target heatmap can be generated, and focused tests pass without touching the paused D183 game.
- **Brief:** `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` §§3,5,10; `tools/objects/{graph,query,loop}.py`; `tools/nav.py` map vectors/heading; `tools/nav/map.json` landmarks.
- **Review:** Revised after user correction. There is one graph, not a parallel map graph. A minority of canonical nodes carry an optional map-example key; their crops and embeddings live in a dedicated vector store. Wiki text provides names/relations only, while `tools/nav/map.json` supplies the existing pixel labels. D183 remains paused and untouched.

## Step 1: Audit labels and define optional node representations
- **Do:** Verify whether the offline wiki contains image labels; inspect existing map screenshots and `tools/nav/map.json`. Put optional `map` metadata only on canonical represented nodes and resolve descendants through their graph ancestry. Remove the rejected transient map-node prototype.
- **Signal:** The audit distinguishes semantic wiki labels from image-level point labels; House and Garden are represented without duplicating Door, Stove, Well, or beds.
- **Done when:** One-graph schema and seed source are explicit.
- **Budget:** 0 game-input calls, 0 game minutes; 30 min coding.
- **If stuck:** Keep the module pure and pass map data/pin explicitly; do not open the live map to debug.

## Step 2: Seed examples and create heatmaps
- **Do:** Add a small map-vector module backed by the existing image-vector store. Crop represented nodes from a labelled map screenshot, embed them, resolve any target to its nearest represented ancestor, score one DINO patch grid, and render a similarity heatmap. Expose safe offline graph commands and add pure focused tests.
- **Signal:** `GardenBed#1` resolves to Garden; a synthetic feature grid peaks at the expected point; a rendered heatmap is written without adding graph nodes.
- **Done when:** `graph map-seed <image>` and `graph map-heatmap <node> <image> [output]` work against saved images.
- **Budget:** 0 game-input calls, 0 game minutes; 30 min coding.
- **If stuck:** Return no plan on missing pin/link and fall back to the existing vision question; never guess a bridge.

## Step 3: Document and verify
- **Do:** Update the object-navigation design and mechanics docs with one-graph optional map representations, the label provenance, and the later Tara-pin-to-heatmap compass derivation. Run focused tests and diff checks; do not resume the game.
- **Signal:** Documentation does not describe parallel spaces; tests and `git diff --check` pass.
- **Done when:** Code, tests, spec, and run report agree on the heatmap behavior.
- **Budget:** 0 game-input calls, 0 game minutes; 20 min verification.
- **If stuck:** Document any unimplemented live-map dependency explicitly; do not resume the game.
