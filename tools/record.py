"""Record the game window to an MP4 with the current ./wf command as a caption (how an agent plays).

Captures the window itself (CGWindowListCreateImage), so it works while other windows cover the game.
Captions come from .shots/actions.log, written by every ./wf call (tools/wfc.py).

  .venv/bin/python tools/record.py start [--fps 8] [--width 1280]   # background; prints the output path
  .venv/bin/python tools/record.py stop
Needs: imageio-ffmpeg in .venv (bundled ffmpeg binary). Run outside the sandbox.
"""
import argparse
import os
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
    height = width * 9 // 16
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
    t0, n, frame = time.time(), 0, None
    while not stop:
        try:
            frame = wf.grab().convert('RGB').resize((width, height))
        except Exception:
            pass  # window briefly unavailable: repeat the last frame
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
