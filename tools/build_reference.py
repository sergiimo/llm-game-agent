"""Import raw Fandom pages directly into the manifest-backed topical Wiki."""
from __future__ import annotations
import argparse
import json
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wikiclean import clean
from wiki_layout import classify_page, normalized_title


def import_reference(raw_dir: Path, root: Path) -> int:
    wiki = root / 'wiki'; wiki.mkdir(parents=True, exist_ok=True)
    manifest_path = wiki / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'version': 1, 'source_count': 0, 'pages': []}
    subjects = {normalized_title(a): p for p in manifest['pages'] for a in p.get('aliases', [])}
    count = 0
    for source in sorted(raw_dir.glob('*.wiki')):
        title = source.stem
        body = '# ' + title.replace('__', '/') + '\n\n' + clean(source.read_text())
        page = subjects.get(normalized_title(title))
        canonical = page['canonical_path'] if page else 'wiki/' + classify_page(title, body)
        target = root / canonical; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and '<!-- fan-wiki:start -->' not in target.read_text(errors='replace'):
            target.write_text(target.read_text().rstrip() + '\n\n<!-- fan-wiki:start -->\n' + body + '\n<!-- fan-wiki:end -->\n')
        elif not target.exists():
            target.write_text('> **Source:** Wylde Flowers Wiki on Fandom, CC BY-SA 3.0.\n\n' + body)
        if page:
            page['aliases'] = sorted(set(page['aliases'] + [title])); page.setdefault('source_paths', []).append(source.as_posix()); page['source'] = 'merged'
        else:
            page = {'title': title, 'source_path': source.as_posix(), 'source_paths': [source.as_posix()], 'canonical_path': canonical, 'aliases': [title], 'kind': canonical.split('/')[1], 'source': 'fan-wiki'}
            manifest['pages'].append(page); subjects[normalized_title(title)] = page
        count += 1
    manifest['source_count'] = sum(len(p.get('source_paths', [])) for p in manifest['pages'])
    manifest['pages'].sort(key=lambda p: p['canonical_path'])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return count


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('raw_dir', type=Path); parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(); print(f'imported {import_reference(args.raw_dir, args.root)} pages')


if __name__ == '__main__': main()
