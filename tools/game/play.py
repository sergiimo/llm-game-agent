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
            'inventory': world.inventory(save, lines),
            'inventory_complete': isinstance(player.get('inventory', {}).get('items'), list),
            'money': money, 'region': region,
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
    refusal = trade_guard(task, current, action, observation)
    if refusal:
        return refusal
    if current['goal'] == 'garden':
        blocked = garden_policy.interrupt(current, task.get('_observation', {}))
        if blocked and action.get('kind') not in ('wait', 'read'):
            return blocked
        return garden_policy.guard(current, action)
    return None


def trade_guard(task, current, action, observation):
    """Observed financial controls require root authority even under a mislabeled task goal."""
    import math
    import re
    from collections.abc import Mapping
    supplied = [(op, action.get(key)) for op, key in (('buy', 'purchase'), ('sell', 'sale')) if action.get(key)]
    if len(supplied) > 1:
        return 'choose one buy or sell operation per input'
    label = str(action.get('label', '')).strip().casefold()
    control = re.match(r'^(buy|purchase|sell)\b', label)
    direction = ('sell' if control[1] == 'sell' else 'buy') if control else None
    texts = observation.get('screen', {}).get('texts', ())
    directions = {('sell' if match[1].casefold() == 'sell' else 'buy') for text in texts
                  if (match := re.match(r'^\s*(buy|purchase|sell)\b', str(text), re.I))}
    surface = bool(directions) or observation.get('screen', {}).get('kind') == 'shop'
    financial = (direction is not None or label == 'confirm' and (surface or current['goal'] == 'shop') or
                 action.get('kind') in ('select_card', 'space', 'target', 'click', 'cell', 'bubble', 'waypoint') and surface)
    if financial and not supplied:
        return 'observed trade surface/control requires explicit authorized purchase or sale metadata'
    if not supplied:
        return None
    operation, trade = supplied[0]
    if financial and direction is None and len(directions) > 1:
        return 'ambiguous observed Buy/Sell controls require an exact named financial control'
    if not isinstance(trade, Mapping):
        return 'trade metadata must name item, quantity and positive total price'
    if direction and direction != operation or not direction and len(directions) == 1 and operation not in directions:
        return 'trade metadata conflicts with the observed buy/sell control'
    if current['goal'] != 'shop' or current['params'].get('trade', 'buy') != operation:
        return 'trade requires the matching active shop buy/sell subgoal'
    item, quantity, price = trade.get('item'), trade.get('quantity'), trade.get('price')
    if (not isinstance(item, str) or not item or type(quantity) is not int or quantity <= 0 or
            type(price) not in (int, float) or not math.isfinite(price) or price <= 0):
        return 'trade needs an item, positive integer quantity and positive finite total price'
    if action.get('kind') not in ('press', 'select_card', 'space'):
        return 'trade metadata requires one financial control input'
    params, root = current['params'], task['params']
    if item != params.get('item') or quantity > params.get('quantity', 0):
        return 'trade exceeds active subgoal item/quantity bounds'
    key = '_purchase_intents' if operation == 'buy' else '_sale_intents'
    history = root.get(key, ())
    used_quantity = sum(row['quantity'] for row in history if row['item'] == item)
    rules = root.get('authorization', {}).get('purchases' if operation == 'buy' else 'sales', ())
    if operation == 'sell':
        count = inventory_count(observation, item)
        if count is None or count < quantity:
            return 'sale requires observed sufficient item stock'
        if any(row.get('item') == item and quantity + used_quantity <= row.get('quantity', 0) and
               price >= quantity * row.get('min_unit_price', 0) for row in rules):
            return None
        return 'sale exceeds root task item/quantity/price authorization'
    if price > params.get('max_spend', 0):
        return 'purchase exceeds active subgoal spend bound'
    entry = next((row for row in params.get('catalogue', ()) if row.get('item') == item), None)
    for row in rules:
        if row.get('item') == item:
            limit = row.get('quantity', 0)
            spent = sum(old['price'] for old in history if old['item'] == item)
        elif (entry and entry.get('available') is True and entry.get('category') == row.get('category') and
              entry.get('category') and entry.get('frame_path') and entry.get('evidence_refs')):
            limit = row.get('quantity_per_type', 0)
            if params.get('quantity') != limit:
                continue  # catalogue completion must acquire the exact authorized amount of this type
            spent = sum(old['price'] for old in history)
        else:
            continue
        if type(limit) is not int or limit <= 0 or quantity + used_quantity > limit:
            continue
        budget = row.get('max_spend', 0)
        if budget == 'available_money':
            start = root.get('_trade_start_money')
            if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
                continue
            earned = sum(completed['result'].get('earned', 0) for completed in root.get('_subgoal_results', ())
                         if completed['goal'] == 'shop')
            if price + sum(old['price'] for old in history) <= start + earned:
                return None
        elif type(budget) in (int, float) and math.isfinite(budget) and price + spent <= budget:
            return None
    return 'purchase exceeds root task item or discovered available-type quantity/spend authorization'


