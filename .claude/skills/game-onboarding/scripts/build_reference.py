"""Rebuild reference/wiki/*.md from a directory of raw .wiki files (fandom API dump)."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wikiclean import clean  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for f in glob.glob(os.path.join(src, '*.wiki')):
    name = os.path.basename(f)[:-5]
    with open(os.path.join(dst, name + '.md'), 'w') as out:
        out.write('# ' + name.replace('__', '/') + '\n\n' + clean(open(f).read()))
