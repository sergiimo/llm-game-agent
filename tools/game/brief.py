"""A full-frame state brief for the model's one near-navigation decision."""
import math
import statistics

from PIL import ImageDraw

from . import affordances, core, observe, where, world


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
    kinds = (kind,) if isinstance(kind, str) else tuple(kind)
    ids = [nid for k in kinds for nid in world.query(g, {'kind': k})]
    return [nid for nid in ids if not areas or world.area_of(g, nid) in areas]


def build(g, kind, targets, res):
    """Build one immutable decision brief from graph state and one frame read."""
    from . import engine

    source, tara = _position(g)
    spec, params = res.get('spec') or {}, res.get('params') or {}
    where_filter = engine._where(spec, params)
    region = where_filter.get('region')
    if region is None and targets:
        region = world.area_of(g, targets[0])
    from objects import graph as OG
    relative = OG.relative_to(g, 'Tara', region) if region else None
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
            'need': nid in targets if res.get('coverage_targets') else engine._passes(g, nid, where_filter),
            'screen': engine.screen_point(tara, pos) if tara is not None else None,
            'dist': round(math.dist(tara, pos), 2) if tara is not None else None,
        })
    bubbles = []
    for a in observe.scan():
        nearest = min(((observe.d(a.pt, o['screen']), o['id']) for o in objects if o['screen'] is not None),
                      default=None)
        owner = nearest[1] if nearest is not None and nearest[0] <= engine.OWN_PX else None
        bubbles.append({'pt': tuple(a.pt), 'kind': a.kind, 'icon': a.icon, 'badge': a.badge, 'owner': owner})
    detector_region = region if res.get('inside_region') == region else None
    heatmap = [{'kind': d.kind, 'pt': tuple(d.point)} for d in observe.see_all(region=detector_region)]
    try:
        core.WF.run_log('perception', source='object_heatmap',
                        detections=[{'kind': d['kind'], 'pt': list(d['pt'])} for d in heatmap])
    except (AttributeError, TypeError):
        pass
    state = {
        'tara': {'pos': tara, 'source': source, 'relative': relative},
        'objects': objects,
        'bubbles': bubbles,
        'heatmap': heatmap,
        'recent': list(res.get('recent') or [])[-6:],
    }
    state['region_conflicts'] = region_conflicts(g, state, region) if region else []
    return state


def region_conflicts(g, state, region):
    """Distinctive visible kinds owned elsewhere veto entry; shared appearances prove no identity."""
    visible = {h['kind'] for h in state.get('heatmap', ())}
    visible.update(affordances.OWNER[b['kind']] for b in state.get('bubbles', ())
                   if b['kind'] in affordances.OWNER)
    actor = g.nodes.get('Tara')
    if actor is not None:
        visible.discard(actor.kind)  # the controlled actor moves; its graph parent cannot identify a region
    conflicts = []
    for kind in sorted(visible):
        owners = [n for n in g.nodes.values() if n.kind == kind and n.type in ('unique', 'member')
                  and not n.extra.get('transient') and n.region]
        if owners and not any(region in g.chain(n.id) for n in owners):
            areas = {world.area_of(g, n.id) for n in owners} - {None}
            if not areas:
                continue
            regions = ', '.join(sorted(areas))
            conflicts.append(f'visible {kind} belongs to {regions}, not {region}; likely current region: {regions}')
    return conflicts


def text(state):
    """Plain-text companion to the marked frame: one explicit line per object and bubble."""
    tara = state['tara']
    rel = tara.get('relative')
    relative = (f" relative={rel['compass']} of {rel['b']} distance={rel['distance']}"
                if rel else '')
    lines = [f"Tara {tara['source']} pos={tara['pos']}{relative}"]
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


ENTRY_KINDS = {'GardenBed', 'BeeHive', 'Well'}


def entry_text(state, region):
    """Compact, geometry-first brief for reaching a region.

    When Tara's world position is unknown every graph object's projected
    ``screen`` point is also unknown. Dumping all object states then buries the
    only useful evidence for a small model: this frame's appearance detections.
    """
    from objects import graph as OG
    hits = [h for h in state.get('heatmap', ()) if h.get('kind') in ENTRY_KINDS]
    counts = {}
    for h in hits:
        counts[h['kind']] = counts.get(h['kind'], 0) + 1
    lines = [f'ENTRY {region}: {len(state.get("objects", ()))} graph targets; '
             + ', '.join(f'{k}={v}' for k, v in sorted(counts.items())) + ' visible detections.']
    for conflict in state.get('region_conflicts', ()):
        lines.append(f'REGION CONTRADICTION: {conflict}. Do not confirm inside; correct localization from this frame.')
    if hits:
        cx = statistics.median(h['pt'][0] for h in hits)
        cy = statistics.median(h['pt'][1] for h in hits)
        toward = OG.compass((cx - observe.CENTRE[0], cy - observe.CENTRE[1]))
        relative = OG.compass((observe.CENTRE[0] - cx, observe.CENTRE[1] - cy))
        lines.append(f'NON-MODEL GEOMETRY: visible target cluster is {toward} of Tara '
                     f'(median {round(cx)},{round(cy)}); Tara is approximately {relative} of this visible cluster. '
                     f'Appearance alone does not identify it as {region}.')
        shown = hits[:16]
        lines.append('VISIBLE TARGETS: ' + ', '.join(f'{h["kind"]}@{h["pt"][0]},{h["pt"][1]}' for h in shown)
                     + (f' (+{len(hits) - len(shown)} more)' if len(hits) > len(shown) else ''))
    else:
        lines.append('NON-MODEL GEOMETRY: no target appearance is reliable in this frame; use scene landmarks.')
    old = state.get('tara', {}).get('relative')
    if old:
        lines.append(f'STORED PRIOR (may be stale after every walk): Tara {old["compass"]} of {old["b"]}, '
                     f'distance={old["distance"]}. Re-evaluate it from this frame; never repeat it blindly.')
    lines.append('FARMHOUSE CUTAWAY LANDMARK (apply only when the house interior is visible): every lower-wall '
                 'segment carrying a porch railing is solid. The exit is the opening between two white posts with no '
                 'railing. Its screen column changes when the camera follows Tara: from the bed it begins far right, '
                 'then recentres after crossing the rooms. Always use the fresh frame, never the previous cell. Click '
                 'ground through that opening; if Tara already crossed it onto porch boards, click the stairs below; '
                 'then move beyond the porch until the interior disappears.')
    lines.append('Choose one visible, unobstructed ground waypoint toward the target cluster. '
                 'If already among its beds/hives, answer inside. Report relative from this frame.')
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
