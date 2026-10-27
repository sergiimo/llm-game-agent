# Screen: interaction-menu

> **Summary:** Action-choice bubbles over an NPC after pressing Space at their bubble (state mode `overlay | <NPC name>`).

## Recognise
`./wf state` prints `overlay | Hazel Wylde` (NPC name). Look shows the NPC with 2-3 round icon bubbles above
and a name plate with hearts at the bottom. Verified with Gramma (Hazel): mushroom+spoon (quest topic / hand-in),
speech bubbles (talk), potato (another topic).

## Actions
- The first (leftmost) bubble is already highlighted (orange ring); `key:left` changed nothing visible.
  Plain `key:space` selects it. The right-hand bubbles were not tried.
- Selecting the mushroom bubble ran the quest dialogue ("Did you find the mushrooms?") -> hand-in -> quest popup
  ("Gramma is making something with mushrooms. / Confirm") -> Space -> back to this menu.
- `key:escape` closes the menu back to gameplay (verified).

## Gotchas (run #6)
- Open the menu only when the NPC is standing still; a moving NPC cancels the interaction.
- The single bubble shown over an NPC *before* Space (e.g. a sprout) is not the whole menu; the menu lists the topics.
- The **quest topic** is the icon with an orange **"!"**, highlighted by default (Gramma: sprout). Her full menu had 4 icons: speech (talk), potato, swirl, sprout. The single bubble seen before Space is the quest topic.
- After a topic's dialogue + popups, **the menu reopens**: close with Esc.
- **Shopkeeper variant:** 2 icons, speech (talk) + **coin (trade → shop window)**. See [shop.md](shop.md). Verified with Lina.
