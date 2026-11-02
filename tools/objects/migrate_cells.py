"""One-shot, idempotent: `GardenBed#<index>` -> `GardenBed@Garden#r<row>c<col>` (row-major by the group's cols, from the
member's `index`, which is dropped), group `GardenBed` -> `GardenBed@Garden`; adds the group `GardenBed@FarGarden`
(no pattern, no members yet) and the unique `Tara`. Usage: python tools/objects/migrate_cells.py <graph.json> [...]"""
import json
import sys

OLD, NEW = 'GardenBed', 'GardenBed@Garden'


def migrate(data):
    nodes = data['nodes']
    old = next((n for n in nodes if n['id'] == OLD and n['type'] == 'group'), None)
    if old:
        cols = old['pattern']['cols']
        old['id'] = NEW
        for n in nodes:
            if n['type'] == 'member' and n.get('region') == OLD:
                i = n.pop('index') - 1
                n['id'] = f'{NEW}#r{i // cols + 1}c{i % cols + 1}'
                n['region'] = NEW
        for e in data.get('edges', []):   # kind-level `offers` edges (a == kind) stay: they cover every GardenBed group
            if e['rel'] != 'offers':
                for k in ('a', 'b'):
                    if e[k] == OLD:
                        e[k] = NEW
    ids = {n['id'] for n in nodes}
    if 'GardenBed@FarGarden' not in ids:
        nodes.insert(nodes.index(next(n for n in nodes if n['id'] == NEW)) + 1 if NEW in ids else len(nodes),
                     {'id': 'GardenBed@FarGarden', 'type': 'group', 'kind': 'GardenBed', 'region': 'Farm',
                      'cover': False, 'pattern': None})
    if 'Tara' not in ids:
        nodes.append({'id': 'Tara', 'type': 'unique', 'kind': 'Tara', 'region': 'Farm', 'state': {}})
    return data


if __name__ == '__main__':
    for path in sys.argv[1:]:
        with open(path) as f:
            d = migrate(json.load(f))
        with open(path, 'w') as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
            f.write('\n')
