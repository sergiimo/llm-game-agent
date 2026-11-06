"""Model-owned garden turns: observe, choose one primitive, persist the evidence. Log (D148):
`> unplant` = Space on a wilted bed (card/prompt), `> unplant_impl` = removed; `> plant` is written when the planting
panel closes, `[STATS] totalPlanted.<Seed>` = planted; `> water` = watered."""
import json
import os
import uuid

from .core import action
from .primitives import GameAdapter


class GardenAdapter(GameAdapter):
    """Garden interrupts guard fresh evidence even when the model overrides policy."""
    def __init__(self, task_provider, clue_provider=None):
        super().__init__(clue_provider)
        self.task_provider = task_provider

    def prepare(self, action, observation):
        from . import garden_policy as policy
        blocked = policy.interrupt(self.task_provider().to_dict(), observation)
        if blocked and action.get('kind') not in ('read', 'wait'):
            raise ValueError(blocked)
        return super().prepare(action, observation)

    def observe(self):
        from . import core, observe
        from PIL import Image
        result = super().observe()
        observe.check_texts(result['screen']['texts'])
        map_pin = getattr(core.WF, 'map_pin', None)
        if map_pin and result['screen']['kind'] == 'gameplay':
            with Image.open(result['frame_path']) as frame:
                if map_pin(frame):
                    result['screen'] = {'kind': 'map', 'texts': []}
                    result['interrupts'] = [*result.get('interrupts', ()), 'map open: model must resolve it']
        return result


def turn(region=None, chores=('plant', 'replant', 'harvest', 'water'), answer=None, crops=None,
         *, store=None, adapter=None, turn_id=None, decision=None, seed=None):
    """The public garden boundary. Bare calls observe; decisions consume an exact saved turn."""
    from . import core, engine, garden_policy as policy, learn, observe, ask, world
    from .task_state import TaskState, TaskStore
    from .turn import TurnLoop, Decision
    if set(chores) - set(policy.CHORES):
        raise ValueError('unknown garden chores')
    if store is None:
        directory = core.WF.run_dir()
        if not directory:
            raise ValueError('garden requires an active run: ./wf run start')
        store = TaskStore(os.path.join(directory, 'garden-task.json'))
    existing = store.load() if os.path.exists(store.path) else None
    if existing and region is not None and region != existing.params.get('region', region):
        raise ValueError('active garden region differs; finish/stop it and start a new run')
    region = region or (existing.params.get('region') if existing else None) or 'Garden'
    if adapter is None:
        # Bind the canonical graph before integration; stale process memory must never own event identity.
        graph = engine._open_graph()
        _, save = core.WF.read_save()
        world.refresh(graph, save, core.WF.today_log()[0])
        def clues():
            hour, light = observe.clock()
            rows = [{'node': n.id, 'kind': n.kind, 'state': n.state} for n in graph.nodes.values()
                    if n.id in policy.coverage(graph, region)]
            data = {'graph_clues': rows, 'hour': hour, 'light': light, 'rain': ask.rain(),
                    'can': graph.state_value('Tara', 'can')}
            state = store.load().to_dict() if os.path.exists(store.path) else {'params': {'_started_late': hour is not None and hour > 19}}
            blocked = policy.interrupt(state, data)
            data['interrupts'] = [blocked] if blocked else []
            return data
        adapter = GardenAdapter(lambda: store.load(), clues)
    else:
        graph = learn.MEMORY.get('graph')
    if not os.path.exists(store.path):
        if answer is not None or decision is not None:
            raise ValueError('observe the garden task before supplying a decision')
        with open(os.path.join(os.path.dirname(__file__), 'kinds.json')) as f:
            flowers = json.load(f).get('_lists', {}).get('flowers', [])
        obs = adapter.observe()
        params = {'region': region, 'chores': list(chores), 'crops': crops, 'seed': seed, 'flowers': flowers,
                  '_started_late': obs.get('hour') is not None and obs['hour'] > 19}
        store.create(TaskState(uuid.uuid4().hex, 'garden', params=params,
                               targets=policy.coverage(graph, region) if graph else []))
    loop = TurnLoop(store, adapter, policy.recommend, reducer=policy.reduce)
    if decision is None and answer is not None:
        decision = ask.garden_decision(answer)
    if decision is None:
        return loop.context()
    if turn_id is None:
        raise ValueError('garden continuation requires turn_id from NEXT')
    return loop.decide(int(turn_id), decision if isinstance(decision, Decision) else Decision(**decision))


def crop_name(card_text):
    """The crop a bed card names: its first line ("Green Bean / The unripe fruit … / This plant has wilted")."""
    return card_text.split(' / ', 1)[0].strip()


def _tend(chores, click=None, region='Garden', max_clicks=40, crops=None, **kwargs):
    from . import engine
    return engine.tend_garden(region, chores, answer=click, max_clicks=max_clicks, crops=crops, **kwargs)


@action
def do(region='Garden', click=None, max_clicks=40, crops=None, **kwargs):
    """Treat every bed and hive: harvest/collect, plant empty beds, replant wilted crops, and water.

    `crops` explicitly authorizes named flowers that the default routine preserves for bees.
    """
    return _tend(('plant', 'replant', 'harvest', 'water'), click, region, max_clicks, crops, **kwargs)


@action
def water_all(click=None, region='Garden', max_clicks=40, **kwargs):
    """Water every growing, dry bed (goal `water`)."""
    return _tend(('water',), click, region, max_clicks, **kwargs)


@action
def replant_all(seed=None, click=None, region='Garden', max_clicks=40, **kwargs):
    """Every wilted bed: remove, replant the same crop (read from the wilted card), water (goal `replant`); `seed`
    plants that crop instead."""
    return _tend(('replant',), click, region, max_clicks, seed=seed, **kwargs)


@action
def harvest_all(crops=None, click=None, region='Garden', max_clicks=40, **kwargs):
    """One harvest turn; named crops authorize flowers, otherwise protect flowers for the bees."""
    return _tend(('harvest',), click, region, max_clicks, crops, **kwargs)


@action
def plant_all(seed=None, region='Garden', click=None, **kwargs):
    """Plant `seed` in every empty bed of the area `region` (goal `plant`; `./wf world nodes` lists the areas)."""
    return _tend(('plant',), click, region, seed=seed, **kwargs)


def summary(res):
    if hasattr(res, 'to_dict'):
        return ('NEXT ' if res.task['status'] == 'active' else 'GARDEN ') + json.dumps(res.to_dict(), sort_keys=True)
    return (f"garden: visited {len(res['visited'])}, hives {len(res.get('hives_visited', []))}, "
            f"honey {res.get('honey', 0)}, acted {len(res['acted'])}, flowers {len(res['flowers'])}, "
            f"unresolved {len(res['unresolved'])}, harvested {res['harvested']}, replanted {res['replanted']}, "
            f"watered {res['watered']}, clicks {res['clicks']}, vision {res['vision']}, stop: {res['stop']}")
