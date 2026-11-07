import unittest
from audit_knowledge_tree import audit as knowledge
from audit_operations_docs import audit as operations

class Audits(unittest.TestCase):
    def test_repository_gates(self):
        self.assertEqual(knowledge(), [])
        self.assertEqual(operations(), [])

if __name__ == '__main__': unittest.main()
