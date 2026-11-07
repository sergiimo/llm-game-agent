"""Canonical turn-envelope lookup and compact durable-task migration."""
import json


SCHEMA = 2


def records(log_path, evidence_refs):
    """Return exact intent/outcome envelopes in requested ID order; fail on missing or conflicting evidence."""
    wanted = list(dict.fromkeys(evidence_refs or ()))
    if not wanted:
        return []
    intents, found = {}, {}
    try:
        with open(log_path) as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if row.get('type') != 'turn':
                    continue
                key = (row.get('task_id'), row.get('turn_id'))
                if row.get('phase') == 'intent' and isinstance(row.get('intent'), dict):
                    # A stale/retried request may legitimately reuse a turn ID. The canonical envelope is
                    # chronological: an outcome belongs to the latest preceding intent for that task/turn.
                    intents[key] = row['intent']
                elif row.get('phase') == 'outcome' and isinstance(row.get('experience'), dict):
                    experience = row['experience']
                    experience_id = experience.get('id')
                    if experience_id not in wanted:
                        continue
                    intent = intents.get(key)
                    if intent is None:
                        raise ValueError(f'outcome {experience_id} lacks its canonical intent record')
                    envelope = {'experience': experience, 'before': intent.get('before', {}),
                                'action': intent.get('action', {}), 'expects': intent.get('expects', {})}
                    old = found.get(experience_id)
                    if old is not None and old != envelope:
                        raise ValueError(f'conflicting outcome records for experience {experience_id}')
                    found[experience_id] = envelope
    except OSError as error:
        raise ValueError(f'cannot read canonical turn log: {error}') from error
    missing = [experience_id for experience_id in wanted if experience_id not in found]
    if missing:
        raise ValueError('canonical turn log lacks experiences: ' + ', '.join(missing))
    return [found[experience_id] for experience_id in wanted]


def public_task(task):
    """Current model-facing state only; raw evidence remains in the journals and is addressed by ID."""
    from .task_state import thaw
    data = thaw(task)
    for key in ('current_turn', 'last_experience', 'last_surprise', 'pending_intent'):
        data.pop(key, None)
    return data


def _inline_groups(task):
    groups = []
    root = task.params.get('_outcomes')
    if root is not None:
        groups.append(('root', task, root))
    for child in task.stack:
        if 'outcomes' in child.result:
            groups.append(('subgoal', child, child.result['outcomes']))
    for completed in task.params.get('_subgoal_results', ()):
        result = completed.get('result', {})
        if 'outcomes' in result:
            groups.append(('completed', completed, result['outcomes']))
    for cancelled in task.params.get('_cancelled_subgoals', ()):
        child = cancelled.get('subgoal', {})
        result = child.get('result', {})
        if 'outcomes' in result:
            groups.append(('cancelled', child, result['outcomes']))
    return groups


def compact(task, log_path):
    """Remove reconstructible legacy outcome bodies after proving their exact canonical journal records."""
    if getattr(task, 'history_schema', 1) >= SCHEMA:
        if task.current_turn and isinstance(task.current_turn, dict):
            task.current_turn['task'] = public_task(task)
        return False
    groups = _inline_groups(task)
    inline = [row for _, _, rows in groups for row in rows]
    ids = [row.get('experience', {}).get('id') for row in inline]
    if any(not isinstance(experience_id, str) or not experience_id for experience_id in ids):
        raise ValueError('legacy inline outcome lacks an experience ID')
    canonical = {row['experience']['id']: row for row in records(log_path, ids)} if ids else {}
    for row in inline:
        exact = canonical[row['experience']['id']]
        for key in ('experience', 'before', 'action'):
            if row.get(key) != exact[key]:
                raise ValueError(f'legacy outcome {row["experience"]["id"]} conflicts with canonical {key}')
        if 'expects' in row and row['expects'] != exact['expects']:
            raise ValueError(f'legacy outcome {row["experience"]["id"]} conflicts with canonical expectations')

    for kind, owner, rows in groups:
        refs = [row['experience']['id'] for row in rows]
        if kind == 'root':
            for experience_id in refs:
                if experience_id not in task.evidence_refs:
                    task.evidence_refs.append(experience_id)
            task.params.pop('_outcomes', None)
        elif kind == 'subgoal':
            for experience_id in refs:
                if experience_id not in owner.evidence_refs:
                    owner.evidence_refs.append(experience_id)
            owner.result.pop('outcomes', None)
        else:
            for experience_id in refs:
                if experience_id not in owner.setdefault('evidence_refs', []):
                    owner['evidence_refs'].append(experience_id)
            owner.get('result', {}).pop('outcomes', None)
    task.history_schema = SCHEMA
    if task.current_turn and isinstance(task.current_turn, dict):
        task.current_turn['task'] = public_task(task)
    return True
