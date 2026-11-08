"""Thin client for the warm `wf` daemon. Falls back to running tools/wf.py directly (and starts the daemon)."""
import json
import os
import re
import socket
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # wrapper uses -I; import only this owned tools dir
from runtime.timing import measure
from runtime.db import Database
from runtime.run_store import RunStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOCK = os.path.join(os.environ.get('WF_SHOT_DIR', os.path.join(ROOT, '.shots')), 'wf.sock')
PY = os.path.join(ROOT, '.venv', 'bin', 'python')
WF = os.path.join(ROOT, 'tools', 'wf.py')
LOCAL_ONLY = {'serve', 'wiki', 'wait', 'tips', 'actions', 'learn', 'routines'}  # run: in the daemon (game clock for step stamps, L76)
LOCAL_AUTOMATION = (
    ('controller', 'tools/wf.py serve'),
    ('watcher', r'tools/runwatch\.py .*--follow'),
)

# Model-owned gameplay returns a settled receipt and then reasons before the next call.  Wylde Flowers advances
# its clock whenever it remains frontmost, so freeze that reasoning interval even when the user's persistent
# focus-mode is `front`.  The next input focuses the game again; this does not change the saved focus-mode setting.
GAMEPLAY_RECEIPTS = frozenset({'play', 'achieve', 'garden', 'sleep', 'forage'})


def freeze_after_gameplay_receipt(argv, run=subprocess.run, sleep=time.sleep, monotonic=time.monotonic):
    """Keep Warp frontmost through the game's background-save bounce after a gameplay receipt."""
    if not argv or argv[0] not in GAMEPLAY_RECEIPTS:
        return False
    try:
        from AppKit import NSWorkspace
        from Foundation import NSDate, NSRunLoop
        warp = 'dev.warp.Warp-Stable'
        deadline, stable_since, activated = monotonic() + 8.0, None, False
        while monotonic() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.01))
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            front = app.bundleIdentifier() if app is not None else None
            now = monotonic()
            if front == warp:
                stable_since = stable_since or now
                # Wylde Flowers can reclaim focus when its ~2-second background save finishes. Do not declare the
                # handoff safe until Warp survives beyond that bounce.
                if now - stable_since >= 3.0:
                    return True
            else:
                stable_since = None
                activated = (run(['open', '-b', warp], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL).returncode == 0) or activated
            sleep(0.1)
        return False
    except (ImportError, OSError):
        return False


class DeliveryUnknown(RuntimeError):
    """The daemon may have accepted this request. Never automatically resend or execute it locally."""


def via_daemon(argv, timeout=60., with_meta=False):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    deadline = time.monotonic() + timeout
    delivered = False
    received = 0
    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('RPC deadline exceeded')
        s.settimeout(seconds)
    try:
        with measure('client.connect', command=argv[0] if argv else ''):
            remaining()
            s.connect(SOCK)
        with measure('client.send', command=argv[0] if argv else ''):
            remaining()
            delivered = True  # even a partial send can have reached the server
            s.sendall(json.dumps(argv).encode() + b'\n')
        chunks = []
        with measure('client.receive', command=argv[0] if argv else ''):
            while True:
                remaining()
                chunk = s.recv(65536)
                if not chunk:
                    raise EOFError('daemon closed before a complete response')
                chunks.append(chunk)
                received += len(chunk)
                if chunk.endswith(b'\n'):
                    break
        data = b''.join(chunks)  # linear assembly; repeated bytes concatenation stalls large NEXT evidence
        with measure('client.decode', bytes=len(data)):
            res = json.loads(data.decode())
            if not isinstance(res, dict) or not isinstance(res.get('out'), str) or type(res.get('code')) is not int:
                raise ValueError('invalid daemon response envelope')
        with measure('client.output', bytes=len(res['out'])):
            sys.stdout.write(res['out'])
        result = (res['code'], bool(res.get('input_issued', True)))
        return result if with_meta else result[0]
    except (OSError, ValueError, EOFError) as error:
        if delivered:
            raise DeliveryUnknown(f'outcome unknown after request delivery ({received} response bytes): {error}; '
                                  'not retried; inspect the current task/turn before another decision') from error
        raise
    finally:
        s.close()


