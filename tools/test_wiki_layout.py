"""Offline tests for unified Wiki classification."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from wiki_layout import build_manifest, classify_page, normalized_title


class WikiLayout(unittest.TestCase):
    def test_specific_infobox_wins_over_generic_item(self):
        self.assertEqual(classify_page('Apple Pie', '[Item]\n[Food]\n'), 'items/food/apple-pie.md')

    def test_generic_item_has_a_browsable_item_home(self):
        self.assertEqual(classify_page('Blue Jacket', '[Item]\n'), 'items/misc/blue-jacket.md')

    def test_character_and_subpages_share_directory(self):
        self.assertEqual(classify_page('Amira Syed', '[Character]\n'), 'characters/amira-syed/INDEX.md')
        self.assertEqual(classify_page('Amira Syed__Schedule', ''), 'characters/amira-syed/schedule.md')

    def test_topical_kinds(self):
        cases = {
            'Quest Name': ('[Quest]\n', 'quests/other/quest-name.md'),
            'Farm': ('[Location]\n', 'places/farm.md'),
            'Dahl General Store': ('', 'businesses/dahl-general-store.md'),
            'Fishing': ('', 'mechanics/fishing.md'),
            'Achievements': ('', 'story/achievements.md'),
            'Odd Lore': ('', 'story/topics/odd-lore.md'),
        }
        for title, (body, expected) in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classify_page(title, body), expected)

    def test_normalization_folds_unicode_punctuation(self):
        self.assertEqual(normalized_title("Kai’s Treasures"), normalized_title("Kai's Treasures"))
        self.assertEqual(normalized_title('Oh, Chute!'), normalized_title('Oh Chute'))

    def test_curated_quest_wins_and_alias_is_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            imported = os.path.join(td, 'reference', 'wiki')
            curated = os.path.join(td, 'docs', 'quests', 'town')
            os.makedirs(imported)
            os.makedirs(curated)
            Path(imported, 'Oh, Chute!.md').write_text('# Oh, Chute!\n\n[Quest]\n')
            Path(curated, 'oh-chute.md').write_text('---\nquest: Oh Chute\n---\n# Oh Chute\n')
            manifest = build_manifest(imported, [os.path.join(td, 'docs', 'quests')])
            entry = manifest['pages'][0]
            self.assertEqual(entry['canonical_path'], 'wiki/quests/town/oh-chute.md')
            self.assertEqual(entry['source'], 'merged')
            self.assertIn('Oh, Chute!', entry['aliases'])

    def test_manifest_merges_normalized_alias_titles(self):
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'wiki'))
            Path(td, 'wiki', 'A!.md').write_text('# A!\n')
            Path(td, 'wiki', 'A.md').write_text('# A\n')
            manifest = build_manifest(os.path.join(td, 'wiki'), [])
            self.assertEqual(len(manifest['pages']), 1)
            self.assertEqual(manifest['pages'][0]['aliases'], ['A', 'A!'])
            self.assertEqual(len(manifest['pages'][0]['source_paths']), 2)


if __name__ == '__main__':
    unittest.main()
