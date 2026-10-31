# Retro 1: world-walk step 2 escalated (D149 7:00–7:20 pm)
Image (agent): Tara on the top-row bed; the hive row, hedge and fence between her and the well (upper left).
Live world (`./wf world route`): a good route existed — west along the beds, round the west end of the hives, north.
Cause (reproduced offline, test_covered_target_on_screen_walks_the_route): the well counted as on screen, every
candidate point near it was covered by hive sprites, `click_point` returned None and `walk` failed instead of using
the route. Fix: covered target → route waypoints; no point at all → NEED_VISION step instead of a dead end.
Also seen: the entity cache knows 5 of 8 hives (the rest not in this session's log) — partial obstacle map remains;
covered by the stuck → vision path.
