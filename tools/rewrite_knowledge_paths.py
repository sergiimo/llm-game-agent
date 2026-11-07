"""Mechanically rewrite live knowledge-tree references after Wiki migration."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent.parent
manifest = json.loads((ROOT / 'wiki/manifest.json').read_text())
aliases = {}
for page in manifest['pages']:
    for alias in page['aliases']:
        aliases[alias + '.md'] = page['canonical_path']

REPLACEMENTS = {
    'wiki/mechanics/': 'wiki/mechanics/', 'wiki/quests/': 'wiki/quests/',
    'wiki/places/locations.md': 'wiki/places/locations.md',
    'wiki/businesses/INDEX.md': 'wiki/businesses/INDEX.md',
    'wiki/characters/INDEX.md': 'wiki/characters/INDEX.md',
    'wiki/': 'wiki/', 'wiki/tips/INDEX.md': 'wiki/tips/INDEX.md',
    'docs/operations/actions.md': 'docs/operations/actions.md',
    'docs/operations/routines.md': 'docs/operations/routines.md',
    'docs/architecture/self-improvement.md': 'docs/architecture/self-improvement.md',
}


def rewrite(text: str) -> str:
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    def wiki_ref(match):
        name = match.group(1)
        return aliases.get(name, match.group(0))
    return re.sub(r'reference/wiki/([^`\n]+?\.md)', wiki_ref, text)


for base in ('AGENTS.md', 'README.md', '.claude', 'tools', 'docs/ui', 'docs/operations',
             'docs/architecture', 'docs/troubleshooting', 'docs/testing', 'wiki'):
    path = ROOT / base
    files = [path] if path.is_file() else path.rglob('*')
    for file in files:
        if file.is_file() and file.suffix in {'.md', '.py', '.json'} and 'superpowers' not in file.parts:
            old = file.read_text(errors='replace')
            new = rewrite(old)
            if new != old:
                file.write_text(new)
