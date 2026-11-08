# Sleeping

> **Summary:** the model enters the house, locates the west bed, interacts and verifies `sleep_transition` in
> separate turns. `./wf sleep` observes a universal turn; it never runs a bed-navigation workflow.

Prerequisites: sleep authorization (quest scope or the standing new-task-after-19:00 rule), current clock and region,
and a preserved parent interaction via `push:{goal:"sleep"}`. Load [regions.md](regions.md) if outside. Check graph
placement and Bed appearance samples against the fresh frame. If both clues are missing/stale, look and record the
named graph/appearance correction or gap before moving again.

Outside click the visible entrance/porch. After entering the bed is west: Tara's pink bed is in the front-left room;
the purple bed is not hers. Choose one visible target/waypoint. Once the sleep bubble is detected, click that bubble
with the `bubble` primitive and its fresh point; do not press Space for the initial world interaction. Inspect the
bedtime prompt. When its affirmative `Yes` bubble is highlighted, confirm in the next turn with the dedicated
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

Bubble expectations use text, for example `expects:{card:"<verified prompt substring>"}`, or `card:"?"` to read
an unknown prompt as a gap. Boolean `card:true` is invalid. Supply `visible_road:true` only for a freshly verified
target/road; the bubble does not bypass that guard. Completion still requires the actual `sleep_transition` event.
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
