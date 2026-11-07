"""Offline tests for manifest plus curated Wiki title lookup."""
import json
from pathlib import Path
import tempfile
import unittest

from wiki_layout import search_catalog


class WikiSearch(unittest.TestCase):
    def test_normalizes_alias_punctuation_and_includes_curated_pages(self):
        with tempfile.TemporaryDirectory() as td:
            wiki = Path(td)
            (wiki / 'businesses').mkdir()
            (wiki / 'mechanics').mkdir()
            (wiki / 'businesses/kai.md').write_text('# Kai\'s Treasures\n')
            (wiki / 'mechanics/energy.md').write_text('# Energy\n')
            manifest = {'pages': [{'aliases': ["Kai's Treasures"],
                                   'canonical_path': 'wiki/businesses/kai.md'}]}
            self.assertEqual(search_catalog(wiki, manifest, 'Kai’s Treasures')[0], 'businesses/kai.md')
            self.assertEqual(search_catalog(wiki, manifest, 'energy')[0], 'mechanics/energy.md')


if __name__ == '__main__':
    unittest.main()
