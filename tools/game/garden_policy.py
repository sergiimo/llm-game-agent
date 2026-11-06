"""Pure garden evidence reduction and recommendations. No I/O, scheduler, or vision callbacks."""
from .turn import Recommendation

CHORES = ('plant', 'replant', 'harvest', 'water')


def names(value):
    return tuple(value) if isinstance(value, (tuple, list)) else tuple(x.strip() for x in (value or '').split('|') if x.strip())


def coverage(graph, region):
    """Graph supplies a coverage set, never an action order or ownership of screen clicks."""
    def inside(node):
        parent, seen = node.region, set()
        while parent and parent not in seen:
            if parent == region:
                return True
            seen.add(parent)
            parent = graph.nodes[parent].region if parent in graph.nodes else None
        return False
    return sorted(n.id for n in graph.nodes.values() if n.kind in ('GardenBed', 'BeeHive') and inside(n))


def interrupt(task, obs):
    hour = obs.get('hour')
    if hour is not None and (hour >= 23 or hour < 6):
        return 'HARD_STOP: after 23:00 or before 06:00; finish tonight and sleep'
    if (obs.get('rain') or obs.get('light') in ('dusk', 'night') or
            task.get('params', {}).get('_started_late') and (hour is None or hour > 19)):
        return 'SLEEP_REQUIRED: rain, darkness, or new task after 19:00; sleep then resume garden'
    if obs.get('can') == 'empty':
        return 'REFILL_REQUIRED: fill the watering can, then resume this transaction'
    return None


def recommend(task, obs):
    """Recommend one primitive for the model's current transaction; never select a new target."""
    def rec(action=None, reason='', expects=None):
        return Recommendation(action, 1.0 if action else 0.0, (reason,), expects or {})
    if task.get('status') != 'active':
        return rec(reason=task.get('status'))
    blocked = interrupt(task, obs)
    if blocked:
        return rec(reason=blocked)
    screen = obs.get('screen') or {}
    mode, texts = screen.get('kind'), screen.get('texts') or ()
    if mode == 'pause':
        return rec({'kind': 'press', 'label': 'Resume Game'}, 'resolve pause explicitly')
    if mode not in ('gameplay', 'card', 'picker'):
        return rec(reason=f'resolve {mode} before garden input')
    active = task.get('active')
    if not active:
        return rec(reason='model selects a visible uncovered target with its full road, or a short walkable waypoint')
    facts = active.get('provisional', {}).get('facts', {})
    crop = active.get('crop')
    chores = task.get('params', {}).get('chores', CHORES)
    low = ' / '.join(texts).lower()
    if 'collect' in low:
        protected = crop in task.get('params', {}).get('flowers', ())
        authorized = crop in names(task.get('params', {}).get('crops'))
        if 'harvest' in chores and (facts.get('hive') or crop and (not protected or authorized)):
            return rec({'kind': 'press', 'label': 'Collect'}, 'ready card permits collecting this crop',
                       {'events': ['harvest|grab_item|beehive_collect']})
        return rec({'kind': 'close'}, 'preserve flowers or identify the crop before collecting')
    if 'wilted' in low and 'replant' in chores:
        if any(t.lower() == 'remove' for t in texts):
            return rec({'kind': 'press', 'label': 'Remove'}, 'remove wilted crop', {'events': ['unplant_impl']})
        return rec(reason='wilted card: model selects the visible removal control')
    if mode == 'picker' or 'seeds' in low:
        if not ('plant' in chores or 'replant' in chores and facts.get('emptied')):
            return rec({'kind': 'close'}, 'pre-existing empty bed excluded by this narrow task')
        selected = facts.get('seed_selected')
        if selected:
            label = next((t for t in texts if t.lower() in ('select', 'plant', 'confirm')), None)
            return rec({'kind': 'press', 'label': label}, 'confirm the selected seed', {'log': 'totalPlanted'}) if label else rec(reason='model locates the seed confirmation control')
        wanted = task.get('params', {}).get('seed') or crop
        labels = obs.get('seed_choices') or [t for t in texts if t.lower().endswith((' seeds', ' bulbs'))]
        label = next((t for t in labels if wanted and wanted.lower() in t.lower()), None)
        if wanted and not label:
            return rec(reason=f'need visible seed card for {wanted}; preserve remembered crop')
        label = label or next(iter(labels), None)
        return rec({'kind': 'press', 'label': label}, 'select remembered/requested crop or an available seed') if label else rec(reason='model reads available seed cards')
    if mode == 'card':
        return rec({'kind': 'close'}, 'close the inspected card before the next world action')
    if active.get('phase') == 'verify' and facts.get('verified'):
        if not active.get('actual_node'):
            return rec(reason='verification lacks positioned-event identity; model must resolve or report it')
        return rec({'kind': 'read'}, 'verify the recorded event and cover the actual node')
    affordances = obs.get('visible_affordances') or ()
    point = active.get('provisional', {}).get('point')
    # Only a uniquely highlighted affordance at the active point is an obvious recommendation.
    candidates = [a for a in affordances if a.get('highlighted') and point and
                  sum((a['point'][i] - point[i]) ** 2 for i in (0, 1)) < 180 ** 2]
    if len(candidates) != 1:
        return rec(reason='model inspects the current target/road; keep this transaction')
    a = candidates[0]
    kind = a.get('kind')
    expected = {}
    if active.get('phase') == 'water' and not obs.get('rain'):
        expected = {'events': ['water|hazel_waterplant']}
    elif kind == 'plant':
        if not ('plant' in chores or 'replant' in chores and facts.get('emptied')):
            return rec(reason='empty bed excluded by this narrow task')
        expected = {'card': 'Seeds'}
    elif a.get('drop'):
        return rec({'kind': 'bubble', 'point': a['point'], 'visible_road': True},
                   'water drop may mean dry or wilted: inspect interaction evidence')
    elif kind in ('honey', 'beehive_progress'):
        expected = {'events': ['beehive_collect' if a.get('ready') else 'beehive_progress']}
    elif a.get('ready'):
        expected = {'card': 'Collect'}
    return rec({'kind': 'space'}, 'interact with the active highlighted affordance', expected)


