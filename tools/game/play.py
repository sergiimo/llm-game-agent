"""Universal model-owned entry point. Constructors/clues never choose or execute gameplay inputs."""
import json
import os
import uuid

from .primitives import GameAdapter
from .task_state import TaskState, TaskStore
from .turn import Decision, Recommendation, TurnLoop


def _clues(store):
    from . import ask, core, engine, garden_policy, observe, world
    graph = engine._open_graph()
    path, save = core.WF.read_save()
    lines = core.WF.today_log()[0]
    world.refresh(graph, save, lines)
    hour, light = observe.clock()
    player = save.get('gameState', {}).get('player', {})
    values = {row['name']: row['value'] for row in player.get('state', {}).get('userState', {}).get('entries', [])}
    money = values.get('money')
    if money is not None:
        money = int(money)
    save_proof = {'source': 'save', 'path': path, 'save_count': save.get('saveCount'),
                  'game_time': world.save_time(save)}
    region = getattr(core.WF, 'current_scene', lambda: None)()
    point = save.get('currentPlayerPosition') or {}
    data = {'graph_clues': ([dict(node=n.id, **n.to_dict()) for n in graph.nodes.values()] +
                            [{'edge': dict(edge)} for edge in graph.edges()]),
            'hour': hour, 'light': light, 'rain': ask.rain(), 'can': graph.state_value('Tara', 'can'),
            'inventory': world.inventory(save, lines), 'money': money, 'region': region,
            'state_provenance': {'inventory': save_proof, 'money': save_proof,
                                 'position': save_proof, 'region': {'source': 'scene_log'}}}
    if 'x' in point and 'z' in point:
        data['position'] = [point['x'], point['z']]
    state = store.load().to_dict() if os.path.exists(store.path) else {
        'params': {'_started_late': hour is not None and hour > 19}}
    blocked = garden_policy.interrupt(domain(state), data)
    data['interrupts'] = [blocked] if blocked else []
    return data


def domain(task):
    """Read the current subgoal without changing the frozen parent interaction or root authorization."""
    if task.get('stack'):
        top = task['stack'][-1]
        params = dict(top['params'], _started_late=task.get('params', {}).get('_started_late', False))
        return dict(task, goal=top['goal'], params=params)
    return task


def recommend(task, observation):
    from . import garden_policy
    current = domain(task)
    if current['goal'] == 'garden':
        return garden_policy.recommend(current, observation)
    return Recommendation(reasons=('model chooses one primitive; read actions/INDEX.md for this workflow',))


def reduce(task, experience):
    from . import garden_policy
    if not task.stack and task.goal == 'garden':
        garden_policy.reduce(task, experience)


def guard(task, action):
    from . import garden_policy
    current = domain(task)
    observation = task.get('_observation', {})
    sleeping = current['goal'] == 'sleep' or any(row['goal'] == 'sleep' for row in task.get('stack', ()))
    if not sleeping and current['goal'] != 'garden':
        blocked = garden_policy.interrupt(current, observation)
        if blocked and action.get('kind') not in ('wait', 'read', 'close'):
            return blocked
    purchase = action.get('purchase')
    label = str(action.get('label', '')).casefold()
    import re
    buying = bool(re.match(r'^(buy|purchase)\b', label)) or current['goal'] == 'shop' and label == 'confirm'
    if (buying or current['goal'] == 'shop' and action.get('kind') in ('select_card', 'space')) and not purchase:
        return 'purchase needs explicit item, quantity and total price'
    if purchase:
        if current['goal'] != 'shop':
            return 'purchase requires an active shop subgoal'
        item, quantity, price = purchase.get('item'), purchase.get('quantity'), purchase.get('price')
        if (not item or type(quantity) is not int or quantity <= 0 or
                type(price) not in (int, float) or price <= 0):
            return 'purchase needs an item, positive integer quantity and bounded positive total price'
        params = current['params']
        if item != params.get('item') or quantity > params.get('quantity', 0) or price > params.get('max_spend', 0):
            return 'purchase exceeds active subgoal item/quantity/spend bounds'
        history = task['params'].get('_purchase_intents', ())
        used_quantity = sum(row['quantity'] for row in history if row['item'] == item)
        used_spend = sum(row['price'] for row in history if row['item'] == item)
        authorized = task['params'].get('authorization', {}).get('purchases', ())
        if not any(row.get('item') == item and quantity + used_quantity <= row.get('quantity', 0) and
                   price + used_spend <= row.get('max_spend', 0) for row in authorized):
            return 'purchase exceeds root task authorization'
    if current['goal'] == 'garden':
        blocked = garden_policy.interrupt(current, task.get('_observation', {}))
        if blocked and action.get('kind') not in ('wait', 'read'):
            return blocked
        return garden_policy.guard(current, action)
    return None


