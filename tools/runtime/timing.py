"""Optional, payload-free boundary timings; append diagnostics survive client cancellation/process failure."""
import json
import os
import time
from contextlib import contextmanager


@contextmanager
def measure(phase, **details):
    path = os.environ.get('WF_TIMING_FILE')
    if not path:
        yield
        return
    started = time.perf_counter()
    status = 'ok'
    try:
        yield
    except BaseException:
        status = 'error'
        raise
    finally:
        row = dict(t=time.time(), pid=os.getpid(), phase=phase, seconds=round(time.perf_counter() - started, 6),
                   status=status, **details)
        try:
            with open(path, 'a') as stream:
                stream.write(json.dumps(row) + '\n')
        except (OSError, TypeError, ValueError):
            pass  # diagnostic failure must never change evidence/input behavior
