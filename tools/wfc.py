"""Thin client for the warm `wf` daemon. Falls back to running tools/wf.py directly (and starts the daemon)."""
import json
import os
import socket
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get('WF_SHOT_DIR', os.path.join(ROOT, '.shots')), 'wf.sock')
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
WF = os.path.join(ROOT, 'tools', 'wf.py')
LOCAL_ONLY = {'serve', 'wiki', 'wait', 'tips', 'actions', 'run', 'learn'}


def via_daemon(argv):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(600)
    s.connect(SOCK)
    s.sendall(json.dumps(argv).encode() + b'\n')
    data = b''
    while not data.endswith(b'\n'):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    res = json.loads(data.decode())
    sys.stdout.write(res['out'])
    return res['code']


def log_call(argv):
    """Append each call to .shots/actions.log (`<unix time>\t<args>`); tools/record.py shows it as a caption.
    Returns the start time (None if not logged); log_end() then writes `<start>\t<end>` to actions_done.log."""
    if argv and argv[0] not in ('stop', 'status', 'log', 'save', 'wiki', 'tips', 'actions', 'run', 'learn', '-h', '--help'):
        try:
            import time
            t = round(time.time(), 2)
            with open(os.path.join(os.path.dirname(SOCK), 'actions.log'), 'a') as f:
                f.write(f"{t:.2f}\t{' '.join(argv)}\n")
            return t
        except OSError:
            pass
    return None


def log_end(start, argv):
    """Call end time, so tools/idle.py can split still time into 'command running' vs 'agent thinking';
    also one `call` event in the open run log (tools/wf.py run_log, L53)."""
    if start is not None:
        try:
            import time
            end = time.time()
            shots = os.path.dirname(SOCK)
            with open(os.path.join(shots, 'actions_done.log'), 'a') as f:
                f.write(f'{start:.2f}\t{end:.2f}\n')
            run = open(os.path.join(shots, 'run.current')).read().strip()
            if run:
                with open(run, 'a') as f:
                    f.write(json.dumps({'t': start, 'type': 'call', 'start': start, 'end': round(end, 2),
                                        'cmd': ' '.join(argv)}) + '\n')
        except OSError:
            pass


def main():
    argv = sys.argv[1:]
    start = log_call(argv)
    if argv and argv[0] in ('-h', '--help'):
        os.execv(PY, [PY, WF] + argv)
    if argv and argv[0] == 'stop':
        subprocess.run(['pkill', '-f', 'tools/wf.py serve'])
        return 0
    if argv and argv[0] not in LOCAL_ONLY and os.environ.get('WF_NO_DAEMON') != '1':
        try:
            code = via_daemon(argv)
            log_end(start, argv)
            return code
        except (OSError, ValueError):
            # start the daemon for next time, run this call locally
            log = open(os.path.join(os.path.dirname(SOCK), 'daemon.log'), 'a')
            subprocess.Popen([PY, WF, 'serve'], stdout=log, stderr=log, start_new_session=True)
    os.execv(PY, [PY, WF] + argv)


if __name__ == '__main__':
    sys.exit(main())
