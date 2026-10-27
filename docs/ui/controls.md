# Controls (keyboard + mouse, macOS build)

> **Summary:** WASD move · **Space = interact/advance/confirm** · J journal · M map · Esc pause/close · mouse for UI
> buttons. Hold keys ≥0.2 s. No key-bindings screen exists.

| Key | Action | Status |
|---|---|---|
| W / A / S / D | move screen-up / left / down / right; two at once = diagonal | ✅ |
| **Space** | interact (plant, fill can at well, water, talk), advance dialogue/cutscene, confirm popups | ✅ (L19) |
| J | journal toggle | ✅ |
| M | map | ✅ |
| Esc | pause menu open/close; closes journal/map | ✅ (L20) |
| I | inventory; sections incl. **Tools** (Tools: watering can, axe…) and **Seeds** (Seeds) | ✅ |
| E | does nothing | ✅ (L19) |
| tool/item switching | ? | ❓ |
| Mouse left click | UI buttons (OK, hint, Select (EN ❓), seed cards, settings tabs). **Not** prompt bubbles, **not** "Resume Game" | ✅ |
| Mouse left click on the world | **click-to-move**: Tara pathfinds to the spot; on an object she stops in front of it with its bubble (no interaction). `./wf do go:x:y` (L49) | ✅ (Thu d4) |

Rules: hold keys about 0.2 s (`wf key` default) or the game drops them (L6). The game must be frontmost for input;
`./wf` focuses it per action and then gives focus back (L28).
