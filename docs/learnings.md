# Learnings — things that did not go as expected

A log of surprises found while building and testing the setup on the real game. Each entry: **expected →
actual → what we do now → where it's reflected**. Add a new entry whenever reality contradicts the docs, the
wiki or an assumption, then fix the affected doc/tool/skill in the same change.

## Environment & permissions
| # | Expected | Actual | Now | Updated |
|---|---|---|---|---|
| L1 | Screenshots work from the terminal | Warp had no Screen Recording/Accessibility; the first macOS prompt was named **"old"**, not Warp | Grant **Warp** in both lists. "old" can be ignored | AGENTS.md (Setup) |
| L2 | Granting Screen Recording makes `screencapture -l` work | `screencapture` still failed ("could not create image from window"), while **in-process** `CGWindowListCreateImage` in Python worked | `wf` captures via Quartz in-process, with `screencapture` only as a fallback | tools/wf.py `_capture_window_quartz` |
| L3 | Sandboxed shell can talk to the window server | Quartz/AppKit/CGEvent calls fail or return nothing inside the sandbox | Run every `./wf` call that touches the game **without the sandbox** | AGENTS.md |
| L4 | One game window | The app owns **two** 1920×1080 windows; one is always pure black | `wf` probes candidates, keeps the non-black one, caches the id in `.shots/.window_id` | tools/wf.py `game_window` |
| L5 | `NSRunningApplication.activate` focuses the game | Ignored on macOS 26/27 for background callers | Focus with `open -b com.studiodrydock.mayflower` | tools/wf.py `focus` |

## Input
| # | Expected | Actual | Now | Updated |
|---|---|---|---|---|
| L6 | An 80 ms key tap registers | Unity dropped J at 80 ms. It worked at 200–250 ms | `wf key` holds 0.2 s by default | tools/wf.py, ui/ |
| L7 | Walking in a straight line follows the road | Tara snags on lamp posts and stair edges and gate pillars | Side-step 0.5 s and retry; record working paths as `routes/*.txt` | quest to-grammas-house-i-go, routes/ |
| L8 | Need to find WASD mapping | WASD works, and the camera follows. Screen-relative directions | `wf walk/path/route` | ui/ |