def register_catalogue(task, params, frames):
    """Persist model-read catalogue facts from captured frames; never choose an item or issue input."""
    from .turn import DecisionRejected
    rows = params.get('catalogue')
    if rows is None:
        if params.get('catalogue_complete'):
            raise DecisionRejected('catalogue_complete requires captured catalogue entries')
        return
    if not isinstance(rows, (list, tuple)) or not rows:
        raise DecisionRejected('catalogue needs a nonempty list of model-observed item entries')
    known = {row['item']: dict(row) for row in task.params.get('_shop_catalogue', ())}
    allowed = set(frames) | {row['frame_path'] for row in known.values()}
    added = False
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('item'), str) or not row['item'] or
                not isinstance(row.get('category'), str) or not row['category'] or
                type(row.get('available')) is not bool or row.get('frame_path') not in allowed or
                not isinstance(row.get('evidence_refs'), (list, tuple)) or
                row.get('frame_path') not in row['evidence_refs']):
            raise DecisionRejected('catalogue entry needs item/category/availability and captured frame references')
        if row['item'] in known and known[row['item']]['category'] != row['category']:
            raise DecisionRejected('catalogue category conflicts with the previously observed item')
        added = added or row['item'] not in known
        known[row['item']] = dict(row)
    task.params['_shop_catalogue'] = list(known.values())
    if 'catalogue_complete' in params:
        task.params['_shop_catalogue_complete'] = params['catalogue_complete'] is True
    elif added:
        task.params['_shop_catalogue_complete'] = False


def trade_receipt(before, after, trade, operation):
    """True only for exact opposite inventory/money deltas; complete sparse snapshots can prove zero."""
    old_count, count = inventory_count(before, trade.get('item')), inventory_count(after, trade.get('item'))
    old_money, money = before.get('money'), after.get('money')
    if None in (old_count, count, old_money, money):
        return False
    sign = -1 if operation == 'sell' else 1
    return count - old_count == sign * trade.get('quantity', 0) and old_money - money == sign * trade.get('price', 0)


def verify_shop_plan(task):
    """Verify all declared sale quantities and every discovered available type; no workflow selection."""
    from .turn import DecisionRejected
    auth = task.params.get('authorization', {})
    results = [row['result'] for row in task.params.get('_subgoal_results', ()) if row['goal'] == 'shop']
    for rule in auth.get('sales', ()):
        if sum(row.get('sold', 0) for row in results if row.get('item') == rule.get('item')) != rule.get('quantity'):
            raise DecisionRejected('shop plan still lacks the required verified sales')
    catalogue_rules = [rule for rule in auth.get('purchases', ()) if rule.get('category')]
    if catalogue_rules and not task.params.get('_shop_catalogue_complete'):
        raise DecisionRejected('shop plan requires explicit captured catalogue-complete evidence')
    for rule in auth.get('purchases', ()):
        items = ([rule['item']] if rule.get('item') else
                 [row['item'] for row in task.params.get('_shop_catalogue', ())
                  if row['available'] and row['category'] == rule.get('category')])
        if not items:
            raise DecisionRejected('shop plan lacks discovered available types')
        for item in items:
            required = rule.get('quantity') if rule.get('item') else rule.get('quantity_per_type')
            if sum(row.get('acquired', 0) for row in results if row.get('item') == item) != required:
                raise DecisionRejected('shop plan still lacks exact verified purchases for every available type')
    if not auth.get('sales') and not auth.get('purchases'):
        raise DecisionRejected('shop plan needs bounded sale or purchase authorization')
    return {'trades_verified': len(results)}


def inventory_count(observation, item):
    """A missing key means zero only in an explicitly complete inventory snapshot."""
    from collections.abc import Mapping
    inventory = observation.get('inventory')
    if observation.get('inventory_complete') is False or not isinstance(inventory, Mapping):
        return None
    count = inventory.get(item)
    if count is None and item not in inventory and observation.get('inventory_complete') is True:
        return 0
    return count if type(count) is int and count >= 0 else None


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
    if current.goal == 'refill':
        if 'fill_watering_can' not in events:
            raise DecisionRejected('refill completion needs fill_watering_can evidence')
        return {'can': 'full'}
    if current.goal == 'shop':
        if current is task and not params.get('item'):
            return verify_shop_plan(task)
        operation = params.get('trade', 'buy')
        key = 'sale' if operation == 'sell' else 'purchase'
        trades = [row for row in outcomes if row.get('action', {}).get(key)]
        if not trades:
            raise DecisionRejected('trade completion needs an authorized buy/sell intent')
        after = dict(outcomes[-1]['experience']['evidence'].get('state', ()))
        before = trades[0]['before']
        item, quantity = params.get('item'), params.get('quantity')
        total_quantity = sum(row['action'][key]['quantity'] for row in trades)
        total_price = sum(row['action'][key]['price'] for row in trades)
        if total_quantity != quantity or not trade_receipt(before, after,
                {'item': item, 'quantity': total_quantity, 'price': total_price}, operation):
            raise DecisionRejected('trade needs matching signed inventory AND money deltas')
        result = {'trade': operation, 'item': item, 'evidence_refs':
                  list(current.evidence_refs) if hasattr(current, 'evidence_refs') else
                  [row['experience']['id'] for row in outcomes]}
        result.update({'sold': total_quantity, 'earned': total_price} if operation == 'sell' else
                      {'acquired': total_quantity, 'spent': total_price})
        return result
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
        params['_trade_start_money'] = obs.get('money')
        params['_trade_start_money_provenance'] = obs.get('state_provenance', {}).get('money')
        graph = learn.MEMORY.get('graph')
        targets = garden_policy.coverage(graph, params['region']) if graph and goal == 'garden' else []
        task = TaskState(uuid.uuid4().hex, goal, params=params, targets=targets)
        register_catalogue(task, params, {obs.get('frame_path')})
        store.create(task)
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
