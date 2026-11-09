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


def _vector_scope(graph, *candidates, learned_kinds=None, relevant_nodes=()):
    """World-object appearance kinds visible in the region plus the exact active nested destination.

    A region's immediate children keep the routine scan bounded.  The named destination is the one justified
    exception: a Well inside Garden can be visible while Tara is still scoped to Farm, and omitting its already
    learned vector discards the strongest task-relevant landmark in the current frame.
    """
    region = next((candidate for candidate in candidates if candidate in graph.nodes), None)
    allowed = set(learned_kinds) if learned_kinds is not None else None
    selected = {node.kind for node in graph.nodes.values()
                if region and node.region == region and node.type == 'unique' and node.kind != 'Tara' and
                (allowed is None or node.kind in allowed)}
    for reference in relevant_nodes or ():
        matches = ([graph.nodes[reference]] if reference in graph.nodes else
                   [node for node in graph.nodes.values() if node.kind == reference])
        if len(matches) == 1 and region in graph.chain(matches[0].id):
            node = matches[0]
            if node.type == 'unique' and node.kind != 'Tara' and (allowed is None or node.kind in allowed):
                selected.add(node.kind)
    kinds = sorted(selected)
    return {'region': region, 'kinds': kinds if region else None}


def _sleep_workflow(task):
    if task is None:
        return False
    goal = task.get('goal') if hasattr(task, 'get') else task.goal
    stack = task.get('stack', ()) if hasattr(task, 'get') else task.stack
    return goal == 'sleep' or any((row.get('goal') if hasattr(row, 'get') else row.goal) == 'sleep'
                                  for row in stack)


def _operational_hour(observation, belief=None):
    """Choose one current source for the safety gate without merging clock timelines."""
    hour = observation.get('hour')
    if hour is not None:
        return hour, 'hud'
    belief_hour = (belief or {}).get('observed_hour')
    if belief_hour is not None:
        return belief_hour, 'model_hud'
    # Cutscenes and black transition frames intentionally have no HUD. The action-bound log timestamp is still a
    # coherent, independently refreshed source and is safer than making the morning transition impossible.
    from .world import when
    stamp = observation.get('log_time') or observation.get('game_time')
    seconds = when(stamp)
    return ((seconds % 86400) / 3600, 'log') if seconds is not None else (None, None)


def _clock_interrupt(task, observation):
    hour, _source = _operational_hour(observation)
    if hour is not None and hour >= 18 and not _sleep_workflow(task):
        return ('SLEEP_REQUIRED: at or after 18:00, return home and sleep before ordinary gameplay '
                'or hand control to the human')
    return None


def _clues(store, frame_context=None):
    from . import core, engine, garden_policy, learn, observe, snapshot, world
    frame_context = frame_context or {}
    coherent = frame_context.get('observation_snapshot')
    if coherent is not None:
        path, save = coherent.candidate.path, coherent.candidate.decoded
        lines = list(coherent.log_epoch.lines)
    else:  # direct diagnostic/test callers without the production observation boundary
        path, save = core.WF.read_save()
        lines = core.WF.today_log()[0]
    world_store = None
    graph_loader = engine._open_graph
    graph_revision = snapshot.file_revision(learn.graph_path())
    if coherent is not None and coherent.profile_id is not None:
        from .world_store import WorldStore
        world_store = WorldStore(store.db, coherent.profile_id)
        def graph_loader():
            graph = world_store.load(learn.graph_path(), coherent.observation_id)
            learn.MEMORY['graph'] = graph
            return graph
        graph_revision = (graph_revision, coherent.observation_id, coherent.profile_id)
    world_delta = snapshot.world_for(store.run_dir).refresh(graph_loader, save, lines, graph_revision)
    graph = world_delta.graph
    if world_store is not None and world_delta.changed:
        world_store.capture_graph(graph, learn.graph_path(), coherent.observation_id, coherent.candidate.game_time,
                                  store.run_id)
    hour, light = frame_context.get('hour'), frame_context.get('light')
    if not frame_context:  # compatibility for direct read-only callers; production always passes its captured frame
        hour, light = observe.clock()
    player = save.get('gameState', {}).get('player', {})
    money, money_field = _save_money(save)
    save_stamp = world.save_time(save)
    save_proof = {'source': 'save', 'path': path, 'save_count': save.get('saveCount'),
                  'game_time': save_stamp}
    scene, region = world.scene_context(lines, save.get('currentScene'), since=world.save_time(save))
    region = world.graph_scope(lines, graph, scene, region)
    task_state = store.load() if store.exists() else None
    declaration = _declaration(task_state) if task_state else {'params': {}}
    nav_params = declaration.get('params') or {}
    relevant_nodes = tuple(value for value in (
        nav_params.get('destination'), nav_params.get('region'), nav_params.get('where')) if value)
    position_node = world.graph_position_anchor(lines, graph, scene)
    vector_scope = _vector_scope(graph, region, scene, save.get('currentScene'), relevant_nodes=relevant_nodes)
    point = save.get('currentPlayerPosition') or {}
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
            'hud_hour': hour, 'save_time': save_stamp,
            'observation_id': coherent.observation_id if coherent is not None else None,
            'vector_scope': vector_scope,
            'map_pin': frame_context.get('map_pin') if frame_context.get('screen') == 'map' else None,
            'state_provenance': {'inventory': save_proof, 'money': dict(save_proof, field=money_field),
                                 'position': save_proof, 'save_scene': save_proof,
                                 'region': {'source': 'scene_log'}}}
    if position_node:
        data['position_node'] = position_node
        data['position_node_provenance'] = {'source': 'sleep_spawn', 'node': position_node}
    if 'x' in point and 'z' in point:
        data['position'] = [point['x'], point['z']]
    if task_state and _declaration(task_state)['goal'] == 'navigate':
        from . import navigation
        data['navigation'] = navigation.receipt(_declaration(task_state), data)
    state = _declaration(task_state) if task_state else {
        'params': {'_started_late': hour is not None and hour >= 19}}
    blocked = garden_policy.interrupt(state, data) if state.get('goal') == 'garden' else None
    data['interrupts'] = [value for value in (blocked, _clock_interrupt(task_state, data)) if value]
    return data


