"""LEARN: what the game's answers teach (framework: observe -> act -> learn -> nav).

- memory (law 6, a hint, never a gate): the group's tally per game day, crops, can, soil view (objects/graph)
- bubble kinds: a clicked bubble is labelled by the event the game logs next (wf.learn_bubble)
- the actions DB (chains.json): every click checked against its step; surprises; gaps fill from 2 agreeing observations
- graph directions: a graph step that reached its node moves the edge toward the direction that worked"""
import os

from . import chains, core, observe as O

GRAPH = None        # Farm.json path (None = objects/graph/Farm.json)
GROUP = 'GardenBed@Garden'
MEMORY = {'graph': None}
SURPRISES = []      # this run's mismatches vs chains.json (reset by a run)
STEP_OF = {'unplant': ('replant', 0), 'water': ('water', 0), 'out_of_water': ('water', 1), 'grab_item': ('harvest', 0),
           'plant_growing': ('bed', 0)}   # a bubble-loop click's chain step, known only from its event


# ---- memory --------------------------------------------------------------------------------------------------
def graph_path():
    if GRAPH:
        return GRAPH
    from objects import graph as OG
    return os.path.join(OG.DEFAULT_DIR, 'Farm.json')


def open_memory():
    from objects import graph as OG
    g = OG.Graph()
    try:
        g.load(graph_path())
    except (OSError, ValueError):
        g = None
    MEMORY['graph'] = g if g is not None and GROUP in g.nodes else None


def close_memory():
    g, MEMORY['graph'] = MEMORY['graph'], None
    if g is not None:
        try:
            g.save(graph_path())
        except OSError:
            pass


def stamp():
    try:
        return core.WF.game_stamp()
    except Exception:   # noqa: BLE001
        return None


def remember(events, crop=None):
    """A click's events (and a crop read from a card) -> the group's memory (objects/graph.note_click)."""
    g = MEMORY['graph']
    if g is None or not (events or crop):
        return
    from objects import graph as OG
    OG.note_click(g, GROUP, list(events), stamp(), crop=crop)


def remember_soil(counts):
    """The soil heat map's dry/wet cells on this frame: the group's latest soil view."""
    g = MEMORY['graph']
    if g is None or not counts:
        return
    g.set_state(GROUP, 'soil_seen', {'dry_cells': counts[0], 'wet_cells': counts[1]}, stamp(), 'frame', 0.6)


BED_STATE_OF = {'plant': 'planted', 'water': 'watered', 'plant_growing': 'growing', 'unplant_impl': 'empty',
                'grab_item': 'picked', 'unplant': 'wilted'}


def place(node, at, events=()):
    """A bed event's world position -> its bed's group ('GardenBed@GardenSouth'), and the bed member's state from the
    event (L137: the graph of beds inside a garden). Other nodes pass through."""
    g = MEMORY['graph']
    if g is None or at is None or not node or not node.startswith('GardenBed'):
        return node
    from objects import graph as OG
    mid = OG.node_at(g, at[0], at[1])
    if mid is None or '@' not in mid:   # world objects (engine) carry their own state (game/world.place)
        return node
    for e in events:
        if e in BED_STATE_OF:
            g.set_state(mid, 'plant' if e in ('plant', 'unplant_impl', 'plant_growing', 'unplant') else e,
                        BED_STATE_OF[e], stamp(), 'event')
    return g.nodes[mid].region


def memory_hint():
    g = MEMORY['graph']
    if g is None:
        return ''
    from objects import graph as OG
    return OG.hint(g, GROUP)


def toward(a, b):
    from objects import graph as OG
    return OG.toward(MEMORY['graph'], a, b)


def learn_toward(a, b, direction):
    """A graph step from node a reached node b: the a->b direction moves halfway toward the one that worked."""
    g = MEMORY['graph']
    if g is None:
        return
    from objects import graph as OG
    OG.learn_toward(g, a, b, direction)


