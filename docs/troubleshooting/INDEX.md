# Troubleshooting

> **Summary:** Recover the app from capture, permission, input, or stale-daemon failures.

- If capture or Screen Recording status fails, run `./wf stop` once and retry before changing macOS permissions.
- Warp needs Screen & System Audio Recording and Accessibility in System Settings → Privacy & Security.
- Repeated “Warp would like to access data from other apps” prompts mean separate helper processes are reading the
  game container. Keep one persistent `wf` daemon; do not use `WF_NO_DAEMON=1` during live play. For persistent macOS
  approval, enable Warp under System Settings → Privacy & Security → Full Disk Access, then reopen Warp after the run.
- The daemon holds an OS singleton lock in addition to its socket. A stale-code restart must verify every old
  controller has exited before unlink/rebind; otherwise two processes can hold different Unix socket inodes at the
  same pathname and one may hang capture or repeat macOS data-access prompts.
- Run game-touching `./wf` commands outside restricted sandboxes so Quartz, AppKit, and CGEvent can reach the WindowServer.
- The app ignores the game's black secondary window and captures the non-black game window through Quartz.
- In `focus-mode front`, the persistent controller gives each settled gameplay receipt a sixty-second foreground
  lease. A next gameplay call cancels it; expiry activates Warp and freezes a slow model turn without starting a new
  permission-bearing helper. The following turn must read/resolve the exact Pause modal, never send a stale-frame
  waypoint. Lease expiry verifies Warp stays frontmost for three seconds through Unity's delayed focus bounce; a
  one-shot `open -b` is insufficient. SQLite `model.deliberation` measures the receipt-to-next-call gap and marks
  anything over three seconds a requirement violation. A fresh `restart=true` excludes the prior human handoff from
  that metric. Background mode hands focus back immediately.
- Use `./wf log` and `./wf save` before screenshots: they are authoritative quest, inventory, time, and event evidence.
- Runtime integrity: `sqlite3 runs/wf.sqlite3 'PRAGMA integrity_check;'` must print `ok`. Back up consistently with
  `sqlite3 runs/wf.sqlite3 ".backup 'runs/wf-backup.sqlite3'"` while the daemon is stopped.
- `save_lineage_mismatch` is a safe zero-input stop, not a navigation failure. Inspect the cited observation/profile,
  correct the active game/profile, then take a fresh read or stop; never rebind the run to a contradictory save.
- `no_coherent_profile` with a current low-day save beside an old high-day save can mean `Player.log` retained both
  playthroughs under one file identity. A backward jump of more than two game days starts a new log epoch; only the
  latest suffix is midnight-normalized and compared with save slots. A same-day 23:xx → 02:00 wrap is not a reset.
- A time-bounded shop run is not feasible merely because the shop is currently open. Before input, require the minutes
  until closing/last entry to cover all remaining navigation and transaction budgets plus 15 game minutes. With
  `focus-mode front`, activate Codex during off-game reasoning; otherwise an agent round trip can consume most of a
  shop window. Do not open Pause just for analysis.
- The bedtime `Yes`/`Not yet` choice is classified as a card. Its affirmative action is dedicated Space bound to the
  exact current-view `Yes` control id. Bare Space remains refused, as does binding Space to `Not yet`; do not replace
  the documented confirmation with an unbound key or coordinate click. A successful sleep normally emits
  `sleep_transition`, `advance_day`, `day_start_intro`, and `complete`; the latter three are allowed co-events, not a
  mismatch, and the next fresh save read must still prove the new day coherently.
- A world interaction may settle one frame before its expected modal appears. If the immutable outcome still shows
  the unchanged source mode and a following zero-input read shows the expected card/panel with no intervening domain
  input, reconciliation credits that delayed modal transition and clears the mismatch; never replay the interaction.
- Day-start generation may log the new day's forecast at the prior evening clock, then reset the same explicit day
  to 07:00. This is not the pre-AdvanceDay midnight wrap and must not be shifted forward another day; otherwise a
  valid D6 save is falsely compared against D7 and fails closed with `no_coherent_profile`.
- The first new-day background slot may still decode to the prior evening even after the same live log records
  `advance_day`, `[TIME] Day N`, and `day_start_intro`. Profile selection bridges only that explicit one-day transition,
  only forward, and only within 24 game hours; unrelated or multi-day stale profiles still fail closed. The
  involuntary pass-out variant `day_start_intro_late` is the same bridge only when all three markers are present.
