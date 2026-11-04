"""FORAGE: the foraging strategy (user D188, spec 2026-11-03 §13). Rocks, trees, branches, forage plants and drops
grow and get destroyed, so they are NEVER graph nodes: each step is one model-vision question on the current frame -
the grid cell of the nearest fitting object. A click there walks her to it and turns her to it (D150); then the
bubble at her is clicked until the job's log proof comes (`destroying`, `grab_item`) or max_hits. The result is
recorded (run log `forage`), the answered look is stored under the proven name (objects db: vectors, not the graph),
and the next question is asked. Stop: vision answers none, the clock / rain / daylight, energy below the job's floor,
the click cap. Separate from the garden strategy (engine.py); shared only: click, screen rules, recording, vision.

`run(job, answer=None)`: no answer -> NeedVision (the question); answer = a grid cell, `walk:<cell>` (free ground
toward more of them, off-screen) or `none`."""
import json
import os
import re

from . import act as A, ask, core, learn as L, observe as O

JOBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'forage.json')
NEAR_HER = 200       # px from the frame centre: a bubble this close is the one at her (she stands at the object)
MAX_CLICKS = 30      # clicks per call


def jobs():
    with open(JOBS) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith('_')}


def _job(name):
    js = jobs()
    if name not in js:
        raise core.Failed(f'unknown forage job {name!r}: {", ".join(js)}')
    return js[name]


def _energy():
    try:
        return core.WF.read_energy(core.WF.grab())
    except Exception:   # noqa: BLE001
        return None


def _stops(name, job, res):
    """The stop rules before any click: clock, rain, daylight, energy. True when stopped."""
    if ask.late(res):
        return True
    r = ask.rain()
    if r:
        res['stop'] = f'rain ({r} today): no chores in the rain for now (user D187)'
        return True
    if res.get('light') not in (None, 'day'):
        res['stop'] = f'dark ({res["light"]}): vision is unreliable outside daylight - suggest sleeping (ask the user)'
        return True
    e = _energy()
    if e is not None and e < job.get('energy', 0):
        res['stop'] = f'energy {e}% < {job["energy"]}% for {name}: eat/drink or sleep (ask the user)'
        return True
    return False


def question(name, job):
    q = (f'Forage job {name}: Tara is the magenta circle (the frame centre). Give the grid cell ON the nearest '
         f'{job["targets"]}')
    if job.get('drops'):
        q += '; or, nearer, a dropped item lying on the ground (wood, stone: pick drops up first)'
    return q + ('. If none is in view but more may be off-screen, answer walk:<cell> on free ground toward them; '
                'answer none if there are none left.')


def _ask(name, job, res):
    ask.ask('click', question(name, job), {'goal': f'forage:{name}', 'params': {}}, res)


def _proof(job, lines):
    """The job's proof in the log lines: (what, the object's name) or (None, None)."""
    for line in lines:
        m = re.search(job['proof'], line)
        if m:
            what = 'destroying' if 'destroying' in line else 'grab_item'
            return what, next((g for g in m.groups() if g), None)
    return None, None


def _record(res, **kw):
    res.setdefault('done', []).append(kw)
    try:
        core.WF.run_log('forage', **kw)
    except Exception:   # noqa: BLE001
        pass


def _work(name, job, pt, res):
    """Walk to the answered point (a click on it), then click the bubble at her until the proof or max_hits."""
    W = core.WF
    mark = W.log_mark()
    c = A.click(pt, 'point')
    res['clicks'] += 1
    what, obj = _proof(job, c.lines)
    hits = 0
    while what is None and hits < job.get('max_hits', 1) and res['clicks'] < res['max_clicks']:
        at_her = [a for a in O.scan() if O.d(a.pt, O.CENTRE) <= NEAR_HER]
        if not at_her:
            break
        b = min(at_her, key=lambda a: O.d(a.pt, O.CENTRE))
        A.click(b.pt, 'bubble')
        res['clicks'] += 1
        hits += 1
        what, obj = _proof(job, core.log_text(mark).splitlines())
    if what is None:
        _record(res, job=name, pt=list(pt), result='no bubble' if hits == 0 else f'no proof after {hits} hits',
                hits=hits, moved=c.moved)
        return False
    stored = False
    if obj and c.img0 is not None:   # the answered look, named by the game's proof: detection finds it next time
        hx, hy = L.ANSWER_BOX
        stored = L.relabel(c.img0, (max(0, pt[0] - hx), max(0, pt[1] - hy), pt[0] + hx, pt[1] + hy), obj)
    _record(res, job=name, pt=list(pt), result=what, object=obj, hits=hits, look_stored=bool(stored))
    return True


def run(name, answer=None, max_clicks=MAX_CLICKS):
    """One step of the foraging job `name`. Raises NeedVision with the next question; returns res when it stops."""
    job = _job(name)
    goal = f'forage:{name}'
    res = {'goal': goal, 'clicks': 0, 'vision': 0, 'done': [], 'stop': None, 'notes': [], 'trace': [],
           'max_clicks': max_clicks}
    O.check_language()
    A.gameplay()
    if answer is not None:
        ask.take_answer(goal)
        a = str(answer).strip()
        if a.lower() == 'none':
            ask.progress(goal)
            res['stop'] = 'done: vision sees none left'
            return res
        try:
            if a.lower().startswith('walk:'):
                pt = ask.parse_point(a.split(':', 1)[1])
                A.click(pt, 'step')
                res['clicks'] += 1
            else:
                pt = ask.parse_point(a)
                if _stops(name, job, res):
                    return res
                if _work(name, job, pt, res):
                    ask.progress(goal)
        except ValueError as e:
            raise core.Failed(f'answer rejected: {e}. Answer a grid cell A1-X16, walk:<cell>, or none') from None
        A.gameplay()
    if _stops(name, job, res):
        return res
    _ask(name, job, res)


def summary(res):
    return (f"{res['goal']}: done {len(res['done'])} ({[d.get('result') for d in res['done']]}), clicks {res['clicks']}"
            f", stop: {res['stop']}")
