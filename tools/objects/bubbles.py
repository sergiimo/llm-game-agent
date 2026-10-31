"""Bubble ownership in frame px: a bubble floats above its object."""


def owner(bubble_pt, dets, dx=90, up=(20, 260)):
    """The detection whose point is below the bubble (up[0] < det.y - bubble.y <= up[1], |dx| <= dx), nearest; else None."""
    best, bd = None, None
    for d in dets:
        vy, vx = d.point[1] - bubble_pt[1], d.point[0] - bubble_pt[0]
        if up[0] < vy <= up[1] and abs(vx) <= dx:
            dist = (vx * vx + vy * vy) ** .5
            if bd is None or dist < bd:
                best, bd = d, dist
    return best
