"""Offline tests for tools/runtime (game-log evidence, actuators, save; M1). Run: .venv/bin/python tools/test_runtime.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime import log  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'game_log.txt')
LINES = open(FIX).read().splitlines()


def line(sub):
    return next(l for l in LINES if sub in l)


class Parse(unittest.TestCase):
    def test_action_with_position(self):
        e = log.parse_line(line('> water me=Player'))
        self.assertEqual((e.kind, e.day, round(e.hour, 2)), ('action', 148, 21.67))
        self.assertEqual(e.f, {'name': 'water', 'target': 'GardenBed', 'x': 5.84, 'z': -31.59})

    def test_action_clone_target(self):
        e = log.parse_line(line('target=BeeHive(Clone) at (0.22'))
        self.assertEqual(e.f, {'name': 'beehive_progress', 'target': 'BeeHive', 'x': 0.22, 'z': -23.46})

    def test_action_without_position(self):
        e = log.parse_line(line('> full_watering_can'))
        self.assertEqual(e.f, {'name': 'full_watering_can', 'target': 'Well'})

    def test_pathfail_to_object(self):
        e = log.parse_line(line('to BeeHive(Clone) at (2.72'))
        self.assertEqual((e.kind, e.f), ('pathfail', {'x': -1.09, 'z': -21.05, 'tx': 2.72, 'tz': -23.46,
                                                      'target': 'BeeHive'}))

    def test_pathfail_to_ground(self):
        e = log.parse_line(line('from  (8.01'))
        self.assertEqual(e.f, {'x': 8.01, 'z': 33.0, 'tx': 8.7, 'tz': 35.83, 'target': None})

    def test_stuck_kinds(self):
        self.assertEqual(log.parse_line(line('locomotion failed')).f, {'scene': 'RuralBeach', 'x': 16.09, 'z': 33.88})
        self.assertEqual(log.parse_line(line('Path blocked')).f, {'scene': None, 'x': 12.5, 'z': -20.0})

    def test_scene_and_spawn(self):
        self.assertEqual(log.parse_line(line('ChangeScene Farm/LinkBeach')).f, {'scene': 'Farm', 'link': 'LinkBeach'})
        self.assertEqual(log.parse_line(line('Spawning player at Farm/LinkBeach')).f, {'scene': 'Farm',
                                                                                        'point': 'LinkBeach'})
        self.assertEqual(log.parse_line(line('last known position')).f, {'scene': None, 'point': None})

    def test_building(self):
        self.assertEqual(log.parse_line(line('OnEnterBuilding Ranch')).f, {'building': 'Ranch', 'enter': True})
        self.assertEqual(log.parse_line(line('OnExitBuilding House')).f, {'building': 'House', 'enter': False})

    def test_pollen_stat_quest_day_forecast(self):
        self.assertEqual(log.parse_line(line('current pollen is 6/12')).f, {'produced': 0, 'current': 6, 'max': 12})
        self.assertEqual(log.parse_line(line('totalPlanted.TulipSeed = 61')).f, {'key': 'totalPlanted.TulipSeed',
                                                                                 'value': '61'})
        self.assertEqual(log.parse_line(line('Complete goal BuildRanch')).f, {'event': 'complete_goal',
                                                                              'quest': 'BuildRanch', 'goal': 'meet'})
        self.assertEqual(log.parse_line(line('Start quest MartyChickens')).f, {'event': 'start',
                                                                              'quest': 'MartyChickens', 'goal': None})
        self.assertEqual(log.parse_line(line('[TIME] Day 149')).f, {'day': 149})
        self.assertEqual(log.parse_line(line('Forecast is')).f, {'weather': 'Sunny'})

    def test_unknown_line_is_none(self):
        self.assertIsNone(log.parse_line(line('Waypoint Farm/Dog')))
        self.assertIsNone(log.parse_line(''))
        self.assertIsNone(log.parse_line('garbage ] > ( at ('))

    def test_every_fixture_line_parses_or_is_none(self):
        for l in LINES:
            log.parse_line(l)  # never raises

    def test_reader_only_new_lines(self):
        p = os.path.join(tempfile.mkdtemp(), 'log.txt')
        open(p, 'w').write(LINES[0] + '\n')
        r = log.LogReader(p)
        self.assertEqual(r.new(), [])
        with open(p, 'a') as fh:
            fh.write(line('> water me=Player') + '\n' + 'noise\n')
        evs = r.new()
        self.assertEqual([e.kind for e in evs], ['action'])
        self.assertEqual(r.new(), [])

    def test_reader_unhashes_real_lines(self):            # review C1: the real log hashes scene names
        p = os.path.join(tempfile.mkdtemp(), 'log.txt')
        open(p, 'w').close()
        names = {'#-131825797': 'Farm', '#-569722337': 'LinkBeach'}
        r = log.LogReader(p, unhash=lambda t: __import__('re').sub(r'#-\d+', lambda m: names.get(m.group(0), m.group(0)), t))
        with open(p, 'a') as fh:
            fh.write('[D148 5:35:07 PM] [GAME] ChangeScene #-131825797/#-569722337\n')
        self.assertEqual(r.new()[0].f, {'scene': 'Farm', 'link': 'LinkBeach'})

    def test_reader_restarts_after_relaunch(self):         # review I4: a relaunched game writes a shorter log
        p = os.path.join(tempfile.mkdtemp(), 'log.txt')
        with open(p, 'w') as fh:
            fh.write('x' * 500 + '\n')
        r = log.LogReader(p)
        with open(p, 'w') as fh:
            fh.write(line('> water me=Player') + '\n')
        self.assertEqual([e.kind for e in r.new()], ['action'])


class FakeWF:
    def __init__(self, mode='gameplay', texts=()):
        self.s = {'mode': mode, 'text': [f'{i}) {t}' for i, t in enumerate(texts)]}
        self.keys, self.clicks, self.reads = [], [], 0

    def state(self, save=False):
        return self.s

    def menu_open(self, s):
        return 'pause' if any('Game Paused' in t for t in s['text']) else None

    def go_to(self, x, y):
        self.clicks.append((x, y))

    def key(self, k):
        self.keys.append(k)
        if k == 'escape':
            paused = any('Game Paused' in t for t in self.s['text'])
            self.s = {'mode': 'gameplay', 'text': []} if paused else {'mode': 'overlay', 'text': ['0) Game Paused']}

    def wait_settle(self):
        pass

    def farm_status(self):
        return {'crops': [{'x': '1', 'z': '2', 'plantState': '##0', 'isWilted': 'false', 'isWatered': 'false'}]}

    def pos(self, refocus=True):
        self.reads += 1
        return {'scene': 'Farm', 'x': 1.0, 'z': 2.0}


class Act(unittest.TestCase):
    def test_click_refuses_menu(self):
        from runtime import act
        w = FakeWF('overlay', ['Game Paused'])
        act.bind(w)
        self.assertTrue(act.click(10, 20).startswith('MENU OPEN'))
        self.assertEqual(w.clicks, [])

    def test_pause_only_from_gameplay(self):
        from runtime import act
        w = FakeWF('overlay', ['Game Paused'])
        act.bind(w)
        self.assertTrue(act.pause())
        self.assertEqual(w.keys, [])                      # already paused: no key
        w2 = FakeWF('gameplay')
        act.bind(w2)
        self.assertTrue(act.pause())
        self.assertEqual(w2.keys, ['escape'])

    def test_resume_only_from_pause_menu(self):
        from runtime import act
        w = FakeWF('overlay', ['Inventory'])               # another menu: resume must not press Escape
        act.bind(w)
        self.assertFalse(act.resume())
        self.assertEqual(w.keys, [])
        w2 = FakeWF('overlay', ['Game Paused'])
        act.bind(w2)
        self.assertTrue(act.resume())
        self.assertEqual(w2.s['mode'], 'gameplay')


class Save(unittest.TestCase):
    def test_crops_normalised(self):
        from runtime import save
        save.bind(FakeWF())
        self.assertEqual(save.crops(), [{'x': 1.0, 'z': 2.0, 'state': 'empty', 'wilted': False, 'watered': False}])

    def test_reading_counts(self):
        from runtime import save
        w = FakeWF()
        save.bind(w)
        save.READINGS[0] = 0
        self.assertEqual(save.reading(), ('Farm', 1.0, 2.0))
        self.assertEqual(save.READINGS[0], 1)


if __name__ == '__main__':
    unittest.main()
