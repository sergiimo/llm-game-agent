# Retro 1: scalar bed state broke world projection

## Outcome
Step 1 stopped before movement or interaction. No new `> water` line appeared, the routine remained 5/12, and the
game was paused. This was a tool exception, not an L75 no-progress episode.

## Cause
`garden.Bed.state` is the crop-status string `"growing"`. `world.view.click_point` reused the generic attribute name
for an optional world `Entity.state` mapping and unconditionally called `.get('click_xz')`, raising `AttributeError`.

## Earlier fixes
- Exact action proof and step escalation held: the run did not count or retry a watering that never occurred.
- Immediate pause held, limiting the failed attempt to about ten game minutes.
- Existing simulated walk tests did not model a game-domain target with scalar `.state`; that coverage gap caused this.

## Fix
- Read `click_xz` only when the target state is a dict; otherwise project the target's own `(x, z)`.
- Added a walk regression test whose target has `state = "growing"`.
- Resume the same step from the unchanged 5/12 routine state after the focused tests pass.