def _bind_task_observation(task, data):
    """Rebind derived local clues after a task create/restart; captured frame/save evidence stays immutable."""
    from . import garden_policy, learn, navigation, snapshot
    data = dict(data)
    declaration = _declaration(task)
    data.pop('navigation', None)
    if declaration['goal'] == 'navigate':
        data['navigation'] = navigation.receipt(declaration, data)
    graph = learn.MEMORY.get('graph')
    if graph is not None:
        data['graph_clues'] = snapshot.project_graph(
            graph, data.get('region'), data.get('candidates', ()), None)
    blocked = garden_policy.interrupt(declaration, data) if declaration['goal'] == 'garden' else None
    lineage = ('SAVE_LINEAGE_MISMATCH: ' + str(data.get('lineage_mismatch'))
               if data.get('lineage_status') == 'save_lineage_mismatch' else None)
    data['interrupts'] = [value for value in (lineage, blocked, _clock_interrupt(task, data)) if value]
    return data


def _observation_provider(store):
    """Capture one immutable save/log lineage snapshot before any derived gameplay clue."""
    from . import core
    candidates = getattr(core.WF, 'save_candidates', None)
    epoch = getattr(core.WF, 'log_epoch', None)
    if not candidates or not epoch:
        return None  # injected test/diagnostic adapters retain their explicit observation contract
    from .observations import ObservationStore
    observations = ObservationStore(store.db)

    def capture(frame_context, validate_only=False):
        current_candidates = candidates()
        if not current_candidates:
            # Unity rotates autosave files by removing/replacing slots. One immediate rescan absorbs the brief
            # no-decodable-file window without relaxing pinned-profile or timeline validation.
            current_candidates = candidates()
        return observations.capture(store.run_id, current_candidates, epoch(),
                                    frame_path=frame_context.get('frame_path'),
                                    view_id=frame_context.get('view_id'))
    return capture


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
        log = getattr(core.WF, 'run_log', None)
        if log:
            log('turn', phase='migration', task_id=task.task_id,
                turn_id=task.current_turn['turn_id'] if task.current_turn else task.turn_seq,
                kind='initial_money_from_root_snapshot', money=money, provenance=recovered)


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
    latest_action = latest.get('action') or {}
    latest_prediction = latest.get('prediction') or {}
    latest_evidence = latest.get('evidence') or {}
    if (latest_action.get('kind') == 'click' and latest_action.get('what') == 'step' and
            latest_prediction.get('moved') is True and latest_evidence.get('moved') is None):
        reasons.append('camera movement is unresolved, not a proved no-move: choose one zero-input read so a fresh '
                       'autosave can reconcile the prior waypoint before revising its direction')
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
        nav_goal = (observation.get('navigation') or {}).get('goal') or {}
        anchor = nav_goal.get('map_anchor') or {}
        if anchor and not anchor.get('exact'):
            reasons.append(
                f'recognized map: label Tara pin as origin_point and the map-labeled {anchor.get("node")} '
                f'({anchor.get("kind")}) as target_point; persist target={anchor.get("node")}, region, current map '
                f'frame and expiry. The ultimate {nav_goal.get("node")} goal has no explicit map marker: do not '
                f'invent an exact {nav_goal.get("node")} point from the illustration. After reaching the labeled '
                'ancestor, use local vectors/model vision for the subobject; then use the close primitive, not '
                'key:m or key:esc')
        else:
            reasons.append('recognized map: label Tara pin as origin_point and the exact navigation goal as '
                           'target_point; persist both with target, region, current map frame and expiry so the '
                           'engine derives direction/range; then use the close primitive, not key:m or key:esc. '
                           'Viewing a map without binding its direction does not change navigation')
    elif (observation.get('navigation') or {}).get('status') == 'route_hint_expired':
        reasons.append('task-local map route expired: refresh from the map or a newly proved landmark before input; '
                       'do not fall back to the broad scene edge')
    if current['goal'] == 'navigate' and observation.get('region') == 'House':
        reasons.append('indoor navigation: exit the building through its visible exit, cross the porch/stairs, and '
                       'move far enough outside that the interior disappears before opening the map')
    else:
        reasons.append('navigation: reconcile the current full-scale frame, last outcome, graph/map/vector advisories '
                       'into one replacement belief, then bind one primitive to its exact next objective. Graph '
                       'compass/range cannot veto the model route. On a long clear road choose the farthest safe '
                       'visible point whose entire path remains visible')
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
    terminal_cleanup = (action.get('kind') == 'press' and
                        str(action.get('label', '')).strip().casefold() == 'zzzz' and
                        (observation.get('screen') or {}).get('kind') == 'popup' and
                        sum(str(row.get('label', '')).strip().casefold() == 'zzzz'
                            for row in observation.get('controls', ())) == 1)
    if terminal_cleanup:
        return None
    if action.get('kind') == 'waypoint' and current['goal'] != 'navigate':
        return 'waypoint requires generic navigation: push a navigate subgoal for the destination region'
    sleeping = current['goal'] == 'sleep' or any(row['goal'] == 'sleep' for row in task.get('stack', ()))
    if current['goal'] == 'navigate' and action.get('kind') in ('waypoint', 'target', 'cell', 'bubble'):
        belief = current.get('params', {}).get('_navigation_belief') or {}
        if (action.get('belief_revision') != belief.get('revision') or
                action.get('belief_objective') != belief.get('next_objective') or
                action.get('objective') != belief.get('next_objective')):
            return 'navigation input is not bound to the current model belief revision and objective'
        hour, _clock_source = _operational_hour(observation, belief)
        destination = str(current.get('params', {}).get('destination') or
                          current.get('params', {}).get('where') or '').casefold()
        returning = destination in {'home', 'house', 'farmhouse', 'bed'}
        if hour is None and not sleeping:
            return 'NEED_VISION: current clock unknown across HUD, model HUD reading, and coherent log time'
        if hour is not None and hour >= 18 and not (sleeping or returning):
            return ('SLEEP_REQUIRED: at or after 18:00, push the sleep workflow and return home '
                    'or hand control to the human')
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
    """Scene/building evidence or captured positioned-object graph ancestry can prove a destination."""
    if state.get('region') == wanted:
        return True
    proof = state.get('region_provenance') or {}
    return (proof.get('source') == 'positioned_event' and
            (proof.get('node') == wanted or wanted in state.get('regions', ())) and
            list(proof.get('regions', ())) == list(state.get('regions', ())))


