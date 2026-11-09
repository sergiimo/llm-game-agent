# Sleeping

> **Summary:** the model enters the house, locates the west bed, interacts and verifies `sleep_transition` in
> separate turns. `./wf sleep` observes a universal turn; it never runs a bed-navigation workflow.

Prerequisites: sleep authorization (quest scope or the standing at/after-18:00 rule), current clock and region,
and a preserved parent interaction via `push:{goal:"sleep"}`. Load [regions.md](regions.md) if outside. Check graph
placement and Bed appearance samples against the fresh frame. If both clues are missing/stale, look and record the
named graph/appearance correction or gap before moving again.

After the sleep interrupt is pushed, its first route decision is always a zero-input `push` of generic `navigate`
with `destination=Bed`. The sleep parent does not accept a direct waypoint; attempting one is a schema refusal and
wastes the live turn even though it issues no input.

Outside click the visible entrance/porch. After entering the bed is west: Tara's pink bed is in the front-left room;
the purple bed is not hers. Choose one visible target/waypoint. Once the named sleep bubble is highlighted, Tara is
already in interaction range: use the `space` primitive bound to that current highlighted world affordance and expect
the bedtime card. Do not click across the bed/footboard merely to hit the bubble point. If the sleep bubble is visible
but not highlighted, approach only by a model-confirmed fully visible walkable road; a bubble never bypasses target
road safety. Inspect the bedtime prompt. When its affirmative `Yes` bubble is highlighted, confirm in the next turn with the dedicated
`space` primitive **bound to that current view's exact `Yes` control id**, for example
`action:{kind:"space",control:"control-0",expects:{events:["sleep_transition"],allowed_events:["advance_day","day_start_intro","complete"]}}`
(the id is observation-owned;
never reuse the example). Bare Space and a `Not yet` control are guard refusals on a card. Do not click `Yes`, look it
up as fresh text, or use `select_card`. Expected evidence includes the prompt
event (`sleep5` in the captured D212 interaction) and then `sleep_transition`; the latter is the completion proof.
`advance_day`, `day_start_intro`, and `complete` are normal accompanying sleep-transition events, not contradictions.
The engine supplies that known co-event allowance for a sleep goal even if the caller omits it; keep it explicit in
the model decision so the evidence contract remains readable.
Morning/spawn/day-change events support the next-day observation. Inspect each dialogue/cutscene before explicitly
continuing it.
After the morning gameplay frame is confirmed, restart the gameplay task before resuming its pre-sleep objective.
The confirmed `ChangeScene …/Bed` sleep spawn establishes exact graph node `Bed`; it is not merely a historical hint.
In the stable House graph, route from `Bed` east through `House/BedroomPassage`, then southeast to `HouseExit`.
Later proved navigation movement replaces the Bed origin normally. Never carry the pre-sleep navigation belief into
the new-day task.

Bubble expectations use text, for example `expects:{card:"<verified prompt substring>"}`, or `card:"?"` to read
an unknown prompt as a gap. Boolean `card:true` is invalid. Supply `visible_road:true` only for a freshly verified
target/road; the bubble does not bypass that guard. A highlighted world bubble uses Space without a road click.
Completion still requires the actual `sleep_transition` event.
A highlighted/ready unknown bubble is not automatically sleep: inspect both icon and owner. In the captured
D210 turn160 room view, `[728,488]` is a green jar/mug bubble over a white-haired NPC by the fridge, while Tara
stands beside the purple east bed. It is not proved to be a sleep affordance. Tara's pink west bed is bottom-left.
Do not replay that point; refresh the full frame and approach/identify the correct bed locally.

No sleep event, wrong bed, blocked approach, wrong modal or missing confirmation is a surprise. Read its captured
frame and choose the smallest correction. Do not resume a private `nav.reach`, click a guessed bed, or blindly retry.
Use `complete` only after the captured `sleep_transition`, then `resume` explicitly. The frozen garden crop/node/phase
must survive. Sleeping itself does not buy seeds, clear seed shortages, plant/water beds, or prove return to the garden.

If the Bed kind has zero samples, `reembed` cannot supply the missing appearance clue. After inspecting a fresh
frame containing Tara’s pink bed, use one provenance-bearing `appearance` correction with `op:sample`, `kind:Bed`
and the bed’s bounded full-frame box. Correct an existing graph edge only if its exact relation exists; never
invent world coordinates from a screen crop. A missing/invisible bed remains a gap until a fresh view supplies it.
