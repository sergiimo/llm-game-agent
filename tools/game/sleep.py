"""Sleep compatibility alias. The model follows actions/sleep.md one turn at a time."""

def do(answer=None, **params):
    from . import play
    store, adapter = params.pop('store', None), params.pop('adapter', None)
    return play.turn('sleep', params, answer, store, adapter)


def summary(res):
    from .play import summary
    return summary(res)