def verify_completion(task, current, outcomes, context=None):
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
        region = params.get('region') or params.get('destination') or params.get('where')
        if region and region_matches(after, region):
            return {'region': region}
        from objects.graph import node_of_line
        event_nodes = {node_of_line(line) for row in outcomes
                       for line in row['experience']['evidence'].get('lines', ())}
        if region and region in event_nodes:
            return {'node': region, 'region': after.get('region'), 'source': 'positioned_event'}
        # Task-derived navigation is rebound after integrating a zero-input read.  Its persisted successor context
        # can therefore contain fresher arrival proof than the read experience's pre-rebind state projection.
        context = context or {}
        navigation = context.get('navigation') or after.get('navigation') or {}
        graph = navigation.get('graph') or {}
        if (navigation.get('status') == 'arrived' and graph.get('current_node') == region and
                graph.get('current_source') == 'visible_affordance'):
            resources = context.get('resources') or {}
            return {'node': region, 'region': resources.get('region') or after.get('region'),
                    'source': 'visible_affordance'}
        # A navigation destination may be a unique/nested world node (Well, Bed, counter), not a scene region.
        # Require a captured chain: the model selected that exact candidate, the click moved Tara, and the settled
        # result still visually detects the same kind. A vector in isolation is never completion proof.
        arrived = False
        for row in reversed(outcomes):
            experience = row['experience']
            action = row.get('action') or {}
            before = row.get('before') or {}
            evidence = experience.get('evidence') or {}
            after_state = dict(evidence.get('state', ()))
            selected = next((candidate for candidate in before.get('candidates', ())
                             if candidate.get('id') == action.get('candidate')), None)
            settled = any(candidate.get('kind') == region
                          for candidate in after_state.get('candidates', ()))
            if (region and action.get('kind') == 'target' and selected and selected.get('kind') == region
                    and evidence.get('moved') is True and settled):
                arrived = True
                after = after_state
                break
        if not arrived:
            raise DecisionRejected('navigation completion needs captured matching region or target-arrival evidence')
        return {'node': region, 'region': after.get('region')}
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
    Task state and its WAL are scoped to the active SQLite run.
    """
    from . import ask, core, garden_policy, learn
    from .params import validate

    if store is None:
        directory = core.WF.run_dir()
        if not directory:
            raise ValueError('play requires an active run: ./wf run start')
        from runtime.db import Database
        run_id = core.WF.run_path()
        if run_id:
            database = Database(os.environ.get('WF_DB', os.path.join(os.path.dirname(directory), 'wf.sqlite3')))
            store = TaskStore(database, run_id)
        else:  # offline adapters still use SQLite, keyed by a non-file fixture identity
            store = TaskStore(os.path.join(directory, '.task-fixture'))
    raw_params = dict(params or {})
    restart = raw_params.pop('restart', False)
    if type(restart) is not bool:
        raise ValueError('restart must be true or false')
    if restart and answer is not None:
        raise ValueError('task restart starts from a fresh observation and accepts no turn answer')
    existing = store.load() if store.exists() else None
    expired = existing if restart else None
    if restart and existing:
        goal = goal or existing.goal
        existing = None
    schema_goal = goal if goal is not None else _declaration(existing)['goal'] if existing else None
    goal, params = _normalize(goal, validate(raw_params, schema_goal))
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
    adapter = adapter or GameAdapter(clue_provider=lambda frame_context: _clues(store, frame_context),
                                     observation_provider=_observation_provider(store))
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
        params['_started_late'] = obs.get('hour') is not None and obs['hour'] >= 18
        params['_trade_start_money'] = obs.get('money')
        params['_trade_start_money_provenance'] = obs.get('state_provenance', {}).get('money')
        graph = learn.MEMORY.get('graph')
        targets = garden_policy.coverage(graph, params['region']) if graph and goal == 'garden' else []
        task = TaskState(uuid.uuid4().hex, goal, params=params, targets=targets)
        if expired:
            old = expired.current_turn or {}
            resources = old.get('resources') or {}
            hint = {'task_id': expired.task_id, 'goal': expired.goal, 'status': expired.status,
                    'game_time': resources.get('game_time'), 'region': resources.get('region') or old.get('region'),
                    'screen': (old.get('screen') or {}).get('kind')}
            store.restart(task, hint)
        else:
            store.create(task)  # root catalogue rows are declarations; only versioned decisions register proof
        initial_observation = _bind_task_observation(task, initial_observation)
    loop = TurnLoop(store, adapter, recommend, reducer=reduce, guard=guard,
                    rebind=_bind_task_observation)
    if answer is None:
        return loop.context(observation=initial_observation)
    if isinstance(answer, str) and answer.strip().startswith('{'):
        answer = json.loads(answer)
    if isinstance(answer, dict):
        answer = dict(answer)
        turn_id = answer.pop('turn_id', turn_id)
        answer = ask.garden_decision(answer)
    if not isinstance(answer, Decision):
        if isinstance(answer, str):
            import re
            answer = re.sub(r'^(walk|target|bubble|cell):', r'\1 ', answer)
        answer = ask.garden_decision(answer)
    if turn_id is None:
        raise ValueError('continuation requires turn_id from NEXT')
    return loop.decide(int(turn_id), answer)


def _model_candidate(row):
    fields = ('id', 'kind', 'point', 'source', 'score', 'view_id', 'box',
              'highlighted', 'ready', 'drop', 'label')
    return {name: row[name] for name in fields if name in row}


def _model_receipt(context):
    """Bounded CLI projection; SQLite retains the complete immutable context and outcome."""
    raw = context.to_dict() if hasattr(context, 'to_dict') else dict(context)
    navigation = raw.get('navigation')
    view = dict(raw.get('view') or {})
    view['candidates'] = [_model_candidate(dict(row)) for row in view.get('candidates', ())[:8]]
    view['controls'] = [{key: row[key] for key in ('id', 'label', 'point', 'view_id') if key in row}
                        for row in view.get('controls', ())[:8]]
    memory = dict(raw.get('memory') or {})
    if navigation:
        memory = {'revision': memory.get('revision')}
    surprise = raw.get('surprise')
    if surprise:
        surprise = surprise.to_dict() if hasattr(surprise, 'to_dict') else dict(surprise)
        surprise = {name: surprise.get(name) for name in ('experience_id', 'reason', 'checks')}
    vectors = []
    for row in raw.get('vector_detections', ())[:8]:
        row = dict(row)
        vectors.append({name: row[name] for name in ('kind', 'point', 'score') if name in row})
    task = dict(raw.get('task') or {})
    if task.get('goal') == 'navigate' and navigation:
        nav = dict(navigation)
        graph = dict(nav.get('graph') or {})
        localization = dict(nav.get('localization') or {})
        navigation = {
            'goal': {key: value for key, value in dict(nav.get('goal') or {}).items()
                     if key in ('node', 'scene', 'enterable')},
            'graph': {key: graph.get(key) for key in
                      ('current_node', 'current_source', 'destination', 'path') if graph.get(key) is not None},
            'next_edge': {key: value for key, value in dict(nav.get('next_edge') or {}).items()
                          if key in ('from', 'to', 'compass', 'range', 'walkable')},
            'localization': {key: localization.get(key) for key in
                             ('stage', 'current', 'likely_region', 'next', 'landmarks', 'graph_slice')
                             if localization.get(key) not in (None, [], {})},
        }
        view = {key: view.get(key) for key in ('path', 'mode', 'scene', 'clock', 'candidates', 'controls', 'bubbles')
                if view.get(key) not in (None, [], {})}
        resources = dict(raw.get('resources') or {})
        result = dict(raw.get('result') or {})
        belief = dict(raw.get('belief') or {})
        recommendation = dict(raw.get('recommendation') or {})
        return {
            'navigation': navigation,
            'turn_id': raw.get('turn_id'),
            'task': {key: task.get(key) for key in ('task_id', 'goal', 'status')},
            'view': view,
            'result': {key: result.get(key) for key in ('experience', 'status', 'events')
                       if result.get(key) not in (None, [], {})},
            'resources': {key: resources.get(key) for key in
                          ('game_time', 'scene', 'region', 'rain', 'light') if resources.get(key) is not None},
            'belief': {key: belief.get(key) for key in ('current', 'next_objective', 'assessment')
                       if belief.get(key) is not None},
            'recommendation': {'reasons': list(recommendation.get('reasons') or ())[:2]},
            'surprise': surprise,
            'interrupts': raw.get('interrupts', ()),
            'vector_detections': vectors,
            'vector_status': raw.get('vector_status'),
            'screen': raw.get('screen'),
            'frame_path': raw.get('frame_path'),
            'observation_freshness': raw.get('observation_freshness'),
            'input_limits': {'frame': [0, 0, 1920, 1080],
                             'world_click_excludes': [[0, 0, 520, 230], [1440, 0, 1920, 230]]},
        }
    # Navigation is deliberately first: even a downstream display cap preserves localization and the route edge.
    return {
        'navigation': navigation,
        'turn_id': raw.get('turn_id'),
        'allowed_decisions': raw.get('allowed_decisions', ()),
        'task': raw.get('task'),
        'belief': raw.get('belief'),
        'view': view,
        'result': raw.get('result'),
        'need': raw.get('need'),
        'resources': raw.get('resources'),
        'recommendation': raw.get('recommendation'),
        'surprise': surprise,
        'transaction': raw.get('transaction'),
        'coverage': raw.get('coverage'),
        'interrupts': raw.get('interrupts', ()),
        'memory': memory,
        'vector_detections': vectors,
        'vector_status': raw.get('vector_status'),
        'screen': raw.get('screen'),
        'frame_path': raw.get('frame_path'),
        'observation_freshness': raw.get('observation_freshness'),
        'observation_id': raw.get('observation_id'),
    }


def summary(context):
    return 'NEXT ' + json.dumps(_model_receipt(context), default=json_record)


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
