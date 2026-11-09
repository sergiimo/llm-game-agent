# Tail Latest Run Decisions

## Intent

Provide one short command that follows the human-readable `decisions.md` projection for the current gameplay run without starting the game daemon.

## Behavior

- Add an executable root-level `tail-run` script.
- Select the run recorded in SQLite's `active_run` table.
- If no run is active, select the newest run recorded in SQLite so the command remains useful after a run ends.
- Resolve the selected run's stored directory and follow `<directory>/decisions.md` with `tail -f`.
- Exit with a clear error if the database has no runs or the selected run has no `decisions.md` yet.

## Constraints and Non-goals

SQLite remains the authority; directory timestamps and lexical filename ordering are not used. The script does not start `wf`, touch the game, regenerate reports, or switch to a newer run while it is already tailing.

## Approaches

The selected approach queries SQLite directly, which is deterministic and has no game-side effects. A `./wf run ...` wrapper was rejected because it may start the daemon, and scanning `runs/` was rejected because it ignores the canonical active-run record.

## Verification

Shell-level tests will use a temporary SQLite database and run directories to cover active-run selection, newest-run fallback, and useful failure messages before the script is implemented.
