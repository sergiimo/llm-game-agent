"""The well (L77). Its position is a learned place (`./wf pos --learn well` standing at it), never a guess."""
from . import core, ui
from .core import Failed, action, prove
from .move import goto


@action
def fill_can():
    """Fill the watering can at the well (an already full can counts as done)."""
    if 'well' not in core.WF.places() and not core.WF.graph_route('well'):
        raise Failed('place "well" unknown: stand at the well and run `./wf pos --learn well`')
    goto('well')
    mark = core.WF.log_mark()
    ui.press_bubble()
    return prove('fill the can', r'target=Well', mark)
