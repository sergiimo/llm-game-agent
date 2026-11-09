"""Host-facing native gameplay tool schemas and result packaging."""
import json

from game import native_bridge


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


def invoke(operation, args):
    values = _values(args)
    if operation == 'observe':
        goal = values.pop('goal', None)
        params = values.pop('params', None) or values
        return package(native_bridge.observe(goal, params or None))
    if operation == 'act':
        allowed = {'turn_id', 'action', 'objective', 'location'}
        if set(values) - allowed or 'turn_id' not in values or 'action' not in values:
            raise ValueError('native act needs turn_id and action, with optional objective/location')
        return package(native_bridge.act(values['turn_id'], values['action'],
                                         values.get('objective'), values.get('location')))
    if operation == 'note':
        allowed = {'turn_id', 'finding', 'evidence_ids'}
        if set(values) != allowed:
            raise ValueError('native note needs turn_id, finding and evidence_ids')
        result = native_bridge.note(values['turn_id'], values['finding'], values['evidence_ids'])
        return {'content': [{'type': 'text', 'text': json.dumps(result, separators=(',', ':'))}]}
    raise ValueError(f'unknown native operation: {operation!r}')


def cli(operation, args):
    print(json.dumps(invoke(operation, args), separators=(',', ':')))
