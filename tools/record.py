"""Record the game window to an MP4 with the current ./wf command as a caption (how an agent plays).

Captures the window itself (CGWindowListCreateImage), so it works while other windows cover the game.
Captions come from .shots/actions.log, written by every ./wf call (tools/wfc.py).
Next to the video it writes two tracks for tools/idle.py (visible non-doing time):
  <video>.tara.tsv    video-seconds \t Tara's activity \t tracker confidence (wf.Tara, L52: scoped to her, so water,
                      NPCs and camera pans don't count; first line `# t0 <unix>`)
  <video>.events.tsv  video-seconds \t game-log line, stamped when it appeared (hits, pickups, dialogue, scenes)

  .venv/bin/python tools/record.py start [--fps 8] [--width 1280]   # background; prints the output path
  .venv/bin/python tools/record.py stop
Needs: imageio-ffmpeg in .venv (bundled ffmpeg binary). Run outside the sandbox.
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
SHOTS = os.path.join(ROOT, '.shots')
PIDFILE = os.path.join(SHOTS, 'record.pid')
ACTIONS = os.path.join(SHOTS, 'actions.log')
OUT_DIR = os.path.join(ROOT, 'recordings')


def last_action(t0):
    """Latest ./wf call since the recording started: (seconds ago, text)."""
    try:
        line = open(ACTIONS).read().rstrip('\n').rsplit('\n', 1)[-1]
        ts, txt = line.split('\t', 1)
        if float(ts) >= t0:
            return time.time() - float(ts), txt
    except (OSError, ValueError):
        pass
    return None, ''


def run(fps, width, out):
    import imageio_ffmpeg
    from PIL import ImageDraw, ImageFont
    import wf
    win = wf.require_window()  # whole window: the game draws under the title bar, the 16:9 frame would clip it
    height = round(width * win['h'] / win['w'] / 2) * 2
    ff = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-loglevel', 'error', '-y', '-f', 'rawvideo',
                           '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps), '-i', '-',
                           '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-pix_fmt', 'yuv420p', out],
                          stdin=subprocess.PIPE)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', max(14, width // 60))
    except OSError:
        font = ImageFont.load_default()
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    base = os.path.splitext(out)[0]
    mo, ev = open(base + '.tara.tsv', 'w', buffering=1), open(base + '.events.tsv', 'w', buffering=1)
    try:
        logpos = os.path.getsize(wf.GAME_LOG)  # own read position: don't disturb ./wf log's
    except OSError:
        logpos = None
    t0, n, frame, tara, reseed = time.time(), 0, None, None, True
    mo.write(f'# t0 {t0:.2f}\n')  # tools/idle.py aligns video time with actions.log by this
    while not stop:
        try:
            raw = wf.grab(crop=False)
            frame = raw.resize((width, height))
            if reseed or tara.conf < 0.4:  # new scene / lost her: Tara is back at the camera centre
                tara, reseed = wf.Tara(), False
            act = tara.update(wf._to_frame(raw, win))
            mo.write(f'{time.time() - t0:.3f}\t{act:.2f}\t{tara.conf:.2f}\n')
        except Exception:
            pass  # window briefly unavailable: repeat the last frame
        vt = time.time() - t0
        if logpos is not None:
            try:
                with open(wf.GAME_LOG, 'rb') as fh:
                    fh.seek(logpos)
                    data = fh.read()
                end = data.rfind(b'\n') + 1
                logpos += end
                for l in data[:end].decode('utf-8', 'replace').splitlines():
                    if l.startswith('[D') and not wf.LOG_NOISE.search(l):
                        ev.write(f'{vt:.3f}\t{l}\n')
                        if re.search(r'ChangeScene|OnEnterBuilding|OnExitBuilding|Spawning player', l):
                            reseed = True
            except OSError:
                pass
        if frame is not None:
            img = frame.copy()
            ago, txt = last_action(t0)
            d = ImageDraw.Draw(img)
            clock = time.strftime('%H:%M:%S', time.gmtime(time.time() - t0))
            cap = f'{clock}  ./wf {txt}' if txt else clock
            if ago is not None and ago > 20:
                cap += '   (thinking…)'
            box = d.textbbox((0, 0), cap, font=font)
            d.rectangle((0, height - box[3] - 16, width, height), fill=(0, 0, 0))
            d.text((10, height - box[3] - 8), cap, fill=(255, 255, 255), font=font)
            ff.stdin.write(img.tobytes())
        n += 1
        time.sleep(max(0.0, t0 + n / fps - time.time()))  # real-time pacing: video time = wall time
    ff.stdin.close()
    ff.wait()
    mo.close()
    ev.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['start', 'stop', '_run'])
    ap.add_argument('--fps', type=int, default=8)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--out')
    a = ap.parse_args()
    if a.cmd == 'start':
        os.makedirs(OUT_DIR, exist_ok=True)
        out = a.out or os.path.join(OUT_DIR, time.strftime('play-%Y%m%d-%H%M%S.mp4'))
        log = open(os.path.join(SHOTS, 'record.log'), 'a')
        p = subprocess.Popen([sys.executable, __file__, '_run', '--fps', str(a.fps), '--width', str(a.width),
                              '--out', out], stdout=log, stderr=log, start_new_session=True)
        open(PIDFILE, 'w').write(f'{p.pid}\n{out}\n')
        print(out)
    elif a.cmd == 'stop':
        pid, out = open(PIDFILE).read().split('\n')[:2]
        os.kill(int(pid), signal.SIGTERM)
        for _ in range(100):
            try:
                os.kill(int(pid), 0)
                time.sleep(0.1)
            except OSError:
                break
        os.remove(PIDFILE)
        print(out, f'{os.path.getsize(out) / 1e6:.1f} MB')
    else:
        run(a.fps, a.width, a.out)


if __name__ == '__main__':
    main()
