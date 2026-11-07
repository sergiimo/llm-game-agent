"""Universal model-owned entry point. Constructors/clues never choose or execute gameplay inputs."""
import json
import os
import re
import uuid

from .primitives import GameAdapter
from .task_state import TaskState, TaskStore, json_record
from .turn import Decision, Recommendation, TurnLoop


def _save_money(save):
    """Player character state is authoritative; direct player state is a legacy save/adapter format."""
    import math
    game = save.get('gameState', {})
    characters = [row for row in game.get('characters', ()) if row.get('name') == 'Player']
    if len(characters) > 1:
        return None, None
    owner = characters[0] if characters else game.get('player', {})
    field = ('gameState.characters[name=Player]' if characters else 'gameState.player') + \
            '.state.userState.entries[name=money]'
    values = [row.get('value') for row in owner.get('state', {}).get('userState', {}).get('entries', ())
              if row.get('name') == 'money']
    if len(values) != 1:
        return None, field
    value = values[0]
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            return None, field
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or int(value) != value:
        return None, field
    return int(value), field


def _vector_scope(graph, *candidates, learned_kinds=None):
    """Learned appearance kinds visible in the current graph region, including nested landmarks and exits."""
    region = next((candidate for candidate in candidates if candidate in graph.nodes), None)
    allowed = set(learned_kinds) if learned_kinds is not None else None
    kinds = sorted({node.kind for node in graph.nodes.values()
                    if region and region in graph.chain(node.id) and
                    (allowed is None or node.kind in allowed)})
    return {'region': region, 'kinds': kinds if region else None}


def _clues(store, frame_context=None):
    from . import core, engine, garden_policy, learn, observe, snapshot, world
    frame_context = frame_context or {}
    path, save = core.WF.read_save()
    lines = core.WF.today_log()[0]
    world_delta = snapshot.world_for(store.path).refresh(
        engine._open_graph, save, lines, snapshot.file_revision(learn.graph_path()))
    graph = world_delta.graph
    hour, light = frame_context.get('hour'), frame_context.get('light')
    if not frame_context:  # compatibility for direct read-only callers; production always passes its captured frame
        hour, light = observe.clock()
    player = save.get('gameState', {}).get('player', {})
    money, money_field = _save_money(save)
    save_proof = {'source': 'save', 'path': path, 'save_count': save.get('saveCount'),
                  'game_time': world.save_time(save)}
    scene, region = world.scene_context(lines, save.get('currentScene'), since=world.save_time(save))
    vector_scope = _vector_scope(graph, region, scene, save.get('currentScene'))
    point = save.get('currentPlayerPosition') or {}
    task_state = store.load() if os.path.exists(store.path) else None
    active_node = task_state.active.actual_node if task_state and task_state.active else None
    data = {'graph_clues': snapshot.project_graph(
                graph, region, frame_context.get('candidates', ()), active_node),
            'memory_revision': world_delta.revision,
            'hour': hour, 'light': light,
            'rain': next((forecast for line in reversed(lines)
                          for forecast in re.findall(r'Forecast is (\w+)', line)
                          if forecast in ('Raining', 'Rain', 'Storm', 'Thunder')), None),
            'can': graph.state_value('Tara', 'can'),
            'inventory': world.inventory(save, lines),
            'inventory_complete': isinstance(player.get('inventory', {}).get('items'), list),
            'money': money, 'region': region, 'scene': scene, 'save_scene': save.get('currentScene'),
            'vector_scope': vector_scope,
            'state_provenance': {'inventory': save_proof, 'money': dict(save_proof, field=money_field),
                                 'position': save_proof, 'save_scene': save_proof,
                                 'region': {'source': 'scene_log'}}}
    if 'x' in point and 'z' in point:
        data['position'] = [point['x'], point['z']]
    if task_state and _declaration(task_state)['goal'] == 'navigate':
        from . import navigation
        data['navigation'] = navigation.receipt(task_state, data)
    state = _declaration(task_state) if task_state else {
        'params': {'_started_late': hour is not None and hour > 19}}
    blocked = garden_policy.interrupt(state, data)
    data['interrupts'] = [blocked] if blocked else []
    return data


