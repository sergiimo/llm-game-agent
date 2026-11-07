import unittest
from audit_knowledge_tree import audit as knowledge
from audit_operations_docs import audit as operations
from audit_learnings import audit as learnings

class Audits(unittest.TestCase):
    def test_repository_gates(self):
        self.assertEqual(knowledge(), [])
        self.assertEqual(operations(), [])
        self.assertEqual(learnings(), [])

if __name__ == '__main__': unittest.main()
