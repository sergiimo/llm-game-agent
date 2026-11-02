"""Actions DB as chains (user D183, docs/mechanics/interaction-laws.md): each game function is a chain of steps, each step
= an action and the result it should leave on screen (log events, card, the clicked object's bubble, short-lived text).
Expectations live in chains.json with their source; "?" marks a gap. Every recorded click is checked against its step
(`observe`): a mismatch is a surprise (returned, logged), a gap gets the observed value. Observations go to
observed.jsonl; `gaps(apply=True)` fills a gap once 2 observations agree (never from one sighting)."""
import json
import os
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'chains.json')
OBSERVED = os.path.join(HERE, 'observed.jsonl')
FIELDS = ('events', 'card', 'bubble', 'text')
AGREE = 2
NEAR = 250   # px: the clicked object's bubble after the click is the nearest one within this distance


def load(path=None):
    with open(path or DB) as fh:
        return json.load(fh)


def step(chain, idx, db=None):
    return (db or load())[chain][idx]


def bubble_after(click):
    """The clicked object's bubble after the click: gone | plant | drop | no-drop | same."""
    def near(affs):
        best = None
        for a in affs:
            d = (a.pt[0] - click.pt[0]) ** 2 + (a.pt[1] - click.pt[1]) ** 2
            if d <= NEAR ** 2 and (best is None or d < best[0]):
                best = (d, a)
        return best[1] if best else None
    b0, b1 = near(click.before), near(click.after)
    if b1 is None:
        return 'gone'
    if b0 is not None and (b0.kind, b0.drop) == (b1.kind, b1.drop):
        return 'same'
    if b1.kind == 'plant':
        return 'plant'
    return 'drop' if b1.drop else 'no-drop'


def actual(click):
    """The click's result in the DB's terms."""
    card = ' / '.join(click.texts[:3]) if click.mode != 'gameplay' else None
    text = ' / '.join(getattr(click, 'burst_texts', [])[:4]) or None
    return {'events': list(click.events), 'card': card, 'bubble': bubble_after(click), 'text': text}


def _match(field, want, got):
    if field == 'events':
        return all(e in got for e in want)
    if want is None:
        return got is None
    if field in ('card', 'text'):
        return got is not None and want.lower() in got.lower()
    return want == got


def observe(chain, idx, click, db=None, log=True):
    """Check one click against its step. Returns the surprises [(field, expected, got)]; records every field."""
    s = step(chain, idx, db)
    got = actual(click)
    surprises, rows = [], []
    for f in FIELDS:
        want = s['expect'].get(f, '?')
        if want == '?':
            verdict = 'gap'
        elif _match(f, want, got[f]):
            verdict = 'ok'
        else:
            verdict = 'surprise'
            surprises.append((f, want, got[f]))
        rows.append({'t': round(time.time(), 2), 'chain': chain, 'step': idx, 'field': f, 'expected': want,
                     'got': got[f], 'verdict': verdict, 'frames': list(click.frames)})
    if log:
        try:
            with open(OBSERVED, 'a') as fh:
                for r in rows:
                    fh.write(json.dumps(r) + '\n')
        except OSError:
            pass
    return surprises


def gaps(apply=False, path=None, observed=None):
    """Every '?' in the DB with what was observed for it. apply=True fills a gap whose last observations agree
    (>= AGREE identical values, none different) and writes the DB. Returns [(chain, step, field, Counter, filled)]."""
    db = load(path)
    seen = {}
    try:
        with open(observed or OBSERVED) as fh:
            for line in fh:
                r = json.loads(line)
                if r.get('verdict') == 'gap':
                    seen.setdefault((r['chain'], r['step'], r['field']), []).append(json.dumps(r['got']))
    except OSError:
        pass
    out, changed = [], False
    for chain, steps in db.items():
        if chain.startswith('_'):
            continue
        for i, s in enumerate(steps):
            for f in FIELDS:
                if s['expect'].get(f, '?') != '?':
                    continue
                c = Counter(seen.get((chain, i, f), []))
                filled = False
                if apply and len(c) == 1 and sum(c.values()) >= AGREE:
                    s['expect'][f] = json.loads(next(iter(c)))
                    s['source'] = s.get('source', '') + f'; {f} observed x{sum(c.values())}'
                    filled = changed = True
                out.append((chain, i, f, c, filled))
    if changed:
        with open(path or DB, 'w') as fh:
            json.dump(db, fh, indent=2)
            fh.write('\n')
    return out