def _repair_start_money(store):
    """Recover only missing initial funds from the already-persisted exact root snapshot; no public value input."""
    import time
    from . import core, world
    read = getattr(core.WF, 'read_save', None)
    if read is None:
        return
    with store.locked():
        task = store.load()
        if task.params.get('_trade_start_money') is not None:
            return
        proof = task.params.get('_trade_start_money_provenance') or {}
        if (proof.get('source') != 'save' or not isinstance(proof.get('path'), str) or not proof['path'] or
                type(proof.get('save_count')) is not int or not proof.get('game_time')):
            return
        try:
            path, save = read(proof['path'])
        except (OSError, ValueError, TypeError):
            return  # no replacement from a later/current balance when the original snapshot is unavailable
        if (os.path.abspath(path) != os.path.abspath(proof['path']) or save.get('saveCount') != proof['save_count'] or
                world.save_time(save) != proof['game_time']):
            return
        money, field = _save_money(save)
        if money is None:
            return
        recovered = dict(proof, field=field, recovered_from_root_snapshot=True)
        task.params.update(_trade_start_money=money, _trade_start_money_provenance=recovered)
        if task.current_turn:
            task.current_turn['task']['params'].update(
                _trade_start_money=money, _trade_start_money_provenance=recovered)
        store.save(task)  # preserve task, turn, transaction, frames and subgoal IDs; repeated reads are a no-op
        with open(os.path.join(os.path.dirname(store.path), 'log.jsonl'), 'a') as stream:
            stream.write(json.dumps({'t': time.time(), 'type': 'turn', 'phase': 'migration',
                'task_id': task.task_id, 'turn_id': task.current_turn['turn_id'] if task.current_turn else task.turn_seq,
                'kind': 'initial_money_from_root_snapshot', 'money': money, 'provenance': recovered}) + '\n')


def domain(task):
    """Read the current subgoal without changing the frozen parent interaction or root authorization."""
    if task.get('stack'):
        top = task['stack'][-1]
        params = dict(top['params'], _started_late=task.get('params', {}).get('_started_late', False))
        return dict(task, goal=top['goal'], params=params)
    return task


def _declaration(task):
    """Only current goal/params for validation and interrupts; never copy historical evidence to read metadata."""
    if task.stack:
        current = task.stack[-1]
        return {'goal': current.goal,
                'params': dict(current.params, _started_late=task.params.get('_started_late', False))}
    return {'goal': task.goal, 'params': task.params}


def recommend(task, observation):
    from . import garden_policy
    current = domain(task)
    if current['goal'] == 'garden':
        return garden_policy.recommend(current, observation)
    reasons = ['model chooses one primitive; read actions/INDEX.md for this workflow']
    latest = task.get('last_experience') or {}
    verdict = latest.get('verdict') or {}
    if latest.get('id') and verdict.get('value'):
        checks = '; '.join(f'{row.get("field")} expected={row.get("expected")} got={row.get("got")} '
                           f'ok={row.get("ok")}' for row in verdict.get('checks', ())[:3])
        reasons.append(f'latest outcome {latest["id"]}: verdict={verdict["value"]}' +
                       (f'; {checks}' if checks else ''))
    surprise = task.get('last_surprise') or {}
    actual = surprise.get('actual') or {}
    guard = next((check for check in surprise.get('checks', ()) if check.get('field') == 'guard'), None)
    if guard:
        reasons.append(f'authoritative guard refusal: {guard.get("got")}; zero input was issued, so moved remains '
                       'unknown and the refused action must not be described as a game miss')
    if actual:
        evidence = []
        if actual.get('mode'):
            evidence.append(f'mode={actual["mode"]}')
        if actual.get('events'):
            evidence.append('events=' + ','.join(map(str, actual['events'])))
        if actual.get('texts'):
            evidence.append('texts=' + ' / '.join(map(str, actual['texts']))[:240])
        if evidence:
            reasons.append('authoritative latest outcome: ' + '; '.join(evidence) +
                           '; use this evidence before correcting and do not infer no input from an unchanged frame')
    missing = [clue for clue in observation.get('graph_clues', ()) if clue.get('appearance_needed')]
    if missing:
        names = ', '.join(dict.fromkeys(str(clue.get('kind') or clue.get('node')) for clue in missing))
        reasons.append(f'confirmed interaction has a missing appearance sample for {names}: use model vision on the '
                       'proven source frame, then a provenance-bearing appearance correction with its bounded box')
    if (observation.get('screen') or {}).get('kind') == 'map':
        reasons.append('recognized map: after inspecting it, use the close primitive, not key:m or key:esc; '
                       'menu-key guard refusals issue no input')
    if current['goal'] == 'navigate' and observation.get('region') == 'House':
        reasons.append('indoor navigation: exit the building through its visible exit, cross the porch/stairs, and '
                       'move far enough outside that the interior disappears before opening the map')
    else:
        reasons.append('long-distance navigation: inspect and learn the map first; use visible roads for local '
                       'approach or only after captured unavailable/insufficient map evidence; on a long clear road '
                       'choose the farthest safe visible point whose entire path remains visible')
    return Recommendation(reasons=tuple(reasons))


