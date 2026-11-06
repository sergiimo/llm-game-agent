"""The supervisor's live watcher over a run log (user D186: "the supervisor was meant to control the execution and see a
detailed log"). One short line per click; rules from the live failures D185-D186 flag NOTE / ALERT / STOP:

  STOP  a click while the pause menu is on screen, or a close that leaves it (attempt 4: the game exited)
  STOP  the game process is gone (health check, follow mode)
  STOP  MISS_STOP arrival misses in a row, or a LOST trace (live D188 12:31: 15+ clicks lost, only ALERTs)
  ALERT a graph step from a look-alike frame node (attempt 2: walked away from the beds she stood at)
  ALERT a prediction miss (attempts 2-3: an empty bed's bubble read as `unplant`)
  ALERT a failed pick_card, an item icon learned under a junk name (attempt 3: 'ılbs')
  ALERT an engine call that stopped for anything but done
  NOTE  `> plant` without its `totalPlanted` proof (a closed panel), STUCK, every vision question, a forage answer
        that reached no target

Usage: .venv/bin/python tools/runwatch.py [run_dir] --follow   (live; for the Monitor tool: one line per event)
       .venv/bin/python tools/runwatch.py [run_dir] --report   (a table per attempt, written to <run>/watch.md)"""
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAUSE = ('game paused', 'пауза')
MISS_STOP = 4   # arrival misses in a row = she is lost (live D188 12:31, S40): stop the agent
IDLE_S = 45.0   # s without a call, click or step while the game runs (~75 game min at Relaxed): thinking too long
_STAMP = re.compile(r'D(\d+) (\d+):(\d+):(\d+) (AM|PM)')
JUNK = re.compile(r'^[A-Za-z][A-Za-z _]{2,}$')   # an item name: Latin letters, spaces or _ (folder names), 3+ chars


def _kinds_nodes():
    try:
        with open(os.path.join(ROOT, 'tools', 'game', 'kinds.json')) as f:
            return {v['node'] for k, v in json.load(f).items() if not k.startswith('_') and '@' in v.get('node', '')}
    except (OSError, ValueError):
        return set()


LOOKALIKE = _kinds_nodes() or {'GardenBed@Garden'}


def _paused(texts):
    return any(w in str(t).lower() for t in texts for w in PAUSE)


def game_alive():
    try:
        return bool(subprocess.run(['pgrep', '-f', 'Wylde Flowers.app'], capture_output=True, text=True).stdout.strip())
    except OSError:
        return True


