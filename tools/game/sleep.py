"""Sleep as one resumable engine task.

Bed is a unique graph object, not a positioned save object, so it cannot be
selected by the generic ``achieve`` object query.  Navigation still knows its
region and the transition table knows how to operate its sleep bubble.
"""
from . import act as A, ask, core, nav, observe as O, plan, steps
from .core import action


def _row():
    return next((r for r in plan.rows('Bed') if r.get('id') == 'sleep'), None)


def _cell(answer):
    """Accept the same shell-safe waypoint spelling as garden: walk:F7/target:F7/F7."""
    value = str(answer).strip()
    if ':' in value and value.split(':', 1)[0].lower() in ('walk', 'target'):
        value = value.split(':', 1)[1]
    return ask.parse_point(value)


@action
def do(answer=None):
    """Reach Tara's pink bed, run the learned sleep row, and prove ``sleep_transition``.

    A NEED_VISION waypoint is resumed with ``./wf sleep answer=walk:<cell>``.
    """
    row = _row()
    if row is None:
        raise core.Failed('sleep: no Bed sleep transition row')
    res = {'goal': 'sleep', 'done': False, 'clicks': 0, 'vision': 0, 'stop': None}
    O.check_language()
    A.gameplay()
    if answer is not None:
        try:
            pt = _cell(answer)
        except ValueError as e:
            raise core.Failed(f'sleep answer rejected: {e}') from None
        click = A.click(pt, 'vision', context={'goal': 'sleep', 'answer': str(answer)})
        res['clicks'] += 1
        if 'sleep_transition' in click.events:
            res.update(done=True, stop='done: slept')
            return res
        A.gameplay()
    try:
        bubble = nav.reach(plan.fits(row), kind='Bed', node='Bed', region='House',
                           target="Tara's pink bed sleep bubble")
    except core.Failed as e:
        res['vision'] += 1
        raise core.Failed(f'{e} Resume with ./wf sleep answer=walk:<cell>.') from None
    out = steps.run(row, {}, bubble)
    res['clicks'] += out.get('clicks', 0)
    if not out.get('ok') or 'sleep_transition' not in out.get('events', ()):
        res['vision'] += 1
        why = out.get('why') or out.get('surprises') or 'sleep_transition not observed'
        raise core.Failed('sleep transition failed: ' + str(why) + '; '
                          + core.ask_vision('What is on screen after trying Tara\'s bed, and what should be clicked?'))
    res.update(done=True, stop='done: slept')
    return res


def summary(res):
    return (f"sleep: done {res['done']}, clicks {res['clicks']}, vision {res['vision']}, "
            f"stop: {res['stop']}")
