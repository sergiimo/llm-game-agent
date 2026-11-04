"""INTEGRATE: the one integration boundary of the improvement loop (spec docs/superpowers/specs/2026-11-04-unified-
improvement-loop-refactor.md).

    action settles -> capture/record (an immutable Experience) -> propose (the smallest sufficient Correction) -> apply

`apply` persists the experience, then commits its updates in one order - world facts, evals, learned memory,
transition observations, escalation - each ONCE per experience (applied keys journal: replay is idempotent).
Consumers delegate to the existing rules (learn.py: bubble labels, answer looks, relabels, directions; world.py via
learn.observe_card: crop cards; the transition journal steps.OBSERVED). Gap bundles: a check that keeps failing
without a resolution (`settle`), or a capability the table can't represent (`gap`), is written for the offline code
factory (`fixture` makes it an offline test). The runtime never patches code.

act.click only captures and calls `on_click` (registered below); nav passes what it knows (a detection box, a
direction tried) as the action's context, and the memory consumers decide what that teaches."""
import json
import os
import re
import subprocess
import time
import types

from . import act as A, core, experience as X, observe as O

JOURNAL_DIR = None     # None = the open run's dir, else act.SHOTS (tests: a temp dir)
GAP_REPEAT = 2         # the same unresolved check failing this many times = a gap bundle
CARD_WAIT = 3.0        # s an expected card gets to show after the action (live D189: Collect came late)
_APPLIED = {}          # journal dir -> set of applied update keys (cache of applied.txt)
_RESOLVED = set()      # experience ids a later rule explained (an info card, another row's card): never a gap


# ---- storage --------------------------------------------------------------------------------------------------------
def _dir():
    if JOURNAL_DIR:
        return JOURNAL_DIR
    try:
        d = core.WF.run_dir()
    except Exception:   # noqa: BLE001
        d = None
    return d or A.SHOTS


def _path(name):
    return os.path.join(_dir(), name)


