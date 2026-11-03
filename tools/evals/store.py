"""Hits and misses of every prediction (spec 2026-10-30 §7.1): a component predicts something (`predict`), the game
later confirms or refutes it (`outcome`), and `report` gives the hit rate per component. Append-only JSON lines, so
pending predictions survive a daemon restart."""
import itertools
import json
import math
import os
import time

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'predictions.jsonl')
WORST = 3                 # latest misses shown per component
_N = itertools.count()


ENABLED = False   # only the real tool writes (wf main sets it): tests importing game code never touch the real file


def _append(rec):
    if not ENABLED:
        return
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, 'a') as fh:
        fh.write(json.dumps(rec) + '\n')


def predict(component, what, value, ctx=None):
    pid = f'p{int(time.time() * 1000)}-{next(_N)}'
    _append({'t': round(time.time(), 3), 'id': pid, 'component': component, 'what': what, 'value': value,
             'ctx': ctx or {}})
    return pid


def outcome(pid, value, hit):
    _append({'t': round(time.time(), 3), 'id': pid, 'outcome': value, 'hit': bool(hit)})


def record(component, what, value, outcome_value, hit, ctx=None):
    """A prediction checked in the same call: prediction and outcome at once."""
    pid = predict(component, what, value, ctx)
    outcome(pid, outcome_value, hit)
    return pid


def belief_hit(pred, to, tol=1.0):
    """Dead-reckoned position within `tol` world units of the reading."""
    return math.dist(pred, to) <= tol


def report(since=None, until=None):
    """{component: {hits, misses, pending, rate, worst}} over predictions made in [since, until]."""
    try:
        lines = [json.loads(line) for line in open(PATH) if line.strip()]
    except OSError:
        return {}
    preds, outs = {}, {}
    for r in lines:
        if 'component' in r:
            if (since is None or r['t'] >= since) and (until is None or r['t'] <= until):
                preds[r['id']] = r
        else:
            outs[r['id']] = r
    rep = {}
    for pid, p in preds.items():
        c = rep.setdefault(p['component'], {'hits': 0, 'misses': 0, 'pending': 0, 'rate': None, 'worst': []})
        o = outs.get(pid)
        if o is None:
            c['pending'] += 1
        elif o['hit']:
            c['hits'] += 1
        else:
            c['misses'] += 1
            c['worst'] = (c['worst'] + [p['ctx']])[-WORST:]
    for c in rep.values():
        n = c['hits'] + c['misses']
        c['rate'] = c['hits'] / n if n else None
    return rep


def format_report(rep):
    if not rep:
        return 'no predictions yet'
    out = []
    for k, c in sorted(rep.items()):
        n = c['hits'] + c['misses']
        rate = f' ({c["rate"]:.0%})' if c['rate'] is not None else ''
        out.append(f'{k}: {c["hits"]}/{n} hits{rate}' + (f' · {c["pending"]} pending' if c['pending'] else ''))
        for w in c['worst']:
            out.append(f'    miss: {json.dumps(w)[:160]}')
    return '\n'.join(out)
