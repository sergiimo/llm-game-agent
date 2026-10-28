"""Post-run analysis of visible non-doing time: where the game screen stood still, and why.

A frame counts as DOING if the camera moves (mean grey diff 96x56 vs the previous frame >= --still) or a game-log
event (hit, pickup, dialogue, scene change; <video>.events.tsv from the recorder) happened within ±0.75 s. Small
on-screen actions (a swing) barely change the pixels, so events cover them. Everything else is STILL, attributed to what the agent was doing at that moment, from .shots/actions.log (call start) +
.shots/actions_done.log (call end, written by tools/wfc.py):
  in a call   -> the command was running but nothing moved (fixed waits, settle/OCR overhead, blocked moves)
  between     -> the agent (model) was deciding: no command running

  .venv/bin/python tools/idle.py recordings/play-XXXX.mp4 [--transcript <agent .jsonl>] [--still 1.0] [--min 2]
--transcript recovers call end times from a Claude Code agent transcript (runs recorded before actions_done.log).
t0 defaults to the timestamp in the file name (play-%Y%m%d-%H%M%S). Motion is cached next to the video (.motion.tsv).
"""
import argparse
import os
import re
import subprocess
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, '.shots')
W, H = 96, 56


def tara(video):
    """(t0, [(seconds, activity)]) from the recorder's Tara track, or (None, None) for older recordings."""
    p = os.path.splitext(video)[0] + '.tara.tsv'
    if not os.path.exists(p):
        return None, None
    t0, rows = None, []
    for l in open(p):
        if l.startswith('# t0 '):
            t0 = float(l.split()[2])
        elif l.strip():
            t, act = l.split('\t')[:2]
            rows.append((float(t), float(act)))
    return t0, rows


def motion(video):
    """Per-frame (seconds, diff) from the video; cached in <video>.motion.tsv (the recorder writes the same file live)."""
    cache = os.path.splitext(video)[0] + '.motion.tsv'
    if os.path.exists(cache):
        return [tuple(map(float, l.split('\t'))) for l in open(cache) if l.strip() and not l.startswith('#')]
    import imageio_ffmpeg
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    info = subprocess.run([ff, '-i', video], capture_output=True, text=True).stderr
    fps = float(re.search(r'(\d+(?:\.\d+)?) fps', info).group(1))
    p = subprocess.Popen([ff, '-loglevel', 'error', '-i', video, '-vf', f'scale={W}:{H}', '-f', 'rawvideo',
                          '-pix_fmt', 'gray', '-'], stdout=subprocess.PIPE)
    out, prev, i = [], None, 0
    game_rows = int(H * 0.93)  # cut the caption bar
    while True:
        buf = p.stdout.read(W * H)
        if len(buf) < W * H:
            break
        cur = buf[:W * game_rows]
        if prev is not None:
            out.append((i / fps, sum(abs(a - b) for a, b in zip(cur, prev)) / len(cur)))
        prev, i = cur, i + 1
    with open(cache, 'w') as f:
        f.writelines(f'{t:.3f}\t{d:.3f}\n' for t, d in out)
    return out


def transcript_ends(path):
    """[(start, end)] of Bash ./wf tool calls in a Claude Code transcript (tool_use -> tool_result times)."""
    import json
    from datetime import datetime
    pend, res = {}, []
    for l in open(path):
        r = json.loads(l)
        c = r.get('message', {}).get('content')
        if 'timestamp' not in r or not isinstance(c, list):
            continue
        t = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')).timestamp()
        for b in c:
            if b.get('type') == 'tool_use' and './wf' in str(b.get('input', {}).get('command', '')):
                pend[b['id']] = t
            elif b.get('type') == 'tool_result' and b.get('tool_use_id') in pend:
                res.append((pend.pop(b['tool_use_id']), t))
    return res


def calls(t0, t1, transcript=None):
    """[(start, end|None, cmd)] of ./wf calls in [t0, t1]."""
    done = {}
    if transcript:
        tr = transcript_ends(transcript)
        for l in open(os.path.join(SHOTS, 'actions.log')):
            s = float(l.split('\t', 1)[0])
            if t0 <= s <= t1:
                best = min(tr, key=lambda x: abs(x[0] - s), default=None)
                if best and abs(best[0] - s) < 3:
                    done[round(s, 2)] = best[1]
    try:
        for l in open(os.path.join(SHOTS, 'actions_done.log')):
            s, e = l.split('\t')[:2]
            done[round(float(s), 2)] = float(e)
    except OSError:
        pass
    res = []
    for l in open(os.path.join(SHOTS, 'actions.log')):
        ts, cmd = l.rstrip('\n').split('\t', 1)
        s = float(ts)
        if t0 <= s <= t1:
            res.append((s, done.get(round(s, 2)), cmd))
    return res


