# Plan: multi-active-arrival

- **Goal:** store every showing bubble as transient graph-node state, represent all bubble-active objects, connect a
  dynamic Tara node to them with relative directions, and let `goto_bed()` arrive at any matching active bed
- **Done when:** the object loop records `bubble={kind, point}` on every detected object with an available bubble,
  `goto_bed()` returns any matching active bed without first choosing an arbitrary member, transient state is not
  persisted, Tara has transient screen-relative `near` edges to active nodes, and focused regressions pass.
- **Brief:** user correction in this conversation · `tools/objects/loop.py` · `tools/objects/bubbles.py` ·
  `tools/objects/query.py` · `tools/test_loop.py` · object-graph navigation design §6–7.
- **Review:** scoped offline change; the game stays paused. Preserve strict bubble ownership where it is known, but
  represent all owned bubbles simultaneously. Do not use proximity to an unrelated unowned bubble as arrival.

## Step 1: Define multi-active arrival
- **Do:** read `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md`; trace all `ACTIVE` consumers and encode the invariant: each owned relevant bubble contributes one active
  `(node, region)`; arrival succeeds when at least one active node satisfies the query.
- **Signal:** tests cover multiple bubbles where the preselected/lowest-index bed is not active.
- **Done when:** failing regression expresses the live failure and expected active set.
- **Budget:** 20 min.
- **If stuck:** reduce to synthetic detections and bubbles in `FakeWf`; do not touch the live game.

## Step 2: Implement and verify
- **Do:** follow `docs/superpowers/plans/2026-10-31-objects-step3-loop.md`; change the loop's active state and arrival selection; run `tools.test_loop`, the `goto_bed` wrapper test,
  and formatting/static checks available in the repo.
- **Signal:** regressions and existing loop tests pass.
- **Done when:** no single-current-object dependency remains in the loop.
- **Budget:** 30 min.
- **If stuck:** keep the change local to `objects.loop` and report the incompatible consumer.

## Step 3: Update the model documentation
- **Do:** update `docs/superpowers/specs/2026-10-31-object-graph-navigation-design.md` and `docs/learnings.md`: replace singular active-object language and add the verified correction.
- **Signal:** docs say bubbles define an active set and distinguish active/reachable from the one selected interaction.
- **Done when:** code, tests, and design use the same invariant; end the run.
- **Budget:** 15 min.
- **If stuck:** document any unresolved identity ambiguity explicitly.
