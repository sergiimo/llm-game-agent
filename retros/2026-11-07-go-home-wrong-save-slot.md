# Go-home wrong-save-slot retro

> **Summary:** A D4 Town navigation task safely stopped after fresh reads switched to a D219 Farm save slot and
> contaminated scene/vector clues; Tara never moved.

Canonical run evidence and the full retro are in
[`runs/20261107-1628-go-home/retro-1.md`](../runs/20261107-1628-go-home/retro-1.md).

The next navigation retry is gated on durable save-lineage pinning and a regression proving that cross-slot evidence
is rejected before scene, vector, or graph derivation.

## Suggestions returned to the user

1. **P0:** pin the root task to its initial save lineage.
2. **P0:** create one immutable observation snapshot shared by save, log, frame, vector, and graph consumers.
3. **P0:** refuse cross-evidence region/lineage mismatches before vector search, graph writes, or input.
4. **P1:** make the universal `play`/`turn_id` contract mandatory in navigation manifests and plan review.
5. **P1:** add a validated `./wf run resume` command and automatically unfocus on watcher safety alerts.
6. **P2:** preserve recording segments across daemon restarts and keep broad tests out of live gameplay.

## Follow-up: stop means all automation

The user reported a jumping cursor after the run was described as stopped. Gameplay clicks intentionally move the
real macOS pointer and park it at virtual game coordinate `(110,110)`; the quest agent was interrupted, but the
Accessibility-enabled `wf.py serve` controller was still alive.

The stop contract is now two-level and verified: the supervisor interrupts all managed quest/runner descendants and
closes the durable task/run, while `./wf stop` terminates the controller (and recording thread) plus live watcher
processes, removes the daemon socket, and reports any survivor as failure. The supervisor must verify both the agent
tree and OS process list before reporting stopped or starting a retro.

The full retro includes rationale, concrete fixes, acceptance tests, and the recommended implementation order.
