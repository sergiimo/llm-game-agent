# Retro 1: bench B step 1 escalated (D149 12:50–1:50 pm)

Not a geometry stuck. (1) My S13 guard blocked clicks on the passive hive card (S17, fixed: `menu_open`). (2) The
step's signal "NEAR" was right — `farm-garden` is a map-only place (coarse ±26.6) — but the template didn't say NEAR
counts as done, and its 6-call budget left no room after (1).
Earlier fixes: L76 escalation ✅ (stopped at 8/6 calls, clean report). Eval: belief 0/3 (dead reckoning off by up to
13 units after the blocked clicks), click 6/7.
Fix: step 1 marked done by the supervisor (NEAR = done for map-only places); templates A/B: say "NEAR (coarse map
place) counts as done" and budgets +50 % for the baseline. Map-only places are a known weakness → M2/M3 (entities
learned with exact positions).
