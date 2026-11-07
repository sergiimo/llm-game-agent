"""Offline tests for tools/plan.py (task plans, L76). Run: .venv/bin/python tools/test_plan.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan  # noqa: E402
from runtime.db import Database  # noqa: E402
from runtime.run_reports import render_progress  # noqa: E402
from runtime.run_store import RunStore  # noqa: E402

PLAN = '''# Plan: VioletBeehives

- **Goal:** hand 1 honey to Violet
- **Done when:** `./wf save` lists VioletBeehives under done
- **Brief:** wiki/quests/town/meant-to-bee.md
- **Review:** ok

## Step 1: Water the wilted beds
- **Do:** `./wf routines`, then per docs/operations/routines.md R1
- **Signal:** `> water me=Player target=GardenBed` in the log
- **Done when:** R1 DONE
- **Budget:** 2 calls, 60 min
- **If stuck:** refill at the well

## Step 2: Inspect a hive
- **Do:** look at the hives,
  then `./wf do key:space`
- **Signal:** a bubble
- **Done when:** noted
- **Budget:** 10 calls
'''


class Plan(unittest.TestCase):
    def test_progress_projection_cites_canonical_step_event_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = os.path.join(directory, 'run')
            os.makedirs(run_dir)
            database = Database(os.path.join(directory, 'wf.sqlite3'))
            store = RunStore(database)
            run_id = store.start('VioletBeehives', 'hand honey to Violet', run_dir)
            event_id = store.append_event('plan_step', {'n': '1', 'state': 'start', 'text': 'watering'}, t=100)

            text = render_progress(database, run_id, PLAN, now=160)

            self.assertIn(f'event #{event_id}', text)
            self.assertIn('step 1', text)
            with open(os.path.join(run_dir, 'progress.md')) as stream:
                self.assertEqual(stream.read(), text)

    def test_parse(self):
        head, steps = plan.parse(PLAN)
        self.assertEqual(head['Goal'], 'hand 1 honey to Violet')
        self.assertEqual([s['n'] for s in steps], ['1', '2'])
        self.assertEqual(steps[0]['title'], 'Water the wilted beds')
        self.assertEqual(plan.budget(steps[0]['Budget']), (2, 60))
        self.assertEqual(plan.budget(steps[1]['Budget']), (10, None))

    def test_review(self):
        self.assertEqual(plan.review(PLAN), [])  # the command is on the Do field's continuation line
        self.assertIn('./wf do key:space', plan.parse(PLAN)[1][1]['Do'])
        self.assertEqual(plan.review(PLAN.replace('then `./wf do key:space`', 'then press it')),
                         ['step 2: Do names no ./wf command or docs/ file'])
        probs = plan.review(plan.template('X'))
        self.assertIn('header: Done when missing', probs)
        self.assertIn('step 1: Do missing', probs)

    def test_budget_and_restart(self):
        steps = plan.parse(PLAN)[1]
        ev = [{'type': 'plan_step', 'n': 1, 'state': 'start', 't': 100, 'hour': 19.0},
              {'type': 'call', 't': 110}, {'type': 'call', 't': 120}, {'type': 'call', 't': 130}]
        st = plan.steps_state(steps, ev, now=160, hour_now=20.5)
        self.assertEqual((st[0]['state'], st[0]['calls'], st[0]['game_min']), ('start', 3, 90))
        self.assertEqual(st[0]['over'], ['3/2 calls', '90/60 game min'])
        self.assertEqual(st[1]['state'], 'todo')
        ev += [{'type': 'plan_step', 'n': 1, 'state': 'escalate', 't': 140},
               {'type': 'plan_step', 'n': 1, 'state': 'start', 't': 150, 'hour': 21.0}]
        st = plan.steps_state(steps, ev, now=160, hour_now=21.2)[0]   # after the escalation: counted afresh
        self.assertEqual((st['state'], st['calls'], st['over']), ('start', 0, []))
        md = plan.progress_md('VioletBeehives', steps, plan.steps_state(steps, ev, 160, 21.2), ['18:10 step 1 start'])
        self.assertIn('| 1 | Water the wilted beds | ▶️ |', md)
        self.assertIn('- 18:10 step 1 start', md)


if __name__ == '__main__':
    unittest.main()