# ---- object kinds (appearance vectors) ----------------------------------------------------------------------------
def relabel(img, box, kind):
    """A detection the game proved to be another object (clicked as a bed, the log said BeeHive): its crop becomes an
    example of `kind` (source 'event'), so the rival kind wins that look from now on. True when stored."""
    if img is None or box is None or not kind:
        return False
    try:
        from objects import detect as D, store as S
        x0, y0, x1, y1 = (int(v) for v in box)
        crop = img.convert('RGB').crop((x0, y0, x1, y1))
        return S.Store().add(kind, crop, D.dino.mean_vector(crop), source='event', force=True) is not None
    except Exception:   # noqa: BLE001 (learning never breaks play)
        return False


def kind_of(node):
    """Graph node -> detection kind ('GardenBed@Garden' -> 'GardenBed', 'BeeHive#3' -> 'BeeHive')."""
    return node.split('@')[0].split('#')[0] if node else None


# ---- bubble kinds --------------------------------------------------------------------------------------------
def learn_bubble(c, img0):
    """A clicked bubble is labelled by the interaction the game logged next; a wrong/unknown kind is stored as a new
    reference (wf.learn_bubble). The label or None."""
    W = core.WF
    if c.what != 'bubble' or not hasattr(W, 'event_kind') or not hasattr(W, 'learn_bubble'):
        return None
    b = O.nearest(c.before, c.pt, max_d=60)
    label = W.event_kind(c.lines)
    if b is None or not label or b.kind == label:
        return None
    try:
        return label if W.learn_bubble(W.bubble_crop(img0, b.pt), label, b.kind) else None
    except Exception:   # noqa: BLE001
        return None


# ---- actions DB ------------------------------------------------------------------------------------------------
def text_gaps():
    """OCR the burst only while some step's short-lived text is still a gap or expected (costly)."""
    try:
        db = chains.load()
    except (OSError, ValueError):
        return False
    return any(s['expect'].get('text', '?') is not None for k, v in db.items() if not k.startswith('_') for s in v)


def check(c, chain=None, idx=None):
    """Check a click against its chains.json step (by event when not given); surprises go on the click."""
    if chain is None:
        hit = next((STEP_OF[e] for e in c.events if e in STEP_OF), None)
        if hit is None:
            return c
        chain, idx = hit
    try:
        c.surprises = chains.observe(chain, idx, c)
    except Exception:   # noqa: BLE001 (the DB never breaks play)
        pass
    SURPRISES.extend(f'{chain}[{idx}] {f}: expected {w!r}, got {g!r}' for f, w, g in c.surprises)
    return c


def settle_db():
    """After every run: the actions DB learns from what the game showed - '?' gaps with 2 agreeing observations are
    filled, expectations contradicted 3+ times in a row (and never confirmed since) are revised. Logged."""
    try:
        filled = [g for g in chains.gaps(apply=True) if g[4]]
        revised = [r for r in chains.revise(apply=True) if r[6]]
    except Exception:   # noqa: BLE001 (the DB never breaks play)
        return
    for g in filled:
        log_db('filled', f'{g[0]}[{g[1]}] {g[2]}')
    for r in revised:
        log_db('revised', f'{r[0]}[{r[1]}] {r[2]} -> {r[4]!r} (x{r[5]})')


def log_db(what, msg):
    try:
        core.WF.run_log('learn', what=what, msg=msg)
    except Exception:   # noqa: BLE001
        pass


# ---- the transition table (actions.json): rows learned from play ------------------------------------------------
NEAR_BUBBLE = 60   # px: the clicked object's bubble after the click is within this distance of the clicked point


def _parse_value(v):
    s = str(v).strip()
    return {'true': True, 'false': False, 'none': None}.get(s.lower(), s)


