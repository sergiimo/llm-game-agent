"""Costmap per area (spec 2026-10-30 §3; the Nav2 costmap_2d pattern in numpy): layers solid (+ inflation), walls,
refused clicks (fade after 1 game hour), walked cells (cheaper). Grid A* plans the real path inside an area, so walks
go round the hive row instead of straight into it (S11, S12)."""
import heapq
import math

import numpy as np

CELL = 0.5            # world units per cell
INFLATE = 0.5         # margin around solid entities
REFUSED_HOURS = 1.0   # a refused click blocks its cell this long (game hours)
WALKED_COST = 0.5
MARGIN = 10.0         # world units around everything known, for build()


class Costmap:
    def __init__(self, area, bounds, cell=CELL):
        self.area, self.cell = area, cell
        self.x0, self.z0, x1, z1 = bounds
        self.nx = max(1, math.ceil((x1 - self.x0) / cell))
        self.nz = max(1, math.ceil((z1 - self.z0) / cell))
        shape = (self.nz, self.nx)
        self.solid = np.zeros(shape, bool)
        self.walls = np.zeros(shape, bool)
        self.refused = np.full(shape, np.nan)
        self.walked = np.zeros(shape, bool)
        self.capped = False   # the last astar() gave up (too many cells): "unknown", not "no way"

    def cell_of(self, x, z):
        return (min(self.nz - 1, max(0, int((z - self.z0) / self.cell))),
                min(self.nx - 1, max(0, int((x - self.x0) / self.cell))))

    def center(self, iz, ix):
        return self.x0 + (ix + 0.5) * self.cell, self.z0 + (iz + 0.5) * self.cell

    def _disc(self, x, z, r):
        zz, xx = np.mgrid[0:self.nz, 0:self.nx]
        cx, cz = self.x0 + (xx + 0.5) * self.cell, self.z0 + (zz + 0.5) * self.cell
        return np.hypot(cx - x, cz - z) <= r

    def add_solid(self, x, z, r):
        self.solid |= self._disc(x, z, r + INFLATE)

    def add_wall(self, x, z, dx=0.0, dz=0.0):
        self.walls[self.cell_of(x, z)] = True
        n = math.hypot(dx, dz)
        if n:
            self.walls[self.cell_of(x + dx / n * self.cell, z + dz / n * self.cell)] = True

    def add_refused(self, x, z, game_hour):
        self.refused[self.cell_of(x, z)] = game_hour

    def add_walked(self, x0, z0, x1, z1):
        n = max(1, int(math.dist((x0, z0), (x1, z1)) / (self.cell / 2)))
        for i in range(n + 1):
            t = i / n
            self.walked[self.cell_of(x0 + (x1 - x0) * t, z0 + (z1 - z0) * t)] = True

    def cost(self, now_hour):
        c = np.where(self.walked, WALKED_COST, 1.0)
        age = now_hour - self.refused   # absolute game hours (day*24 + hour)
        blocked = self.solid | self.walls | (~np.isnan(self.refused) & (age < REFUSED_HOURS))
        return np.where(blocked, np.inf, c)


MAX_EXPAND = 20000    # cells: beyond this the search gives up (unknown), so a walk never waits seconds for it


def astar(cm, start, goal, now_hour, reach=0.0, max_expand=MAX_EXPAND):
    """World points (cell centres) from start to the first cell within `reach` of goal, or None. The start cell is
    always enterable (she may stand in an inflated margin)."""
    c = cm.cost(now_hour)
    s, g = cm.cell_of(*start), cm.cell_of(*goal)
    c[s] = min(c[s], 1.0) if math.isinf(c[s]) else c[s]
    done = lambda cell: math.dist(cm.center(*cell), goal) <= max(reach, cm.cell / 2) or cell == g  # noqa: E731
    h = lambda cell: math.hypot(cell[0] - g[0], cell[1] - g[1]) * 0.5  # noqa: E731  (min cell cost 0.5)
    dist, prev, q = {s: 0.0}, {}, [(h(s), 0.0, s)]
    cm.capped, n = False, 0
    while q:
        n += 1
        if n > max_expand:
            cm.capped = True
            return None
        _, d, u = heapq.heappop(q)
        if d > dist.get(u, math.inf):
            continue
        if done(u):
            path = [u]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return [cm.center(*p) for p in reversed(path)]
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not dz and not dx:
                    continue
                v = (u[0] + dz, u[1] + dx)
                if not (0 <= v[0] < cm.nz and 0 <= v[1] < cm.nx) or math.isinf(c[v]):
                    continue
                nd = d + math.hypot(dz, dx) * (c[u] + c[v]) / 2
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(q, (nd + h(v), nd, v))
    return None


def waypoints(path, hop=8.0):
    """Thin a cell path to click points: every turn, and enough points that consecutive ones are ≤ hop apart."""
    if not path:
        return []
    out, last = [], path[0]
    for i in range(1, len(path) - 1):
        a, b, cnext = path[i - 1], path[i], path[i + 1]
        turn = (round(b[0] - a[0], 6), round(b[1] - a[1], 6)) != (round(cnext[0] - b[0], 6), round(cnext[1] - b[1], 6))
        if turn or math.dist(last, cnext) > hop:
            out.append(b)
            last = b
    out.append(path[-1])
    return out


def build(area, entities, facts, now_hour, extra=()):
    """The costmap of `area` from solid entities, learned walls, recent refused clicks and walked segments. `extra`
    points (start, goal) are inside the bounds too."""
    import nav
    pts = [(e.x, e.z) for e in entities.find(area=area)] + [tuple(p) for p in extra]
    for f in facts:
        if f.get('scene') == area:
            pts += [tuple(p) for p in (f.get('from'), f.get('to'), f.get('target')) if p]
    if not pts:
        return None
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    cm = Costmap(area, (min(xs) - MARGIN, min(zs) - MARGIN, max(xs) + MARGIN, max(zs) + MARGIN))
    for e in entities.find(area=area):
        if e.solid:
            cm.add_solid(e.x, e.z, e.r)
    for x, z, dx, dz in nav.walls(facts, {}).get(area, []):
        cm.add_wall(x, z, dx or 0.0, dz or 0.0)
    for f in facts:
        if f.get('scene') == area and f.get('result') == 'no_move' and f.get('target') and f.get('hour') is not None:
            cm.add_refused(*f['target'], game_hour=nav.game_hours(f))
    for (s, x, z), ends in nav.trail(facts).items():
        if s == area:
            for ex, ez in ends:
                cm.add_walked(x, z, ex, ez)
    return cm