def events(video):
    """Video times of game-log events (recorder track); [] for older recordings."""
    p = os.path.splitext(video)[0] + '.events.tsv'
    try:
        return sorted(float(l.split('\t', 1)[0]) for l in open(p) if l.strip())
    except OSError:
        return []


def kind(cmd):
    if 'key:space' in cmd and 'wait:' in cmd:
        return 'hit/pickup batch (Space + fixed waits)'
    if cmd.startswith('do') and 'go:' in cmd:
        return 'go: moves'
    if 'key:i' in cmd or 'text:' in cmd:
        return 'menus (inventory/eat)'
    if cmd.startswith(('state', 'look', 'save', 'log', 'route')):
        return 'observe (state/look)'
    return 'other do'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('video')
    ap.add_argument('--t0', type=float)
    ap.add_argument('--still', type=float, default=1.0, help='diff below this = no visible change')
    ap.add_argument('--min', type=float, default=2.0, help='report still stretches at least this long (s)')
    ap.add_argument('--top', type=int, default=12)
    ap.add_argument('--transcript', help='agent transcript .jsonl to recover call end times')
    a = ap.parse_args()
    t0, mo = tara(a.video)
    signal = 'Tara activity (median of 3 > 6)'
    if mo is None:  # older recording: whole-screen motion (anything moving counts, e.g. water)
        mo, signal = motion(a.video), f'whole-screen motion > {a.still}'
    if a.t0 is not None:
        t0 = a.t0
    if t0 is None:
        m = re.search(r'(\d{8}-\d{6})', os.path.basename(a.video))
        t0 = time.mktime(time.strptime(m.group(1), '%Y%m%d-%H%M%S'))
    if signal.startswith('Tara'):
        acts = [d for _, d in mo]
        busy = [sorted(acts[max(0, i - 1):i + 2])[len(acts[max(0, i - 1):i + 2]) // 2] > 6 for i in range(len(acts))]
    else:
        busy = [d >= a.still for _, d in mo]
    busy_at = {t: b for (t, _), b in zip(mo, busy)}
    steps = [t - p for t, p in zip([m[0] for m in mo], [0.0] + [m[0] for m in mo[:-1]])]  # real frame gaps
    dur = mo[-1][0]
    cs = calls(t0, t0 + dur, a.transcript)
    import bisect
    ev = events(a.video)

    def event_near(t, w=0.75):
        i = bisect.bisect_left(ev, t - w)
        return i < len(ev) and ev[i] <= t + w
    # without end times: a call is assumed to run until the next one starts (upper bound for "in call")
    known_end = sum(1 for c in cs if c[1])

    def at(t):
        """What the agent was doing at video time t: (label, call index or None)."""
        u = t0 + t
        for i, (s, e, cmd) in enumerate(cs):
            nxt = cs[i + 1][0] if i + 1 < len(cs) else t0 + dur
            if s <= u < nxt:
                if e is None or u < e:
                    return kind(cmd), i
                return 'agent thinking (between calls)', i
        return 'before first call', None

    doing = lambda t, d: busy_at[t] or event_near(t)
    moving = sum(st for (t, d), st in zip(mo, steps) if doing(t, d))
    buckets = defaultdict(float)
    stretches, cur = [], None
    for (t, d), dt in zip(mo, steps):
        if not doing(t, d):
            lab, ci = at(t)
            buckets[lab] += dt
            if cur and cur[2] == lab and cur[3] == ci and t - cur[1] <= 0.5:
                cur[1] = t
            else:
                cur = [t, t, lab, ci]
                stretches.append(cur)
    print(f'{os.path.basename(a.video)}: {dur / 60:.1f} min, {len(cs)} ./wf calls '
          f'({known_end} with end times{"" if known_end else ": in-call vs thinking is an upper bound"})')
    print(f'doing {moving / 60:.1f} min ({moving / dur:.0%}) · still {(dur - moving) / 60:.1f} min ({1 - moving / dur:.0%})'
          f'  [doing = {signal} + {len(ev)} game events]')
    print('\nstill time by cause:')
    for lab, s in sorted(buckets.items(), key=lambda x: -x[1]):
        print(f'  {s / 60:5.1f} min  {s / dur:4.0%}  {lab}')
    long_ = sorted((s for s in stretches if s[1] - s[0] >= a.min), key=lambda s: s[0] - s[1])[:a.top]
    print(f'\nlongest still stretches (≥{a.min:.0f} s):')
    for s, e, lab, ci in sorted(long_):
        cmd = cs[ci][2][:70] if ci is not None else ''
        print(f'  {time.strftime("%M:%S", time.gmtime(s))}  {e - s:5.1f}s  {lab:38s} {cmd}')


if __name__ == '__main__':
    sys.exit(main())
