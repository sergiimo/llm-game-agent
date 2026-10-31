"""Benchmark (spec 2026-10-30 §7.2): fixed tasks A (garden day), B (trips), C (NPC + menus) run as ordinary plan runs
(`./wf bench start A` copies tools/bench/A.md to the run's plan.md) and scored from the run log, the nav events and
the eval store, so toolkit versions compare by number (`./wf bench compare`)."""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(DIR, 'results.jsonl')
KEYS = ['calls', 'real_min', 'game_min', 'thinking_s', 'readings', 'stuck', 'interrupts', 'escalations',
        'steps_done', 'steps_total']


def score(events, nav_events, evals_rep):
    """Score one run: events = its log.jsonl, nav_events = tools/nav/events.jsonl, evals_rep = evals.report(since)."""
    from game import track
    out = dict.fromkeys(KEYS, 0)
    out['eval'] = {k: c['rate'] for k, c in evals_rep.items()}
    if not events:
        return out
    t0, t1 = events[0]['t'], events[-1].get('end', events[-1]['t'])
    steps = [e for e in events if e.get('type') == 'plan_step']
    hours = [e['hour'] for e in steps if e.get('hour') is not None]
    out.update(
        calls=sum(1 for e in events if e.get('type') == 'call'),
        real_min=round((t1 - t0) / 60, 1),
        game_min=round(((hours[-1] - hours[0]) % 24) * 60) if len(hours) > 1 else 0,
        thinking_s=round(sum(g for g, _ in track.waits(events)['thinking']), 1),
        readings=sum(1 for e in nav_events if e.get('what') == 'pos' and t0 <= e['t'] <= t1),
        stuck=sum(1 for e in events if e.get('type') == 'stuck'),
        interrupts=sum(1 for e in events if e.get('type') == 'interrupt'),
        escalations=sum(1 for e in steps if e['state'] == 'escalate'),
        steps_done=len({e['n'] for e in steps if e['state'] in ('done', 'skip')}),
        steps_total=len({e['n'] for e in steps}))
    return out


def upsert_result(row):
    """Add a result row; a row for the same run is replaced (re-reporting a run doesn't duplicate it)."""
    rows = [r for r in results() if r.get('run') != row.get('run')] + [row]
    with open(RESULTS, 'w') as fh:
        fh.writelines(json.dumps(r) + '\n' for r in rows)


def results(task=None):
    try:
        rows = [json.loads(line) for line in open(RESULTS) if line.strip()]
    except OSError:
        return []
    return [r for r in rows if task is None or r['task'] == task]


def compare_table(rows):
    if not rows:
        return 'no bench results yet'
    head = ['date', 'task', 'toolkit'] + KEYS
    lines = [' · '.join(head)]
    for r in rows:
        lines.append(' · '.join(str(r.get(k, '')) for k in head))
    return '\n'.join(lines)