class Watch:
    def __init__(self, alive=game_alive):
        self.alive = alive
        self.pending = None   # a `> plant` line waiting for its totalPlanted (logged when the panel opens, D186)
        self.misses = 0       # arrival misses in a row
        self.last_t, self.last_cmd, self.idle_flagged = None, None, False

    def idle(self, now):
        """No call, click or step for IDLE_S while the game runs (the last command was not a pause): once per stretch
        (user D189: "it was standing doing nothing for too long, so we should be able to spot that")."""
        if self.last_t is None or self.idle_flagged or str(self.last_cmd or '').startswith('pause'):
            return []
        if now - self.last_t <= IDLE_S:
            return []
        self.idle_flagged = True
        return [('ALERT', f'idle {now - self.last_t:.0f}s: no call or click while the game runs (last: '
                          f'{self.last_cmd or "?"}) - the game clock runs ~100 game min per real min')]

    def health(self):
        return [] if self.alive() else [('STOP', 'the game process is gone (Wylde Flowers not running)')]

    def feed(self, r):
        t = r.get('type')
        out = []
        if t in ('call', 'click', 'seek', 'action', 'engine', 'plan_step'):
            self.last_t, self.idle_flagged = max(r.get('end') or 0, r.get('t') or 0), False
            if t == 'call':
                self.last_cmd = r.get('cmd')
        if t == 'click':
            ts = r.get('texts') or []
            moved = {True: 'walked', False: 'still'}.get(r.get('moved'), '?')
            out.append(('INFO', f"click {r.get('what')} @{r['pt'][0]},{r['pt'][1]}: {moved}; events "
                                f"{r.get('events') or '-'}; screen {r.get('mode')}"
                                f"{' (' + ' / '.join(ts[:2]) + ')' if ts else ''}; bubbles {r.get('after') or '-'}"))
            if _paused(ts) or _paused(r.get('burst_texts') or []):
                out.append(('STOP', f"click @{r['pt'][0]},{r['pt'][1]} with the pause menu on screen "
                                    f"(Resume / Settings / Exit Game): stop the agent now"))
        elif t == 'action':
            if r.get('name') == 'ui.close' and _paused([r.get('after') or '']):
                out.append(('STOP', 'a close left the pause menu open: Escape toggled it'))
            elif r.get('name') == 'ui.pick_card' and r.get('ok') is False:
                out.append(('ALERT', f"pick_card({r.get('args')}) failed: {str(r.get('why'))[:120]}"))
        elif t == 'seek':
            if r.get('what') == 'graph':
                msg = f"graph step {r.get('here')} -> {r.get('to')} dir {r.get('dir')}"
                out.append(('ALERT', f'{msg}: from a look-alike node (the frame can\'t say which area she is in)')
                           if r.get('here') in LOOKALIKE else ('INFO', msg))
            elif r.get('what') == 'trace':
                msg = str(r.get('msg'))
                out.append(('STOP', f'{msg}: stop the agent') if msg.startswith('LOST') else
                           ('NOTE', msg) if msg.startswith('STUCK') else ('INFO', f'seek: {msg}'))
        elif t == 'predict':
            line = f"predict {r.get('component')} {r.get('what')}: expected {r.get('expected')}, got {r.get('got')}"
            if r.get('what') == 'arrive':
                self.misses = 0 if r.get('hit') else self.misses + 1
            if not r.get('hit') and r.get('what') == 'arrive' and self.misses >= MISS_STOP:
                out.append(('STOP', f'{line} - MISS #{self.misses} in a row: she is lost, stop the agent'))
            else:
                out.append(('INFO', line + ' - hit') if r.get('hit') else ('ALERT', line + ' - MISS'))
        elif t == 'learn' and r.get('what') == 'item_icon' and not JUNK.match(str(r.get('name', ''))):
            out.append(('ALERT', f"an item icon was learned under the name {r.get('name')!r} (not a readable name)"))
        elif t == 'game':
            line = str(r.get('line', ''))
            if 'totalPlanted' in line:
                self.pending = None   # the planting is proven
            elif self.pending and ('closed without result' in line or re.search(r'> \w+ me=Player', line)):
                out.append(('NOTE', f'`> plant` without totalPlanted (a closed panel, not a planting): '
                                    f'{self.pending[:90]}'))
                self.pending = None
            if re.search(r'> plant me=Player', line):
                self.pending = line
        elif t == 'vision':
            out.append(('NOTE', f"vision {r.get('kind')}: {str(r.get('question'))[:140]}"))
        elif t == 'perception':
            seen = ', '.join(f"{d.get('kind')}@{(d.get('pt') or ['?', '?'])[0]},{(d.get('pt') or ['?', '?'])[1]}"
                             for d in r.get('detections') or ()) or 'none'
            out.append(('INFO', f"perception {r.get('source')}: {seen}"))
        elif t == 'engine':
            msg = (f"engine {r.get('goal')}: done {r.get('done')}, left {r.get('left')}, clicks {r.get('clicks')}, "
                   f"vision {r.get('vision')}, stop {r.get('stop')}")
            stop = str(r.get('stop') or '')
            out.append(('STOP', msg) if stop.startswith('RED FLAG') else
                       ('INFO', msg) if stop.startswith('done') or not stop else ('ALERT', msg))
        elif t == 'forage':   # the foraging strategy: one vision answer -> one result (spec §13)
            msg = (f"forage {r.get('job')} @{(r.get('pt') or ['?', '?'])[0]},{(r.get('pt') or ['?', '?'])[1]}: "
                   f"{r.get('result')} {r.get('object') or ''} (hits {r.get('hits')})")
            proven = r.get('result') in ('destroying', 'grab_item')
            out.append(('INFO', msg) if proven else ('NOTE', msg + ' - the answer did not reach a target'))
        elif t in ('think', 'decide', 'reasoning'):
            out.append(('INFO', trace_lines([r])[0][9:]))
        elif t in ('plan_step', 'end', 'issue'):
            out.append(('INFO', f"{t}: {json.dumps({k: v for k, v in r.items() if k not in ('t', 'type')})[:160]}"))
        return out


