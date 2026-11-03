"""The supervisor's live watcher over a run log (user D186: "the supervisor was meant to control the execution and see a
detailed log"). One short line per click; rules from the live failures D185-D186 flag NOTE / ALERT / STOP:

  STOP  a click while the pause menu is on screen, or a close that leaves it (attempt 4: the game exited)
  STOP  the game process is gone (health check, follow mode)
  ALERT a graph step from a look-alike frame node (attempt 2: walked away from the beds she stood at)
  ALERT a prediction miss (attempts 2-3: an empty bed's bubble read as `unplant`)
  ALERT a failed pick_card, an item icon learned under a junk name (attempt 3: 'ılbs')
  ALERT an engine call that stopped for anything but done
  NOTE  `> plant` without its `totalPlanted` proof (a closed panel), STUCK, every vision question

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
        self.proof = False   # a totalPlanted line since the last game event

    def health(self):
        return [] if self.alive() else [('STOP', 'the game process is gone (Wylde Flowers not running)')]

    def feed(self, r):
        t = r.get('type')
        out = []
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
                out.append(('NOTE', msg) if msg.startswith('STUCK') else ('INFO', f'seek: {msg}'))
        elif t == 'predict':
            line = f"predict {r.get('component')} {r.get('what')}: expected {r.get('expected')}, got {r.get('got')}"
            out.append(('INFO', line + ' - hit') if r.get('hit') else ('ALERT', line + ' - MISS'))
        elif t == 'learn' and r.get('what') == 'item_icon' and not JUNK.match(str(r.get('name', ''))):
            out.append(('ALERT', f"an item icon was learned under the name {r.get('name')!r} (not a readable name)"))
        elif t == 'game':
            line = str(r.get('line', ''))
            if 'totalPlanted' in line:
                self.proof = True
            elif re.search(r'> plant me=Player', line):
                if not self.proof:
                    out.append(('NOTE', f'`> plant` without totalPlanted (a closed panel, not a planting): {line[:90]}'))
                self.proof = False
            elif re.search(r'> \w+ me=Player', line):
                self.proof = False
        elif t == 'vision':
            out.append(('NOTE', f"vision {r.get('kind')}: {str(r.get('question'))[:140]}"))
        elif t == 'engine':
            msg = (f"engine {r.get('goal')}: done {r.get('done')}, left {r.get('left')}, clicks {r.get('clicks')}, "
                   f"vision {r.get('vision')}, stop {r.get('stop')}")
            stop = str(r.get('stop') or '')
            out.append(('INFO', msg) if stop.startswith('done') or not stop else ('ALERT', msg))
        elif t in ('plan_step', 'end', 'issue'):
            out.append(('INFO', f"{t}: {json.dumps({k: v for k, v in r.items() if k not in ('t', 'type')})[:160]}"))
        return out


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
    md = '\n'.join(lines) + '\n'
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
