# Shopping

> **Summary:** the model confirms hours, enters the merchant UI, selects one authorized item/quantity and buys with
> one explicit input. Only matching inventory AND money deltas verify acquisition and reopen seed constraints.

Prerequisites: shop hours/day from `docs/world/businesses.md` plus live open/closed evidence, current coins/inventory,
and explicit root-task authorization. Record authorization at task creation, for example:
`authorization:{"purchases":[{"item":"TulipSeed","quantity":2,"max_spend":20}]}`. Values are user-authorized bounds,
not defaults. A subgoal cannot grant itself spending authority.

Push `goal:"shop",params:{"item":"TulipSeed","quantity":2,"max_spend":20}`. Follow navigation/region docs to reach
and enter the shop. Inspect the merchant affordance, select the visible merchant control, read the item card and price,
and adjust quantity one explicit turn at a time. Use the actual named inventory ID, bounded quantity and total price.
Every purchasing `press`/`space`/card confirmation must carry `purchase:{item,quantity,price}` metadata; e.g. a visible
Buy control is `action:{"kind":"press","label":"Buy","purchase":{"item":"TulipSeed","quantity":2,"price":20}}`.
No code chooses an item, quantity, merchant icon or follow-up click. Do not use an old raw coordinate to buy.

The boundary checks root and subgoal limits and durably reserves quantity/spend before input. A crash or ambiguous
outcome cannot authorize the same spend again. Capture inventory and coins before/after; save-derived readings retain
save count/time provenance and may lag. Wait/read fresh evidence as needed; never fabricate a purchase from an item
label, money alone, or model-supplied result. Completion needs the authorized intent, exact acquired quantity and
matching total money debit. A failed/unproved purchase stays constrained; use correction or human resolution.

A closed shop, wrong item/quantity/price, unapproved spend, absent inventory delta, missing money delta or stale clue
is a surprise. Read the source frame and correct the decision/data or record a gap. `complete` on verified acquisition
removes only `reason:"seed_shortage",item:"<matching seed ID>"` constraints. Those beds return to remaining work:
they are never marked planted, watered or covered. Complete, explicitly resume, push/complete a return subgoal,
and resume the frozen garden interaction. Verify each bed's actual planting/watering afterward.
