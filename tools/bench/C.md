# Plan: bench C — NPC and menus

- **Goal:** benchmark C (spec 2026-10-30 §7.2): find Violet's shop in Town and talk to her; measured by
  `./wf bench report` (questions asked, answers that worked, calls).
- **Done when:** a `[REL] Violet` or Violet dialogue line in the log, menu closed, back in gameplay.
- **Brief:** docs/world/businesses.md (Violet's Violets: Tue–Sat 9–17) · docs/actions.md (A12) ·
  docs/ui/screens/interaction-menu.md · .claude/skills/wylde-navigate/SKILL.md
- **Review:** template; run after M4 (question protocol), Tue–Sat 9–17 only; no buying or selling.

## Step 1: To Town
- **Do:** `./wf goto fountain-square`
- **Signal:** ChangeScene Town
- **Done when:** NEAR fountain-square
- **Budget:** 15 calls, 90 min
- **If stuck:** on `NEED_VISION step` Read the image, `./wf teach step X:Y`, re-run; 2 unhelpful answers → escalate

## Step 2: Find Violet's Violets
- **Do:** `./wf key m` (map: the flower shop), `./wf look`, walk there with `./wf do go:<x>:<y>`; at the door
  `./wf pos --learn violets`
- **Signal:** the shop sign / Violet on screen
- **Done when:** `violets` is a learned place
- **Budget:** 15 calls, 60 min
- **If stuck:** as step 1

## Step 3: Talk to Violet and leave the menu
- **Do:** docs/actions.md A12: `./wf do go:<Violet>` → `./wf do key:space` → interaction menu → the talk topic →
  `./wf advance` → one `./wf do key:escape`
- **Signal:** Violet's dialogue lines in `./wf log`
- **Done when:** gameplay mode again
- **Budget:** 10 calls, 20 min
- **If stuck:** a menu you don't know → `./wf state`, escalate with a look image (no buying/selling)