def log_call(argv):
    """Append each call to .shots/actions.log (`<unix time>\t<args>`); tools/record.py shows it as a caption.
    Returns the start time (None if not logged); log_end() then writes `<start>\t<end>` to actions_done.log."""
    if argv and argv[0] not in ('stop', 'status', 'log', 'save', 'wiki', 'tips', 'actions', 'run', 'learn', 'routines',
                                'eval', 'bench', 'objects', 'graph', '-h', '--help'):
        try:
            import time
            t = round(time.time(), 2)
            with open(os.path.join(os.path.dirname(SOCK), 'actions.log'), 'a') as f:
                f.write(f"{t:.2f}\t{' '.join(argv)}\n")
            return t
        except Exception:  # noqa: BLE001 - call accounting must not replace an already-known delivery result
            pass
    return None


def log_end(start, argv, delivery=None):
    """Call end time, so tools/idle.py can split still time into 'command running' vs 'agent thinking';
    also one `call` event in the active SQLite run without importing the game or starting its daemon."""
    if start is not None:
        try:
            import time
            end = time.time()
            shots = os.path.dirname(SOCK)
            with open(os.path.join(shots, 'actions_done.log'), 'a') as f:
                f.write(f'{start:.2f}\t{end:.2f}\n')
            row = {'start': start, 'end': round(end, 2), 'cmd': ' '.join(argv)}
            if delivery:
                row['delivery'] = delivery
            path = os.environ.get('WF_DB', os.path.join(ROOT, 'runs', 'wf.sqlite3'))
            if os.path.exists(path):
                RunStore(Database(path)).append_event('call', row, t=end)
        except Exception:  # noqa: BLE001 - accounting must not obscure a command's delivery result
            pass


READ_ONLY = {'log', 'save', 'state', 'look', 'shot', 'objects', 'graph', 'run', 'eval', 'bench', 'wiki', 'tips', 'actions',
             'routines', 'learn', 'status', 'focus-mode', 'coverage', 'world', 'gaps'}
_CALL = re.compile(r'(?:^|[\s;&|(\'"`])(?:\./wf|\S*wf\.py|\S*wfc\.py)(?=\s|$)')
_JOIN = re.compile(r';|&&|\|\||\n')


def parent_cmdline():
    try:
        return subprocess.run(['ps', '-o', 'command=', '-p', str(os.getppid())], capture_output=True, text=True).stdout
    except OSError:
        return ''


def chain_refusal(argv, parent):
    """AGENTS.md rule 8: a message when `argv` (not read-only) runs in a shell line `parent` that chains >= 2 ./wf calls
    with ; && || or a newline, else None."""
    if not argv or (argv[0] in READ_ONLY and not (argv[0] == 'focus-mode' and len(argv) > 1)):
        return None
    if len(_CALL.findall(parent or '')) >= 2 and _JOIN.search(parent):
        return 'REFUSED: one game command per tool call (AGENTS.md rule 8) \u2014 run each ./wf call in its own tool call'
    return None


CODE = [os.path.join(ROOT, 'tools')]
# play and all domain aliases share the daemon's durable task; none are LOCAL_ONLY.
# These change executable vocabulary/configuration loaded at import time. Learning journals, actions.json,
# graph JSON and image/vector stores are read hot and must never erase the daemon's process context.
CONFIG = {'goals.json', 'kinds.json', 'forage.json'}


def code_mtimes():
    out = []
    for p in CODE:
        if os.path.isdir(p):
            for directory, subdirs, files in os.walk(p):
                subdirs[:] = [d for d in subdirs if d != '__pycache__']
                out += [os.path.getmtime(os.path.join(directory, f)) for f in files
                        if f.endswith('.py') or (os.path.basename(directory) == 'game' and f in CONFIG)]
        elif os.path.exists(p):
            out.append(os.path.getmtime(p))
    return out


