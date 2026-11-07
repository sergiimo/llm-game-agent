# Troubleshooting

> **Summary:** Recover the app from capture, permission, input, or stale-daemon failures.

- If capture or Screen Recording status fails, run `./wf stop` once and retry before changing macOS permissions.
- Warp needs Screen & System Audio Recording and Accessibility in System Settings → Privacy & Security.
- Run game-touching `./wf` commands outside restricted sandboxes so Quartz, AppKit, and CGEvent can reach the WindowServer.
- The app ignores the game's black secondary window and captures the non-black game window through Quartz.
- Keep the game paused before documentation or code work; focus-front mode otherwise lets game time continue.
- Use `./wf log` and `./wf save` before screenshots: they are authoritative quest, inventory, time, and event evidence.