TRACED = ('decide', 'reasoning', 'click', 'think', 'vision', 'perception', 'call', 'action', 'engine', 'game', 'gap', 'learn',
          'plan_step')


def trace_lines(rows):
    """Every decision, click (with its game events), thought, question, answer call and result, in order - the
    absolute trace (user D189). One short line each."""
    out = []
    for r in rows:
        t = r.get('type')
        if t not in TRACED:
            continue
        ts = time.strftime('%H:%M:%S', time.localtime(r.get('t') or 0))
        if t == 'decide':
            body = (f"decide {r.get('target')} ({r.get('dist')} units): {r.get('why')}"
                    f"{' row ' + str(r.get('row')) if r.get('row') else ''}")
        elif t == 'reasoning':
            body = (f"reasoning {r.get('cycle')} {r.get('phase')}: "
                    f"decision={r.get('decision') or r.get('action') or '-'} "
                    f"vision={r.get('vision_requested', False)} verdict={r.get('verdict') or '-'} "
                    f"gap={r.get('code_fix') or '-'}")
        elif t == 'click':
            body = (f"click {r.get('what')} @{(r.get('pt') or ['?', '?'])[0]},{(r.get('pt') or ['?', '?'])[1]}"
                    f" {r.get('gt') or ''}: events {r.get('events') or '-'}, "
                    f"{'walked' if r.get('moved') else 'still'}{', screen ' + ' / '.join(r.get('texts') or [])[:60] if r.get('texts') else ''}")
        elif t == 'think':
            body = f"think: {r.get('text')}"
        elif t == 'vision':
            body = f"vision {r.get('kind')}: {str(r.get('question'))[:120]}"
        elif t == 'perception':
            body = f"perception {r.get('source')}: {len(r.get('detections') or ())} detections"
        elif t == 'call':
            body = f"call {r.get('cmd')} ({(r.get('end') or 0) - (r.get('start') or 0):.1f}s)"
        elif t == 'engine':
            body = f"engine {r.get('goal')}: done {r.get('done')}, left {r.get('left')}, stop {r.get('stop')}"
        elif t == 'game':
            body = f"game {r.get('line')}"
        else:
            body = f"{t} " + json.dumps({k: v for k, v in r.items() if k not in ('t', 'type')})[:120]
        out.append(f'{ts} {body}')
    return out


def _game_s(stamp):
    m = _STAMP.search(str(stamp or ''))
    if not m:
        return None
    d, h, mi, s, ap = m.groups()
    return int(d) * 86400 + (int(h) % 12 + (12 if ap == 'PM' else 0)) * 3600 + int(mi) * 60 + int(s)