def stale(started, mtimes):
    """The daemon runs older code than the files (it imports game modules once): restart it (L141)."""
    return bool(mtimes) and max(mtimes) > started


def stop_local_automation(run=subprocess.run, unlink=os.unlink, sleep=time.sleep):
    """Terminate every local process that can drive/watch gameplay and verify that each one is gone."""
    attempted, errors = [], []
    quiet = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
    for label, pattern in LOCAL_AUTOMATION:
        attempted.append(label)
        try:
            result = run(['pkill', '-f', pattern], **quiet)
            if result.returncode not in (0, 1):
                errors.append(f'{label} stop failed (exit {result.returncode})')
        except OSError as error:
            errors.append(f'{label} stop failed: {error}')
    try:
        unlink(SOCK)
    except FileNotFoundError:
        pass
    except OSError as error:
        errors.append(f'socket cleanup failed: {error}')
    for label, pattern in LOCAL_AUTOMATION:
        for attempt in range(10):
            try:
                result = run(['pgrep', '-f', pattern], **quiet)
            except OSError as error:
                errors.append(f'{label} verification failed: {error}')
                break
            if result.returncode == 1:
                break
            if result.returncode != 0:
                errors.append(f'{label} verification failed (exit {result.returncode})')
                break
            if attempt == 9:
                errors.append(f'{label} still running')
                break
            sleep(0.05)
    return attempted, errors


def main():
    argv = sys.argv[1:]
    msg = chain_refusal(argv, parent_cmdline())
    if msg:
        print(msg, file=sys.stderr)
        return 2
    start = log_call(argv)
    if argv and argv[0] in ('-h', '--help'):
        os.execv(PY, [PY, WF] + argv)
    if argv and argv[0] == 'stop':
        attempted, errors = stop_local_automation()
        if errors:
            print(f'STOP FAILED: {"; ".join(errors)}', file=sys.stderr)
            return 1
        print(f'stopped: {", ".join(attempted)}')
        return 0
    if argv and argv[0] not in LOCAL_ONLY and not (argv[0] in ('objects', 'graph') and os.environ.get('WF_FRAME')) and os.environ.get('WF_NO_DAEMON') != '1':
        try:
            if os.path.exists(SOCK) and stale(os.path.getmtime(SOCK), code_mtimes()):
                print('wf: code changed since the daemon started: restarting it', file=sys.stderr)
                subprocess.run(['pkill', '-f', 'tools/wf.py serve'])
                os.remove(SOCK)
        except OSError:
            pass
        try:
            delivered = via_daemon(argv, with_meta=True)
            code, input_issued = delivered if isinstance(delivered, tuple) else (delivered, True)
            if input_issued:
                freeze_after_gameplay_receipt(argv)
            log_end(start, argv)
            return code
        except DeliveryUnknown as error:
            freeze_after_gameplay_receipt(argv)
            log_end(start, argv, delivery='unknown')
            print(f'ERROR: {error}', file=sys.stderr)
            return 1
        except (OSError, ValueError):
            # start the daemon and send this call to it: a process run straight from some shells lacks the
            # Screen Recording grant the daemon has (macOS attributes permissions by launching process)
            import time
            with open(os.path.join(os.path.dirname(SOCK), 'daemon.log'), 'a') as log:
                subprocess.Popen([PY, WF, 'serve'], stdout=log, stderr=log, start_new_session=True)
            for _ in range(60):
                time.sleep(0.25)
                try:
                    delivered = via_daemon(argv, with_meta=True)
                    code, input_issued = delivered if isinstance(delivered, tuple) else (delivered, True)
                    if input_issued:
                        freeze_after_gameplay_receipt(argv)
                    log_end(start, argv)
                    return code
                except DeliveryUnknown as error:
                    freeze_after_gameplay_receipt(argv)
                    log_end(start, argv, delivery='unknown')
                    print(f'ERROR: {error}', file=sys.stderr)
                    return 1
                except (OSError, ValueError):
                    pass
    os.execv(PY, [PY, WF] + argv)


if __name__ == '__main__':
    sys.exit(main())