def reduce(task, experience):
    from . import garden_policy
    if not task.stack and task.goal == 'garden':
        garden_policy.reduce(task, experience)
    if domain(task.to_dict())['goal'] == 'navigate':
        from . import navigation
        navigation.advance(task, experience)


def guard(task, action):
    from . import garden_policy
    current = domain(task)
    observation = task.get('_observation', {})
    if current['goal'] == 'navigate' and action.get('kind') == 'waypoint':
        from . import navigation
        assessment = navigation.assess(action, observation.get('navigation'))
        if not assessment.get('allowed'):
            return ('navigation compass mismatch: graph requires '
                    f'{assessment.get("graph_compass")}, waypoint predicts '
                    f'{(assessment.get("world") or {}).get("compass")}; '
                    'choose a waypoint within one compass sector')
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
    named_inspection = action.get('kind') == 'select_card' and bool(label) and control is None and label != 'confirm'
    financial = (direction is not None or label == 'confirm' and (surface or current['goal'] == 'shop') or
                 action.get('kind') in ('select_card', 'space', 'target', 'click', 'cell', 'bubble', 'waypoint')
                 and surface and not named_inspection)
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
    observations = [dict(row) for row in task.params.get('_shop_catalogue_observations',
                                                       task.params.get('_shop_catalogue', ()))]
    categories = {row['item']: row['category'] for row in observations}
    allowed = set(frames) | {row['frame_path'] for row in observations}
    changed = False
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get('item'), str) or not row['item'] or
                not isinstance(row.get('category'), str) or not row['category'] or
                type(row.get('available')) is not bool or row.get('frame_path') not in allowed or
                not isinstance(row.get('evidence_refs'), (list, tuple)) or
                row.get('frame_path') not in row['evidence_refs']):
            raise DecisionRejected('catalogue entry needs item/category/availability and captured frame references')
        if (('source' in row) != ('page' in row) or
                any(not isinstance(row[key], str) or not row[key].strip() for key in ('source', 'page') if key in row)):
            raise DecisionRejected('catalogue source and page must be nonempty text supplied together')
        if row['item'] in categories and categories[row['item']] != row['category']:
            raise DecisionRejected('catalogue category conflicts with the previously observed item')
        categories[row['item']] = row['category']
        if row not in observations:
            observations.append(dict(row))
            changed = True
    # Preserve raw provenance. Latest observation per named source/page (or legacy frame) feeds the item union.
    latest = {}
    for row in observations:
        source = ('named', row['source'], row['page']) if 'source' in row else ('frame', row['frame_path'])
        latest[(row['item'], source)] = row
    known = {}
    for row in latest.values():
        if row['item'] not in known or row['available'] or not known[row['item']]['available']:
            known[row['item']] = dict(row)
    task.params['_shop_catalogue_observations'] = observations
    task.params['_shop_catalogue'] = list(known.values())
    if 'catalogue_complete' in params:
        task.params['_shop_catalogue_complete'] = params['catalogue_complete'] is True
    elif changed:
        task.params['_shop_catalogue_complete'] = False


