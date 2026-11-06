"""STEPS: run one transition row's steps (spec 2026-11-03 §4) with checked expectations.

Primitives are the only code per step type: click_bubble, click_object, press <label>, press_space, pick_card <name>,
close, read_card (stores the card's first line into a state key). Each step is one action = one experience (the
improvement loop's boundary, integrate.py): a click step's `expect` goes with the click and comes back checked; any
other step is recorded by integrate.record. The boundary writes the checked fields to OBSERVED (row, step, field,
expected, got, verdict, exp) for the table's learning. A failed expectation stops the row and closes cards (law 5)."""
import json
import os
import re
import time

from . import act as A, core, integrate as I, ui

OBSERVED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'observed-steps.jsonl')
_TARGET = re.compile(r'target=(\w+)')
KIND = {'press': 'press', 'press_space': 'space', 'pick_card': 'pick', 'close': 'close', 'click_cell': 'cell',
        'read_card': 'read'}   # step -> the experience's action kind


def recommend(row, params, index, point=None):
    """Pure: recommend exactly one resolved step. Missing visual coordinates stay for the model to supply.

    The legacy run() remains for unmigrated callers; model-owned tasks use this function and primitives instead.
    Card selection never scans through cards: the model supplies one visible card point.
    """
    from .plan import resolve
    from .turn import Recommendation
    r = resolve(row, params or {})
    if not 0 <= index < len(r['steps']):
        return Recommendation(None, 1., ('transition finished; verify evidence',), {})
    s = r['steps'][index]
    kinds = {'click_bubble': 'bubble', 'click_object': 'target', 'press': 'press', 'press_space': 'space',
             'pick_card': 'select_card', 'close': 'close', 'click_cell': 'cell', 'read_card': 'read'}
    action = {'kind': kinds[s['do']], 'row': r['id'], 'step': index}
    if point is not None:
        action['point'] = list(point)
    if s['do'] == 'press':
        action['label'] = s['arg']
    if s['do'] == 'pick_card':
        action['name'] = s['arg']
    if s['do'] == 'click_cell':
        action['cell'] = s['arg']
    if s['do'] == 'read_card':
        action['store'] = s.get('store', 'crop')
    return Recommendation(action, 1., (f'transition {r["id"]} step {index}',), s.get('expect') or {})


def _lines_since(mark):
    if not core.seen(A.EVENT.pattern, mark, 0):
        core.seen(A.EVENT.pattern, mark, A.EVENT_WAIT)
    return core.log_text(mark).splitlines()


def _card():
    try:
        return ' / '.join(ui.texts())
    except Exception:   # noqa: BLE001
        return ''


def run(row, params, bubble, node_state=None):
    """Run `row` on the fitting `bubble` (an Affordance in reach). Returns {'ok', 'events', 'lines', 'at', 'kind',
    'frame' (the bubble's sub-icons before the click), 'surprises' [(step, field, expected, got)], 'clicks',
    'failed_step', 'missing', 'stored'}."""
    from .plan import resolve
    r = resolve(row, params or {})
    cycle = I.reasoning('clues', goal=r['kind'], row=r['id'], state=node_state or {},
                        bubble={'kind': getattr(bubble, 'kind', None), 'pt': getattr(bubble, 'pt', None),
                                'drop': bool(getattr(bubble, 'drop', False)),
                                'ready': bool(getattr(bubble, 'ready', False))},
                        decision='ready_to_act', vision_requested=False)
    out = {'ok': True, 'events': [], 'lines': [], 'at': None, 'kind': None, 'surprises': [], 'clicks': 0,
           'failed_step': None, 'missing': None, 'stored': {}, 'row': r['id'], 'after': [], 'exps': [],
           'frame': {'drop': bool(getattr(bubble, 'drop', False)), 'ready': bool(getattr(bubble, 'ready', False))}}
    for i, s in enumerate(r['steps']):
        I.reasoning('final_decision', cycle, action=s['do'], argument=s.get('arg'), step=i,
                    reason=f"transition {r['id']} fits the observed bubble and state")
        mark = core.WF.log_mark()
        lines, events, c = [], [], None
        goal = {'row': r['id'], 'step': i, 'params': params or {}}
        try:
            if s['do'] in ('click_bubble', 'click_object'):
                c = A.click(bubble.pt, 'bubble' if s['do'] == 'click_bubble' else 'object', predict=s.get('expect'),
                            goal=goal)
                out['clicks'] += 1
                lines, events = c.lines, c.events
                out['exps'].append(c.exp)
                out['after'], out['img0'], out['bubble_pt'] = c.after, c.img0, tuple(bubble.pt)
            elif s['do'] == 'press':
                ui.press(s['arg'])
            elif s['do'] == 'press_space':
                ui.press_bubble()
            elif s['do'] == 'pick_card':
                ui.pick_card(s['arg'])
            elif s['do'] == 'close':
                ui.close()
            elif s['do'] == 'click_cell':   # a grid cell vision named (a button without text, a card)
                from .ask import parse_point
                x, y = parse_point(s['arg'])
                core.WF.run_action(f'click:{x}:{y}')
                core.WF.wait_settle()
            elif s['do'] == 'read_card':
                from .garden import crop_name
                out['stored'][s.get('store', 'crop')] = crop_name(_card()) or None
        except core.Failed as e:
            out.update(ok=False, failed_step=i, why=str(e)[:200], screen=_card())
            if s['do'] == 'pick_card':
                out['missing'] = s.get('arg')
            e_, _ = I.record(KIND.get(s['do'], s['do']), s.get('arg'), mark, core.log_text(mark).splitlines(), [],
                             None, goal)
            out['exps'].append(e_.id)
            break
        if c is not None:   # the click's experience checked its expectation (the same evidence)
            bad = [(ch.field, ch.expected, ch.got) for ch in (c.checks or ()) if ch.ok is False]
            if c.exp is None:   # no boundary registered (a bare act): check here, record nothing
                _, bad = I.verify(s.get('expect'), lines, events)
        else:
            lines = _lines_since(mark) if s['do'] in ('press', 'press_space') else core.log_text(mark).splitlines()
            events = A.events_of(lines)
            e_, bad = I.record(KIND.get(s['do'], s['do']), s.get('arg'), mark, lines, events, s.get('expect'), goal)
            out['exps'].append(e_.id)
        out['lines'] += lines
        out['events'] += events
        if bad:
            out['surprises'] += [(i, f, w, g) for f, w, g in bad]
            out.update(ok=False, failed_step=i, screen=_card())   # the card still open: what vision is asked about
            I.reasoning('outcome', cycle, action=s['do'], step=i, experience=out['exps'][-1] if out['exps'] else None,
                        events=events, verdict='miss', code_fix='evaluate_gap', discrepancy=bad)
            out['why'] = core.ask_vision(
                f'Unexpected result for {r["kind"]} transition {r["id"]}, step {i} ({s["do"]}). '
                f'Expected vs actual: {bad}. Screen text: {out["screen"] or "none"}. '
                'Identify what is on screen, what the interaction actually did, and whether to update '
                'the visual label, transition code, or report an unresolved game-logic issue.')
            break
        I.reasoning('outcome', cycle, action=s['do'], step=i, experience=out['exps'][-1] if out['exps'] else None,
                    events=events, verdict='hit' if s.get('expect') else 'observed')
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
