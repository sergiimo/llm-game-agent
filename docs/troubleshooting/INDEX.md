# Troubleshooting

> **Summary:** Recover the app from capture, permission, input, or stale-daemon failures.

- If capture or Screen Recording status fails, run `./wf stop` once and retry before changing macOS permissions.
- Warp needs Screen & System Audio Recording and Accessibility in System Settings → Privacy & Security.
- Run game-touching `./wf` commands outside restricted sandboxes so Quartz, AppKit, and CGEvent can reach the WindowServer.
- The app ignores the game's black secondary window and captures the non-black game window through Quartz.
- Before documentation or code work, let the game lose focus so time freezes; do not open the in-game Pause menu merely for thinking.
- Use `./wf log` and `./wf save` before screenshots: they are authoritative quest, inventory, time, and event evidence.
- A bounded `./wf do go:... --look` may legitimately need more than 25 seconds (pre-check OCR + up to 15 seconds of
  movement tracking + settle/final OCR). The daemon client deadline is 60 seconds as of D4; an exact 25-second
  `outcome unknown after request delivery` indicates an older client. Do not retry the movement blindly: inspect the
  action trace and full-size frame first, then restart/update the client before continuing.