def available_money(params):
    """Captured root funds plus completed/resumed receipts minus every reserved purchase; no fresh balance guess."""
    import math
    start = params.get('_trade_start_money')
    if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
        return None
    earned = sum(row['result'].get('earned', 0) for row in params.get('_subgoal_results', ()) if row['goal'] == 'shop')
    spent = sum(row['price'] for row in params.get('_purchase_intents', ()))
    return max(0, start + earned - spent)


def bind_shop(task, params):
    """Bind evidence and a numeric spend ceiling to the model's chosen item; never select or trade an item."""
    from .turn import DecisionRejected
    item = params.get('item')
    if not item or params.get('trade', 'buy') != 'buy':
        return
    entry = next((row for row in task.params.get('_shop_catalogue', ()) if row['item'] == item), None)
    if entry:
        params['catalogue'] = [dict(entry)]
    funds = available_money(task.params)
    if funds is None:
        if 'max_spend' not in params:
            raise DecisionRejected('automatic shop spend bound needs captured starting money and verified receipts')
    else:
        params['max_spend'] = min(params.get('max_spend', funds), funds)


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


def region_matches(state, wanted):
    """Scene/building evidence or captured positioned-object graph ancestry can prove a named region."""
    if state.get('region') == wanted:
        return True
    proof = state.get('region_provenance') or {}
    return (proof.get('source') == 'positioned_event' and wanted in state.get('regions', ()) and
            list(proof.get('regions', ())) == list(state.get('regions', ())))


def verify_completion(task, current, outcomes):
    """Evidence-only completion proof. Model supplied results cannot manufacture successful gameplay."""
    from .turn import DecisionRejected
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
        if not region or not region_matches(after, region):
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
    from .params import validate

    if store is None:
        directory = core.WF.run_dir()
        if not directory:
            raise ValueError('play requires an active run: ./wf run start')
        old = os.path.join(directory, 'garden-task.json')
        store = TaskStore(old if os.path.exists(old) else os.path.join(directory, 'task.json'))
    if os.path.exists(store.path):
        store.compact()
    existing = store.load() if os.path.exists(store.path) else None
    schema_goal = goal if goal is not None else _declaration(existing)['goal'] if existing else None
    goal, params = _normalize(goal, validate(params, schema_goal))
    turn_id = params.pop('turn_id', None)
    if existing:
        current = _declaration(existing)
        if goal is not None and goal != existing.goal and goal != current['goal']:
            raise ValueError('active task differs; use an explicit push decision for a subgoal')
        for key, value in params.items():
            if current['params'].get(key) != value:
                raise ValueError(f'active task parameter {key} differs; start a new run')
    elif answer is not None:
        raise ValueError('observe a task before supplying a decision')
    if existing and answer is None and existing.params.get('_trade_start_money') is None:
        _repair_start_money(store)
    adapter = adapter or GameAdapter(clue_provider=lambda frame_context: _clues(store, frame_context))
    initial_observation = None
    if not existing:
        goal = goal or 'play'
        if goal == 'garden':
            params.setdefault('region', 'Garden')
            params.setdefault('chores', list(garden_policy.CHORES))
            if set(params['chores']) - set(garden_policy.CHORES):
                raise ValueError('unknown garden chores')
            with open(os.path.join(os.path.dirname(__file__), 'kinds.json')) as f:
                params['flowers'] = json.load(f).get('_lists', {}).get('flowers', [])
        obs = initial_observation = adapter.observe()
        params['_started_late'] = obs.get('hour') is not None and obs['hour'] > 19
        params['_trade_start_money'] = obs.get('money')
        params['_trade_start_money_provenance'] = obs.get('state_provenance', {}).get('money')
        graph = learn.MEMORY.get('graph')
        targets = garden_policy.coverage(graph, params['region']) if graph and goal == 'garden' else []
        task = TaskState(uuid.uuid4().hex, goal, params=params, targets=targets)
        store.create(task)  # root catalogue rows are declarations; only versioned decisions register proof
    loop = TurnLoop(store, adapter, recommend, reducer=reduce, guard=guard)
    if answer is None:
        return loop.context(observation=initial_observation)
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
    return 'NEXT ' + json.dumps(context, default=json_record, sort_keys=True)


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
