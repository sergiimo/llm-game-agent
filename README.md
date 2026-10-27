# AI agents playing Wylde Flowers

A toolkit and docs that let LLM agents (Claude Code) play **Wylde Flowers** (Apple Arcade, macOS) through a
command-line tool, plus a world model of the game written for agents.

- `./wf`: see and control the game. It takes screenshots, reads the screen with Apple's text recognition, sends
  keyboard and mouse input (moving uses click-to-move: `./wf do go:<x>:<y>`), and reads the game's own log and save.
  Code: `tools/wf.py`. Screen recordings with command captions: `tools/record.py`.
- `AGENTS.md`: the rules agents follow. Start there.
- `docs/`: quests (one file each, with verified steps), mechanics, UI screens, locations, and learnings.
- `.claude/`: agent and skill definitions. A supervisor dispatches quest agents, which send steps to action agents.
- `routes/`: recorded walking routes.

Requires macOS, the Apple Arcade build of the game, and Screen Recording + Accessibility permissions for the terminal.
Python deps: `.venv` with pyobjc (Quartz, Vision, Cocoa), Pillow, numpy, zstandard, imageio-ffmpeg.

## Credits / licences
- Wylde Flowers is © Studio Drydock. This is an unofficial fan project, not affiliated with or endorsed by them.
- `reference/wiki/` and the generated tables in `docs/` come from the Wylde Flowers fan wiki (Fandom), licensed
  **CC BY-SA 3.0**, and stay under that licence.
