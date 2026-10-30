"""Action tracking (L77): every @action call becomes one event in the open run log and one printed line, nested by
depth, so a run shows `replant(bed 3) → unplant 9.1s → plant 14.0s` and the time between calls is the agent's
thinking. `waits(events)` sums time per action and per screen."""
from . import core

LINES = []   # printed lines of the current ./wf py / call (wf prints them)


def action_event(name, args, t0, t1, depth, ok, why, before, after):
    mark = '✓' if ok else '✗'
    LINES.append(f'{"  " * depth}{mark} {name}({args}) {t1 - t0:.1f}s' + ('' if ok else f'  ← {why}'))
    try:
        core.WF.run_log('action', name=name, args=args, start=round(t0, 2), end=round(t1, 2), depth=depth, ok=ok,
                        why=why, before=before, after=after)
    except Exception:  # noqa: BLE001 (logging must never break an action)
        pass


def waits(events):
    """{'actions': {name: [n, seconds, failed]}, 'thinking': [(gap s, screen before the next call)]} from a run's
    events: top-level action time, and the gaps between ./wf calls labelled with the screen the agent was looking at."""
    acts = {}
    for e in events:
        if e.get('type') == 'action':
            a = acts.setdefault(e['name'], [0, 0.0, 0])
            a[0] += 1
            a[1] += e['end'] - e['start']
            a[2] += 0 if e['ok'] else 1
    calls = [e for e in events if e.get('type') == 'call']
    screens = [(e['end'], e.get('after', '?')) for e in events if e.get('type') == 'action' and e.get('depth') == 0]
    think = []
    for a, b in zip(calls, calls[1:]):
        gap = b['start'] - a['end']
        scr = next((s for t, s in reversed(screens) if t <= a['end'] + 0.5), a.get('cmd', '?'))
        think.append((round(gap, 1), scr))
    return {'actions': acts, 'thinking': think}