def times(rows, game_lines=()):
    """Per attempt (each `plan_step 1 start`): wall minutes, minutes inside ./wf calls, thinking (the gaps between
    calls: total and the longest), game minutes (first to last click's game clock), clicks, vision questions, picks
    (the game log's `> harvest` lines inside the attempt's game window)."""
    attempts, cur = [], None
    for r in rows:
        if (r.get('type') == 'plan_step' and str(r.get('n')) == '1' and r.get('state') == 'start') or cur is None:
            cur = {'t0': r.get('t'), 't1': r.get('t'), 'calls': [], 'clicks': 0, 'vision': 0, 'gts': []}
            attempts.append(cur)
        cur['t1'] = max(cur['t1'] or 0, r.get('end') or r.get('t') or 0)
        if r.get('type') == 'call' and r.get('end'):
            cur['calls'].append((r['start'], r['end']))
        elif r.get('type') == 'click':
            cur['clicks'] += 1
            g = _game_s(r.get('gt'))
            if g is not None:
                cur['gts'].append(g)
        elif r.get('type') == 'vision':
            cur['vision'] += 1
    harvests = [g for g in (_game_s(l) for l in game_lines if '> harvest ' in l) if g is not None]
    out = []
    for a in attempts:
        cs = sorted(a['calls'])
        gaps = [max(0.0, cs[i][0] - cs[i - 1][1]) for i in range(1, len(cs))]
        g0, g1 = (min(a['gts']), max(a['gts'])) if a['gts'] else (None, None)
        out.append({'start': a['t0'], 'wall_min': round(((a['t1'] or 0) - (a['t0'] or 0)) / 60, 2),
                    'calls': len(cs), 'in_calls_min': round(sum(e - s for s, e in cs) / 60, 2),
                    'think_min': round(sum(gaps) / 60, 2), 'longest_think_s': round(max(gaps, default=0), 1),
                    'game_min': round((g1 - g0) / 60) if g0 is not None else None,
                    'clicks': a['clicks'], 'vision': a['vision'],
                    'picks': sum(1 for h in harvests if g0 is not None and g0 <= h <= g1)})
    return out


def time_table(rows, game_lines=()):
    lines = ['| attempt | wall min | in calls | thinking | longest think s | game min | clicks | vision | picks |',
             '|---|---|---|---|---|---|---|---|---|']
    for i, a in enumerate(times(rows, game_lines), 1):
        lines.append(f"| {i} | {a['wall_min']} | {a['in_calls_min']} | {a['think_min']} | {a['longest_think_s']} | "
                     f"{a['game_min'] if a['game_min'] is not None else '-'} | {a['clicks']} | {a['vision']} | "
                     f"{a['picks']} |")
    return '\n'.join(lines)


def garden_table(rows):
    """Latest structured garden checkpoint per region: every target must be covered or explicitly unresolved."""
    latest, visits = {}, {}
    for row in rows:
        if row.get('type') == 'garden_summary' and row.get('region'):
            latest[row['region']] = row
        elif row.get('type') == 'garden_visit' and row.get('node'):
            visits[row['node']] = row
    lines = ['| region | required | covered | unresolved | missing | constraints | status |',
             '|---|---|---|---|---|---|---|']
    for region, row in latest.items():
        targets = set(row.get('targets') or ())
        covered = set(row.get('covered') or ()) & targets
        unresolved = set(row.get('unresolved') or ()) & targets
        missing = sorted(targets - covered - unresolved)
        reasons = {node: str((visits.get(node) or {}).get('reason') or '').strip() for node in unresolved}
        constraints = '; '.join(f'{node}: {reasons[node].replace("|", "/")}' for node in sorted(unresolved)
                                if reasons[node])
        exact_constraints = len(reasons) == len(unresolved) and all(reasons.values())
        stop = str(row.get('stop') or '')
        status = ('COMPLETE' if not missing and not unresolved and stop.startswith('done:') else
                  'CONSTRAINED' if not missing and unresolved and exact_constraints
                  and stop.startswith('unresolved:') else
                  'PENDING')
        lines.append(f'| {region} | {len(targets)} | {len(covered)} | {len(unresolved)} | '
                     f'{", ".join(missing) if missing else "-"} | {constraints or "-"} | {status} |')
    return '\n'.join(lines) if latest else ''


def _game_log_lines():
    try:
        sys.path.insert(0, os.path.join(ROOT, 'tools'))
        import wf
        with open(wf.GAME_LOG, errors='replace') as f:
            return f.read().splitlines()
    except Exception:   # noqa: BLE001
        return []


def rows_of(path, start=0):
    with open(path) as f:
        f.seek(start)
        data = f.read()
        pos = f.tell()
    rows = []
    for line in data.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows, pos


