"""Verify disposition evidence for the deleted chronological learning ledger."""
from pathlib import Path
import json, re, subprocess

ROOT=Path(__file__).resolve().parent.parent
EVIDENCE=ROOT/'docs/migrations/2026-11-07-learning-disposition.json'


def audit(root: Path=ROOT) -> list[str]:
    data=json.loads((root/EVIDENCE.relative_to(ROOT)).read_text()); issues=[]
    source=subprocess.check_output(['git','show',f"{data['source_commit']}:docs/learnings.md"],cwd=root,text=True)
    expected=set(re.findall(r'^\| (L\d+) \|',source,re.M)); rows=data['entries']; actual=[r['id'] for r in rows]
    if len(actual)!=len(set(actual)): issues.append('duplicate learning IDs')
    if set(actual)!=expected: issues.append(f'learning IDs differ: expected {len(expected)}, got {len(set(actual))}')
    for row in rows:
        if row.get('status') not in {'integrated','superseded','historical'} or not row.get('resolution'): issues.append(f'invalid disposition: {row.get("id")}')
    return issues


if __name__ == '__main__':
    found=audit(); print('\n'.join(found) if found else 'learning dispositions: ok'); raise SystemExit(bool(found))
