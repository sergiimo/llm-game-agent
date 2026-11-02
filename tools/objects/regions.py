"""Detection scope per region and the region entry signal. Scene regions (Farm, House) are entered/left by log scene
changes; view regions (Garden) have no scene change: inside = (nearly) all members of one group detected (COVER_MIN)."""


def scope(graph, region_id):
    """Kinds to detect inside a region: its unique/group kinds + view child regions by their own name. Scene child
    regions are reached through their door (a kind of the parent), never searched by name; a region never searches
    itself. A region's exit node (e.g. House -> HouseExit) is a child of the region, so it is in the scope."""
    out = []
    for n in graph.children(region_id):
        if n.type == 'member' or n.id == region_id or n.kind == 'Tara':   # Tara is the chain's cursor, not a detectable object
            continue
        if n.type == 'group' and n.extra.get('pattern') is None:   # a group without a pattern yet (GardenBed@FarGarden)
            continue
        if n.type == 'region' and n.extra.get('signal') != 'view':
            continue
        if n.kind not in out:
            out.append(n.kind)
    return out


COVER_MIN = 0.85   # share of one group's members that must be detected (hives 7 of 8, beds 11 of 12)


def _groups(graph, region_id):
    """[(kind, size)] of the region's groups; size from the pattern (rows x cols), else the member count."""
    out = []
    for n in graph.children(region_id):
        if n.type != 'group' or n.extra.get('cover') is False:   # cover:false = too noisy to count (beds over-detect everywhere)
            continue
        pat = n.extra.get('pattern') or getattr(n, 'pattern', None) or {}
        size = int(pat.get('rows', 0)) * int(pat.get('cols', 0)) or len(graph.members(n.id))
        if size:
            out.append((n.kind, size))
    return out


def _covered(graph, region_id, detections):
    for kind, size in _groups(graph, region_id):
        found = min(sum(1 for d in detections if d.kind == kind), size)
        if found / size >= COVER_MIN:
            return True
    return False


def inside_check(graph, region_id, detections, view=None):
    """(inside, uncertain). Inside = we can detect (nearly) all members of one of the region's groups, so their states can
    be updated: >= COVER_MIN of a group's size, counting at most group-size detections. `detections` must come from
    detect(..., region=region_id) (the region's own thresholds). `view` (nearest ViewStore region) is only evidence: if
    it disagrees with the coverage result, the coverage result stands and `uncertain` is set."""
    ins = _covered(graph, region_id, detections)
    return ins, view is not None and (view == region_id) != ins


def inside(graph, region_id, detections, view=None):
    """View-region entry signal (bool of `inside_check`)."""
    return inside_check(graph, region_id, detections, view)[0]


def current_region(graph, scene, detections, view=None):
    """(region_id, uncertain). Scene region from the log (`scene` = a scene region id such as House, else Farm), then the
    deepest view child whose coverage `inside` holds (`detections` = a list, or a callable region_id -> detect(..., region=that
    region) so each candidate view region is probed with its own thresholds). `view` is optional evidence: a disagreement with the coverage result sets uncertain. No scene evidence ->
    the top region, uncertain."""
    top = next((n.id for n in graph.nodes.values() if n.type == 'region' and n.region is None), None)
    n = graph.nodes.get(scene)
    if n is not None and n.type == 'region' and n.extra.get('signal') == 'scene':
        cur = n.id
        uncertain = False
    else:
        cur, uncertain = top, True
    while True:
        nxt = []
        for c in graph.children(cur):
            if c.type == 'region' and c.extra.get('signal') == 'view':
                dets = detections(c.id) if callable(detections) else detections
                ins, unc = inside_check(graph, c.id, dets, view)
                uncertain = uncertain or unc
                if ins:
                    nxt.append(c)
        if not nxt:
            return cur, uncertain
        cur = nxt[0].id
