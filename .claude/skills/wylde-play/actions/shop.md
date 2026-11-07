# Shopping and selling

> **Summary:** the model owns merchant navigation, inspection and each buy/sell confirmation. Observed financial
> surfaces require authority regardless of the declared goal. Completion needs exact signed inventory/money deltas.

Prerequisites: read shop hours/day and actual open/closed evidence, current stock and money, and the user's exact trade
scope. Enter root authorization at task creation. Never substitute another product, increase quantities, or infer a
spending budget. Exact item IDs come from game evidence, not display-name guesses.

Root task parameters support these generic bounds:

```json
{
  "authorization": {
    "sales": [{"item":"<authorized grown product>","quantity":3}],
    "purchases": [{"category":"<authorized category>","quantity_per_type":10,"max_spend":"available_money"}]
  }
}
```

Each sale is bounded by exact item/quantity; an optional `min_unit_price` sets a floor. Exact-item purchase rules remain
`{item,quantity,max_spend}`. A category rule authorizes the exact `quantity_per_type` for each model-discovered,
available item of that category. These values come from the user's task; runtime has no crop, honey or quantity-ten
constants. Numeric `max_spend` is a cap (category caps include all reserved purchases). Explicit `available_money`
authorizes captured starting money plus **verified, completed/resumed sale proceeds**, minus reserved purchases.
Later stale/high money readings cannot inflate this budget. Unknown starting funds cannot authorize that mode.
A child cannot grant itself root authorization.

Use an itemless root `shop` task to account for a multi-trade request, or preserve an authorized garden root while trading. Push one `shop` subgoal per item:

- Sell: `params:{trade:"sell",item:"<ID>",quantity:N}`.
- Buy: `params:{trade:"buy",item:"<ID>",quantity:N}` (`trade` defaults to buy). The child binds that exact item’s registered catalogue entry and a numeric `max_spend` from captured root funds plus completed/resumed sale proceeds minus reserved purchases. An explicit numeric `max_spend` can lower that ceiling. Omit it only when starting funds are known; the string `available_money` belongs to root authorization, never child params.

Follow navigation/region docs to reach the merchant. Opening a nonfinancial merchant interaction, inspecting an item, or adjusting a quantity is a separate turn. To inspect a shop card before its price/quantity is known, use `action:{kind:"select_card",label:"<exact visible item name>"}`. The primitive resolves that unique text; a supplied point cannot redirect a named inspection. Missing/ambiguous labels are refused. Read each resulting card; code never chooses
items, quantities, tabs or follow-up controls. On an observed Buy/Sell surface, unlabelled coordinate inputs and Space require
explicit authorized trade metadata under **every** declared goal. Prefer the exact visible Buy/Sell label; a coordinate
with both Buy and Sell controls is ambiguous and refused. Direction metadata cannot contradict the observed control.

One final purchase input carries `purchase:{item,quantity,price}`; one final sale carries
`sale:{item,quantity,price}`. `price` is the positive total debit/proceeds shown for that exact quantity. For example,
`action:{kind:"press",label:"Sell 3",sale:{item:"<ID>",quantity:3,price:12}}`. Observe actual labels/prices; do not reuse
these illustrative numbers. Root and child bounds are checked and reserved before input. A crash or ambiguous result
cannot spend or sell the same authorized quantity again.

Record each newly read catalogue page without pushing a child:

```sh
./wf play turn_id=<id> answer='{"kind":"catalogue","action":{"catalogue":[{"item":"<ID>","category":"<observed category>","available":true,"source":"<merchant ID/name>","page":"<catalogue page ID>","frame_path":"<current captured frame>","evidence_refs":["<current captured frame>"]}],"catalogue_complete":false}}'
```

The catalogue action has this shape (the same fields remain supported inside an actual item-trade push):

```json
{
  "catalogue":[{
    "item":"<exact item ID>","category":"<observed category>","available":true,
    "source":"<merchant ID/name>","page":"<catalogue page ID>",
    "frame_path":"<captured source frame>","evidence_refs":["<captured source frame>"]
  }],
  "catalogue_complete":true
}
```