- A full paper map whose pin is not colour-detected is still a map when the labelled paper/cloud header appearance
  vector matches. The header proves the modal; the pink pin only localises Tara. Do not downgrade such a frame to
  gameplay or issue a world click through it.
- A control-free frame can have unreadable HUD OCR even while the world is visible. After semantic map, pause, card,
  and menu checks, a positive Tara appearance-vector hit upgrades only an otherwise `unknown` frame to `gameplay`;
  never use OCR garbage such as a partial HUD label as proof of a modal.
- Movement phase-correlation must exclude the fixed HUD. Otherwise the clock/menu icons produce a strong zero-shift
  peak while the world camera visibly pans, falsely recording `moved=false` against a stale autosave position.
- A coherent day-start bridge does not make its stale evening position click-local evidence. Saved displacement may
  override image geometry only when both endpoint saves are operationally fresh for their observations; otherwise the
  next autosave can falsely credit the entire overnight relocation to the first morning click.
- Localization examples need stable context. Gameplay zoom is stable per scene, so calibrate a fixed source-pixel
  crop for that scene: the whole named landmark or the full object plus enough surroundings to disambiguate it,
  commonly 0.5–1 object width. Do not add arbitrary scale margins. If Tara occludes the identifying shape or the
  frame clips the object/context (the porch mailbox case), skip or region-disable that vector instead of storing a
  partial crop. Scale is stable per scene but viewing angle varies, so store a few clean angle exemplars at the same
  calibrated scale instead of growing one crop indefinitely. Use separate scene/state templates when stable views differ. Never relabel a broad house crop as
  `HouseDoor`; use a matching contextual landmark kind. Multiple hits for one unique node collapse to the strongest.
- Navigation decisions consume the deduplicated `navigation.localization.landmarks`, not every raw patch in
  `view.candidates`. Multiple Stove patches still form one Stove landmark; its relative direction to Tara is the
  localization evidence even when the landmark is elsewhere in the room.
- A labelled gap/threshold such as `HouseExit` is a spatial structure, not a bag of wall/board patches. Store the
  full opening crop with state `structure`; detection then correlates its aligned DINO patch grid in one existing
  frame pass. A high relative z-score is insufficient by itself: the structural window must also clear the absolute
  cosine floor, or ordinary floor/rug patterns can become the best bad match. The returned point must lie inside the
  unrailed gap. A rejected click remains an immutable experience and `appearance_attempt` fact on that graph node.
- If navigation appears to “know” an exact location but chooses a worse route, reject that metric inference. Route
  authority is the nested object graph's next `compass` + `near|mid|far` edge; screen coordinates identify one click
  in one frame only. Garden uses the same `navigate` child as a building. A waypoint from a garden/root task without
  that child is correctly refused with zero input.
- Apparent clock disagreement is not repaired by choosing one timestamp. `hud_hour` comes from the current frame,
  `log_time` from the action/event boundary, and `save_time` from the latest autosave snapshot. Refresh the source
  needed by the decision and keep its provenance; never copy save time into the live action clock.
- For navigation regressions, use `./wf live-eval start bed-to-well` after restarting the task at a fresh House+Bed
  clue. If bookkeeping starts late, it may bind to the immutable coherent `sleep_spawn` Bed clue from that exact
  still-active task and include inputs since that event; another task or static Bed graph row remains invalid. Play
  through the ordinary graph workflow, then `finish` and `report <id>`. The evaluation passes only
  with newer current visual Garden+Well evidence or a positioned Well interaction, and stores immutable checkpoints,
  bounded gameplay metrics, and start/finish revisions in SQLite. Different revisions mean the run exercised hot fixes
  and should not be presented as a single-revision baseline.
- If `NEXT.need.kind=vision` is followed by a durable `stop` without a `vision` or correction event, the failure is
  orchestration ownership, not an absent engine callback. The same primary gameplay agent must open `view.path`,
  resolve/correct the surprise, and continue. Do not delegate the turn to the exact-command runner. If evidence stays
  ambiguous, return `need-help` with the task active; `stop` is reserved for an intentional terminal outcome or an
  explicit user stop.
- A bounded `./wf do go:... --look` may legitimately need more than 25 seconds (pre-check OCR + up to 15 seconds of
  movement tracking + settle/final OCR). The daemon client deadline is 60 seconds as of D4; an exact 25-second
  `outcome unknown after request delivery` indicates an older client. Do not retry the movement blindly: inspect the
  action trace and full-size frame first, then restart/update the client before continuing.
