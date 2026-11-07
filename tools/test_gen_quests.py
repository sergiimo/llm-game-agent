"""Quest generator preservation tests."""
from pathlib import Path
import tempfile
import unittest

import gen_quests


class QuestGenerator(unittest.TestCase):
    def test_read_front_preserves_custom_fields_verbatim(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td, 'q.md')
            raw = 'quest: Q\nru: Локализация\ncustom: keep # exactly\nstatus: active   # note'
            path.write_text(f'---\n{raw}\n---\n# Q\n')
            meta, rest, front = gen_quests.read_front(path)
            self.assertEqual(front, f'---\n{raw}\n---\n')
            self.assertEqual(meta['ru'], 'Локализация')
            self.assertEqual(rest, '# Q\n')


if __name__ == '__main__':
    unittest.main()