The model must inspect the source frames, enumerate every page/type, classify availability/category, and set
`catalogue_complete` only after checking the whole catalogue. Frame references are validated against captured turn/
outcome frames or previously registered catalogue evidence. This operation records facts and issues no input.
Give both `source` and `page` for each new live observation. These are generic model-read identities, not hardcoded merchant capabilities; both fields are supplied together. Older entries without them use their captured frame as source identity. Raw per-source observations remain in `_shop_catalogue_observations` across restarts. The latest observation per source/page feeds `_shop_catalogue`, one exact item ID per row, available if any source/page currently offers it. An unavailable duplicate at another merchant/page cannot erase an available offer. A refreshed source/page supersedes only that source/page’s availability and retains its prior evidence in history.

Out-of-stock/wrong-category entries do not authorize purchases. New or changed observations invalidate completeness until the model explicitly accounts for them. Purchase reservations, per-type quantities and root completion use the deduplicated item union; do not buy the same type again at a second merchant. A category purchase subgoal's quantity must equal its
root rule's exact `quantity_per_type`; individual confirmations can be smaller batches within that total.

Capture stock and coins before/after. Purchase proof is inventory **+quantity**, money **−total price**; sale proof is
inventory **−quantity**, money **+total price**. Both sides must match. A complete sparse inventory snapshot can omit
zero-stock items; an absent item then means zero. Unavailable or explicitly incomplete readings cannot prove a trade.
Save-derived completeness/count/time provenance may lag: use read turns for fresh evidence, never model assertions.
Missing/wrong-signed deltas are surprises; correct/read or ask the human without repeating a reserved transaction.

Complete and explicitly resume every verified child. Itemless root completion checks the declared sale quantities and
exact purchases for every available discovered type; it also requires explicit catalogue-complete evidence for category
rules. Partial purchases cannot finish the plan. Only verified acquisition clears a matching typed seed-shortage
constraint. A sale never clears a seed shortage, and buying never marks a bed planted, watered or covered. Use a return
subgoal and inspect/finish each reopened garden bed afterward.

For a request spanning multiple merchants, verify each merchant’s actual Buy/Sell UI and inspect every relevant
seed catalogue. Offline references list Violet as accepting flowers/honey and Dahl/Lina as selling crop seeds;
these are navigation clues until observed. Do not create an itemless shop child solely to register a page: it lacks an item receipt and cannot complete. The zero-input `catalogue` decision changes no subgoal stack. Record merchant identity alongside frame evidence in the run notes.
Register each freshly inspected page in a versioned `catalogue` decision while its source frame is current; later frames
cannot retroactively authorize an unregistered page. Set catalogue completeness only after all relevant merchants
and pages are accounted for. Deduplicate exact item IDs across merchants: a request for ten of each type means
ten total per unique available type, including earlier reserved/verified purchases. Unknown money or insufficient
verified sale proceeds requires an explicit constrained/human outcome; do not lower quantities or inflate funds.

Money in the decoded save comes from the `Player` entry in `gameState.characters`, while inventory comes from
`gameState.player.inventory`. A bare `./wf play` can repair a missing initial-funds reading from the root’s
recorded original save path/count/time only. This zero-input migration preserves the task and pending turn,
records its provenance, and is idempotent. It never replaces known starting funds or rebases them from a later
balance. If that original snapshot is unavailable/mismatched, funds remain unknown and purchases stay guarded;
do not reset the task or declare runtime money manually.

Before pushing a trade child, inspect `NEXT.task.stack`. If the same bounded trade is already active, continue it;
do not repeat a manifest’s push merely because a new runner started. Bare `./wf play` resumes the existing stack.
An untouched or administrative duplicate can use the action index’s zero-input `cancel`; the cancellation guard
will reject reserved/partial trades, completed receipts or uncertain domain effects. Complete/resume verified
trades through their normal proof path. Cancelled children never count as verified trades or release reservations.
