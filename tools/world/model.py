"""World (spec 2026-10-30 §3): one state every skill will query. Built from evidence (`observe`), our clicks
(`clicked`) and save readings (`reading`); entities are cached in tools/world/entities.json. In M2 it runs in shadow
mode: it predicts, the eval scores it (`world_belief`, `world_route`), nothing acts on it yet."""
import json
import math
import os

from . import belief as bel
from . import costmap, entities
from .entities import Entity

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'entities.json')
REACH = 2.5        # world units: an entity this close is in reach
BELIEF_HIT = 1.0   # world units: a predicted position this close to the reading is a hit
USE_NEAR = 6.0     # world units: use points this close belong to the same object (both sides of the well ≈ 4.8)
MAX_USE = 10
PASSIVE = ('_progress',)   # cards shown while walking past (beehive_progress): entity evidence, not a position fix (S19)


class World:
    def __init__(self, facts=None, cache=None, spawn_inside=None):
        self.facts = facts if facts is not None else []
        self.spawn_inside = spawn_inside or {}   # 'Farm/Bed' -> 'House': spawn points inside a building
        self.pending_use = None                  # an object she just used whose position the log didn't give
        self.ents = entities.Entities()
        self.belief = bel.Belief()
        self.scene = None          # the outdoor scene; belief.area adds /Building inside
        self.cache = cache or CACHE
        self._load(self.cache)

    # ---- persistence
    def _load(self, path):
        try:
            rows = json.load(open(path))
        except (OSError, ValueError):
            return
        for r in rows:
            e = Entity(**r)
            self.ents.all.append(e)
            entities.reserve_id(e.id)

    def save(self, path=None):
        rows = [e.__dict__ for e in self.ents.all]
        with open(path or self.cache, 'w') as fh:
            json.dump(rows, fh, indent=0, default=list)

    # ---- evidence
    def observe(self, ev):
        k, f = ev.kind, ev.f
        if k in ('scene', 'spawn') and f.get('scene'):
            self.scene = f['scene']
            inside = self.spawn_inside.get(f'{f["scene"]}/{f.get("point") or f.get("link")}')
            self.belief.scene(f'{self.scene}/{inside}' if inside else self.scene)
        elif k == 'building' and self.scene:
            self.belief.area = f'{self.scene}/{f["building"]}' if f['enter'] else self.scene
        elif k in ('pathfail', 'stuck'):
            if self.belief.area and (f.get('scene') in (None, self.scene)):
                self.belief.fix(f['x'], f['z'], bel.SIGMA_LOG)
        if (k == 'action' and 'x' not in f and f.get('target') not in (None, 'null', 'Player')
                and not f['name'].endswith(PASSIVE)):
            self.pending_use = f['target']  # her next exact reading is a use point of this object
        e = self.ents.observe(ev, self.belief.area)
        if e is not None and k == 'action' and not f['name'].endswith(PASSIVE):  # she used it: she is at it
            self.belief.fix(e.x, e.z, bel.SIGMA_BUBBLE)
            self.belief.in_reach = e
        return e

    def end_replay(self):
        """After replaying old log lines: an old use is not where she stands now (obj-walk-2)."""
        self.pending_use = None

    def clicked(self, dx, dz):
        self.pending_use = None  # she moved: the next reading is no longer where she used the object
        self.belief.clicked = True
        self.belief.click(dx, dz)

    def reading(self, area, x, z):
        """A save reading: score the prediction (eval `world_belief`), then fix the belief exactly."""
        p_area, px, pz, u = self.belief.predicted()
        if p_area == area and u < bel.UNKNOWN / 2:
            try:
                import evals
                d = math.dist((px, pz), (x, z))
                evals.record('world_belief', 'position', [round(px, 2), round(pz, 2)], [round(x, 2), round(z, 2)],
                             d <= BELIEF_HIT, {'area': area, 'u': round(u, 2), 'err': round(d, 2)})
            except Exception:  # noqa: BLE001 (scoring never breaks play)
                pass
        if area != self.belief.area:
            self.belief.area = area
            self.scene = area.split('/')[0]
            self.belief._set(x, z, bel.SIGMA_READING)
        else:
            self.belief.fix(x, z, bel.SIGMA_READING)
        if self.pending_use:
            self.add_use(self.pending_use, area, x, z)
            self.pending_use = None

    def add_use(self, kind, area, x, z):
        """A spot where she used an object (exact reading): the object's position is the mean of its use points
        (the well used from both sides → between them). Clicking the object itself is how to reach it (D150)."""
        near = [e for e in self.ents.find(kind=kind, area=area) if 'use_points' in e.state and
                any(math.dist(p, (x, z)) <= USE_NEAR for p in e.state['use_points'])]
        if near:
            e = near[0]
        else:
            e = self.ents.add(kind, area, x, z, ('use', round(x, 2), round(z, 2)))
            e.state['use_points'] = []
        e.state['use_points'] = (e.state['use_points'] + [[round(x, 2), round(z, 2)]])[-MAX_USE:]
        e.x = sum(p[0] for p in e.state['use_points']) / len(e.state['use_points'])
        e.z = sum(p[1] for p in e.state['use_points']) / len(e.state['use_points'])
        self.save()
        return e

    # ---- queries
    def tara(self):
        return self.belief.predicted()

    def needs_fix(self):
        return self.belief.needs_fix()

    def entities(self, **filters):
        return self.ents.find(**filters)

    def explain(self, eid):
        return self.ents.explain(eid)

    def where(self, name_or_id):
        for e in self.ents.all:
            if str(e.id) == str(name_or_id) or e.kind == name_or_id:
                return e
        return None

    def in_reach(self):
        if self.needs_fix():
            return None
        area, x, z, _ = self.tara()
        near = self.ents.find(area=area, near=(x, z), within=REACH)
        return near[0] if near else None

    def route_status(self, goal, reach=0.0, now_hour=float('inf')):
        """('way', waypoints) / ('none', None) / ('unknown', None) for goal (area, x, z) inside the current area.
        Unknown = her position is uncertain, the goal is in another area (the scene graph decides, M3), or the search
        gave up. now_hour = absolute game hours (refused clicks fade); inf = all faded."""
        area, x, z, _ = self.tara()
        if self.needs_fix() or area is None or goal[0] != area:
            return 'unknown', None
        cm = costmap.build(area, self.ents, self.facts, now_hour, extra=[(x, z), goal[1:]])
        path = costmap.astar(cm, (x, z), goal[1:], now_hour, reach=max(reach, cm.cell))
        if path is None:
            return ('unknown' if cm.capped else 'none'), None
        return 'way', costmap.waypoints(path)

    def route(self, goal, reach=0.0, now_hour=float('inf')):
        status, wps = self.route_status(goal, reach, now_hour)
        return wps if status == 'way' else None
