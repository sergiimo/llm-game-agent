# Retro 2: bench B step 3 escalated (D149 1:50–3:40 pm) — baseline ends here

Step 2 (garden → well) worked in 1 call (learned place). Step 3 (well → ranch): `ruined-ranch` is a map-only place
that `nav.map_places_world` attributes to **Farm** (nearest pin pairs; RuralBeach has only 2 pins and a bad fit), so
the graph plans a walk to Farm (-9.1, -37.5) and never crosses into RuralBeach. Two coarse NEARs in the wrong scene,
then a manual click toward a road ended near the mine (`OnPlayerNearMine`) and a STUCK (false: she was moving,
marked miss). Eval in this run: belief 3/11, click 27/37, stuck 0/1, ask 1/1.
Earlier fixes: the vision step worked again at the hive row (1 answer). L72 map compass: superseded by the graph,
which trusts a wrong area for map places.
Cause: places known only from the map get their area from a guess (nearest pins). Fix → M2: entities carry the area
they were observed in (a place is in RuralBeach because she stood there in RuralBeach); a map-only place has no area
until observed, and routes to it go through the known exits. Ruling: the baseline stops here — no tool changes
during the baseline; legs 4–6 are measured after M3.
