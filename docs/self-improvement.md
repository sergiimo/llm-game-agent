# Self-improvement loop (L56)

> **Summary:** every skill the tools use gets better from play the same way: **act → capture → label from the game's
> own ground truth → store when we were wrong or blind → verify → use**. Nobody hand-labels the common case; people
> review the uncommon one. `./wf learn` shows the current state.

## The pattern
| Step | Rule |
|---|---|
| Act | The agent acts as usual (`do act:<kind>`, `key:space`, `go:`). No extra calls for learning. |
| Capture | The tool keeps what it predicted and the evidence (bubble crop, Tara's activity, call times). |
| Label | Ground truth comes from the **game log**, never from our own guess: `> <performance> me=Player target=<obj>`, `[DAMAGE] … destroying`, `grab_item`, `[QUEST]`, `[STATS]`. A label the tool has never seen **creates a new class** named after it. |
| Store | Only when the prediction was **wrong or unknown** (that's where the information is). Skip near-duplicates; cap per class. Every addition goes to a log (`.shots/learned.log`). |
| Verify | `./wf learn`: classes, leave-one-out accuracy, recent additions, observed vs expected outcomes. The supervisor checks it in every debrief and deletes bad samples. |
| Use | The next prediction uses the new reference / number immediately (refs reload; the docs row is updated). |

## Where it runs now
| Skill | Prediction | Ground truth | Storage | Status |
|---|---|---|---|---|
| Bubble kind (what a prompt means) | `bubble@x,y:<kind>`, `act:<kind>` | next `> <performance> … target=…` after Space (aliases: grab_item→pickup, hit_rock→pickaxe, PlayerGardening→axe, water, fill_can, plant, sleep, routine_sign→info, *_trade→talk; anything else → its own name) | `tools/bubbles/<kind>/*.png` (auto, cap 30, dup < 0.15) | ✅ automatic |
| Action outcomes (hits, drops) | `docs/actions.md` **Expect** | run logs: `damage = HP … destroying` → hits; `grab_item` after it → pickups | `docs/actions.md` rows (supervisor edits from `./wf learn`) | ✅ reported; edit by hand |
| Movement (did Tara move / stop) | `go:` arrival, `still` | Tara tracker + `OnEnter/ExitBuilding`, `ChangeScene` | thresholds in `tools/wf.py` (`Tara.ACTIVE`) | manual tuning |
| Briefs, docs | quest brief Steps/Where | run log `issue` / `gap` / `decision` lines | quest files, `docs/world/locations.md` | supervisor debrief |

## Adding a new skill to the loop
1. Find the game-log line that proves the outcome (search `./wf log --tail 200` right after doing it by hand).
2. Make the tool record its prediction next to it (state line, run log).
3. Store only disagreements, report in `./wf learn`, and review in the debrief.
