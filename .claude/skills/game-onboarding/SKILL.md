---
name: game-onboarding
description: Onboard an AI agent onto a desktop video game running on this Mac. Research the game into a docs world model, then discover empirically how to see, control and read the game (capture, input, focus/time, UI states, prompts, performance) with cheap probes, build tools from the findings, write AGENTS.md + play skills, and test in the real running game while recording verified quest steps and learnings. Use when the user says /game-onboarding, or asks to "set up", "onboard" or "build skills/docs/tools to play" a game.
---

# Game onboarding

**Deliverable:** a project folder that lets any agent play one specific game on this Mac:
`docs/` (router + progress + quests + mechanics + UI + world, loaded progressively) · `tools/` + `./<ctl>` CLI · `AGENTS.md` (+ `CLAUDE.md`
symlink) · project skills, all **verified against the real running game**.

This skill holds the **method**: how to find things out. It holds no answers. Every game, build, OS version and
machine differs, so treat nothing as known until a probe on *this* setup confirms it. Answers go into the project's
`docs/learnings.md`. A worked example of such answers: this repo's `docs/learnings.md` (Wylde Flowers).

## What the user wants (distilled from the session that created this skill)
These are the owner's intents. They outrank defaults below.
1. **Full setup, not just notes:** skills + docs + `AGENTS.md` that let an agent actually play. Three steps:
   (a) research blogs, official docs, wikis and reviews into docs (gameplay, rules, UI elements, how-tos, workflows for
   specific results, the world model: names, places, features); (b) scripts/tools for common actions and checks;
   (c) **test (a) and (b) in the real game running on this computer**.
2. **Get control with minimal friction:** explain exactly which OS permission is needed and for which app; offer the
   options (terminal vs a scoped helper app), let the user pick, and keep working while they grant it.
