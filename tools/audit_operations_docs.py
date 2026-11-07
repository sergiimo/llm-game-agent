"""Check current operations docs against the CLI command surface and filesystem."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent.parent


def audit(root: Path=ROOT) -> list[str]:
    issues=[]; source=(root/'tools/wf.py').read_text(errors='replace')
    commands=set(re.findall(r"add_parser\(['\"]([^'\"]+)",source))
    for page in (root/'docs').rglob('*.md'):
        if 'superpowers' in page.parts: continue
        text=page.read_text(errors='replace')
        for command in re.findall(r'\./wf\s+([a-z][\w-]*)',text):
            if command not in commands and command not in {'stop'}: issues.append(f'unknown command {command}: {page}')
    return sorted(set(issues))


if __name__ == '__main__':
    found=audit(); print('\n'.join(found) if found else 'operations docs: ok'); raise SystemExit(bool(found))
