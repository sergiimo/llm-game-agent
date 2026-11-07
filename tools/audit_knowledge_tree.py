"""Permanent integrity gate for the unified Wiki and current Docs."""
from pathlib import Path
import json, re

ROOT = Path(__file__).resolve().parent.parent
LEGACY = re.compile(r'docs/learnings\.md|reference/wiki|docs/(?:mechanics|quests|world|tips\.md)')


def audit(root: Path = ROOT) -> list[str]:
    issues=[]; wiki=root/'wiki'; docs=root/'docs'
    current=[p for base in (wiki,docs,root/'.claude') for p in base.rglob('*.md') if 'superpowers' not in p.parts]
    for p in current:
        text=p.read_text(errors='replace')
        if LEGACY.search(text): issues.append(f'legacy path: {p}')
        for target in re.findall(r'\[[^]]*\]\(([^)#]+)', text):
            if '://' not in target and not (p.parent/target).resolve().exists(): issues.append(f'broken link: {p} -> {target}')
    manifest=json.loads((wiki/'manifest.json').read_text()); seen={(wiki/'INDEX.md').resolve()}; todo=list(seen)
    while todo:
        p=todo.pop()
        if not p.exists(): continue
        for target in re.findall(r'\[[^]]*\]\(([^)#]+)',p.read_text(errors='replace')):
            if '://' in target: continue
            q=(p.parent/target).resolve()
            try:q.relative_to(wiki.resolve())
            except ValueError:continue
            if q.is_dir():q=q/'INDEX.md'
            if q not in seen:seen.add(q);todo.append(q)
    for page in manifest['pages']:
        if (root/page['canonical_path']).resolve() not in seen: issues.append(f'unreachable: {page["canonical_path"]}')
    return issues


if __name__ == '__main__':
    found=audit(); print('\n'.join(found) if found else 'knowledge tree: ok'); raise SystemExit(bool(found))
