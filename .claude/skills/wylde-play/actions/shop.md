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

Use an itemless root `shop` task to account for a multi-trade request. Push one `shop` subgoal per item:

- Sell: `params:{trade:"sell",item:"<ID>",quantity:N}`.
- Buy: `params:{trade:"buy",item:"<ID>",quantity:N,max_spend:<this purchase cap>}` (`trade` defaults to buy).

Follow navigation/region docs to reach the merchant. Opening a nonfinancial merchant interaction, selecting a named
item to inspect, or adjusting a quantity is a separate ordinary turn. Read each resulting card; code never chooses
items, quantities, tabs or follow-up controls. On an observed Buy/Sell surface, coordinate inputs and Space require
explicit authorized trade metadata under **every** declared goal. Prefer the exact visible Buy/Sell label; a coordinate
with both Buy and Sell controls is ambiguous and refused. Direction metadata cannot contradict the observed control.

One final purchase input carries `purchase:{item,quantity,price}`; one final sale carries
`sale:{item,quantity,price}`. `price` is the positive total debit/proceeds shown for that exact quantity. For example,
`action:{kind:"press",label:"Sell 3",sale:{item:"<ID>",quantity:3,price:12}}`. Observe actual labels/prices; do not reuse
these illustrative numbers. Root and child bounds are checked and reserved before input. A crash or ambiguous result
cannot spend or sell the same authorized quantity again.

For each newly read catalogue page, a push decision may include:

```json
{
  "catalogue":[{
    "item":"<exact item ID>","category":"<observed category>","available":true,
    "frame_path":"<captured source frame>","evidence_refs":["<captured source frame>"]
  }],
  "catalogue_complete":true
}
```

The model must inspect the source frames, enumerate every page/type, classify availability/category, and set
`catalogue_complete` only after checking the whole catalogue. Frame references are validated against captured turn/
outcome frames or previously registered catalogue evidence. This operation records facts and issues no input.
Out-of-stock/wrong-category entries do not authorize purchases. Reuse recorded entries as needed; newly discovered
items invalidate completeness until explicitly accounted for. A category purchase subgoal's quantity must equal its
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
