# Retro 1: step 2 escalated (water the wilted beds), D148 8:30 pm

## What happened
Step 2 assumed "water wilted beds first" (docs/routines.md R1). Wilted beds can't be watered: the bubble is a tulip
with a drop, Space shows a card "This plant has wilted. You should remember to water plants every day" and logs
`> unplant me=Player target=GardenBed(Clone)`; no `> water` line, the plant unchanged. 30 calls, 80 game min, then
escalated as the plan says (budget 60 calls; escalated before it, correctly, on "plan doesn't fit").
Also on the way: porch → garden needed 2 vision answers; a click near the construction workbench opened build mode.

## Earlier fixes: did they hold? (retros/stuck-ledger.md)
- L75 stuck rule + vision step: ✅ the agent got from the porch to the garden with 2 answers, no loop.
- L76 plan + escalation: ✅ first escalation came at 30 calls with a clear report, not after 80+ like S1–S5.
- Plan review (mine): ❌ I passed step 2 although its key action ("water a wilted bed") was never verified.
  docs/routines.md even said "wilted first" without a ✅.

## Cause
An unverified assumption in the docs went into a plan step as if it were a fact. Bees: the beds ARE the flowers for
the hives ("Plant flowers nearby to encourage the bees"), so wilted tulips also explain the flat pollen.

## Fixes
1. Plan review rule: every step's key action must be ✅ in docs/actions.md or routines; an unverified one becomes its own
   small scout step ("try X once on one target, report"), with a tiny budget. (supervisor skill §3)
2. Docs: wilted bed facts (save + bubble + card + unplant log) in docs/routines.md and docs/actions.md A8.
3. Plan from step 2: decision for the user (unplant = destructive): replant the wilted tulips from the 26 bulbs.
4. Tool gaps (⏸, not blocking): `go:` "ALREADY THERE" while another bed's bubble is in range; build mode opened by a
   click near the workbench; bubble label `unplant` for the wilted bed.
