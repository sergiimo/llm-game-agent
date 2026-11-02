# Retro 1: fill-can live budget escalation

## Outcome
`fill_can()` succeeded. The exact proof was `[D156 10:03:34 AM] > fill_watering_can me=Player target=Well`, and the
game showed the top-left success notification **“Rusty Watering Can”**. The game was paused immediately afterward.

## Why step 1 escalated
This was not an L75 stuck episode. The visible well was not detected in the first frame, so the loop correctly raised
one `NeedVision`. Labelling the Well from `ask-1.frame.png` fixed detection and the retry succeeded. The plan budget was
four calls but its documented recovery path requires six: resume, attempt, pause, label, resume, retry (plus the final
pause before review).

## Earlier fixes
- The object-loop question protocol held: it stopped without blind clicks and one label fixed the miss.
- The two-answer ceiling was not reached.
- The plan-review budget did not include its own recovery path; that is the actual escalation cause.

## Fix
- Added the live Well example `1793454489113-0`.
- Revised step 1 to seven calls and explicitly budgeted pause/resume around one correction.
- Recorded both top-left water messages in the HUD/action docs.

## Verification remaining
Read-only: `./wf graph show Garden` must report `Well can=full@(log)` and the log must contain only one fill proof.
