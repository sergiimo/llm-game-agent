"""Entities (spec 2026-10-30 §3): one record per thing in the world, merged from every source that saw it. The game
log names objects with exact positions; the area comes from the caller (the current scene), never guessed — evidence
without an area is held in `pending`."""
import itertools
import math
from dataclasses import dataclass, field

MERGE = 0.5                       # world units: same kind + same area + this close = the same entity
WALKABLE_KINDS = {'GardenBed'}    # she stands on these to use them
MAX_SOURCES = 20                  # sources kept per entity (passive cards repeat every game minute)
_ids = itertools.count(1)


def reserve_id(n):
    """Ids continue after n (entities loaded from the cache keep theirs)."""
    global _ids
    nxt = next(_ids)
    _ids = itertools.count(max(nxt, n + 1))


@dataclass
class Entity:
    id: int
    kind: str
    area: str
    x: float
    z: float
    r: float = 0.6
    solid: bool = True
    uses: list = field(default_factory=list)
    state: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)

    def __str__(self):
        return f'{self.kind}#{self.id} {self.area} ({self.x:.2f}, {self.z:.2f})' + ('' if self.solid else ' walkable')


class Entities:
    def __init__(self):
        self.all = []
        self.pending = []

    def add(self, kind, area, x, z, src, **kw):
        for e in self.all:
            if e.kind == kind and e.area == area and math.dist((e.x, e.z), (x, z)) <= MERGE:
                if src not in e.sources:  # a daemon restart replays the same lines
                    e.sources = (e.sources + [src])[-MAX_SOURCES:]
                for k, v in kw.items():
                    if k == 'uses':
                        e.uses = sorted(set(e.uses) | set(v))
                    elif k == 'state':
                        e.state.update(v)
                return e
        e = Entity(next(_ids), kind, area, x, z, solid=kind not in WALKABLE_KINDS, sources=[src],
                   uses=sorted(set(kw.get('uses', []))), state=dict(kw.get('state', {})))
        self.all.append(e)
        return e

    def observe(self, ev, area):
        """An action / pathfail with a target and position → upsert that entity (None if nothing to record)."""
        if ev.kind == 'action' and 'x' in ev.f and ev.f.get('target') not in (None, 'null'):
            kind, x, z, uses = ev.f['target'], ev.f['x'], ev.f['z'], [ev.f['name']]
        elif ev.kind == 'pathfail' and ev.f.get('target'):
            kind, x, z, uses = ev.f['target'], ev.f['tx'], ev.f['tz'], []
        else:
            return None
        if area is None:
            self.pending.append(ev)
            return None
        return self.add(kind, area, x, z, (ev.kind, ev.day, ev.hour), uses=uses)

    def find(self, kind=None, area=None, near=None, within=None):
        out = [e for e in self.all if (kind is None or e.kind == kind) and (area is None or e.area == area)]
        if near is not None:
            out = [e for e in out if within is None or math.dist((e.x, e.z), near) <= within]
            out.sort(key=lambda e: math.dist((e.x, e.z), near))
        return out

    def explain(self, eid):
        e = next((e for e in self.all if e.id == eid), None)
        return e.sources if e else []