def _append(name, line):
    try:
        os.makedirs(_dir(), exist_ok=True)
        with open(_path(name), 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass


def journal(path=None):
    """Every recorded experience (oldest first)."""
    out = []
    try:
        with open(path or _path('experiences.jsonl')) as f:
            for line in f:
                try:
                    out.append(X.Experience.from_dict(json.loads(line)))
                except (ValueError, TypeError, KeyError):
                    continue
    except OSError:
        pass
    return out


def _applied():
    d = _dir()
    if d not in _APPLIED:
        try:
            with open(_path('applied.txt')) as f:
                _APPLIED[d] = {l.rstrip('\n') for l in f}
        except OSError:
            _APPLIED[d] = set()
    return _APPLIED[d]


def _persist(e):
    keys = _applied()
    k = f'{e.id}:experience'
    if k in keys:
        return False
    _append('experiences.jsonl', json.dumps(e.to_dict(), default=str))
    keys.add(k)
    _append('applied.txt', k)
    return True


def _save_img0(img0, frames):
    """The frame before the click, next to its burst frames: memory updates (and their replay) read it from here."""
    if img0 is None:
        return None
    try:
        d = A.frames_dir()
        os.makedirs(d, exist_ok=True)
        base = os.path.basename(frames[0]).rsplit('-', 1)[0] if frames else time.strftime('%H%M%S')
        p = os.path.join(d, f'{base}-img0.jpg')
        img0.convert('RGB').save(p, quality=88)
        return p
    except Exception:   # noqa: BLE001 (fakes, disk): recording never breaks play
        return None


# ---- the verifier: expectations against evidence (moved from steps._check) -------------------------------------------
def _card():
    from . import ui
    try:
        return ' / '.join(ui.texts())
    except Exception:   # noqa: BLE001
        return ''


def verify(expect, lines, events, card=None):
    """(checks, bad): each expectation field (events, card, log; '?' = a gap: observe, never a failure)."""
    checks, bad = [], []
    for fld, want in (expect or {}).items():
        if want == '?':
            got = list(events) if fld == 'events' else (card if card is not None else _card()) if fld == 'card' \
                else next(iter(lines), None)
            checks.append(X.Check(fld, want, got, None))
            continue
        if fld == 'events':
            got = list(events)
            ok = all(any(e in got for e in alt.split('|')) for alt in want)
        elif fld == 'card':
            got = card if card is not None else _card()
            ok = want.lower() in got.lower()
            if not ok and card is None:   # it may show a moment later (she walks to the bed first, live D189)
                from . import ui
                if ui.shows(want, wait=CARD_WAIT):
                    got, ok = _card(), True
        elif fld == 'log':
            got = next((l for l in lines if re.search(want, l)), None)
            ok = got is not None
        else:
            continue   # bubble/text: in the click's evidence, not a gate here
        checks.append(X.Check(fld, want if not isinstance(want, tuple) else list(want), got, ok))
        if not ok:
            bad.append((fld, want, got))
    return checks, bad


def _verdict(checks):
    if not checks or all(c.ok is None for c in checks):
        return X.Verdict('unknown', tuple(checks))
    return X.Verdict('hit' if all(c.ok is not False for c in checks) else 'miss', tuple(checks))


def _aff(a):
    return (a.kind, int(a.pt[0]), int(a.pt[1]), bool(getattr(a, 'drop', False)), bool(getattr(a, 'ready', False)),
            bool(getattr(a, 'highlighted', False)))


def _affs(rows):
    from .affordances import Affordance
    out = []
    for r in rows or ():
        if isinstance(r, (list, tuple)) and len(r) >= 5:
            out.append(Affordance(r[0], None, (r[1], r[2]), bool(r[5]) if len(r) > 5 else False, 0.0, r[3], r[4]))
    return out


def _ctx(context):
    return tuple(sorted((k, X._t(v)) for k, v in (context or {}).items() if v is not None))


# ---- capture: actions -> experiences ----------------------------------------------------------------------------------
def capture(c, img0=None, here=None):
    """A Click (act.click's record) -> its Experience (prediction and goal as the caller gave them)."""
    pred = getattr(c, 'predict', None) or {}
    checks = []
    if any(k in pred for k in ('events', 'card', 'log')):
        checks, _ = verify(pred, c.lines, c.events)
    ctx = dict(getattr(c, 'context', None) or {})
    if here is not None:
        ctx.setdefault('here', here)
    g = getattr(c, 'goal', None) or {}
    frames = tuple(c.frames or ())
    return X.Experience.new(
        goal=X.GoalRef(g.get('name'), _ctx(g.get('params')), g.get('target'), g.get('row'), g.get('step')),
        before=X.Observation(None, tuple(_aff(a) for a in (c.before or ()))),
        prediction=X.Prediction(events=X._t(pred.get('events') or ()), card=pred.get('card'), log=pred.get('log'),
                                arrive=ctx.get('det_kind')),
        action=X.Action('click', c.what, (int(c.pt[0]), int(c.pt[1])), None, _ctx(ctx)),
        evidence=X.Evidence(tuple(c.lines or ()), tuple(c.events or ()), X._t(c.at), c.node, c.mode,
                            tuple(c.texts or ()), tuple(str(t) for t in (c.burst_texts or ())),
                            tuple(_aff(a) for a in (c.after or ())), c.moved),
        verdict=_verdict(checks),
        artifacts=X.Artifacts(frames, _save_img0(img0, frames), _dir(), c.mark, round(time.time(), 3)))


def record(kind, arg, mark, lines, events, expect=None, goal=None, card=None):
    """A non-click step (press <label>, Space, pick_card, close, a cell click): its own Experience, applied."""
    checks, bad = verify(expect, lines, events, card)
    g = goal or {}
    e = X.Experience.new(
        goal=X.GoalRef(g.get('name'), _ctx(g.get('params')), g.get('target'), g.get('row'), g.get('step')),
        prediction=X.Prediction(events=X._t((expect or {}).get('events') or ()), card=(expect or {}).get('card'),
                                log=(expect or {}).get('log')),
        action=X.Action(kind, None, None, arg),
        evidence=X.Evidence(tuple(lines or ()), tuple(events or ())),
        verdict=_verdict(checks),
        artifacts=X.Artifacts((), None, _dir(), mark, round(time.time(), 3)))
    apply(e)
    return e, bad


def on_click(c, img0=None, here=None):
    """act.click's hook: capture, propose, apply. (experience, learned label or None)."""
    e = capture(c, img0, here)
    res = apply(e, img0=img0)
    return e, res.get('learned')


# ---- propose: the smallest sufficient correction (pure: the experience decides) --------------------------------------
def propose(e):
    ctx = dict(e.action.context or ()) if e.action else {}
    world, memory, transitions = [], [], []
    if e.action and e.action.kind == 'click':
        if e.evidence.at:
            world.append(X.Update('world', 'card_state'))
        if e.action.what == 'bubble':
            memory.append(X.Update('memory', 'bubble_label'))
            label = _badge_proof(e)
            if label:   # wave 1 learns from what the click proved (user D189)
                memory.append(X.Update('memory', 'badge', {'label': label}))
        if e.action.what == 'point':
            memory.append(X.Update('memory', 'answer_look', {'here': ctx.get('here')}))
        if ctx.get('det_box') and e.evidence.node and e.evidence.node != ctx.get('target'):
            memory.append(X.Update('memory', 'relabel', {'box': list(ctx['det_box']), 'node': e.evidence.node}))
        if ctx.get('toward'):
            memory.append(X.Update('memory', 'direction', {'toward': list(ctx['toward']), 'target': ctx.get('target')}))
    for i, ch in enumerate(e.verdict.checks):
        transitions.append(X.Update('transitions', 'observation', {'i': i}))
    return X.Correction(e.id, world=tuple(world), memory=tuple(memory), transitions=tuple(transitions))


_DAYS = re.compile(r'\d+ days? remaining', re.I)


def _badge_proof(e):
    """What a bubble click proved about its badge: a Collect prompt = ready, a crop card's days left = none, a water
    event = drop; None without proof."""
    ev = e.evidence
    texts = list(ev.texts) + list(ev.burst_texts)
    if any(c.field == 'card' and str(c.expected).lower() == 'collect' and c.ok for c in e.verdict.checks) \
            or any(str(t).strip().lower() == 'collect' for t in ev.texts):
        return 'ready'
    if any(_DAYS.search(str(t)) for t in texts):
        return 'none'
    if any(x in ('water', 'hazel_waterplant') for x in ev.events):
        return 'drop'
    return None


def _ns(e, img_path=None):
    """A Click-like view of the experience for the existing learn rules."""
    ev = e.evidence
    return types.SimpleNamespace(pt=tuple(e.action.pt) if e.action.pt else None, what=e.action.what,
                                 before=_affs(e.before.affordances), after=_affs(ev.after), lines=list(ev.lines),
                                 events=list(ev.events), at=tuple(ev.at) if ev.at else None, node=ev.node,
                                 mode=ev.mode or 'gameplay', texts=list(ev.texts), burst_texts=list(ev.burst_texts),
                                 moved=ev.moved, mark=e.artifacts.log_mark, exp=e.id)


def _img(e, img0):
    if img0 is not None:
        return img0
    p = e.artifacts.img0
    if p and os.path.exists(p):
        try:
            from PIL import Image
            return Image.open(p).convert('RGB')
        except Exception:   # noqa: BLE001
            return None
    return None


def _run(u, e, img0):
    """One update by the existing rules. Its result (a learned name, a node id) or None."""
    from . import learn as LN
    if u.consumer == 'world' and u.op == 'card_state':
        nid = LN.observe_card(_ns(e))
        g = LN.MEMORY['graph']
        if g is not None and e.evidence.at:
            from . import world
            hit = world.find(g, None, tuple(e.evidence.at)) if hasattr(world, 'find') else None
            for n in {nid, hit} - {None}:
                note(g, n, e.id)
        return nid
    if u.consumer == 'memory':
        img = _img(e, img0)
        if u.op == 'bubble_label':
            return LN.learn_bubble(_ns(e), img)
        if u.op == 'answer_look':
            return LN.learn_answer(_ns(e), img, u.args.get('here'), exp=e.id)
        if u.op == 'badge':   # the clicked bubble's 140-px crop -> its corner is an example of the label
            from . import badges
            if img is None or not e.action.pt:
                return None
            from . import icons
            badges.add(u.args['label'], icons.bubble140(img, e.action.pt), f'exp {e.id}')
            return f'badge:{u.args["label"]}'
        if u.op == 'proven_look':   # a box on the frame before the click, named by a later log proof
            ok = LN.relabel(img, tuple(u.args['box']), u.args['kind'])
            return f'look:{u.args["kind"]}' if ok else None
        if u.op == 'relabel':
            kind = LN.kind_of(u.args['node'])
            ok = LN.relabel(img, tuple(u.args['box']), kind)
            return f'look:{kind}' if ok else None
        if u.op == 'direction':
            a, b, d = u.args['toward']
            target = u.args.get('target')
            if e.evidence.node == target or O.closest_node(_affs(e.evidence.after)) == target:
                LN.learn_toward(a, b, tuple(d))
                return f'direction:{a}->{b}'
            return None
    if u.consumer == 'transitions':
        from . import steps
        ch = e.verdict.checks[u.args['i']]
        try:
            with open(steps.OBSERVED, 'a') as f:
                f.write(json.dumps({'t': time.strftime('%Y-%m-%d %H:%M:%S'), 'row': e.goal.row, 'step': e.goal.step,
                                    'field': ch.field, 'expected': ch.expected, 'got': ch.got,
                                    'verdict': 'gap' if ch.ok is None else 'ok' if ch.ok else 'surprise',
                                    'exp': e.id}, default=str) + '\n')
        except OSError:
            pass
        return None
    return None


def apply(e, correction=None, img0=None):
    """Persist `e`, then its correction's updates in order, each once. {'learned', 'applied': n, op: result}."""
    _persist(e)
    corr = correction or propose(e)
    keys, out = _applied(), {'applied': 0, 'learned': None}
    for u in corr.updates():
        k = u.key(e.id)
        if k in keys:
            continue
        try:
            r = _run(u, e, img0)
        except Exception as ex:   # noqa: BLE001 (learning never breaks play)
            r = None
            out.setdefault('errors', []).append(f'{u.op}: {ex}')
        keys.add(k)
        _append('applied.txt', k)
        out['applied'] += 1
        out[u.op] = r
        if r and u.consumer == 'memory' and out['learned'] is None:
            out['learned'] = r
    return out


def replay(path=None):
    """Re-propose and apply every journal experience; already-applied updates are skipped. The number applied."""
    n = 0
    for e in journal(path):
        n += apply(e)['applied']
    return n


def note(g, nid, exp_id):
    """The graph node remembers the experiences that changed it (traceable from one record)."""
    if g is None or nid not in g.nodes:
        return
    ex = g.nodes[nid].extra.setdefault('exps', [])
    if exp_id not in ex:
        ex.append(exp_id)
        del ex[:-20]


def prove(exp_id, op, img0=None, **args):
    """A later proof for an earlier experience (forage: the answered spot was a StoneRock - the log said so after the
    hits): one memory update on THAT experience, applied once. Its result or None."""
    e = next((x for x in journal() if x.id == exp_id), None)
    if e is None:
        return None
    corr = X.Correction(e.id, memory=(X.Update('memory', op, args),))
    return apply(e, corr, img0=img0).get(op)


def relation(a, b, direction, proof, **dist):
    """A traversal proved the way a -> b (the map pin got closer): the graph's learned `toward` edge (with its
    compass point and distance: route_px / map_px / steps), once per proof."""
    from . import learn as LN
    k = f'relation:{a}->{b}:{list(direction)}:{proof}'
    keys = _applied()
    if k in keys:
        return False
    LN.learn_toward(a, b, tuple(direction))
    g = LN.MEMORY['graph']
    for e in (g.edges(a, 'toward') if g is not None else []):
        if e['b'] == b:
            e.update({k: v for k, v in dist.items() if v is not None})
    keys.add(k)
    _append('applied.txt', k)
    try:
        core.WF.run_log('learn', what='way', msg=f'{a} -> {b}: {list(direction)} ({proof})')
    except Exception:   # noqa: BLE001
        pass
    return True


def world_facts(g, out, kind, row, stamp):
    """A row run (steps.run's result) -> proven world facts: its events by position (world.place, with the proof
    lines), stored card values, Tara's state from position-less events. The node records the run's experience ids.
    (object id or None, its area)."""
    from . import plan, world
    nid = None
    if out['at']:
        nid = world.place(g, out['kind'] or kind, out['at'], out['events'], stamp=stamp, params=row.get('params'),
                          lines=out['lines'])
    for k, v in out['stored'].items():
        if nid and v:
            g.set_state(nid, k, v, stamp, 'card')
    if not out['at']:   # an event without a position (Tara's can): its effects still count
        for ev in out['events']:
            for k, v in plan.effects_of_event(ev).items():
                if k.startswith('Tara.') and 'Tara' in g.nodes:
                    g.set_state('Tara', k.split('.', 1)[1], v, stamp, 'event')
    for x in out.get('exps') or ():
        note(g, nid, x)
    return nid, (world.area_of(g, nid) if nid else None)


def resolved(exp_id):
    """A later rule explained this experience's miss (an info card, another row's card): never a gap."""
    if exp_id:
        _RESOLVED.add(exp_id)


# ---- escalation: gap bundles for the offline code factory -----------------------------------------------------------
TABLES = ('actions.json', 'goals.json', 'kinds.json', 'forage.json')


def _revision():
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__)), timeout=5).stdout.strip() or None
    except Exception:   # noqa: BLE001
        return None


