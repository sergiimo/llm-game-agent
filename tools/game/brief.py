"""A full-frame state brief for the model's one near-navigation decision."""
import math

from PIL import ImageDraw

from . import observe, where, world


LIVE_SOURCES = {'card', 'bubble', 'vision', 'event'}


def _position(g):
    source, pos = where.position(far_ok=False, walk_ok=True)
    if source in ('event', 'walk') and pos is not None:
        return source, tuple(pos)
    if where.invalidated_by_unpositioned_walk():
        return 'unknown', None
    pos = world.tara_pos(g)
    return ('save', tuple(pos)) if pos is not None else ('unknown', None)


def _fresh(g, nid, today):
    observations = [v for v in g.nodes[nid].state.values() if isinstance(v, dict)]
    if any(v.get('source') in LIVE_SOURCES and world.checked_day(g, nid, key) == today
           for key, v in g.nodes[nid].state.items() if isinstance(v, dict)):
        return 'today'
    if any(v.get('source') == 'save' for v in observations):
        return 'save'
    return 'unknown'


def _area_objects(g, kind, targets):
    areas = {world.area_of(g, nid) for nid in targets if nid in g.nodes} - {None}
    ids = world.query(g, {'kind': kind})
    return [nid for nid in ids if not areas or world.area_of(g, nid) in areas]


def build(g, kind, targets, res):
    """Build one immutable decision brief from graph state and one frame read."""
    from . import engine

    source, tara = _position(g)
    spec, params = res.get('spec') or {}, res.get('params') or {}
    where_filter = engine._where(spec, params)
    today = engine._today()
    objects = []
    for nid in _area_objects(g, kind, targets):
        pos = tuple(g.nodes[nid].extra['pos'])
        status = world.state_of(g, nid)
        objects.append({
            'id': nid,
            'status': status,
            'fresh': _fresh(g, nid, today),
            'crop': status.get('crop'),
            'need': engine._passes(g, nid, where_filter),
            'screen': engine.screen_point(tara, pos) if tara is not None else None,
            'dist': round(math.dist(tara, pos), 2) if tara is not None else None,
        })
    bubbles = []
    for a in observe.scan():
        nearest = min(((observe.d(a.pt, o['screen']), o['id']) for o in objects if o['screen'] is not None),
                      default=None)
        owner = nearest[1] if nearest is not None and nearest[0] <= engine.OWN_PX else None
        bubbles.append({'pt': tuple(a.pt), 'kind': a.kind, 'icon': a.icon, 'badge': a.badge, 'owner': owner})
    heatmap = [{'kind': d.kind, 'pt': tuple(d.point)} for d in observe.see_all()]
    return {
        'tara': {'pos': tara, 'source': source},
        'objects': objects,
        'bubbles': bubbles,
        'heatmap': heatmap,
        'recent': list(res.get('recent') or [])[-6:],
    }


def text(state):
    """Plain-text companion to the marked frame: one explicit line per object and bubble."""
    tara = state['tara']
    lines = [f"Tara {tara['source']} pos={tara['pos']}"]
    for o in state['objects']:
        lines.append(f"object {o['id']} status={o['status']} fresh={o['fresh']} crop={o['crop']} "
                     f"need={o['need']} screen={o['screen']} dist={o['dist']}")
    for b in state['bubbles']:
        lines.append(f"bubble {b['kind']} pt={b['pt']} icon={b['icon']} badge={b['badge']} owner={b['owner']}")
    for h in state['heatmap']:
        lines.append(f"heatmap {h['kind']} pt={h['pt']}")
    for r in state['recent']:
        lines.append(f"recent {r}")
    return '\n'.join(lines)


def draw(img, state):
    """Return a labelled copy at exactly the input frame's full resolution."""
    out = img.copy().convert('RGB')
    pen = ImageDraw.Draw(out)
    centre = observe.CENTRE
    pen.ellipse((centre[0] - 18, centre[1] - 18, centre[0] + 18, centre[1] + 18),
                outline='#00ffff', width=4)
    for o in state['objects']:
        if o['screen'] is None:
            continue
        x, y = o['screen']
        colour = '#ff3030' if o['need'] else '#50d050'
        pen.ellipse((x - 10, y - 10, x + 10, y + 10), outline=colour, width=5)
        pen.ellipse((x - 2, y - 2, x + 2, y + 2), fill=colour)
        short = o['id'].split('#', 1)[-1][-14:]
        pen.text((x + 12, y - 12), f"{short} {o['fresh']} {o['status']}", fill=colour,
                 stroke_width=2, stroke_fill='black')
    for b in state['bubbles']:
        x, y = b['pt']
        pen.rectangle((x - 8, y - 8, x + 8, y + 8), outline='#ffd000', width=3)
    return out
