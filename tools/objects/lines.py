"""Shared 1-D clustering of tile points into grid rows/columns (frame pixels only)."""


def lines(vals, sizes):
    """Cluster index per value (input order): split sorted values only at gaps > half the median tile size, so pixel
    jitter never makes phantom rows/columns even when fewer lines than the pattern has are visible."""
    lim = .5 * sorted(sizes)[len(sizes) // 2]
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    lab, c = [0] * len(vals), 0
    for k, i in enumerate(order):
        if k and vals[i] - vals[order[k - 1]] > lim:
            c += 1
        lab[i] = c
    return lab