def reduce(task, experience):
    """Reduce one integrated outcome; identity has already been bound by positioned events."""
    if not task.active or experience.verdict.value == 'unsafe' or task.params.get('_garden_reduced') == experience.id:
        return
    task.params['_garden_reduced'] = experience.id
    a = task.active
    facts = a.provisional.setdefault('facts', {})
    if a.phase == 'approach' and experience.action.kind in ('click', 'space'):
        a.phase = 'inspect'
    ev, text = set(experience.evidence.events), ' / '.join(experience.evidence.texts)
    if not a.crop:
        crops = names(task.params.get('crops'))
        a.crop = task.params.get('seed') or (crops[0] if len(crops) == 1 else None)
    if experience.action.pt and not a.provisional.get('point'):
        a.provisional['point'] = list(experience.action.pt)
    # Crop names from actual cards beat a requested crop; Collect-only cards do not name a crop.
    if 'days remaining' in text.lower() or 'wilted' in text.lower():
        a.crop = experience.evidence.texts[0]
    if 'Collect' in text:
        a.phase = 'collect'
    elif 'Seeds' in text:
        a.phase = 'plant'
        if not ('plant' in task.params.get('chores', CHORES) or facts.get('emptied')):
            facts['verified'] = True
    if ev & {'harvest', 'grab_item', 'unplant_impl'}:
        facts['emptied'] = True
        facts['seed_selected'] = False
        a.phase = 'plant' if 'replant' in task.params.get('chores', CHORES) else 'verify'
        if a.phase == 'verify':
            facts['verified'] = True
    if experience.action.kind in ('pick', 'press') and experience.action.arg and not ev:
        label = experience.action.arg
        if label.lower() not in ('collect', 'remove', 'select', 'plant', 'confirm', 'resume game'):
            facts['seed_selected'] = True
    if any('totalPlanted.' in l for l in experience.evidence.lines):
        facts['planted'] = True
        a.phase = 'water'
    if ev & {'water', 'hazel_waterplant', 'beehive_collect', 'beehive_progress'}:
        facts['verified'] = True
        facts['hive'] = bool(ev & {'beehive_collect', 'beehive_progress'})
        a.phase = 'verify'
    if 'plant_growing' in ev and 'wilted' not in text.lower():
        at_point = [b for b in experience.before.affordances if experience.action.pt and
                    tuple(b[1:3]) == tuple(experience.action.pt)]
        if at_point and not at_point[0][3] and not at_point[0][4]:
            facts['verified'] = True
            a.phase = 'verify'
    if experience.action.kind == 'close' and facts.get('verified'):
        a.phase = 'verify'
    if experience.action.kind == 'close' and a.phase == 'collect':
        # Protected ready flowers are successfully inspected, not harvested.
        facts['verified'] = bool(a.crop and a.crop in task.params.get('flowers', ()))
        a.phase = 'verify'
    if experience.action.kind == 'read' and facts.get('verified') and a.actual_node:
        if a.actual_node not in task.targets:
            task.unresolved.append({'node': a.actual_node, 'experience': experience.id,
                                    'reason': 'positioned event identified an object outside task coverage'})
            task.status = 'unresolved'
            return
        if a.actual_node in task.targets and a.actual_node not in task.covered:
            task.covered.append(a.actual_node)
        task.active = None
        if set(task.targets) <= set(task.covered):
            task.status = 'complete'
