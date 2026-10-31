"""The save as evidence (spec 2026-10-30 §4): crops, inventory, and the exact position reading — the only 2.5 s call
that takes the game out of the front, counted in READINGS so the eval/bench can see how often it is used."""
WF = None
READINGS = [0]


def bind(wf):
    global WF
    WF = wf


def crops():
    out = []
    for c in WF.farm_status()['crops']:
        st = (c.get('plantState') or '').strip('#')
        out.append({'x': float(c['x']), 'z': float(c['z']), 'state': 'empty' if st in ('', '0') else st,
                    'wilted': c.get('isWilted') == 'true', 'watered': c.get('isWatered') == 'true'})
    return out


def inventory():
    """{item name: count} as `./wf save` reads it (player.inventory.items, nameHash = the item name)."""
    _, d = WF.read_save()
    g = d['gameState']
    return {i['nameHash']: int(i['count']) for i in g['player']['inventory']['items']}


def reading():
    """(area, x, z) from a fresh autosave."""
    READINGS[0] += 1
    p = WF.pos()
    return p['scene'], float(p['x']), float(p['z'])
