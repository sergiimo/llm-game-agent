# Screen: gameplay

> **Summary:** Free movement in the world with the HUD visible.

## Recognise
`wf state` mode `gameplay` (HUD template matched: pause button early, or journal button once 3 HUD buttons exist).

## Elements
- HUD, see [../hud.md](../hud.md).
- Interaction **prompt bubbles**: round cream badges with an icon above Tara/the target (sprout = plant, watering can = fill at well, potato + drop = water). `wf state` shows `bubble@x,y`.
- Empty can: a non-blocking top-left modal says **“Fill watering can at the Well”** with a grey drop. The exact proof
  is log `> out_of_water … target=GardenBed`; this means Tara reached/interacted with the bed, not that movement failed.
- Filled can: a non-blocking top-left notification says **“Rusty Watering Can”**. Exact success proof is log
  `> fill_watering_can … target=Well`.

## Actions
- Move: `./wf do go:<x>:<y>` (click-to-move, the only way, L54); then `key:space` at the `bubble@`.
- Interact with the bubble target: `./wf do key:space`.
- Open journal `J`, map `M`, inventory `I` (❓), pause `Esc`.

## Exit
—
