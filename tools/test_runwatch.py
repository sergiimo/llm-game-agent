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

    def test_an_engine_stop_that_is_not_done_is_an_alert(self):
        out = self.levels([{'type': 'engine', 'goal': 'plant', 'done': 0, 'left': 11, 'clicks': 4, 'vision': 0,
                            'stop': 'missing TulipSeed'}])
        self.assertEqual(out[0][0], 'ALERT')
        self.assertEqual(self.levels([{'type': 'engine', 'goal': 'plant', 'done': 12, 'left': 0, 'clicks': 14,
                                       'vision': 0, 'stop': 'done: query empty'}]), [])

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


if __name__ == '__main__':
    unittest.main()
