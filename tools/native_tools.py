"""Host-facing native gameplay tool schemas and result packaging."""
import json
import time
import uuid

from game import native_bridge
from runtime.run_store import RunStore


SCHEMAS = {
    'wf_observe': {'operation': 'observe', 'arguments': {'goal': 'string?', 'params': 'object?'}},
    'wf_act': {'operation': 'act', 'arguments': {
        'turn_id': 'integer', 'action': 'object', 'objective': 'string?', 'location': 'string?'}},
    'wf_note': {'operation': 'note', 'arguments': {
        'turn_id': 'integer', 'finding': 'string', 'evidence_ids': 'string[]'}},
}


def package(receipt):
    """Return bounded text and the exact saved frame as separate native content blocks."""
    receipt = dict(receipt)
    image = receipt.pop('image', None)
    content = [{'type': 'text', 'text': json.dumps(receipt, separators=(',', ':'))}]
    if image and image.get('path'):
        content.append({'type': 'image', 'path': image['path'],
                        'mime_type': image.get('mime_type', 'image/jpeg')})
    return {'content': content}


def _values(args):
    values = {}
    for arg in args:
        key, sep, value = arg.partition('=')
        if not sep or not key or key in values:
            raise ValueError(f'native arguments must be unique key=value entries: {arg!r}')
        try:
            values[key] = json.loads(value)
        except json.JSONDecodeError:
            values[key] = value
    return values


OWNER = 'chatgpt_native_computer_use'
TRANSPORT = 'wf_daemon_argv_v1'


def _event(store, phase, payload, *, turn_id=None, stamp=None):
    RunStore(store.db).append_event('timing', payload, phase=phase, turn_id=turn_id,
                                    run_id=store.run_id, t=stamp)


def _ready(store, operation, call_id, started, request_turn_id, receipt):
    package_started = time.time()
    result = package(receipt)
    ready = time.time()
    encoded = json.dumps(result, separators=(',', ':')).encode()
    outcome = receipt.get('result') or {}
    _event(store, 'bridge.receipt_ready', {
        'call_id': call_id, 'operation': operation, 'owner': OWNER, 'transport': TRANSPORT,
        'call_received_at': started, 'receipt_ready_at': ready,
        'request_turn_id': request_turn_id, 'next_turn_id': receipt.get('turn_id'),
        'experience_id': outcome.get('experience'), 'outcome_status': outcome.get('status'),
        'packaging_seconds': round(max(0.0, ready - package_started), 6),
        'output_bytes': len(encoded),
    }, turn_id=receipt.get('turn_id'), stamp=ready)
    return result


def invoke(operation, args):
    values = _values(args)
    store = native_bridge._current_store()
    started, call_id = time.time(), uuid.uuid4().hex
    request_turn_id = values.get('turn_id') if type(values.get('turn_id')) is int else None
    _event(store, 'bridge.call_received', {
        'call_id': call_id, 'operation': operation, 'owner': OWNER, 'transport': TRANSPORT,
        'call_received_at': started, 'request_turn_id': request_turn_id,
    }, turn_id=request_turn_id, stamp=started)
    try:
        if operation == 'observe':
            goal = values.pop('goal', None)
            params = values.pop('params', None) or values
            receipt = native_bridge.observe(goal, params or None)
            return _ready(store, operation, call_id, started, request_turn_id, receipt)
        if operation == 'act':
            allowed = {'turn_id', 'action', 'objective', 'location'}
            if set(values) - allowed or 'turn_id' not in values or 'action' not in values:
                raise ValueError('native act needs turn_id and action, with optional objective/location')
            receipt = native_bridge.act(values['turn_id'], values['action'],
                                        values.get('objective'), values.get('location'))
            return _ready(store, operation, call_id, started, request_turn_id, receipt)
        if operation == 'note':
            allowed = {'turn_id', 'finding', 'evidence_ids'}
            if set(values) != allowed:
                raise ValueError('native note needs turn_id, finding and evidence_ids')
            result = native_bridge.note(values['turn_id'], values['finding'], values['evidence_ids'])
            ready = time.time()
            packaged = {'content': [{'type': 'text', 'text': json.dumps(result, separators=(',', ':'))}]}
            _event(store, 'bridge.receipt_ready', {
                'call_id': call_id, 'operation': operation, 'owner': OWNER, 'transport': TRANSPORT,
                'call_received_at': started, 'receipt_ready_at': ready,
                'request_turn_id': request_turn_id, 'next_turn_id': request_turn_id,
                'packaging_seconds': 0.0,
                'output_bytes': len(json.dumps(packaged, separators=(',', ':')).encode()),
            }, turn_id=request_turn_id, stamp=ready)
            return packaged
        raise ValueError(f'unknown native operation: {operation!r}')
    except Exception as error:
        failed = time.time()
        _event(store, 'bridge.call_failed', {
            'call_id': call_id, 'operation': operation, 'owner': OWNER, 'transport': TRANSPORT,
            'call_received_at': started, 'failed_at': failed, 'request_turn_id': request_turn_id,
            'error_type': type(error).__name__,
        }, turn_id=request_turn_id, stamp=failed)
        raise


def cli(operation, args):
    print(json.dumps(invoke(operation, args), separators=(',', ':')))
