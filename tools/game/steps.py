"""STEPS: run one transition row's steps (spec 2026-11-03 §4) with checked expectations.

Primitives are the only code per step type: click_bubble, click_object, press <label>, press_space, pick_card <name>,
close, read_card (stores the card's first line into a state key). Each step's `expect` (events, card, log) is checked;
every checked field is written to OBSERVED (row, step, field, expected, got, verdict) for the table's learning. A failed
expectation stops the row and closes cards (law 5: failure = reset)."""
import json
import os
import re
import time

from . import act as A, core, ui

OBSERVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'observed-steps.jsonl')
_TARGET = re.compile(r'target=(\w+)')


def observe(row, step, field, expected, got, ok):
    try:
        with open(OBSERVED, 'a') as f:
            f.write(json.dumps({'t': time.strftime('%Y-%m-%d %H:%M:%S'), 'row': row, 'step': step, 'field': field,
                                'expected': expected, 'got': got, 'verdict': 'ok' if ok else 'surprise'}) + '\n')
    except OSError:
        pass


def _lines_since(mark):
    if not core.seen(A.EVENT.pattern, mark, 0):
        core.seen(A.EVENT.pattern, mark, A.EVENT_WAIT)
    return core.log_text(mark).splitlines()


def _card():
    try:
        return ' / '.join(ui.texts())
    except Exception:   # noqa: BLE001
        return ''


def _check(expect, lines, events):
    """[(field, expected, got)] of the expectations that failed, and the ones checked."""
    bad, checked = [], []
    for field, want in (expect or {}).items():
        if field == 'events':
            got = events
            ok = all(any(e in got for e in alt.split('|')) for alt in want)
        elif field == 'card':
            got = _card()
            ok = want.lower() in got.lower()
        elif field == 'log':
            got = next((l for l in lines if re.search(want, l)), None)
            ok = got is not None
        else:
            continue   # bubble/text: observed by act.click's record, not a gate here
        checked.append((field, want, got, ok))
        if not ok:
            bad.append((field, want, got))
    return bad, checked


def run(row, params, bubble, node_state=None):
    """Run `row` on the fitting `bubble` (an Affordance in reach). Returns {'ok', 'events', 'lines', 'at', 'kind',
    'frame' (the bubble's sub-icons before the click), 'surprises' [(step, field, expected, got)], 'clicks',
    'failed_step', 'missing', 'stored'}."""
    from .plan import resolve
    r = resolve(row, params or {})
    out = {'ok': True, 'events': [], 'lines': [], 'at': None, 'kind': None, 'surprises': [], 'clicks': 0,
           'failed_step': None, 'missing': None, 'stored': {}, 'row': r['id'],
           'frame': {'drop': bool(getattr(bubble, 'drop', False)), 'ready': bool(getattr(bubble, 'ready', False))}}
    for i, s in enumerate(r['steps']):
        mark = core.WF.log_mark()
        lines, events = [], []
        try:
            if s['do'] in ('click_bubble', 'click_object'):
                c = A.click(bubble.pt, 'bubble' if s['do'] == 'click_bubble' else 'object')
                out['clicks'] += 1
                lines, events = c.lines, c.events
            elif s['do'] == 'press':
                ui.press(s['arg'])
            elif s['do'] == 'press_space':
                ui.press_bubble()
            elif s['do'] == 'pick_card':
                ui.pick_card(s['arg'])
            elif s['do'] == 'close':
                ui.close()
            elif s['do'] == 'read_card':
                from .garden import crop_name
                out['stored'][s.get('store', 'crop')] = crop_name(_card()) or None
        except core.Failed as e:
            out.update(ok=False, failed_step=i, why=str(e)[:200])
            if s['do'] == 'pick_card':
                out['missing'] = s.get('arg')
            break
        if s['do'] not in ('click_bubble', 'click_object'):
            lines = _lines_since(mark) if s['do'] in ('press', 'press_space') else core.log_text(mark).splitlines()
            events = A.events_of(lines)
        out['lines'] += lines
        out['events'] += events
        bad, checked = _check(s.get('expect'), lines, events)
        for field, want, got, ok in checked:
            observe(r['id'], i, field, want, got, ok)
        if bad:
            out['surprises'] += [(i, f, w, g) for f, w, g in bad]
            out.update(ok=False, failed_step=i)
            break
    for line in out['lines']:
        p = A.position_of(line)
        if p:
            out['at'] = p
            m = _TARGET.search(line)
            out['kind'] = m.group(1) if m else None
    if not out['ok']:
        try:
            if _card():
                ui.close()
        except Exception:   # noqa: BLE001
            pass
    return out
