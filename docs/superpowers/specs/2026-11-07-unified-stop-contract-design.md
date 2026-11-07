# Unified Stop Contract Design

## Intent

A user instruction to stop gameplay must leave no agent or local automation capable of issuing game input. It must
also leave the game unfocused, close the current run as stopped, and preserve enough evidence for a retrospective.

## Scope

- The supervisor owns managed quest/runner agents, durable-task termination, run closure, unfocusing, and final
  verification.
- `./wf stop` owns local automation: the `wf.py serve` controller (including its recording thread), live
  `runwatch.py --follow` processes, and the stale daemon socket.
- The game process itself is not terminated. Completed/offline report processes are not targets.

## Approaches

1. **Broaden only `./wf stop`.** Simple, but a shell process cannot interrupt managed Codex agents or safely close
   their orchestration state. This could falsely report a complete stop.
2. **Two-level stop contract (selected).** The supervisor interrupts managed work and closes the run, then invokes a
   verified local shutdown. This matches the actual ownership boundaries.
3. **Persistent PID registry.** More exact than process matching, but all launch sites would need migration and stale
   PID handling. It is unnecessary for the two currently owned local process types.

## Requirements

- `./wf stop` attempts every local target even when an earlier target is already absent.
- It removes the daemon socket after process termination.
- It verifies that no targeted local process remains and returns nonzero with their names if shutdown is incomplete.
- It never starts the daemon while stopping or verifying.
- A user stop takes precedence over recording preservation or retrospective work; those happen only after input-capable
  agents are interrupted.
- The supervisor verifies managed-agent state and local-process state separately before reporting that everything
  stopped.

## Non-goals

- Quitting Wylde Flowers.
- Killing unrelated Python, shell, monitoring, or Codex processes.
- Making `./wf stop` control the collaboration-agent service.
