"""Optional, payload-free boundary timings; append diagnostics survive client cancellation/process failure."""
import json
import os
import time
from contextvars import ContextVar
from contextlib import contextmanager


_CONTEXT = ContextVar('wf_timing_context', default={})


@contextmanager
def scope(**details):
    """Attach run/turn attribution to every nested measurement in this execution block."""
    token = _CONTEXT.set({**_CONTEXT.get(), **details})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _persist(row):
    """Best-effort canonical timing event; diagnostics may never affect gameplay."""
    if os.environ.get('WF_TIMING_DB') != '1':
        return
    try:
        from runtime.db import Database
        from runtime.run_store import RunStore
        path = os.environ.get('WF_DB')
        store = RunStore(Database(path) if path else None)
        payload = {key: value for key, value in row.items() if key not in ('t', 'phase', 'turn_id')}
        turn_id = row.get('turn_id')
        store.append_event('timing', payload, turn_id=int(turn_id) if turn_id is not None else None,
                           phase=row['phase'], t=row['t'])
    except Exception:  # noqa: BLE001 - timing failure cannot replace a gameplay result
        pass


@contextmanager
def measure(phase, _persist_db=True, **details):
    path = os.environ.get('WF_TIMING_FILE')
    persist = os.environ.get('WF_TIMING_DB') == '1'
    if not path and not persist:
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
                   status=status, **_CONTEXT.get(), **details)
        if path:
            try:
                with open(path, 'a') as stream:
                    stream.write(json.dumps(row) + '\n')
            except (OSError, TypeError, ValueError):
                pass  # diagnostic failure must never change evidence/input behavior
        if _persist_db:
            _persist(row)
