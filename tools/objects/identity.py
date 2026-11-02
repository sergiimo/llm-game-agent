"""Group member identity from frame points only (no coordinates stored): dedupe detections of one kind, assign pattern
cells to members."""
from statistics import median

from .detect import Detection
from .graph import order


def _dist(a, b, axis):
    dx, dy = a.point[0] - b.point[0], a.point[1] - b.point[1]
    return abs(dx) if axis == 'x' else abs(dy) if axis == 'y' else (dx * dx + dy * dy) ** .5


def _spacing(dets, axis):
    if axis is None:
        return median(min(_dist(a, b, None) for j, b in enumerate(dets) if j != i) for i, a in enumerate(dets))
    # one-row/column groups: gaps along the axis; near-duplicates make tiny gaps, so take the upper half of the gaps
    v = sorted(d.point[0 if axis == 'x' else 1] for d in dets)
    gaps = sorted((b - a for a, b in zip(v, v[1:])), reverse=True)
    return median(gaps[:max(1, (len(gaps) + 1) // 2)])


def dedupe(dets, min_frac=0.5, axis=None):
    """Merge same-kind detections closer than min_frac x the typical spacing (keep the higher z). axis=None: euclidean,
    typical = median nearest-neighbour distance. axis='x'|'y' (a group laid out in one row/column, e.g. hives: two
    detections per hive at different heights): compare only that coordinate, typical = median of the larger half of
    the gaps along it."""
    out = []
    for kind in dict.fromkeys(d.kind for d in dets):
        ds = [d for d in dets if d.kind == kind]
        if len(ds) < 2:
            out += ds
            continue
        lim = min_frac * _spacing(ds, axis)
        kept = []
        for d in sorted(ds, key=lambda d: -d.dist):
            if all(_dist(d, k, axis) >= lim for k in kept):
                kept.append(d)
        out += kept
    return sorted(out, key=lambda d: -d.dist)


def _cluster(vals, n_expected):
    """Cluster sorted values 1-D: split at gaps > 0.5 x the median of the (n_expected - 1) largest gaps.
    Returns the cluster index of each value (in input order)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    gaps = [vals[order[k + 1]] - vals[order[k]] for k in range(len(order) - 1)]
    if not gaps or n_expected < 2:
        return [0] * len(vals)
    big = sorted(gaps, reverse=True)[:n_expected - 1]
    lim = .5 * median(big)
    lab, c = [0] * len(vals), 0
    for k, i in enumerate(order):
        if k and gaps[k - 1] > lim:
            c += 1
        lab[i] = c
    return lab


def assign(group, members, dets, anchor_y=None):
    """({member_id: Detection}, uncertain). Rows by clustering y, columns by x; `group.pattern` rows x cols, north row
    (smallest y) first, west (smallest x) first. All rows and columns seen -> absolute indices. Fewer -> relative indices
    from the first seen row/column, rows trusted only when anchored: `anchor_y` is the frame y of a row known to lie just
    north of the group (beds: the hive row); the topmost seen row then is the north row. uncertain=False only when rows are absolute AND all columns seen."""
    rows, cols = group.pattern['rows'], group.pattern['cols']
    if not dets:
        return {}, True
    ry = _cluster([d.point[1] for d in dets], rows)
    cx = _cluster([d.point[0] for d in dets], cols)
    nr, nc = max(ry) + 1, max(cx) + 1
    anchored = False
    if anchor_y is not None and nr > 1:
        top = median(d.point[1] for d, r in zip(dets, ry) if r == 0)
        mean_row = [median(d.point[1] for d, r in zip(dets, ry) if r == k) for k in range(nr)]
        step = median(b - a for a, b in zip(mean_row, mean_row[1:]))
        anchored = 0 < top - anchor_y < 1.5 * step
    elif anchor_y is not None:
        anchored = True
    out = {}
    def pos(m):   # (row, col) 1-based: the cell id, or the legacy `index` (hives) row-major
        return order(m) if '#r' in m.id else (divmod(m.index - 1, cols)[0] + 1, divmod(m.index - 1, cols)[1] + 1)

    by_cell = {pos(m): m for m in members}
    for d, r, c in zip(dets, ry, cx):
        m = by_cell.get((r + 1, c + 1))
        if m is not None and (m.id not in out or d.dist > out[m.id].dist):
            out[m.id] = d
    return out, not ((nr == rows or anchored) and nc == cols)


def dedupe_for(group, dets, min_frac=0.5):
    """dedupe with the axis its pattern implies: 'x' for one row, 'y' for one column, else euclidean."""
    p = group.pattern
    return dedupe(dets, min_frac, axis='x' if p['rows'] == 1 else 'y' if p['cols'] == 1 else None)
