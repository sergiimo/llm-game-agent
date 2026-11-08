# Troubleshooting

> **Summary:** Recover the app from capture, permission, input, or stale-daemon failures.

- If capture or Screen Recording status fails, run `./wf stop` once and retry before changing macOS permissions.
- Warp needs Screen & System Audio Recording and Accessibility in System Settings → Privacy & Security.
- Repeated “Warp would like to access data from other apps” prompts mean separate helper processes are reading the
  game container. Keep one persistent `wf` daemon; do not use `WF_NO_DAEMON=1` during live play. For persistent macOS
  approval, enable Warp under System Settings → Privacy & Security → Full Disk Access, then reopen Warp after the run.
- Run game-touching `./wf` commands outside restricted sandboxes so Quartz, AppKit, and CGEvent can reach the WindowServer.
- The app ignores the game's black secondary window and captures the non-black game window through Quartz.
- Before documentation or code work, let the game lose focus so time freezes; do not open the in-game Pause menu merely for thinking.
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
- Day-start generation may log the new day's forecast at the prior evening clock, then reset the same explicit day
  to 07:00. This is not the pre-AdvanceDay midnight wrap and must not be shifted forward another day; otherwise a
  valid D6 save is falsely compared against D7 and fails closed with `no_coherent_profile`.
- A full paper map whose pin is not colour-detected is still a map when the labelled paper/cloud header appearance
  vector matches. The header proves the modal; the pink pin only localises Tara. Do not downgrade such a frame to
  gameplay or issue a world click through it.
- A control-free frame can have unreadable HUD OCR even while the world is visible. After semantic map, pause, card,
  and menu checks, a positive Tara appearance-vector hit upgrades only an otherwise `unknown` frame to `gameplay`;
  never use OCR garbage such as a partial HUD label as proof of a modal.
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
- For navigation regressions, use `./wf live-eval start bed-to-well` only after a fresh House+Bed clue in an active
  run. Play through the ordinary graph workflow, then `finish` and `report`. The evaluation passes only with a newer
  Garden+Well clue and stores its checkpoints, input/no-move counts, and start/finish revisions in SQLite. Different
  revisions mean the run exercised hot fixes and should not be presented as a single-revision baseline.
- A bounded `./wf do go:... --look` may legitimately need more than 25 seconds (pre-check OCR + up to 15 seconds of
  movement tracking + settle/final OCR). The daemon client deadline is 60 seconds as of D4; an exact 25-second
  `outcome unknown after request delivery` indicates an older client. Do not retry the movement blindly: inspect the
  action trace and full-size frame first, then restart/update the client before continuing.
