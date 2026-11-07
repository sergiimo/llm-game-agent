"""Classify the offline game corpus into one topical Wiki.

The generated manifest is the sole title-to-path authority used by migration,
generators and lookup.  Classification is deterministic and has no hidden
filesystem fallback.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent.parent
OVERRIDES_PATH = Path(__file__).with_name('wiki_overrides.json')

ITEM_TYPES = [
    ('Food', 'food'), ('Crops', 'crops'), ('Seeds', 'seeds'), ('Forage', 'forage'),
    ('Fish', 'fish'), ('Crafting Ingredient', 'ingredients'),
    ('Potions Incantations', 'potions'), ('Workstation', 'workstations'),
    ('Tool', 'tools'), ('Book', 'books'), ('Item', 'misc'),
]
CHARACTER_SUFFIXES = {'Dialogues': 'dialogues.md', 'Conversations': 'conversations.md',
                      'Events': 'events.md', 'Schedule': 'schedule.md'}


def _overrides() -> dict:
    return json.loads(OVERRIDES_PATH.read_text())


def normalized_title(title: str) -> str:
    text = unicodedata.normalize('NFKD', title).replace('’', "'").lower()
    text = text.replace('&', ' and ')
    return re.sub(r'[^a-z0-9]+', '', text)


def slug(title: str) -> str:
    text = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode().lower()
    text = text.replace('&', ' and ').replace("'", '')
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-') or 'untitled'


def classify_page(title: str, text: str) -> str:
    if '__' in title:
        owner, suffix = title.rsplit('__', 1)
        if suffix in CHARACTER_SUFFIXES:
            return f'characters/{slug(owner)}/{CHARACTER_SUFFIXES[suffix]}'
    if '[Character]\n' in text:
        return f'characters/{slug(title)}/INDEX.md'
    if '[Quest]\n' in text:
        return f'quests/other/{slug(title)}.md'
    if '[Location]\n' in text:
        return f'places/{slug(title)}.md'
    for box, directory in ITEM_TYPES:
        if f'[{box}]\n' in text:
            return f'items/{directory}/{slug(title)}.md'
    overrides = _overrides()
    if title in overrides['businesses']:
        return f'businesses/{slug(title)}.md'
    if title in overrides['mechanics']:
        return f'mechanics/{slug(title)}.md'
    if title in overrides['story']:
        return f'story/{slug(title)}.md'
    return f'story/topics/{slug(title)}.md'


def _front_title(path: Path) -> str:
    text = path.read_text(errors='replace')
    match = re.search(r'^quest:\s*(.+?)\s*$', text, re.M)
    if match:
        return match.group(1)
    heading = re.search(r'^#\s+(.+?)\s*$', text, re.M)
    return heading.group(1) if heading else path.stem


def _curated_map(roots: list[str]) -> dict[str, tuple[str, str]]:
    result = {}
    for root_s in roots:
        root = Path(root_s)
        if not root.exists():
            continue
        for path in root.rglob('*.md'):
            if path.name == 'INDEX.md':
                continue
            title = _front_title(path)
            parts = path.parts
            if 'quests' in parts:
                i = parts.index('quests')
                canonical = Path('wiki', 'quests', *parts[i + 1:]).as_posix()
            elif 'mechanics' in parts:
                canonical = f'wiki/mechanics/{path.name}'
            elif 'world' in parts:
                canonical = f'wiki/{classify_page(title, path.read_text(errors="replace"))}'
            else:
                continue
            result[normalized_title(title)] = (title, canonical)
    return result


def build_manifest(imported_dir: str, curated_roots: list[str]) -> dict:
    base = Path(imported_dir)
    curated = _curated_map(curated_roots)
    pages = []
    seen_paths: dict[str, dict] = {}
    for path in sorted(base.rglob('*.md')):
        title = path.relative_to(base).with_suffix('').as_posix().replace('/', '__')
        text = path.read_text(errors='replace')
        key = normalized_title(title)
        curated_hit = curated.get(key)
        canonical = curated_hit[1] if curated_hit else 'wiki/' + classify_page(title, text)
        aliases = sorted(set([title] + ([curated_hit[0]] if curated_hit else [])))
        rel_source = path.as_posix()
        try:
            rel_source = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            pass
        prior = seen_paths.get(canonical.lower())
        if prior:
            if normalized_title(prior['title']) != key:
                raise ValueError(f"unresolved canonical collision: {prior['title']!r} and {title!r} -> {canonical}")
            prior['aliases'] = sorted(set(prior['aliases'] + aliases))
            prior['source_paths'].append(rel_source)
            prior['source'] = 'merged'
            continue
        entry = {
            'title': curated_hit[0] if curated_hit else title,
            'source_path': rel_source,
            'source_paths': [rel_source],
            'canonical_path': canonical,
            'aliases': aliases,
            'kind': canonical.split('/')[1] if '/' in canonical else 'unknown',
            'source': 'merged' if curated_hit else 'fan-wiki',
        }
        pages.append(entry)
        seen_paths[canonical.lower()] = entry
    return {'version': 1, 'source_count': sum(len(p['source_paths']) for p in pages), 'pages': pages}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('manifest')
    p.add_argument('imported_dir')
    p.add_argument('output')
    args = parser.parse_args()
    roots = [ROOT / 'docs' / name for name in ('mechanics', 'quests', 'world')]
    manifest = build_manifest(args.imported_dir, [str(p) for p in roots])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    counts = {}
    for page in manifest['pages']:
        counts[page['kind']] = counts.get(page['kind'], 0) + 1
    print(f"{manifest['source_count']} sources -> {len(manifest['pages'])} subjects: " +
          ', '.join(f'{k}={v}' for k, v in sorted(counts.items())))


if __name__ == '__main__':
    main()