def _tables():
    import hashlib
    out = {}
    for t in TABLES:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), t)
        try:
            out[t] = hashlib.sha1(open(p, 'rb').read()).hexdigest()[:12]
        except OSError:
            pass
    return out


def _owner(e):
    """The component that owns the violated invariant."""
    if e.goal.row is not None:
        return 'steps'
    if e.action and e.action.what in ('step', 'explore', 'soil'):
        return 'nav'
    return 'act'


def gaps():
    out = []
    d = _path('gaps')
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.endswith('.json'):
                try:
                    out.append(json.load(open(os.path.join(d, f))))
                except (OSError, ValueError):
                    continue
    return out


def gap(exp_ids, invariant, owner, kind='capability'):
    """Write one gap bundle (once per invariant + experiences). Its id."""
    exp_ids = sorted(set(i for i in exp_ids if i))
    bid = X._hash({'inv': invariant, 'exps': exp_ids})
    if any(b['id'] == bid for b in gaps()):
        return bid
    byid = {e.id: e for e in journal()}
    b = {'id': bid, 'kind': kind, 'invariant': invariant, 'owner': owner, 'experiences': exp_ids,
         'evidence': [byid[i].to_dict() for i in exp_ids if i in byid], 'revision': _revision(), 'tables': _tables(),
         't': time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        os.makedirs(_path('gaps'), exist_ok=True)
        with open(os.path.join(_path('gaps'), f'{bid}.json'), 'w') as f:
            json.dump(b, f, indent=1, default=str)
    except OSError:
        pass
    try:
        core.WF.run_log('gap', id=bid, invariant=invariant, owner=owner, experiences=exp_ids)
    except Exception:   # noqa: BLE001
        pass
    return bid


def settle():
    """Unresolved misses that repeat (same row, step, field, expected) GAP_REPEAT times -> one bundle each. Ids."""
    groups = {}
    for e in journal():
        if e.verdict.value != 'miss' or e.id in _RESOLVED:
            continue
        for ch in e.verdict.checks:
            if ch.ok is False:
                k = (e.goal.row, e.goal.step, ch.field, json.dumps(ch.expected, default=str))
                groups.setdefault(k, []).append(e)
    out = []
    for (row, step, fld, want), es in groups.items():
        if len(es) >= GAP_REPEAT:
            got = sorted({str(c.got)[:60] for e in es for c in e.verdict.checks if c.field == fld and c.ok is False})
            inv = f'row {row} step {step}: {fld} {json.loads(want)!r} expected; got {got}'
            out.append(gap([e.id for e in es], inv, _owner(es[0]), kind='repeated'))
    return out


def fixture(bundle_id, out_dir=None):
    """A gap bundle -> an offline fixture (its experiences + the invariant). The path."""
    b = next((x for x in gaps() if x['id'] == bundle_id), None)
    if b is None:
        raise core.Failed(f'no gap bundle {bundle_id}')
    d = out_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fixtures', 'gaps')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{bundle_id}.json')
    with open(p, 'w') as f:
        json.dump({'id': b['id'], 'invariant': b['invariant'], 'owner': b['owner'], 'revision': b.get('revision'),
                   'experiences': b['evidence']}, f, indent=1, default=str)
    return p


def verify_fixture(fx):
    """Replay a fixture's experiences through the verifier: True when every check now holds (the gap is closed)."""
    for d in fx['experiences']:
        e = X.Experience.from_dict(d)
        pred = {k: v for k, v in (('events', list(e.prediction.events) or None), ('card', e.prediction.card),
                                  ('log', e.prediction.log)) if v}
        card = ' / '.join(e.evidence.texts)
        for ch in e.verdict.checks:
            if ch.field == 'card' and ch.got is not None:
                card = str(ch.got)
        _, bad = verify(pred, e.evidence.lines, e.evidence.events, card)
        if bad:
            return False
    return True


A.ON_CLICK = on_click   # act.click hands every capture to the boundary (act itself imports no learning)
