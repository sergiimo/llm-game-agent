"""Compact native-owner tools over the existing durable gameplay turn boundary."""
from . import play
from .turn import Decision, StaleTurn


_KINDS = frozenset({'waypoint', 'target', 'bubble', 'press', 'space', 'close', 'key'})
_MENU_KEYS = frozenset({'j', 'm', 'i', 'escape'})


def _point(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2 or
            any(type(number) not in (int, float) for number in value)):
        raise ValueError('action point must be two canonical pixel numbers')
    x, y = value
    if not 0 <= x < 1920 or not 0 <= y < 1080:
        raise ValueError('action point outside canonical 1920x1080 frame')
    return [round(x), round(y)]


def _action(raw, objective=None):
    if not isinstance(raw, dict):
        raise ValueError('action must be an object')
    action = dict(raw)
    kind = action.get('kind')
    if kind not in _KINDS:
        raise ValueError(f'unsupported native action kind: {kind!r}')
    if kind == 'waypoint':
        action['point'] = _point(action.get('point'))
        action['walkable'] = True
        action['expects'] = {**dict(action.get('expects') or {}), 'moved': True}
    elif kind == 'target':
        if action.get('point') is not None:
            action['point'] = _point(action['point'])
        if not action.get('candidate') and action.get('point') is None:
            raise ValueError('target needs a current candidate or canonical point')
        action['visible_road'] = True
    elif kind == 'bubble':
        if action.get('point') is not None:
            action['point'] = _point(action['point'])
    elif kind == 'press':
        if not isinstance(action.get('label'), str) or not action['label'].strip():
            raise ValueError('press needs a visible control label')
        action['label'] = action['label'].strip()
    elif kind == 'key':
        label = str(action.get('label') or action.get('key') or '').strip().casefold()
        if label not in _MENU_KEYS:
            raise ValueError('native key is limited to j, m, i or escape')
        action = {'kind': 'key', 'label': label}
    elif kind in ('space', 'close'):
        action = {'kind': kind}
    if objective is not None:
        if not isinstance(objective, str) or not objective.strip() or len(objective.strip()) > 320:
            raise ValueError('objective must be nonempty and at most 320 characters')
        action['objective'] = objective.strip()
    return action


def _receipt(context):
    receipt = play._model_receipt(context)
    path = receipt.get('frame_path') or (receipt.get('view') or {}).get('path')
    receipt['image'] = {'path': path, 'mime_type': 'image/jpeg'} if path else None
    return receipt


def observe(goal=None, params=None, *, store=None, adapter=None):
    """Return one current receipt without issuing input."""
    context = play.turn(goal, params, store=store, adapter=adapter)
    if context.observation_freshness == 'cached':
        context = play.turn(params={'turn_id': context.turn_id}, answer=Decision('read'),
                            store=store, adapter=adapter)
    return _receipt(context)


def act(turn_id, action, objective=None, location=None, *, store=None, adapter=None):
    """Consume one current turn with at most one primitive and return its next receipt."""
    if type(turn_id) is not int:
        raise ValueError('turn_id must be an integer')
    normalized = _action(action, objective)
    belief = None
    if objective is not None or location is not None:
        belief = {}
        if objective is not None:
            belief['next_objective'] = objective.strip()
        if location is not None:
            if not isinstance(location, str) or not location.strip() or len(location.strip()) > 320:
                raise ValueError('location must be nonempty and at most 320 characters')
            belief['current'] = location.strip()
    decision = Decision('act', action=normalized, belief_update=belief,
                        rationale='native_owner')
    return _receipt(play.turn(params={'turn_id': turn_id}, answer=decision,
                              store=store, adapter=adapter))


def _current_store():
    from . import core
    directory = core.WF.run_dir()
    run_id = core.WF.run_path()
    if not directory or not run_id:
        raise ValueError('native tools require an active run')
    from runtime.db import Database
    from .task_state import TaskStore
    import os
    database = Database(os.environ.get('WF_DB', os.path.join(os.path.dirname(directory), 'wf.sqlite3')))
    return TaskStore(database, run_id)


def note(turn_id, finding, evidence_ids, *, store=None):
    """Append bounded evidence without consuming or invalidating the current turn."""
    if type(turn_id) is not int or not isinstance(finding, str) or not finding.strip():
        raise ValueError('note needs integer turn_id and nonempty finding')
    finding = finding.strip()
    if len(finding) > 500:
        raise ValueError('finding must be at most 500 characters')
    if (not isinstance(evidence_ids, (list, tuple)) or len(evidence_ids) > 8 or
            any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in evidence_ids)):
        raise ValueError('evidence_ids must contain at most 8 bounded strings')
    store = store or _current_store()
    with store.locked():
        task = store.load()
        current = task.current_turn or {}
        if current.get('turn_id') != turn_id:
            raise StaleTurn(f'turn {turn_id} is stale; request context')
        refs = [value.strip() for value in evidence_ids]
        store.append_event(task, turn_id, 'native.note', finding=finding, evidence_refs=refs)
        return {'status': 'recorded', 'turn_id': turn_id, 'finding': finding,
                'evidence_ids': refs, 'task_id': task.task_id}
