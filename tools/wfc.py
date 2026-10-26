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
LOCAL_ONLY = {'serve', 'wiki', 'wait', 'tips'}


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


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ('-h', '--help'):
        os.execv(PY, [PY, WF] + argv)
    if argv and argv[0] == 'stop':
        subprocess.run(['pkill', '-f', 'tools/wf.py serve'])
        return 0
    if argv and argv[0] not in LOCAL_ONLY and os.environ.get('WF_NO_DAEMON') != '1':
        try:
            return via_daemon(argv)
        except (OSError, ValueError):
            # start the daemon for next time, run this call locally
            log = open(os.path.join(os.path.dirname(SOCK), 'daemon.log'), 'a')
            subprocess.Popen([PY, WF, 'serve'], stdout=log, stderr=log, start_new_session=True)
    os.execv(PY, [PY, WF] + argv)


if __name__ == '__main__':
    sys.exit(main())