def new_row(kind, state, aff, outcome, answer=None):
    """A click on a bubble no row knew -> a row: when = the state it had, bubble = its kind and sub-icons, steps = the
    click (expecting the event the game logged), effect = what changed: the clicked bubble's sub-icons gone ("!" gone ->
    ready false; drop gone -> watered true) or vision's `answer` ('key=value'). None when nothing shows a change."""
    effect = {}
    if answer:
        for part in str(answer).split(','):
            if '=' in part:
                k, v = part.split('=', 1)
                effect[k.strip()] = _parse_value(v)
    else:
        near = [b for b in outcome.get('after', []) if O.d(b.pt, aff.pt) < NEAR_BUBBLE]
        if aff.ready and not any(b.ready for b in near):
            effect['ready'] = False
        if aff.drop and not any(b.drop for b in near):
            effect['watered'] = True
    if not effect:
        return None
    when = {k: (not v if isinstance(v, bool) else state.get(k)) for k, v in effect.items()
            if isinstance(v, bool) or state.get(k) is not None}
    bubble = {'kind': aff.kind}
    for k in ('ready', 'drop'):
        if getattr(aff, k, False):
            bubble[k] = True
    events = [e for e in outcome.get('events', [])]
    step = {'do': 'click_bubble'}
    if events:
        step['expect'] = {'events': [events[-1]]}
    return {'id': f'learned_{kind}_{aff.kind}', 'kind': kind, 'when': when, 'bubble': bubble, 'steps': [step],
            'effect': effect, 'source': f'learned {stamp() or ""}'.strip(), 'seen': 1, 'ok': 1, 'surprises': 0}


def add_row(row):
    """Store a learned row; an agreeing one (same kind, bubble, effect) counts one more sighting. The stored row."""
    from . import plan
    rs = plan.rows()
    for r in rs:
        if r['kind'] == row['kind'] and r.get('bubble') == row['bubble'] and r['effect'] == row['effect']:
            r['seen'] = r.get('seen', 0) + 1
            r['ok'] = r.get('ok', 0) + 1
            plan.save_rows(rs)
            return r
    ids = {r['id'] for r in rs}
    base, k = row['id'], 2
    while row['id'] in ids:
        row['id'], k = f'{base}_{k}', k + 1
    rs.append(row)
    plan.save_rows(rs)
    log_db('learned', f'{row["id"]}: {row["kind"]} {row["when"]} --{row["bubble"]}--> {row["effect"]}')
    return row


def settle_rows():
    """After every run: '?' gaps with AGREE agreeing observations are filled; expectations contradicted REVISE times
    in a row with the same value (none confirmed since) are revised. From steps.OBSERVED."""
    import json
    from . import plan, steps
    try:
        with open(steps.OBSERVED) as fh:
            recs = [json.loads(l) for l in fh if l.strip()]
    except (OSError, ValueError):
        return []
    by = {}
    for r in recs:
        by.setdefault((r['row'], r['step'], r['field']), []).append(r)
    rs, changed = plan.rows(), []
    for r in rs:
        for i, s in enumerate(r['steps']):
            for field, want in list((s.get('expect') or {}).items()):
                obs = by.get((r['id'], i, field), [])
                if want == '?':
                    got = [o['got'] for o in obs if o['verdict'] == 'gap']
                    if len(got) >= AGREE and all(g == got[-1] for g in got[-AGREE:]):
                        s['expect'][field] = got[-1]
                        changed.append(('filled', r['id'], i, field, got[-1]))
                    continue
                tail = []
                for o in reversed(obs):
                    if o['verdict'] != 'surprise':
                        break
                    tail.append(o['got'])
                if len(tail) >= REVISE and all(t == tail[0] for t in tail[:REVISE]) and tail[0] is not None:
                    s['expect'][field] = tail[0]
                    changed.append(('revised', r['id'], i, field, tail[0]))
    if changed:
        plan.save_rows(rs)
        for c in changed:
            log_db(c[0], f'{c[1]}[{c[2]}] {c[3]} -> {c[4]!r}')
    return changed


AGREE, REVISE = 2, 3
