"""Tests for tools/runwatch.py (the supervisor's live watcher). Run: .venv/bin/python -m unittest tools/test_runwatch.py"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runwatch as RW  # noqa: E402

PAUSED = ['Game Paused', 'Game progress is saved automatically while', 'you play.', 'Resume Game']


def click(pt, what='explore', mode='gameplay', texts=(), events=(), after=(), moved=True, **kw):
    return dict(type='click', pt=list(pt), what=what, mode=mode, texts=list(texts), events=list(events),
                after=list(after), moved=moved, **kw)


class Rules(unittest.TestCase):
    """Each rule catches one failure of the live runs D185-D186."""

    def levels(self, rows):
        w = RW.Watch()
        return [(lv, msg) for r in rows for lv, msg in w.feed(r) if lv != 'INFO']

    def test_a_forage_step_without_proof_is_a_note_and_a_proven_one_info(self):   # spec §13: vision answers
        out = self.levels([{'type': 'forage', 'job': 'rock', 'pt': [1320, 371], 'result': 'no bubble', 'hits': 0},
                           {'type': 'forage', 'job': 'rock', 'pt': [1320, 371], 'result': 'destroying', 'hits': 2,
                            'object': 'StoneRock'}])
        self.assertEqual([lv for lv, _ in out], ['NOTE'])
        self.assertIn('no bubble', out[0][1])

    def test_arrival_misses_in_a_row_are_a_stop(self):   # live D188 12:31 (S40): 15+ clicks lost, only ALERTs
        miss = {'type': 'predict', 'component': 'nav', 'what': 'arrive', 'expected': 'GardenBed', 'got': [], 'hit': False}
        out = self.levels([miss] * RW.MISS_STOP)
        self.assertEqual([lv for lv, _ in out], ['ALERT'] * (RW.MISS_STOP - 1) + ['STOP'], out)
        hit = dict(miss, hit=True, got=['pickup @1,1'])
        self.assertNotIn('STOP', [lv for lv, _ in self.levels([miss] * (RW.MISS_STOP - 1) + [hit, miss])])

    def test_a_lost_trace_is_a_stop(self):
        out = self.levels([{'type': 'seek', 'what': 'trace', 'msg': 'LOST: 6 walks without an event or a bubble'}])
        self.assertEqual(out[0][0], 'STOP')

    def test_a_click_on_the_pause_menu_is_a_stop(self):   # attempt 4: the game exited
        out = self.levels([click((960, 840), mode='overlay', texts=PAUSED, moved=False)])
        self.assertEqual(out[0][0], 'STOP')
        self.assertIn('pause menu', out[0][1])

    def test_a_close_that_leaves_the_pause_menu_is_a_stop(self):
        out = self.levels([{'type': 'action', 'name': 'ui.close', 'ok': True,
                            'after': 'overlay: Game Paused / Game progress is saved automatically while / you play.'}])
        self.assertEqual(out[0][0], 'STOP')

    def test_a_graph_step_from_a_look_alike_node_is_an_alert(self):   # attempt 2: walked away from the beds
        out = self.levels([{'type': 'seek', 'what': 'graph', 'here': 'GardenBed@Garden', 'to': 'GardenSouth',
                            'dir': [0.17, 0.99]}])
        self.assertEqual(out[0][0], 'ALERT')
        self.assertIn('look-alike', out[0][1])

    def test_a_graph_step_from_an_area_is_info(self):
        self.assertEqual(self.levels([{'type': 'seek', 'what': 'graph', 'here': 'Garden', 'to': 'GardenSouth',
                                       'dir': [0.17, 0.99]}]), [])

    def test_a_prediction_miss_is_an_alert(self):   # attempts 2-3: empty bed read as unplant
        out = self.levels([{'type': 'predict', 'component': 'engine', 'what': 'bubble', 'expected': {'kind': 'plant'},
                            'got': ['unplant*'], 'hit': False}])
        self.assertEqual(out[0][0], 'ALERT')
        self.assertIn('unplant', out[0][1])

    def test_a_failed_pick_and_a_junk_icon_name_are_alerts(self):   # attempt 3: 'ılbs'
        out = self.levels([{'type': 'learn', 'what': 'item_icon', 'name': 'ılbs'},
                           {'type': 'action', 'name': 'ui.pick_card', 'args': 'Tulip', 'ok': False,
                            'why': 'no "Tulip" among 1 cards'}])
        self.assertEqual([lv for lv, _ in out], ['ALERT', 'ALERT'])
        self.assertEqual(self.levels([{'type': 'learn', 'what': 'item_icon', 'name': 'Tulip_Bulbs'}]), [])

    def test_a_plant_line_without_its_proof_is_a_note(self):   # attempt 3: the cancelled panel
        out = self.levels([{'type': 'game', 'line': '[D186 7:30:05 AM] > plant me=Player target=GardenBed(Clone) '
                                                    'at (10.14, 0.10, -59.36)'},
                           {'type': 'game', 'line': '[D186 7:30:23 AM] InventoryMenuViewModel closed without result, '
                                                    'cancelling performance.'}])
        self.assertEqual(out[0][0], 'NOTE')
        proved = self.levels([{'type': 'game', 'line': '[D186 10:44:35 AM] > plant me=Player target=GardenBed(Clone) '
                                                       'at (10.14, 0.10, -63.11)'},
                              {'type': 'game', 'line': '[D186 10:45:38 AM] [STATS] totalPlanted.TulipSeed = 105'},
                              {'type': 'game', 'line': '[D186 10:45:59 AM] > water me=Player target=GardenBed(Clone) '
                                                       'at (10.14, 0.10, -63.11)'}])
        self.assertEqual(proved, [])   # the live order: `> plant` on opening, totalPlanted after Space

    def test_stuck_and_vision_are_notes(self):
        out = self.levels([{'type': 'seek', 'what': 'trace', 'msg': 'STUCK: 3 clicks in a row did not move her'},
                           {'type': 'vision', 'what': 'ask', 'kind': 'click', 'question': 'Goal plant: no bubble'}])
        self.assertEqual([lv for lv, _ in out], ['NOTE', 'NOTE'])

    def test_perception_is_reported_separately_from_model_vision(self):
        w = RW.Watch()
        row = {'type': 'perception', 'source': 'object_heatmap',
               'detections': [{'kind': 'GardenBed', 'pt': [400, 300]}]}
        self.assertEqual(w.feed(row), [('INFO', 'perception object_heatmap: GardenBed@400,300')])
        self.assertIn('perception object_heatmap', RW.trace_lines([dict(row, t=1.0)])[0])
        self.assertEqual(RW.times([dict(row, t=1.0)])[0]['vision'], 0)

    def test_an_engine_stop_that_is_not_done_is_an_alert(self):
        out = self.levels([{'type': 'engine', 'goal': 'plant', 'done': 0, 'left': 11, 'clicks': 4, 'vision': 0,
                            'stop': 'missing TulipSeed'}])
        self.assertEqual(out[0][0], 'ALERT')
        self.assertEqual(self.levels([{'type': 'engine', 'goal': 'plant', 'done': 12, 'left': 0, 'clicks': 14,
                                       'vision': 0, 'stop': 'done: query empty'}]), [])

    def test_the_watcher_flags_a_red_flag_stop(self):
        out = self.levels([{'type': 'engine', 'goal': 'harvest', 'done': 0, 'left': 3, 'clicks': 1,
                            'vision': 0, 'stop': 'RED FLAG: wrong event'}])
        self.assertEqual(out[0][0], 'STOP')

    def test_every_click_gets_a_short_info_line(self):
        w = RW.Watch()
        (lv, msg), = w.feed(click((968, 484), what='bubble', mode='overlay', texts=['Inventory', 'Seeds'],
                                  events=['plant'], after=[]))
        self.assertEqual(lv, 'INFO')
        self.assertIn('bubble @968,484', msg)
        self.assertIn('plant', msg)

    def test_the_game_process_gone_is_a_stop(self):
        w = RW.Watch(alive=lambda: False)
        self.assertEqual(w.health()[0][0], 'STOP')
        self.assertEqual(RW.Watch(alive=lambda: True).health(), [])


class Report(unittest.TestCase):
    def test_report_splits_attempts_and_counts(self):
        rows = [{'type': 'plan_step', 'n': '1', 'state': 'start'},
                click((1, 1), moved=True), click((2, 2), moved=False),
                {'type': 'predict', 'component': 'nav', 'what': 'arrive', 'hit': True, 'got': [], 'expected': 'GardenBed'},
                {'type': 'engine', 'goal': 'plant', 'done': 0, 'left': 12, 'clicks': 2, 'vision': 1, 'stop': None},
                {'type': 'plan_step', 'n': '1', 'state': 'start'},
                click((3, 3), mode='overlay', texts=PAUSED, moved=False)]
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'log.jsonl')
        with open(p, 'w') as f:
            f.write('\n'.join(json.dumps(r) for r in rows) + '\n')
        md = RW.report(p)
        self.assertIn('| 1 | 2 | 1 | 1 | 1/0 | 0 | 0 |', md)
        self.assertIn('| 2 | 1 | 0 | 1 | 0/0 | 0 | 1 |', md)

    def test_report_proves_garden_target_coverage_from_the_latest_summary(self):
        rows = [
            {'type': 'garden_visit', 'node': 'bed-a', 'status': 'visited', 'actions': ['water']},
            {'type': 'garden_summary', 'region': 'GardenSouth', 'targets': ['bed-a', 'bed-b'],
             'covered': ['bed-a'], 'unresolved': [], 'stop': 'NEED_VISION click'},
            {'type': 'garden_visit', 'node': 'bed-b', 'status': 'visited', 'actions': ['info_growing']},
            {'type': 'garden_summary', 'region': 'GardenSouth', 'targets': ['bed-a', 'bed-b'],
             'covered': ['bed-a', 'bed-b'], 'unresolved': [], 'stop': 'done: all beds visited'},
        ]
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'log.jsonl')
        with open(p, 'w') as f:
            f.write('\n'.join(json.dumps(r) for r in rows) + '\n')

        md = RW.report(p)

        self.assertIn('## Garden coverage', md)
        self.assertIn('| GardenSouth | 2 | 2 | 0 | - | - | COMPLETE |', md)

    def test_report_names_each_exact_garden_constraint(self):
        rows = [
            {'type': 'garden_visit', 'node': 'bed-a', 'status': 'visited', 'actions': ['water']},
            {'type': 'garden_visit', 'node': 'bed-b', 'status': 'unresolved', 'actions': ['pick'],
             'reason': 'missing TulipSeed'},
            {'type': 'garden_summary', 'region': 'GardenSouth', 'targets': ['bed-a', 'bed-b'],
             'covered': ['bed-a'], 'unresolved': ['bed-b'], 'stop': 'unresolved: 1 of 2 beds'},
        ]
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'log.jsonl')
        with open(p, 'w') as f:
            f.write('\n'.join(json.dumps(r) for r in rows) + '\n')

        md = RW.report(p)

        self.assertIn('bed-b: missing TulipSeed', md)
        self.assertIn('| CONSTRAINED |', md)


class Time(unittest.TestCase):
    """User D189: "do we record time we spend? or action timestamps, and thinking"; "it was standing doing nothing
    for too long, so we should be able to spot that"."""

    def test_no_action_for_too_long_while_the_game_runs_is_an_alert(self):
        w = RW.Watch(alive=lambda: True)
        w.feed({'t': 100.0, 'type': 'call', 'start': 99.0, 'end': 100.0, 'cmd': 'achieve harvest'})
        self.assertEqual(w.idle(100.0 + RW.IDLE_S - 1), [])
        out = w.idle(100.0 + RW.IDLE_S + 5)
        self.assertEqual(out[0][0], 'ALERT')
        self.assertIn('idle', out[0][1])
        self.assertEqual(w.idle(100.0 + RW.IDLE_S + 9), [])   # once per idle stretch

    def test_a_paused_game_is_not_idle(self):
        w = RW.Watch(alive=lambda: True)
        w.feed({'t': 100.0, 'type': 'call', 'start': 99.0, 'end': 100.0, 'cmd': 'pause'})
        self.assertEqual(w.idle(100.0 + RW.IDLE_S * 10), [])

    def test_times_per_attempt_split_calls_thinking_game_minutes_and_picks(self):
        rows = [{'t': 0, 'type': 'plan_step', 'n': '1', 'state': 'start'},
                {'t': 10, 'type': 'call', 'start': 10, 'end': 70, 'cmd': 'achieve harvest'},
                {'t': 20, 'type': 'click', 'pt': [1, 1], 'gt': 'D189 8:30:00 AM'},
                {'t': 190, 'type': 'call', 'start': 190, 'end': 200, 'cmd': 'achieve harvest answer=Q6'},
                {'t': 199, 'type': 'click', 'pt': [2, 2], 'gt': 'D189 9:10:00 AM'},
                {'t': 200, 'type': 'vision', 'kind': 'click', 'question': 'q'}]
        lines = ['[D189 8:31:00 AM] > harvest me=Player target=GardenBed(Clone) at (0.84, 0.10, -29.09)',
                 '[D189 9:20:00 AM] > harvest me=Player target=GardenBed(Clone) at (3.34, 0.10, -29.09)']
        a, = RW.times(rows, lines)
        self.assertEqual((a['calls'], a['clicks'], a['vision'], a['picks']), (2, 2, 1, 1))
        self.assertAlmostEqual(a['in_calls_min'], 70 / 60, 2)
        self.assertAlmostEqual(a['think_min'], 120 / 60, 2)        # the gap 70 -> 190
        self.assertAlmostEqual(a['longest_think_s'], 120, 1)
        self.assertEqual(a['game_min'], 40)


