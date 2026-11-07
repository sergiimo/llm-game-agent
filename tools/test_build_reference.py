"""Unified Wiki importer tests."""
import json
from pathlib import Path
import tempfile
import unittest

from build_reference import import_reference


class BuildReference(unittest.TestCase):
    def test_import_classifies_page_and_updates_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); raw = root / 'raw'; raw.mkdir()
            (raw / 'Blue Jacket.wiki').write_text('[Item]\n  itemName: Blue Jacket\n')
            count = import_reference(raw, root)
            self.assertEqual(count, 1)
            self.assertTrue((root / 'wiki/items/misc/blue-jacket.md').exists())
            manifest = json.loads((root / 'wiki/manifest.json').read_text())
            self.assertEqual(manifest['pages'][0]['canonical_path'], 'wiki/items/misc/blue-jacket.md')


if __name__ == '__main__':
    unittest.main()
