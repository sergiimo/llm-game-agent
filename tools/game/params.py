"""Public task declarations, not runtime state. The same explicit schema validates roots and subgoal pushes.

Persisted TaskStore data is trusted recovery state and never passed through this public-input schema. Observation
proofs enter only a versioned subgoal decision; root catalogue inputs merely declare requested item/category pairs.
"""
import math
from collections.abc import Mapping


def _require(ok, description, value):
    if not ok:
        raise ValueError(description)
    return value


def text(value):
    return _require(isinstance(value, str) and bool(value.strip()), 'expected nonempty text', value)


def string(value):
    return _require(isinstance(value, str), 'expected text', value)


def boolean(value):
    return _require(type(value) is bool, 'expected boolean', value)


def number(value):
    return _require(type(value) in (int, float) and math.isfinite(value), 'expected finite number', value)


def nonnegative(value):
    number(value)
    return _require(value >= 0, 'expected nonnegative number', value)


def positive_int(value):
    return _require(type(value) is int and value > 0, 'expected positive integer', value)


def integer(value):
    return _require(type(value) is int, 'expected integer', value)


def nonnegative_int(value):
    integer(value)
    return _require(value >= 0, 'expected nonnegative integer', value)


def optional(check):
    return lambda value: None if value is None else check(value)


def sequence(check, length=None):
    def validate(value):
        _require(isinstance(value, (list, tuple)), 'expected list', value)
        if length is not None:
            _require(len(value) == length, f'expected {length} values', value)
        return [check(row) for row in value]
    return validate


def choice(*checks):
    def validate(value):
        for check in checks:
            try:
                return check(value)
            except ValueError:
                pass
        raise ValueError('value does not match the declared schema')
    return validate


def enum(*values):
    return lambda value: _require(isinstance(value, str) and value in values, f'expected one of {values}', value)


def fields(value, schema, required=()):
    _require(isinstance(value, Mapping), 'expected object', value)
    unknown = set(value) - set(schema)
    if unknown:
        raise ValueError(f'unknown public declaration fields: {sorted(map(str, unknown))}')
    missing = set(required) - set(value)
    if missing:
        raise ValueError(f'missing declaration fields: {sorted(missing)}')
    clean = {}
    for key, item in value.items():
        try:
            clean[key] = schema[key](item)
        except ValueError as error:
            raise ValueError(f'{key}: {error}') from None
    return clean


def purchase_rule(value):
    _require(isinstance(value, Mapping), 'expected purchase bound object', value)
    if 'item' in value:
        schema = {'item': text, 'quantity': positive_int, 'max_spend': choice(nonnegative, enum('available_money'))}
    else:
        schema = {'category': text, 'quantity_per_type': positive_int,
                  'max_spend': choice(nonnegative, enum('available_money'))}
    return fields(value, schema, required=schema)


def sale_rule(value):
    return fields(value, {'item': text, 'quantity': positive_int, 'min_unit_price': nonnegative},
                  required=('item', 'quantity'))


def authorization(value):
    return fields(value, {'purchases': sequence(purchase_rule), 'sales': sequence(sale_rule)})


def catalogue_declaration(value):
    return fields(value, {'item': text, 'category': text}, required=('item', 'category'))


def catalogue_observation(value):
    schema = {'item': text, 'category': text, 'available': boolean, 'frame_path': text,
              'evidence_refs': sequence(text)}
    return fields(value, schema, required=schema)


# Runtime accounting, results, intents, coverage, flowers, clock and budget evidence are never public fields.
# Catalogue observations/completeness are allowed only in a versioned subgoal push, never root creation.
_COMMON = {
    'region': optional(text), 'kind': optional(text), 'node': optional(text), 'target': optional(text),
    'destination': text, 'destination_position': sequence(number, 2), 'marker': optional(text),
    'chores': sequence(enum('plant', 'replant', 'harvest', 'water')), 'seed': optional(text),
    'crops': optional(choice(text, sequence(text))), 'job': text, 'max_clicks': nonnegative_int,
    'trade': enum('buy', 'sell'), 'item': optional(text), 'quantity': positive_int, 'max_spend': nonnegative,
}
PUBLIC_PARAM_SCHEMA = {
    'root': {**_COMMON, 'turn_id': positive_int, 'authorization': authorization,
             'catalogue': sequence(catalogue_declaration)},
    'subgoal': {**_COMMON, 'catalogue': sequence(catalogue_observation), 'catalogue_complete': boolean},
}

# Legacy CLI arguments are inert request descriptions. Their exact fields are enumerated rather than accepting
# arbitrary dictionaries that could later be confused with runtime accounting.
_RECT = optional(sequence(number, 4))
LEGACY_PARAM_SCHEMA = {
    'py': {'request': sequence(string)}, 'call': {'request': sequence(string)},
    'goto': {'place': text, 'hops': nonnegative_int}, 'go-world': {'x': number, 'z': number},
    'improve': {'n': nonnegative_int}, 'calib': {'small': boolean},
    'advance': {'max': nonnegative_int, 'look': optional(nonnegative)},
    'teach': {'kind': text, 'cells': sequence(text)}, 'where': {'learn': optional(text)},
    'pos': {'learn': optional(text)}, 'ask-step': {'place': text}, 'plan': {'place': text},
    'do': {'actions': sequence(string), 'look': optional(nonnegative), 'crop': _RECT},
    'key': {'keys': sequence(text), 'hold': nonnegative, 'gap': nonnegative},
    'click': {'x': number, 'y': number, 'right': boolean, 'double': boolean},
    'click-text': {'text': text, 'index': nonnegative_int, 'region': _RECT, 'exact': boolean},
    'hold': {'seconds': nonnegative, 'keys': sequence(text)}, 'walk': {'direction': text, 'seconds': nonnegative},
    'path': {'steps': sequence(text)}, 'scroll': {'dy': integer, 'at': optional(sequence(number, 2))},
    'type': {'text': string}, 'route': {'name': optional(text), 'list': boolean},
    'edge': {'sub': text, 'args': sequence(string)}, 'road': {'go': boolean, 'calibrate': boolean},
}


def validate(params, goal=None, phase='root'):
    schema = dict(PUBLIC_PARAM_SCHEMA[phase])
    if phase == 'root' and isinstance(goal, str):
        schema.update(LEGACY_PARAM_SCHEMA.get(goal, {}))
    return fields({} if params is None else params, schema)