class Trace(unittest.TestCase):
    """User D189: "tracing should be absolute, including agent reasoning"."""

    def test_the_report_has_every_click_event_decision_and_thought_in_order(self):
        rows = [{'t': 1.0, 'type': 'decide', 'target': 'GardenBed#-1.7,-31.6', 'why': 'nearest ready', 'dist': 4.4},
                {'t': 2.0, 'type': 'click', 'pt': [960, 540], 'what': 'step', 'events': ['out_of_water'], 'moved': False},
                {'t': 3.0, 'type': 'think', 'text': 'the bubble at M8 is a carrot with a drop - not ready'},
                {'t': 4.0, 'type': 'vision', 'kind': 'click', 'question': 'which bed?'}]
        lines = RW.trace_lines(rows)
        self.assertEqual(len(lines), 4)
        self.assertIn('out_of_water', lines[1])
        self.assertIn('nearest ready', lines[0])
        self.assertIn('carrot with a drop', lines[2])

    def test_reasoning_cycle_is_visible_in_the_single_trace(self):
        rows = [{'t': 1.0, 'type': 'reasoning', 'cycle': 'abc123', 'phase': 'clues',
                 'decision': 'need_model_vision', 'vision_requested': True},
                {'t': 2.0, 'type': 'reasoning', 'cycle': 'abc123', 'phase': 'outcome',
                 'action': 'target', 'verdict': 'miss', 'code_fix': 'evaluate_gap'}]
        lines = RW.trace_lines(rows)
        self.assertIn('abc123 clues', lines[0])
        self.assertIn('vision=True', lines[0])
        self.assertIn('gap=evaluate_gap', lines[1])


if __name__ == '__main__':
    unittest.main()
