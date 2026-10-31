"""Offline tests for tools/bench (benchmark scoring, M0). Run: .venv/bin/python tools/test_bench.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
import plan  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class Bench(unittest.TestCase):
    def test_score_counts(self):
        ev = [{'t': 100, 'type': 'plan_step', 'n': '1', 'state': 'start', 'hour': 7.0},
              {'t': 101, 'type': 'call', 'start': 101, 'end': 102, 'cmd': 'py beds()'},
              {'t': 107, 'type': 'call', 'start': 107, 'end': 108, 'cmd': 'py replant(1)'},
              {'t': 108, 'type': 'stuck', 'at': ['Farm', 0, 0]},
              {'t': 109, 'type': 'interrupt', 'text': 'stuck'},
              {'t': 110, 'type': 'plan_step', 'n': '1', 'state': 'escalate', 'hour': 7.5}]
        nav = [{'t': 101.5, 'what': 'pos'}, {'t': 107.5, 'what': 'pos'}, {'t': 50, 'what': 'pos'}]
        s = bench.score(ev, nav, {'belief': {'rate': 0.9}})
        self.assertEqual((s['calls'], s['game_min'], s['readings'], s['stuck'], s['interrupts'], s['escalations'],
                          s['thinking_s']), (2, 30, 2, 1, 1, 1, 5.0))
        self.assertEqual(s['eval'], {'belief': 0.9})

    def test_score_empty_run(self):
        s = bench.score([], [], {})
        self.assertEqual((s['calls'], s['steps_total'], s['game_min']), (0, 0, 0))

    def test_upsert_replaces_same_run(self):                # review #3c
        import tempfile
        bench.RESULTS = os.path.join(tempfile.mkdtemp(), 'r.jsonl')
        bench.upsert_result({'run': 'x', 'task': 'A', 'calls': 1})
        bench.upsert_result({'run': 'y', 'task': 'B', 'calls': 2})
        bench.upsert_result({'run': 'x', 'task': 'A', 'calls': 3})
        self.assertEqual([(r['run'], r['calls']) for r in bench.results()], [('y', 2), ('x', 3)])

    def test_templates_pass_review(self):
        for x in 'ABC':
            self.assertEqual(plan.review(open(os.path.join(HERE, 'bench', f'{x}.md')).read()), [], x)


if __name__ == '__main__':
    unittest.main()
