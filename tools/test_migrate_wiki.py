"""Offline integration tests for the unified Wiki materializer."""
import json
from pathlib import Path
import tempfile
import unittest

from migrate_wiki import materialize


class MigrateWiki(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        (root / 'reference/wiki').mkdir(parents=True)
        (root / 'docs/quests/town').mkdir(parents=True)
        (root / 'docs/tips.md').write_text('# Tips\n\nKeep tips\n')
        (root / 'reference/wiki/Apple.md').write_text('# Apple\n\n[Food]\n')
        (root / 'reference/wiki/Aryel__Schedule.md').write_text('# Aryel/Schedule\n\nMonday\n')
        (root / 'reference/wiki/Quest.md').write_text('# Quest\n\n[Quest]\nImported facts\n')
        (root / 'docs/quests/town/quest.md').write_text(
            '---\nquest: Quest\n---\n# Quest\n\n## Verified steps\nKeep me\n')
        manifest = {'version': 1, 'source_count': 3, 'pages': [
            {'title': 'Apple', 'source_path': 'reference/wiki/Apple.md',
             'source_paths': ['reference/wiki/Apple.md'], 'canonical_path': 'wiki/items/food/apple.md',
             'aliases': ['Apple'], 'kind': 'items', 'source': 'fan-wiki'},
            {'title': 'Aryel__Schedule', 'source_path': 'reference/wiki/Aryel__Schedule.md',
             'source_paths': ['reference/wiki/Aryel__Schedule.md'],
             'canonical_path': 'wiki/characters/aryel/schedule.md', 'aliases': ['Aryel__Schedule'],
             'kind': 'characters', 'source': 'fan-wiki'},
            {'title': 'Quest', 'source_path': 'reference/wiki/Quest.md',
             'source_paths': ['reference/wiki/Quest.md'], 'canonical_path': 'wiki/quests/town/quest.md',
             'aliases': ['Quest'], 'kind': 'quests', 'source': 'merged'},
        ]}
        path = root / 'manifest.json'
        path.write_text(json.dumps(manifest))
        return path

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.fixture(root)
            report = materialize(str(manifest), str(root), dry_run=True)
            self.assertEqual(report.sources, 3)
            self.assertFalse((root / 'wiki').exists())

    def test_materializes_merges_indexes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = self.fixture(root)
            first = materialize(str(manifest), str(root), dry_run=False)
            quest = (root / 'wiki/quests/town/quest.md').read_text()
            self.assertIn('Keep me', quest)
            self.assertIn('<!-- fan-wiki:start -->', quest)
            self.assertIn('Imported facts', quest)
            self.assertTrue((root / 'wiki/characters/aryel/schedule.md').exists())
            self.assertIn('apple.md', (root / 'wiki/items/food/INDEX.md').read_text())
            self.assertIn('CC BY-SA 3.0', (root / 'wiki/ATTRIBUTION.md').read_text())
            self.assertIn('Keep tips', (root / 'wiki/tips/INDEX.md').read_text())
            second = materialize(str(manifest), str(root), dry_run=False)
            self.assertEqual(first.unresolved, 0)
            self.assertEqual(second.unresolved, 0)
            self.assertEqual(quest, (root / 'wiki/quests/town/quest.md').read_text())
            self.assertIn('schedule.md', (root / 'wiki/characters/aryel/INDEX.md').read_text())
            self.assertIn('Keep tips', (root / 'wiki/tips/INDEX.md').read_text())
            saved = json.loads(manifest.read_text())
            saved['pages'][0]['source_paths'] = ['wiki/items/food/apple.md']
            manifest.write_text(json.dumps(saved))
            apple = (root / 'wiki/items/food/apple.md').read_text()
            materialize(str(manifest), str(root), dry_run=False)
            self.assertEqual(apple, (root / 'wiki/items/food/apple.md').read_text())

    def test_reclassifies_a_generic_item_out_of_story(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'reference/wiki').mkdir(parents=True)
            (root / 'reference/wiki/Blue Jacket.md').write_text('# Blue Jacket\n\n[Item]\n')
            manifest = {'version': 1, 'source_count': 1, 'pages': [{
                'title': 'Blue Jacket', 'source_path': 'reference/wiki/Blue Jacket.md',
                'source_paths': ['reference/wiki/Blue Jacket.md'],
                'canonical_path': 'wiki/story/topics/blue-jacket.md', 'aliases': ['Blue Jacket'],
                'kind': 'story', 'source': 'fan-wiki'}]}
            path = root / 'manifest.json'
            path.write_text(json.dumps(manifest))
            materialize(str(path), str(root), dry_run=False)
            self.assertTrue((root / 'wiki/items/misc/blue-jacket.md').exists())
            self.assertFalse((root / 'wiki/story/topics/blue-jacket.md').exists())
            saved = json.loads(path.read_text())
            self.assertEqual(saved['pages'][0]['canonical_path'], 'wiki/items/misc/blue-jacket.md')


if __name__ == '__main__':
    unittest.main()