def verify_completion(task, current):
    """Evidence-only completion proof. Model supplied results cannot manufacture successful gameplay."""
    from .turn import DecisionRejected
    outcomes = current.result.get('outcomes', []) if hasattr(current, 'result') else task.params.get('_outcomes', [])
    if not outcomes and current is task and task.last_experience:
        outcomes = [{'experience': task.last_experience}]
    outcomes = [row for row in outcomes if row['experience']['verdict']['value'] != 'unsafe']
    events = {event for row in outcomes for event in row['experience']['evidence']['events']}
    params = current.params
    if current.goal == 'sleep':
        if 'sleep_transition' not in events:
            raise DecisionRejected('sleep completion needs sleep_transition evidence')
        return {'slept': True}
    if current.goal == 'shop':
        purchases = [row for row in outcomes if row.get('action', {}).get('purchase')]
        if not purchases:
            raise DecisionRejected('purchase completion needs an authorized purchase intent')
        first = purchases[0]
        after = dict(outcomes[-1]['experience']['evidence'].get('state', ()))
        before = first['before']
        item, quantity = params.get('item'), params.get('quantity')
        old_count = before.get('inventory', {}).get(item)
        count = after.get('inventory', {}).get(item)
        old_money, money = before.get('money'), after.get('money')
        if None in (old_count, count, old_money, money):
            raise DecisionRejected('purchase needs captured inventory and money evidence on both sides')
        acquired, spent = count - old_count, old_money - money
        intent_quantity = sum(row['action']['purchase']['quantity'] for row in purchases)
        intent_spend = sum(row['action']['purchase']['price'] for row in purchases)
        if acquired != quantity or acquired != intent_quantity or spent != intent_spend or spent <= 0:
            raise DecisionRejected('purchase needs matching inventory delta AND money delta')
        return {'item': item, 'acquired': acquired, 'spent': spent,
                'evidence_refs': list(current.evidence_refs) if hasattr(current, 'evidence_refs') else
                                 [row['experience']['id'] for row in outcomes]}
    if current.goal in ('navigate', 'enter', 'exit'):
        after = dict(outcomes[-1]['experience']['evidence'].get('state', ())) if outcomes else {}
        region = params.get('region')
        if not region or after.get('region') != region:
            raise DecisionRejected('region completion needs captured matching region evidence')
        return {'region': region}
    if current.goal == 'garden' and task.active is None and set(task.targets) <= set(task.covered):
        return {'covered': list(task.covered)}
    raise DecisionRejected('completion proof unavailable; correct/gap or human resolution required')


def _normalize(goal, params):
    params = dict(params or {})
    if isinstance(goal, str) and goal in ('water', 'plant', 'replant', 'harvest'):
        params.setdefault('chores', [goal])
        goal = 'garden'
    return goal, params


def turn(goal=None, params=None, answer=None, store=None, adapter=None):
    """Observe/resume a durable task, or consume exactly one explicit versioned model decision.

    answer may be {turn_id, kind, action/correction, rationale, evidence_refs}; string decisions use params.turn_id.
    The original garden-task.json is adopted in place. No migration writes an ignored run merely to observe it.
    """
    from . import ask, core, garden_policy, learn
    goal, params = _normalize(goal, params)
    turn_id = params.pop('turn_id', None)
    if store is None:
        directory = core.WF.run_dir()
        if not directory:
            raise ValueError('play requires an active run: ./wf run start')
        old = os.path.join(directory, 'garden-task.json')
        store = TaskStore(old if os.path.exists(old) else os.path.join(directory, 'task.json'))
    existing = store.load() if os.path.exists(store.path) else None
    if existing:
        current = domain(existing.to_dict())
        if goal is not None and goal != existing.goal and goal != current['goal']:
            raise ValueError('active task differs; use an explicit push decision for a subgoal')
        for key, value in params.items():
            if current['params'].get(key) != value:
                raise ValueError(f'active task parameter {key} differs; start a new run')
    elif answer is not None:
        raise ValueError('observe a task before supplying a decision')
    adapter = adapter or GameAdapter(clue_provider=lambda: _clues(store))
    if not existing:
        goal = goal or 'play'
        if goal == 'garden':
            params.setdefault('region', 'Garden')
            params.setdefault('chores', list(garden_policy.CHORES))
            if set(params['chores']) - set(garden_policy.CHORES):
                raise ValueError('unknown garden chores')
            with open(os.path.join(os.path.dirname(__file__), 'kinds.json')) as f:
                params['flowers'] = json.load(f).get('_lists', {}).get('flowers', [])
        obs = adapter.observe()
        params['_started_late'] = obs.get('hour') is not None and obs['hour'] > 19
        graph = learn.MEMORY.get('graph')
        targets = garden_policy.coverage(graph, params['region']) if graph and goal == 'garden' else []
        store.create(TaskState(uuid.uuid4().hex, goal, params=params, targets=targets))
    loop = TurnLoop(store, adapter, recommend, reducer=reduce, guard=guard)
    if answer is None:
        return loop.context()
    if isinstance(answer, str) and answer.strip().startswith('{'):
        answer = json.loads(answer)
    if isinstance(answer, dict):
        answer = dict(answer)
        turn_id = answer.pop('turn_id', turn_id)
        answer = Decision(**answer)
    if not isinstance(answer, Decision):
        if isinstance(answer, str):
            import re
            answer = re.sub(r'^(walk|target|bubble|cell):', r'\1 ', answer)
        answer = ask.garden_decision(answer)
    if turn_id is None:
        raise ValueError('continuation requires turn_id from NEXT')
    return loop.decide(int(turn_id), answer)


def summary(context):
    return 'NEXT ' + json.dumps(context.to_dict(), sort_keys=True)


def cli(goal, args):
    """Parse data only. Legacy code/function strings are task descriptions, never evaluated."""
    params, answer = {}, None
    for arg in args:
        key, sep, value = arg.partition('=')
        if not sep:
            raise ValueError(f'expected key=value: {arg!r}')
        if key == 'answer':
            answer = value
        else:
            try:
                params[key] = json.loads(value)
            except ValueError:
                params[key] = value
    if isinstance(goal, str) and goal.startswith('{'):
        goal = json.loads(goal)
    return summary(turn(goal, params, answer))