## Game content & UI
| # | Expected | Actual | Now | Updated |
|---|---|---|---|---|
| L9 | Game UI in English (wiki names) | Game language is **Russian**. Quest names are localized differently (e.g. *From Bud To Spud* = **Крошка-картошка**) | OCR ru+en; keep a RU↔EN glossary; don't change the user's language | ui/glossary.md, wf.py `OCR_LANGS` |
| L10 | HUD shows clock/energy/money from the start | At game start only **pause / map / journal** buttons. After the farm arrival scene an **inventory (I)** button with **coins (50)** appeared. Still no clock/energy seen | Don't rely on clock/energy OCR early. `wf state` reads money from the inventory badge | ui/, wf.py `MONEY_REGION` |
| L11 | Cutscenes have readable dialogue subtitles | The farm arrival cutscene showed only camera pans (voiced, no text was OCR'd), then returned to gameplay with Tara and Gramma at the garden | Detect cutscenes by **letterbox bars**, not text; use `wf advance` (stops on gameplay or a stuck frame) | wf.py `classify/advance`, quest to-grammas-house-i-go |
| L12 | Journal quest text = what to do next | After arrival the journal's *Крошка-картошка* page read "Ты посадила первое растение. Молодец!" (You planted your first plant, well done), but the hint said "Чтобы посадить семена картошки, активируй взаимодействие с грядкой" (to plant, interact with the bed). The description can show a **later/flavour line**, while the **hint** gives the actionable step | Always click **Показать подсказку** (Show hint) for the actionable step | ui/, quest from-bud-to-spud |
| L13 | Interaction prompts are text ("Press E") | The prompt is an **icon bubble** above the target (sprout icon over the garden bed), with no text and no key shown | Interaction key still unverified (E is the guess). OCR can't see the prompt, so use `wf look` to spot bubbles | ui/ |
| L14 | Vision OCR reads every label | Tiny key badges (Esc/M/J/I) are skipped. Quest-row icons sometimes glue a letter onto the text ("УВ гости…") | Match on substrings; use pixel templates for HUD (`tools/templates/`) | wf.py `classify` |

| L19 | Interact = E (PC convention) | **Space** interacts (plant, fill can, water) and confirms popups. E does nothing. Clicking the prompt bubble does nothing | `wf key space` / `wf do key:space` | ui/, quest from-bud-to-spud |
| L20 | Clicking pause-menu "Продолжить игру" resumes | Click does nothing (twice). **Esc** closes the pause menu; J toggles the journal (Esc sometimes doesn't close it right after a popup) | Use Esc / J toggles, not menu clicks | ui/ |
| L21 | Settings has a key-bindings screen | Settings tabs: general (language, day speed, fishing timer, item tooltips, "no fish sticks"), sound, display (fullscreen, 1920×1080, MSAA, depth of field), achievements, help (reset tutorial, support). **No controls list** | Discover keys empirically, record ✅ | ui/ |
| L22 | HUD stays as first seen | After the first quest popups the **pause button was replaced by a clock widget** top-left (analog clock + orange ring + "Понедельник 10:00"). The HUD template stopped matching, so everything looked like "overlay" | Multiple HUD templates (`hud_pause`, `hud_journal3`); any match = gameplay; recalibrate with `wf save-template` | wf.py `HUD_TEMPLATES` |
| L23 | Dialogue is a dialog box | Dialogue = **subtitle line at the bottom** ("Бабуля: …", y≈1000). Quest updates are centered popups with **Подтвердить** (Confirm) | `wf state` modes `dialogue` / `popup`; `advance` presses Space only in those modes (+cutscene) | wf.py `classify`, `advance` |
| L24 | `advance` is safe | It kept pressing Space 5× on the new clock banner (unchanging overlay). Space also interacts in gameplay | `advance` now stops on any non-dialogue/popup/cutscene mode and on the 2nd identical frame | wf.py `advance` |
| L25 | Walking into a bed is harmless | Pushing into the empty garden bed for ~3 s **opened its planting panel** without Space (cause unclear) | `bubble:` walks in short steps and stops as soon as the prompt appears | wf.py `walk_until_bubble` |
| L26 | Prompt bubble appears while walking | Bubbles **fade in after Tara stops**, so checking right after a step misses them | Wait 0.35 s before each check | wf.py `walk_until_bubble` |
| L27 | Game time pauses while we think | **Time runs in gameplay mode even while the agent works on tools.** During a long tool session the day ran to 02:00 and Tara **passed out** ("Время вышло! Ты выбилась из сил…" + button "Хр-р-р") | **Pause (Esc) or leave a menu/popup open before any non-game work**. Day ends around 02:00 | AGENTS.md rules, wylde-play skill |

| L28 | We could send input to the game in the background | **The game pauses when not frontmost**: game time freezes (clock unchanged over 12 s) and it ignores keys posted to its pid (`CGEventPostToPid`) | **Background by default.** `./wf` focuses the game only for the instant of an input command, then gives focus back to the previous app (Warp). Game time runs only during actions; checks run on the frozen frame (fast). `WF_KEEP_FRONT=1` disables it | wf.py `ensure_front/release_focus`, AGENTS.md |

| L29 | `./wf state` tells the supervisor where Tara is | It has no location. The supervisor assumed "in the garden" while Tara was **inside the house** (woke there on day 2; the bubble was the bed's sleep prompt) | Supervisor orients with one `./wf look` at session/day start and puts the location in the brief | wylde-supervise skill |
| L30 | `find_bubble` catches all prompt bubbles | It **missed the potato+water-drop bubble** on the planted bed (screenshot showed it) | ⏸ Re-sample the colours from that frame and widen the detector; meanwhile verify with `./wf look` when `bubble` is absent | wf.py `find_bubble` (todo) |
| L31 | Quest agent delegates each step to the runner | The Sonnet quest agent did all 24 calls itself (faster to iterate on its own visual checks) | Accept for short goals. Delegate only long mechanical loops (dialogue chains, routes, repeated interactions) | wylde-quest agent §3 |

| L32 | Walking only moves Tara | A `walk right` once opened the **photo/camera** screen (Esc closes it). Cause unknown | If `state` shows an unexpected overlay after a walk: Esc, then continue | ui (todo: camera screen file) |
| L33 | Agents click in `look` image coordinates | `click` takes **game** coordinates (= look pixels / scale). An agent clicked at half scale | ⏸ add `./wf click --img X Y` (uses the last look's scale/offset) | tools/TODO.md |

| L34 | `state` shows quest progress | The gameplay fast-path OCR'd only clock/subtitles/money, so **tracker popups ("Древесина: 5/6") were invisible** and the agent miscounted | Full OCR by default (cheap in the background) + a `tracker:` field; clock OCR'd from its own crop | wf.py `classify`, `brief` |
| L35 | The supervisor learns what agents learned | The user's mid-run corrections to the agent (4 messages) never reached the supervisor's docs; the agent also left stale counts in its notes | Agents write raw notes only to the quest file and report GAPS incl. `[user]`; the supervisor owns the shared docs and the brief template | wylde-quest §5–6, wylde-supervise §3/§5 |

| L36 | (wiki tips) carry food/coffee and eat when low | **User: eating is expensive and gives little vs sleeping; the only good reason is same-day pushes like mining (keys reset when you leave the mine)** | Energy Strategy: default sleep; agents don't eat unless the brief says so | mechanics/energy.md, basic-actions, mining, wylde-quest, wylde-supervise |
| L39 | Agents find what they need in the docs on their own | They hunted, guessed, and the user had to correct them; gaps surfaced only at the end | **Manifest protocol:** the quest brief `Read:` lists every needed file/section/command; on a gap the child returns `need-help` and the parent fixes the docs and resumes it | wylde-quest §1/§4, wylde-supervise §3/§3b, quest briefs |
| L38 | Strategy goes in each concept file | Strategies span concepts (eat vs sleep vs mine vs chop) and were scattered across concept files and the supervisor skill | **One tips table** (`docs/tips.md`, tagged, sourced) + `./wf tips <tags>`; quest briefs carry tags | docs/tips.md, wf.py `tips`, quest briefs, agents |
| L37 | Concepts live where convenient | Energy facts were scattered (hud ❓, energy.md ❓ duplicate, basic-actions) and unreadable by tools | Convention: one concept file (Rules/Strategy/How to see/How to read/Verified), hud = visual + link, a `state` field per measurable concept (`⚡N%` added) | docs/INDEX.md Conventions, wf.py `read_energy` |

## Performance
| # | Expected | Actual | Now | Updated |
|---|---|---|---|---|
| P1 | Each `./wf` call is cheap | Fresh process per call: imports ~1 s + Vision model load **~5 s** on first OCR | **Warm daemon** (`wf.py serve`, auto-started by `./wf`, `./wf stop` to reload after edits) → `state` ≈0.3 s (game in background) | tools/wfc.py, wf |
| P2 | Full-res OCR is best | Half-res OCR is **3.5× faster and more accurate** for this UI font. Vision "fast" level can't read Russian | `OCR_SCALE=0.5` default; gameplay fast path OCRs only the clock/subtitle/money strips | wf.py `ocr_image`, `classify` |
| P3 | Screenshot cost negligible | PNG encode+decode of 1920×1080 = 0.5 s (1.2 s with the game in front) | In-memory `grab()` (CGImage → PIL); files only for `look` (JPEG) | wf.py `grab` |
| P4 | Speed same regardless of focus | **With the game in front everything is 3–10× slower** (game + WindowServer + a running VM compete for the machine): `state` ≈3 s, `do` ≈5 s | Accept for now. Batch actions per `do` call; prefer text checks; see retro ⏸ items | retros/2026-10-26-2116.md |
| P6 | Focusing the game is instant | Switching to the full-screen game's Space takes **3–4.7 s** (slide animation); switching back ~0.3 s. A `do` step ≈ 6–8 s, most of it the switch | ⏸ Options: macOS *Reduce motion* (Space switch becomes a fade) or the game in windowed mode on Warp's Space. Both are user settings, so ask first | retros/2026-10-26-2116.md |
| P7 | Actions are cheap in game time | Each `./wf` input call costs **~10–20 game minutes** (3–4 s focus switch at Normal speed ≈ 1 h 40 min/real min). The day-2 watering trip took 3 h 20 min of game time | Batch actions in one `do`; prefer routes; ⏸ the user's choice: Reduce motion / windowed mode / Relaxed day speed | retros |
| P5 | Fixed sleeps fine | Sleeps waste 1–2.5 s/step; change-detection with a high threshold hit its timeout | `wait_settle`: 2 consecutive still frames (diff<1.5 on 96×54 gray), poll 0.1 s | wf.py |

## Research
| # | Expected | Actual | Now | Updated |
|---|---|---|---|---|
| L15 | wyldeflowers.fandom.com is fetchable | That host returns 402/403 to fetchers. The **wylde-flowers.fandom.com** MediaWiki API answers (200) | Mirror via API (`tools/build_reference.py` + `wikiclean.py`) → `reference/wiki/` | 00-overview.md sources |
| L16 | Some site documents the PC/Mac keyboard controls | No public source lists keyboard bindings | Verify each key in-game; mark ✅/❓ in ui/ | ui/ |

## Process
| # | Expected | Actual | Now | Updated |
|---|---|---|---|---|
| L17 | Spamming Space through a cutscene is fine | User stopped a blind loop. Blind input can skip choices or wrong-click | Observe (cheap `wf state`) before every input; scripted loops must stop on anything unexpected | skill wylde-play, memory |
| L18 | Full 1920×1080 screenshots for every check | Expensive and slow | `wf state` (text only) first. Then `wf look` (960×540 JPEG, `--crop` to zoom). Full `wf shot` only when needed | skill wylde-play, AGENTS.md |
