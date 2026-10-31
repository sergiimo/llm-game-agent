"""Screen projection (spec 2026-10-30 §3): where an entity is on screen from Tara's believed position (calibration at
the current zoom, L85), and the point to click for a target: the target itself — the game pathfinds to an object."""
import math

import nav

BOX = (200, 200, 1720, 980)   # ground clicks stay inside this screen box (HUD, edges)
OBJ_BOX = (20, 150, 1900, 1060)  # an object may be clicked anywhere it shows outside the HUD (the well at x 190, D150)


def _scr(H, b, x, z):
    _, bx, bz, _ = b.predicted()
    return nav.ground_to_screen(H, x - bx, z - bz)


def to_ground(H, b, sx, sy):
    _, bx, bz, _ = b.predicted()
    dx, dz = nav.screen_to_ground(H, sx, sy)
    return bx + dx, bz + dz


def on_screen(H, b, x, z, box=BOX):
    if H is None:
        return False
    sx, sy = _scr(H, b, x, z)
    return box[0] <= sx <= box[2] and box[1] <= sy <= box[3]


def click_point(H, b, target, solids=None, box=OBJ_BOX):
    """Screen (sx, sy) of the target itself when it's on screen: clicking an object makes the game pathfind to it
    (the well from the garden, D148). No guessed occlusion (removed after S21–S25): a point is "covered" only when
    the game refuses it (refused clicks in the costmap). None without calibration or off screen."""
    if H is None:
        return None
    xz = (getattr(target, 'state', None) or {}).get('click_xz')  # where clicking the object's sprite worked (D150)
    sx, sy = _scr(H, b, *(xz if xz else (target.x, target.z)))
    if box[0] <= sx <= box[2] and box[1] <= sy <= box[3]:
        return int(sx), int(sy)
    return None
