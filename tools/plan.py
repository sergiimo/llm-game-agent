"""Task plans (L76): every task runs from runs/<YYYYMMDD-HHMM>-<task>/. plan.md is a markdown document for the agent,
written and reviewed by the supervisor and shown to the user; the agent follows it step by step and stamps each step
(`wf run step N start|done|fail`); the tool writes timestamps and budget use to `runs/<task>/progress.md`. A step over its budget
is escalated (`wf run escalate N`) and gets a stuck retro. Pure functions; wf.py does the I/O.

plan.md:
  # Plan: <task>
  - **Goal:** …   - **Done when:** …   - **Brief:** …   - **Review:** …
  ## Step 1: <title>
  - **Do:** exact ./wf commands, docs/ to read
  - **Signal:** what shows it worked
  - **Done when:** the check
  - **Budget:** <N> calls, <M> min   (game minutes; either part may be left out)
  - **If stuck:** what to try before escalating
"""
import re

HEADER = ['Goal', 'Done when', 'Brief', 'Review']
STEP_FIELDS = ['Do', 'Signal', 'Done when', 'Budget', 'If stuck']
REQUIRED = ['Do', 'Signal', 'Done when', 'Budget']
UNSET = ('', '❓', '-', '—')
MARK = {'todo': '·', 'start': '▶️', 'done': '✅', 'fail': '❌', 'skip': '⏭', 'escalate': '⏫'}


def template(task, goal=''):
    head = '\n'.join(f'- **{h}:** {goal if h == "Goal" and goal else "❓"}' for h in HEADER)
    step = '\n'.join(f'- **{f}:** ❓' for f in STEP_FIELDS)
    return f'# Plan: {task}\n\n{head}\n\n## Step 1: ❓\n{step}\n'


def _fields(text):
    """{field: text} of `- **Field:** …` lines; indented lines below continue the field."""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r'^\s*- \*\*(.+?):\*\*\s*(.*)$', line)
        if m:
            cur = m.group(1)
            out[cur] = m.group(2).strip()
        elif cur and line.startswith((' ', '\t')) and line.strip():
            out[cur] = (out[cur] + ' ' + line.strip()).strip()
        else:
            cur = None
    return out


def parse(md):
    """(header {field: text}, steps [{'n', 'title', 'body', field: text…}]) from plan.md text."""
    parts = re.split(r'^## Step (\d+):\s*(.*)$', md, flags=re.M)
    head = _fields(parts[0])
    steps = []
    for i in range(1, len(parts) - 2, 3):
        n, title, body = parts[i], parts[i + 1].strip(), parts[i + 2]
        steps.append({'n': n, 'title': title, 'body': body.strip(), **_fields(body)})
    return head, steps


def budget(text):
    """'15 calls, 60 min' -> (15, 60); missing parts None."""
    c = re.search(r'(\d+)\s*calls?', text or '')
    m = re.search(r'(\d+)\s*(?:game\s*)?min', text or '')
    return (int(c.group(1)) if c else None, int(m.group(1)) if m else None)


def review(md):
    """Problems the supervisor must fix before dispatching (empty list = complete)."""
    head, steps = parse(md)
    out = [f'header: {h} missing' for h in ('Goal', 'Done when', 'Brief') if head.get(h, '') in UNSET]
    if not steps:
        out.append('no steps (## Step N: <title>)')
    for k, s in enumerate(steps, 1):
        n = s['n']
        if n != str(k):
            out.append(f'step {n}: numbered out of order (expected {k})')
        if s['title'] in UNSET:
            out.append(f'step {n}: title missing')
        for f in REQUIRED:
            if s.get(f, '') in UNSET:
                out.append(f'step {n}: {f} missing')
        do = s.get('Do', '')
        if do not in UNSET and './wf' not in do and 'docs/' not in do:
            out.append(f'step {n}: Do names no ./wf command or docs/ file')
        if s.get('Budget', '') not in UNSET and budget(s['Budget']) == (None, None):
            out.append(f'step {n}: Budget unreadable ("<N> calls, <M> min")')
    return out


def steps_state(steps, events, now, hour_now=None):
    """Per step: {'n', 'title', 'state', 'calls', 'real_min', 'game_min', 'over'} from run events ('plan_step' +
    'call'). A step started again (after an escalation) is counted afresh."""
    starts, ends = {}, {}
    for e in events:
        if e.get('type') == 'plan_step':
            n = str(e['n'])
            if e['state'] == 'start':
                starts[n] = e
                ends.pop(n, None)
            else:
                ends[n] = e
    out = []
    for s in steps:
        n = s['n']
        st0, end = starts.get(n), ends.get(n)
        st = {'n': n, 'title': s['title'], 'state': end['state'] if end else 'todo', 'calls': 0, 'real_min': 0.0,
              'game_min': None, 'over': []}
        if st0:
            st['state'] = end['state'] if end else 'start'
            t1 = end['t'] if end else now
            st['calls'] = sum(1 for e in events if e.get('type') == 'call' and st0['t'] <= e['t'] <= t1)
            st['real_min'] = round((t1 - st0['t']) / 60, 1)
            h0, h1 = st0.get('hour'), (end.get('hour') if end else hour_now)
            if h0 is not None and h1 is not None:
                st['game_min'] = round(((h1 - h0) % 24) * 60)
            bc, bm = budget(s.get('Budget', ''))
            if bc is not None and st['calls'] > bc:
                st['over'].append(f'{st["calls"]}/{bc} calls')
            if bm is not None and st['game_min'] is not None and st['game_min'] > bm:
                st['over'].append(f'{st["game_min"]}/{bm} game min')
        out.append(st)
    return out


def progress_md(task, steps, states, lines):
    """Content for `runs/<task>/progress.md`: budget status table plus timestamped step log."""
    out = [f'# Progress: {task}', '', '| # | Step | Status | Calls | Real min | Game min | Budget | Over |',
           '|---|---|---|---|---|---|---|---|']
    for s, st in zip(steps, states):
        out.append(f'| {s["n"]} | {s["title"]} | {MARK[st["state"]]} | {st["calls"]} | {st["real_min"]} | '
                   f'{"" if st["game_min"] is None else st["game_min"]} | {s.get("Budget", "")} | '
                   f'{", ".join(st["over"])} |')
    return '\n'.join(out + ['', '## Log', ''] + [f'- {l}' for l in lines]) + '\n'
