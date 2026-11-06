# Screen: sleep

> **Summary:** Sleeping in Tara's bed (pink bed, left room of Gramma's farmhouse): zzz bubble -> yes/no dialogue -> overlay -> morning cutscene.

## Flow (verified day 2, Tuesday 20:20; D186 20:08: click the pink bed (visible object) → zzz bubble → click it → dialogue "Am I ready for bed? / Yes / Not yet" → `ui.press('Yes')` → D187 7:00 cutscene → `./wf advance`; leave the house: click the porch below the rail gap, then the steps)
- Tara's bed is the PINK one in the left room (the purple one is Gramma's: no bubble). A half-wall splits the rooms: go down
  through the porch side and approach the pink bed's foot from below, `walk up 0.2` -> `bubble@` with a "zzz" bubble.
- To leave after waking, every lower-wall segment carrying a porch railing is solid. Find the opening between two
  white posts with no railing, and use its position from the fresh frame (it starts far right from the bed and
  recentres as the camera follows Tara). Click through it onto the porch; if already on porch boards click the stairs
  below, then move beyond the porch until the house interior disappears.
- Space -> `dialogue | Yes, I suppose (EN ❓) / Not yet / Tara: Maybe it's time for bed? (EN ❓)` (top option highlighted).
  Space = "Yes, I suppose (EN ❓)" (yes).
- `overlay` (stuck-looking frame ~10s; Space advances) -> `cutscene` (house exterior, morning) -> dialogues -> Wednesday 07:00.
- Wake-up on day 3 triggered a story cutscene (dust/trapdoor, Gramma's moonflower tea) and the quest popup "Steeped in Mystery"
  (collect moonflower in the forest at night). Tara ends outside at the yard gate.
