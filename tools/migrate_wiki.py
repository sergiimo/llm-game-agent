"""Materialize the manifest-backed topical Wiki."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil

from wiki_layout import classify_page


@dataclass
class MigrationReport:
    sources: int = 0
    moved: int = 0
    merged: int = 0
    indexed: int = 0
    unresolved: int = 0


ITEM_INDEX_DIRS = {
    'food-and-drink': 'food', 'crafting-ingredients': 'ingredients',
    'potions-and-incantations': 'potions', 'misc-items': 'misc',
    'crops': 'crops', 'seeds': 'seeds', 'forage': 'forage', 'fish': 'fish',
    'tools': 'tools', 'workstations': 'workstations', 'books': 'books',
}


def _copy_curated(root: Path) -> None:
    mappings = [(root / 'docs/mechanics', root / 'wiki/mechanics'),
                (root / 'docs/quests', root / 'wiki/quests')]
    for source, destination in mappings:
        if not source.exists():
            continue
        for path in source.rglob('*.md'):
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(path, target)
    tips = root / 'docs/tips.md'
    if tips.exists():
        target = root / 'wiki/tips/INDEX.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(tips, target)
    world = root / 'docs/world'
    fixed = {'characters.md': 'wiki/characters/INDEX.md',
             'businesses.md': 'wiki/businesses/INDEX.md',
             'locations.md': 'wiki/places/locations.md',
             'overview.md': 'wiki/places/overview.md'}
    if world.exists():
        for name, rel in fixed.items():
            source = world / name
            target = root / rel
            if source.exists() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for source in (world / 'items').glob('*.md') if (world / 'items').exists() else []:
            directory = ITEM_INDEX_DIRS.get(source.stem, source.stem)
            target = root / f'wiki/items/{directory}/INDEX.md'
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)


def _import_text(root: Path, entry: dict) -> str | None:
    chunks = []
    for rel in entry.get('source_paths') or [entry['source_path']]:
        source = root / rel
        if source.exists():
            chunks.append(source.read_text(errors='replace').rstrip())
    return '\n\n---\n\n'.join(chunks) if chunks else None


def _write_indexes(wiki: Path) -> int:
    count = 0
    for directory in sorted([wiki] + [p for p in wiki.rglob('*') if p.is_dir()], reverse=True):
        index = directory / 'INDEX.md'
        children = sorted(p for p in directory.iterdir() if p.name not in {'INDEX.md', 'manifest.json', 'ATTRIBUTION.md'})
        if not children:
            continue
        title = 'Wylde Flowers Wiki' if directory == wiki else directory.name.replace('-', ' ').title()
        links = []
        for child in children:
            label = child.name.replace('.md', '').replace('-', ' ').replace('_', ' ').title()
            target = child.name + '/INDEX.md' if child.is_dir() else child.name
            links.append(f'- [{label}]({target})')
        if index.exists():
            current = index.read_text(errors='replace')
            if '> **Summary:** Browse this topic through the grouped links below.' in current:
                lines = [f'# {title}', '', '> **Summary:** Browse this topic through the grouped links below.', ''] + links
                index.write_text('\n'.join(lines) + '\n')
            else:
                missing = [line for line in links if f']({line.rsplit("(", 1)[1]}' not in current]
                start, end = '<!-- pages:start -->', '<!-- pages:end -->'
                block = start + '\n## Detailed pages\n\n' + '\n'.join(missing) + '\n' + end
                if start in current:
                    before, rest = current.split(start, 1)
                    _, after = rest.split(end, 1)
                    current = before.rstrip() + '\n\n' + block + after
                else:
                    current = current.rstrip() + '\n\n' + block + '\n'
                index.write_text(current)
        else:
            lines = [f'# {title}', '', '> **Summary:** Browse this topic through the grouped links below.', ''] + links
            index.write_text('\n'.join(lines) + '\n')
        count += 1
    return count


def _reclassify_materialized(manifest: dict, manifest_path: Path, base: Path) -> int:
    moved = 0
    for entry in manifest['pages']:
        old = base / entry['canonical_path']
        if not old.exists() or not entry['canonical_path'].startswith('wiki/story/topics/'):
            continue
        new_rel = 'wiki/' + classify_page(entry['title'], old.read_text(errors='replace'))
        if new_rel == entry['canonical_path']:
            continue
        new = base / new_rel
        new.parent.mkdir(parents=True, exist_ok=True)
        if new.exists():
            raise ValueError(f'reclassification collision: {old} -> {new}')
        old.replace(new)
        entry['canonical_path'] = new_rel
        entry['kind'] = new_rel.split('/')[1]
        moved += 1
    if moved:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return moved


def materialize(manifest_path: str, root: str, dry_run: bool = True) -> MigrationReport:
    base = Path(root).resolve()
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text())
    report = MigrationReport(sources=manifest.get('source_count', len(manifest['pages'])))
    if dry_run:
        for entry in manifest['pages']:
            destination = (base / entry['canonical_path']).resolve()
            if base not in destination.parents or 'wiki' not in destination.relative_to(base).parts[:1]:
                report.unresolved += 1
        return report

    wiki = base / 'wiki'
    wiki.mkdir(parents=True, exist_ok=True)
    _copy_curated(base)
    for entry in manifest['pages']:
        destination = (base / entry['canonical_path']).resolve()
        if base not in destination.parents or destination.relative_to(base).parts[0] != 'wiki':
            report.unresolved += 1
            continue
        imported = _import_text(base, entry)
        if destination.exists():
            if imported:
                current = destination.read_text(errors='replace')
                if '<!-- fan-wiki:start -->' not in current:
                    destination.write_text(current.rstrip() + '\n\n## Fan wiki article\n\n'
                                           '<!-- fan-wiki:start -->\n' + imported +
                                           '\n<!-- fan-wiki:end -->\n')
                    report.merged += 1
            continue
        if imported is None:
            report.unresolved += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('> **Summary:** Fan-wiki-derived game reference.\n\n'
                               '> **Source:** Wylde Flowers Wiki on Fandom, CC BY-SA 3.0.\n\n' + imported + '\n')
        report.moved += 1
    if report.unresolved:
        return report
    report.moved += _reclassify_materialized(manifest, manifest_file, base)
    (wiki / 'ATTRIBUTION.md').write_text(
        '# Attribution\n\n> **Summary:** Licensing and provenance for imported game-reference content.\n\n'
        'Fan-wiki-derived pages originated from the Wylde Flowers Wiki on Fandom and are used under '
        '[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). Local verified notes and '
        'agent-operation documentation are repository-authored.\n')
    report.indexed = _write_indexes(wiki)
    # Delete only after every manifest destination was produced.
    for source in (base / 'reference/wiki', base / 'docs/mechanics', base / 'docs/quests', base / 'docs/world'):
        if source.exists():
            shutil.rmtree(source)
    tips = base / 'docs/tips.md'
    if tips.exists():
        tips.unlink()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    report = materialize(args.manifest, str(Path(__file__).resolve().parent.parent), dry_run=args.dry_run)
    print(json.dumps(report.__dict__, sort_keys=True))
    if report.unresolved:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
