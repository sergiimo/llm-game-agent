"""Regression tests for the removed repository-wide progress file."""
from pathlib import Path
import tempfile
import unittest

from audit_knowledge_tree import global_progress_refs


class ProgressReferences(unittest.TestCase):
    def test_detects_global_progress_reference_but_allows_run_local_progress(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'docs').mkdir()
            (root / 'docs/current.md').write_text('Read docs/progress.md\nUse runs/x/progress.md\n')
            self.assertEqual(global_progress_refs(root), ['global progress reference: docs/current.md'])


if __name__ == '__main__':
    unittest.main()
