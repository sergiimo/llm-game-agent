"""Walking (L77): to a place name, a graph node, or anything with world x/z (a bed). Navigation itself is tools/nav.py
via wf (graph, map compass, stuck rule)."""
from . import core
from .core import Failed, action

REACH = 2.5   # world units: close enough to use an object (D148: bed 2.0 units away, clicks refused)


@action
def goto(target):
    """Walk to a place/node name, or to an object with .x/.z (world coords in the current scene). An object only
    needs to be within REACH: the game refuses closer clicks once its bubble is in range ("ALREADY THERE"), and
    the caller's log proof checks the action hit this object's position, not a neighbour's."""
    try:
        if hasattr(target, 'x'):  # the world model's walk (M3): in reach / on screen / costmap / graph
            from . import walk
            msg = walk.walk(target, reach=REACH)
        else:
            msg = core.WF.goto(str(target))
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ != 'Stuck':
            raise
        # stuck: ask the model for the next step toward this target, with the goal and the layers drawn (L74, L82)
        est = core.WF.seg_estimate() or (None, 0.0, 0.0)
        d = (target.x - est[1], target.z - est[2]) if hasattr(target, 'x') else (0.0, -1.0)
        q = core.WF.stuck_vision(str(target), d, str(e).split(':', 1)[0] + ': no progress over 3 moves')
        raise Failed(f'goto {target}: STUCK, asked for the next step:\n{q}')
    if not msg.startswith(('ARRIVED', 'NEAR')):
        raise Failed(f'goto {target}: {msg.splitlines()[0][:200]}')
    return msg
