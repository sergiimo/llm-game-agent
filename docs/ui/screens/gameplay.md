# Screen: gameplay

> **Summary:** Free movement in the world with the HUD visible.

## Recognise
`wf state` mode `gameplay` (HUD template matched: pause button early, or journal button once 3 HUD buttons exist).

## Elements
- HUD, see [../hud.md](../hud.md).
- Interaction **prompt bubbles**: round cream badges with an icon above Tara/the target (sprout = plant, watering can = fill at well, potato + drop = water). `wf state` shows `bubble@x,y`.

## Actions
- Move: `./wf do walk:<dir>:<s>` / `path:` / `route:`; to reach an interactable: `./wf do bubble:<dir>`.
- Interact with the bubble target: `./wf do key:space`.
- Open journal `J`, map `M`, inventory `I` (❓), pause `Esc`.

## Exit
—
