"""SMOKE: one bed, one primitive at a time, each with its own proof (design review D186: the engine layered guesses
over primitives that were never proven live). `./wf py "from game import smoke; smoke.plant_one('Tulip')"` prints
one line per step and stops at the first that fails:

  screen   gameplay (screen.require_world)
  bubble   a `plant` bubble in view (affordances.scan) - nearest to Tara
  click    click it -> the screen is the picker (its text says Inventory / Seeds)
  pick     ui.pick_card(seed) -> the card's name on screen
  confirm  Space -> `[STATS] totalPlanted` in the game log (the only proof of a planting)
  water    Space -> `> water` (or `> out_of_water`) in the game log

No navigation, no world graph, no table: if this fails, the failing primitive is named with its evidence."""
from . import act as A, core, observe as O, screen, ui

WAIT = 3.0   # s for a proving log line


def _step(out, name, ok, proof):
    out.append({'step': name, 'ok': bool(ok), 'proof': proof})
    try:
        core.WF.run_log('smoke', step=name, ok=bool(ok), proof=str(proof)[:200])
    except Exception:   # noqa: BLE001
        pass
    print(f'{name}: {"ok" if ok else "FAIL"} - {proof}')
    return ok


def _space(pattern):
    mark = core.WF.log_mark()
    ui.press_bubble()
    return core.seen(pattern, mark, WAIT)


def plant_one(seed='Tulip', kind='plant'):
    out = []
    try:
        s = screen.require_world()
    except Exception as e:   # noqa: BLE001
        _step(out, 'screen', False, str(e)[:160])
        return out
    _step(out, 'screen', True, s.kind)
    fit = [a for a in O.scan() if a.kind == kind]
    if not _step(out, 'bubble', bool(fit), str(O.nearest(fit, O.CENTRE)) if fit else
                 f'no {kind} bubble in view: {[str(a) for a in O.scan()] or "none"}'):
        return out
    c = A.click(O.nearest(fit, O.CENTRE).pt, 'bubble')
    s = screen.read()
    if not _step(out, 'click', s.kind == 'picker', f'{s.kind}: {" / ".join(s.texts[:4])}; events {c.events}'):
        ui.close()
        return out
    try:
        title = ui.pick_card(seed)
        _step(out, 'pick', True, title)
    except core.Failed as e:
        _step(out, 'pick', False, str(e)[:160])
        ui.close()
        return out
    line = _space(r'totalPlanted\.')
    if not _step(out, 'confirm', line, line or f'no totalPlanted within {WAIT} s; screen {screen.read().kind}'):
        ui.close()
        return out
    line = _space(r'> (?:water|out_of_water) ')
    _step(out, 'water', line and 'out_of_water' not in line, line or f'no water line within {WAIT} s')
    return out
