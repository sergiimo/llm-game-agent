"""Offline tests for tools/evals (hits and misses of predictions, M0). Run: .venv/bin/python tools/test_evals.py"""
import importlib
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evals  # noqa: E402
from evals import store  # noqa: E402


class Store(unittest.TestCase):
    def setUp(self):
        store.PATH = os.path.join(tempfile.mkdtemp(), 'predictions.jsonl')
        self._enabled = store.ENABLED
        store.ENABLED = True   # writes are on only in the real tool (wf main); these tests write a temp file
        self.addCleanup(setattr, store, 'ENABLED', self._enabled)

    def test_writes_are_off_until_the_tool_enables_them(self):
        """Tests importing game code must never write the real predictions file (D187: test records found in it)."""
        store.ENABLED = False
        evals.predict('skills', 'garden.replant_all', '')
        self.assertFalse(os.path.exists(store.PATH))
        store.ENABLED = True
        evals.predict('skills', 'garden.replant_all', '')
        self.assertTrue(os.path.exists(store.PATH))

    def test_predict_then_outcome_counts(self):
        ids = [evals.predict('belief', 'pos', [0, 0]) for _ in range(3)]
        evals.outcome(ids[0], [0.1, 0], True)
        evals.outcome(ids[1], [0.2, 0], True)
        evals.outcome(ids[2], [3, 0], False)
        r = evals.report()['belief']
        self.assertEqual((r['hits'], r['misses'], r['pending'], round(r['rate'], 3)), (2, 1, 0, 0.667))
        self.assertEqual(len(r['worst']), 1)

    def test_pending_is_not_scored(self):
        evals.predict('belief', 'pos', [0, 0])
        r = evals.report()['belief']
        self.assertEqual((r['pending'], r['rate']), (1, None))

    def test_record_shortcut(self):
        evals.record('click', 'moves her', True, False, False, {'click': [10, 20]})
        self.assertEqual(evals.report()['click']['misses'], 1)

    def test_record_idempotency_key_repairs_partial_write_without_duplicates(self):
        pid = evals.record('vision', 'answer', None, {'kind': 'Well'}, True,
                           idempotency_key='experience-e1-answer')
        with open(store.PATH, 'w') as stream:
            stream.write('{"id":"%s","component":"vision","what":"answer","value":null,"ctx":{}}\n' % pid)
        self.assertEqual(evals.record('vision', 'answer', None, {'kind': 'Well'}, True,
                                      idempotency_key='experience-e1-answer'), pid)
        self.assertEqual(evals.record('vision', 'answer', None, {'kind': 'Well'}, True,
                                      idempotency_key='experience-e1-answer'), pid)
        with open(store.PATH) as stream:
            rows = [line for line in stream if line.strip()]
        self.assertEqual(len(rows), 2)

    def test_since_filters(self):
        evals.record('click', 'moves her', True, True, True)
        cut = time.time() + 0.01
        time.sleep(0.02)
        evals.record('click', 'moves her', True, False, False)
        self.assertEqual(evals.report(since=cut)['click'], {'hits': 0, 'misses': 1, 'pending': 0, 'rate': 0.0,
                                                            'worst': [{}]})

    def test_until_filters(self):                           # review #3b
        evals.record('click', 'moves her', True, True, True)
        cut = time.time() + 0.01
        time.sleep(0.02)
        evals.record('click', 'moves her', True, False, False)
        self.assertEqual(evals.report(until=cut)['click']['hits'], 1)
        self.assertEqual(evals.report(until=cut)['click']['misses'], 0)

    def test_empty_store(self):
        self.assertEqual(evals.report(), {})
        self.assertEqual(evals.format_report({}), 'no predictions yet')

    def test_survives_reload(self):
        pid = evals.predict('stuck', 'stuck', True)
        path = store.PATH
        importlib.reload(store)
        store.PATH, store.ENABLED = path, True
        evals.outcome(pid, True, True)
        self.assertEqual(evals.report()['stuck']['hits'], 1)
        self.assertIn('stuck: 1/1 hits (100%)', evals.format_report(evals.report()))

    def test_belief_rule(self):
        self.assertTrue(evals.belief_hit([0, 0], [0.6, 0.7]))
        self.assertFalse(evals.belief_hit([0, 0], [1, 1]))


if __name__ == '__main__':
    unittest.main()