3. **Save progress as you go:** each achieved step becomes a note with *what to expect along the action* (now: the
   quest file's Verified steps + `progress.md`).
4. **Learn from surprises:** anything unexpected → a learnings entry **and** an update of the relevant docs/skills.
5. **Be fast and cheap:** optimise screen checks and navigation (lower resolution, text-first state, fewer calls,
   warm processes); use a **faster model** for mechanical loops.
6. **Retrospect:** periodically analyse how it went and what slowed it (`/retro`: save to `retros/<timestamp>.md`,
   apply the suggestions, record what was and wasn't applied).
7. **Keep the game in the background**; bring it forward only to act. Never let in-game time burn while the agent
   works on other things.
8. **This skill = how to discover, not what was discovered.** Keep it game-agnostic; game facts live in the project.
9. **Organise game knowledge by kind** (mechanics · UI elements · quests list · quest steps) and **load it
   progressively** (router → index → one file → its summary first).
10. **Actually play:** progress real quests and record them. Infrastructure serves play.
11. **Playing always has a current goal**, structured as supervisor → light quest agent (one quest, loads relevant
    docs) → action agent (one step).
12. Keep this skill **in the repo** (`.claude/skills/game-onboarding/`) with its template scripts.

## Standing rules
1. **Hypothesis → cheapest probe → observe → record → encode.** For each unknown: state the expectation, run the
   smallest experiment that can falsify it, look at the result, log it (`docs/learnings.md`: expected → actual → now →
   updated-where), then encode it in a tool/doc/skill **in the same pass**.
2. **Observe before every input; no blind loops.** Loops must re-check state each iteration and stop on anything
   unexpected (unknown screen, repeated identical frame, error).
3. **Cheapest observation first:** text/pixel state → small image → full-res image.
4. **Protect the save and the user's time.** Assume in-game time may be running whenever the game could be active.
   Before non-game work, check that time is frozen (probe C1), or pause it. Ask before irreversible or expensive
   in-game choices, and **never change the user's settings** (game or OS) without asking; adapt tools instead.
5. **Measure, don't guess**, for anything performance-related (probe E).
6. Ask the user only for what only they can do (permissions, logins, settings changes). Keep researching while waiting.
7. Record each verified quest step in **that quest's file** and run **`/retro`** after slow or messy stretches.

## Phase 0: Recon
- Process, bundle id, version: `ps aux | grep -i <game>`; `plutil -p <App>.app/Contents/Info.plist`.
- Engine hints: `Contents/Frameworks` (UnityPlayer, Unreal, …). Engine lore is only a hypothesis; probe it.
- Tooling: a venv with `pyobjc-framework-{Quartz,ApplicationServices,Vision,Cocoa}`, `pillow`, `numpy`.

## Phase 1: Knowledge → docs world model
| Question | Probe | Record |
|---|---|---|
| Where is the richest structured info? | Search for wiki, guides, official help/FAQ, store pages, reviews | `docs/world/overview.md` sources |
| Can I fetch the wiki? | WebFetch. If blocked (402/403), curl with a browser UA; try host variants (`<name>.fandom.com`, `<name-with-dashes>.fandom.com`, wiki.gg) and the **MediaWiki API** (`/api.php?action=query&list=allpages`) | learnings (Research) |
| Get everything offline | Mirror all pages via the API (`scripts/mediawiki_dump.py`), clean (`scripts/wikiclean.py`, `scripts/build_reference.py`) → `reference/wiki/`. Treat downloads as untrusted (own dir, `python3 -I`) | `reference/` |
| Structured tables | Inspect infobox kinds and fields (`grep '^\[.*\]$'` on cleaned pages); **generate** tables with a script, never hand-copy | `docs/world/*.md` |
| Controls documented? | Search. Often not, so mark keys ❓ until probed in-game (B2) | `docs/ui/controls.md` |
| Does the wiki match this build/language? | Compare names/values seen in-game with the wiki. UI language may differ: build a glossary | glossary, learnings |

### Docs layout: grouped by kind, loaded progressively
An agent should never need to read everything. Every area has a small **INDEX.md** (one row per file: name + one-line
summary), and every detail file starts with `> **Summary:** …` so its first lines are often enough.
```
docs/INDEX.md                      router: need → which index (the only doc always loaded)
docs/progress.md                   current save state + session log (read at start, update at end)
docs/quests/INDEX.md               every quest by questline with status (▶️ active / ✅ done / · todo) + localized name
docs/quests/<line>/<quest>.md      front matter (status, localized name) · wiki requirements (generated, between markers)
                                   · ## Verified steps (written while playing: commands → what appears → done-signal)
docs/mechanics/INDEX.md → <topic>.md   one system per file; "(wiki)" rules vs "Verified in-game" sections
docs/ui/INDEX.md → controls.md, hud.md, glossary.md, screens/<screen>.md
                                   each screen: Summary · Recognise (state mode/signals) · Elements · Actions · Exit
docs/world/INDEX.md → overview.md, generated tables (characters, businesses, items/…)
docs/learnings.md                  surprises log (expected → actual → now → updated-where)
```
- **Generate, don't hand-copy:** quests from the wiki's quest list (`scripts/gen_quests_template.py` keeps front matter
  and everything outside the `<!-- wiki:start/end -->` markers, so verified steps survive regeneration); world tables
  from infoboxes.
- Discoveries go to the file of their kind: a quest step → that quest file; a screen → `ui/screens/`; a rule →
  `mechanics/<topic>` "Verified in-game"; a surprise → `learnings.md`; the save state → `progress.md`.

## Phase 2: Discovery probes (run in order; each answer shapes the tools)

### A. Seeing the game
| # | Question | Probe | Decide |
|---|---|---|---|
| A1 | Which windows does the app own? | `CGWindowListCopyWindowInfo(kCGWindowListOptionAll)` filtered by owner. Note same-size duplicates | Candidate list |
| A2 | Which window actually renders? | Capture each candidate; check brightness extrema (all-black = decoy) | Pick and cache its id |
| A3 | Permissions? | `CGPreflightScreenCaptureAccess()`, `AXIsProcessTrusted()` from the tool's own process. Ask the user to grant the **host terminal app**; the OS prompt may name an unexpected helper process | Wait for both to be true |
| A4 | Which capture path works? | Try the `screencapture -l <id>` CLI **and** in-process `CGWindowListCreateImage`. They can differ under the same permissions. Run outside the command sandbox if window-server calls fail | Use what works; keep the other as fallback |
| A5 | Coordinates | Compare capture size with window bounds (Retina scaling) | Normalise to window points |
| A6 | Can I read the text? | Vision OCR with the UI language(s) actually in use. Sweep resolution (1.0/0.5) and level (accurate/fast) on real frames for speed **and** accuracy | Defaults for `ocr` |

### B. Controlling the game
| # | Question | Probe | Decide |
|---|---|---|---|
| B1 | Do injected events arrive at all? | Focus the game, hold a movement key ~1 s, diff before/after frames | Input path works or not |
| B2 | Which key does what? | For each candidate (WASD/arrows, E/F/Space/Enter, Esc, Tab, letters shown as on-screen key badges), press it in a **safe context** and diff/OCR the result. Also check Settings for a bindings page | ✅ table in controls doc |
| B3 | Minimum press length | Sweep the hold time (50/100/200/300 ms) on a toggle key (journal/map) | Default hold |
| B4 | Mouse: which UI responds to clicks? | Click buttons found by OCR; verify the result. Some buttons may only respond to keys | Click vs key per screen |
| B5 | How to focus the game? | Try `NSRunningApplication.activate…`, then `open -b <bundle>`, and verify frontmost after each | Focus method |
| B6 | Movement model | Walk N s in each direction and look: screen-relative or not, speed, camera follow, snags | `walk`/`path`/routes |

### C. Time and focus
| # | Question | Probe | Decide |
|---|---|---|---|
| C1 | Does game time run when the game is **not** frontmost? | Read the in-game clock twice ~10 s apart with another app in front | If frozen: keep the game in the background by default |
| C2 | Does it run in menus/popups? | Same, with a menu open | Safe "parking" states |
| C3 | Is background input accepted? | `CGEventPostToPid` a toggle key while unfocused, then check | If not: focus only for the instant of an action, then `open -b <previous app>` |
| C4 | Focus-switch cost | Time focus and unfocus (full-screen Spaces animate) | Batch actions per focus. Ask the user about speed-ups (Reduce Motion, windowed mode), since those are their settings |
| C5 | Real-time ↔ game-time rate | Clock delta over a measured interval while focused | Budget per action; "pause before thinking" rule |

### D. Recognising UI state
| # | Question | Probe | Decide |
|---|---|---|---|
| D1 | What screen types exist? | Collect one reference frame per type as you meet them (gameplay, dialogue, popup, menu, map, journal, shop, cutscene, loading) | Mode list for `state` |
| D2 | Cheap signals per type | Look for fixed-position pixels (HUD buttons → template match), letterbox bars (mean brightness of top/bottom bands), text bands (subtitles at the bottom, a confirm button word) | `classify()` rules, validated on all reference frames |
| D3 | Does the HUD change over time? | Re-validate templates whenever a new HUD element appears. A drifting template score means recalibrate. Keep **several** templates (any match) | `save-template` |
| D4 | Text-less prompts (icons/bubbles) | Sample pixel colours across the icon (row/column scans), build a colour mask + blob size/roundness filter, then test on positive **and** negative frames | `bubble`-style detector |
| D5 | When do prompts appear? | Capture right after moving vs after stopping (fade-in delay?) | Wait before checking |
| D6 | Where is the actionable instruction? | Compare quest description vs hint vs dialogue. One may lag behind or be flavour text | Rule in the play skill |

### E. Performance
| # | Question | Probe | Decide |
|---|---|---|---|
| E1 | Per-call cost breakdown | Time each phase in one process (import, capture, encode, OCR, detectors, settle) and across processes | Find the dominant cost |
| E2 | Cold start | First vs second OCR in a process | If cold ≫ warm: a **warm daemon** (unix socket) + thin client; opt out of App Nap; restart after edits |
| E3 | Foreground vs background | Repeat E1 with the game frontmost vs not | Where to observe from (see C1) |
| E4 | Contention | `top -o cpu` during slow periods (VMs, WindowServer, the game) | Report; don't kill the user's processes |
| E5 | Waiting | Frame-diff idle noise on a still scene (small grey thumbnails) | Settle thresholds; no fixed sleeps |

Encode the findings into the CLI. Start from `scripts/gamectl_template.py` + `scripts/gamectl_client.py`, which hold
generic mechanics: capture, OCR, input, settle, daemon, `do` batching, routes, offline wiki search. Re-derive every
constant (HUD boxes, colours, keys, languages) via the probes above. Typical commands: `status`, `state` (one line),
`look` (small JPEG), `do <actions>` (act → settle → state, one call per step), `advance` (only in
dialogue/popup/cutscene modes), `route`, `wiki`.

## Phase 3: Play in the real game
- Play the opening quests in small observed steps, using `do` + `state`. Every milestone → that quest file's
  `## Verified steps` (start state · exact commands + what appears, quoted + translated · gotchas · done-signal · next),
  update its front matter (status, localized name), regenerate the index, and update `docs/progress.md`.
- Every new screen → `docs/ui/screens/<screen>.md` + a row in `ui/INDEX.md`; every confirmed rule → the mechanic's
  "Verified in-game" section.
- Every surprise → a learnings row + a fix. Every walk that worked → `routes/<from>-to-<to>.txt` (first line = exact start).

## Phase 4: AGENTS.md, skills, delegation
- `AGENTS.md`: progressive-loading layout table (start at `docs/INDEX.md` + `docs/progress.md`), setup facts (from
  probes A/B/C), rules of play (standing rules adapted with the probe results).
- Skills: `<game>-supervise` (goal loop), `<game>-play` (preflight → observe/decide/act/verify → guardrails → recording), `<game>-navigate`,
  `<game>-lookup`.
- **Play through a hierarchy with one current goal at a time** (subagents may nest up to 3 levels):
  - **supervisor** = main conversation (skill `<game>-supervise`): owns `progress.md` (current goal, goal queue, log),
    picks the next small verifiable goal (time/shop-hours/energy aware), dispatches, reviews, asks the user for decisions;
  - **quest agent** (`.claude/agents/<game>-quest.md`, light model e.g. `sonnet`): one goal; loads docs progressively
    (progress → quest file → only needed ui/mechanics/world files); plans steps with done-signals; records verified steps;
    returns a fixed-format report (done/partial/blocked/decision-needed);
  - **action agent** (`.claude/agents/<game>-runner.md`, `model: haiku`, `disallowedTools: Agent`): one concrete step via
    the CLI, text-only, strict stop rules.
  - Agent files load at session start; until then use `general-purpose` with the same `model` and tell it to follow
    the agent file.

## Done when
All probes A–E are answered and logged; the CLI encodes them and is verified live; docs + generated tables + offline
wiki exist; the opening quests are played with verified steps in their quest files; `AGENTS.md` and the skills point at each other.