def report(path):
    """A markdown table per attempt (an attempt starts at `plan_step 1 start`), written next to the log."""
    rows, _ = rows_of(path)
    attempts, cur = [], None
    for r in rows:
        if r.get('type') == 'plan_step' and str(r.get('n')) == '1' and r.get('state') == 'start' or cur is None:
            cur = {'clicks': 0, 'walks': 0, 'still': 0, 'hit': 0, 'miss': 0, 'alerts': [], 'stops': [], 'engine': []}
            attempts.append(cur)
            w = Watch(alive=lambda: True)
        if r.get('type') == 'click':
            cur['clicks'] += 1
            cur['walks' if r.get('moved') else 'still'] += 1
        if r.get('type') == 'predict':
            cur['hit' if r.get('hit') else 'miss'] += 1
        if r.get('type') == 'engine':
            cur['engine'].append(f"done {r.get('done')} left {r.get('left')} stop {r.get('stop')}")
        for lv, msg in w.feed(r):
            if lv == 'ALERT':
                cur['alerts'].append(msg)
            elif lv == 'STOP':
                cur['stops'].append(msg)
    lines = ['| attempt | clicks | walks | still | predictions hit/miss | alerts | stops |', '|---|---|---|---|---|---|---|']
    for i, a in enumerate(attempts, 1):
        lines.append(f"| {i} | {a['clicks']} | {a['walks']} | {a['still']} | {a['hit']}/{a['miss']} | "
                     f"{len(a['alerts'])} | {len(a['stops'])} |")
    for i, a in enumerate(attempts, 1):
        if a['engine'] or a['alerts'] or a['stops']:
            lines.append(f'\n### Attempt {i}')
            lines += [f'- engine: {e}' for e in a['engine']]
            lines += [f'- STOP: {m}' for m in a['stops'][:5]]
            lines += [f'- ALERT: {m}' for m in a['alerts'][:8]]
    gardens = garden_table(rows)
    md = ('\n'.join(lines) + ('\n\n## Garden coverage\n' + gardens if gardens else '')
          + '\n\n## Time\n' + time_table(rows, _game_log_lines()) + '\n\n## Trace (last attempt)\n'
          + '\n'.join(trace_lines(rows[max((i for i, r in enumerate(rows) if r.get('type') == 'plan_step'
                                              and r.get('state') == 'start'), default=0):])) + '\n')
    try:
        with open(os.path.join(os.path.dirname(path), 'watch.md'), 'w') as f:
            f.write(md)
    except OSError:
        pass
    return md


def current_run():
    try:
        return open(os.path.join(ROOT, '.shots', 'run.current')).read().strip()
    except OSError:
        return None


def follow(path, every=1.0, health_every=15.0):
    """Print each new event's lines (from the end of the log now), and a health check every `health_every` s."""
    w = Watch()
    _, pos = rows_of(path)
    last = 0.0
    while True:
        rows, pos = rows_of(path, pos)
        for r in rows:
            for lv, msg in w.feed(r):
                print(f"{time.strftime('%H:%M:%S')} {lv} {msg}", flush=True)
        for lv, msg in w.idle(time.time()):
            print(f"{time.strftime('%H:%M:%S')} {lv} {msg}", flush=True)
        if time.time() - last >= health_every:
            last = time.time()
            for lv, msg in w.health():
                print(f"{time.strftime('%H:%M:%S')} {lv} {msg}", flush=True)
        time.sleep(every)


def main(argv):
    args = [a for a in argv if not a.startswith('--')]
    path = args[0] if args else current_run()
    if path and os.path.isdir(path):
        path = os.path.join(path, 'log.jsonl')
    if not path or not os.path.exists(path):
        sys.exit('no run log (open a run with ./wf run start, or pass the run dir)')
    if '--report' in argv:
        print(report(path))
    else:
        follow(path)


if __name__ == '__main__':
    main(sys.argv[1:])
