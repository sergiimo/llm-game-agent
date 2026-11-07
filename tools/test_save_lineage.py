import os
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime.save_lineage import LineageMismatch, LogEpoch, SaveCandidate, select_profile, validate_pinned
from runtime.db import Database
from runtime.run_store import RunStore
from game.observations import ObservationStore
from game.observations import ObservationSnapshot
from game import act, core, primitives, screen


def candidate(profile, day, count=1, slot='1', mtime=0):
    return SaveCandidate(profile, f'/{profile}/{slot}.local', slot, f'd-{profile}-{slot}', count,
                         day * 86400 + 9 * 3600, 'Farm' if day > 4 else 'Town', {}, mtime)


class SaveLineage(unittest.TestCase):
    def test_post_midnight_save_clock_stays_on_the_current_game_day(self):
        from game import world
        save = {'gameState': {'time': {'day': 4, 'timeOfDay': {'totalSeconds': 24 * 3600 + 10 * 60}}}}
        self.assertEqual(world.save_epoch_seconds(save), 4 * 86400 + 24 * 3600 + 10 * 60)
        self.assertEqual(world.save_time(save), 'D4 12:10:00 AM')

    def test_log_clock_wrap_before_day_advance_is_normalized_monotonically(self):
        from runtime.save_lineage import monotonic_log_times
        stamps = [4 * 86400 + 23 * 3600 + 17 * 60,
                  4 * 86400 + 2 * 3600,
                  5 * 86400 + 2 * 3600,
                  5 * 86400 + 11 * 3600 + 30 * 60]
        self.assertEqual(monotonic_log_times(stamps), [
            4 * 86400 + 23 * 3600 + 17 * 60,
            5 * 86400 + 2 * 3600,
            5 * 86400 + 2 * 3600,
            5 * 86400 + 11 * 3600 + 30 * 60,
        ])

    def test_fix_resume_accepts_stale_pinned_save_when_continuous_log_bridges_to_next_day(self):
        save = SaveCandidate('root', '/root/4.local', '4', 'same', 392,
                             4 * 86400 + 24 * 3600 + 10 * 60, 'Town', {})
        previous_log = LogEpoch('log', 4 * 86400, 4 * 86400 + 23 * 3600 + 17 * 60)
        live_log = LogEpoch('log', 4 * 86400, 5 * 86400 + 11 * 3600 + 30 * 60, lines=(
            '[D4 2:00:00 AM] [TRIGGER] AdvanceDay',
            '[D4 2:00:31 AM] [GAME] ChangeScene Farm/Bed',
            '[D5 11:30:00 AM] [TRIGGER] OnDayStarted',
        ), scene='Farm')
        self.assertIs(validate_pinned(save, live_log, 'root', save, previous_log), save)

    def test_captured_d4_town_then_d219_farm_fails_closed(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'play',
                               'save-lineage-d4-town-vs-d219-farm.json')
        with open(fixture) as stream:
            captured = json.load(stream)
        d4 = candidate(captured['root']['profile_key'], 4, 10, mtime=1)
        d219 = candidate(captured['other']['profile_key'], 219, 900, mtime=999)
        with tempfile.TemporaryDirectory() as directory:
            db = Database(os.path.join(directory, 'wf.sqlite3'))
            run_id = RunStore(db).start('captured-lineage', 'go home', directory)
            observations = ObservationStore(db)
            root = observations.capture(run_id, [d219, d4], LogEpoch('d4-log', d4.game_time, d4.game_time))
            self.assertEqual(root.candidate.profile_key, captured['expected_initial_profile'])
            later = observations.capture(run_id, [d219], LogEpoch('d219-log', d219.game_time, d219.game_time))
            self.assertEqual(later.status, captured['expected_later_status'])
            self.assertEqual(list(later.allowed_decisions), captured['allowed_decisions'])
    def test_newer_mtime_from_another_profile_does_not_override_live_log(self):
        d4, d219 = candidate('root-d4', 4, 10, mtime=1), candidate('other-d219', 219, 900, mtime=999)
        selected = select_profile([d219, d4], LogEpoch('log-d4', 4 * 86400, d4.game_time))
        self.assertEqual(selected.profile_key, 'root-d4')

    def test_ambiguous_and_missing_profiles_fail_closed(self):
        log = LogEpoch('log', 4 * 86400, candidate('a', 4).game_time)
        with self.assertRaisesRegex(LineageMismatch, 'ambiguous_profiles'):
            select_profile([candidate('a', 4), candidate('b', 4)], log)
        with self.assertRaisesRegex(LineageMismatch, 'no_coherent_profile'):
            select_profile([candidate('a', 219)], log)

    def test_same_profile_slot_rotation_is_legal_and_cross_profile_or_reverse_time_is_not(self):
        old = candidate('root', 4, 10, '1')
        new = candidate('root', 4, 11, '2')
        log = LogEpoch('log-2', old.game_time, new.game_time, previous_id='log-1')
        self.assertIs(validate_pinned(new, log, 'root', old, LogEpoch('log-1', old.game_time, old.game_time)), new)
        with self.assertRaisesRegex(LineageMismatch, 'profile_changed'):
            validate_pinned(candidate('other', 4, 12), log, 'root', old)
        with self.assertRaisesRegex(LineageMismatch, 'save_count_reversed'):
            validate_pinned(candidate('root', 4, 9), log, 'root', old)
        with self.assertRaisesRegex(LineageMismatch, 'game_time_reversed'):
            earlier = SaveCandidate('root', '/root/3.local', '3', 'earlier', 12,
                                    old.game_time - 1, 'Town', {})
            validate_pinned(earlier, log, 'root', old)

    def test_contradictory_log_rotation_fails(self):
        save = candidate('root', 4, 11)
        with self.assertRaisesRegex(LineageMismatch, 'log_epoch_conflict'):
            validate_pinned(save, LogEpoch('alien', 1, save.game_time), 'root', save,
                            LogEpoch('old', save.game_time, save.game_time))

    def test_scene_conflict_is_not_a_coherent_profile(self):
        save = candidate('root', 4)
        with self.assertRaisesRegex(LineageMismatch, 'no_coherent_profile'):
            select_profile([save], LogEpoch('log', save.game_time, save.game_time, scene='Farm'))

    def test_missing_pinned_profile_records_a_zero_input_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(os.path.join(directory, 'wf.sqlite3'))
            run_id = RunStore(db).start('lineage', 'test', directory)
            store = ObservationStore(db)
            root = candidate('root', 4)
            first = store.capture(run_id, [root], LogEpoch('log', root.game_time, root.game_time))
            self.assertEqual(first.status, 'coherent')
            other = candidate('other', 219)
            mismatch = store.capture(run_id, [other], LogEpoch('log-2', 219 * 86400, other.game_time))
            self.assertEqual(mismatch.status, 'save_lineage_mismatch')
            self.assertEqual(mismatch.allowed_decisions, ('look', 'read', 'stop'))
            self.assertEqual(mismatch.mismatch['reason'], 'pinned_profile_missing')

    def test_adapter_stops_before_clues_or_vectors_on_a_mismatch(self):
        from PIL import Image
        from game import snapshot, world
        observed_snapshot = ObservationSnapshot(17, 'save_lineage_mismatch', mismatch={'reason': 'profile_changed'})
        provider = mock.Mock(return_value=observed_snapshot)
        clues = mock.Mock(side_effect=AssertionError('clues must not derive from a mismatched save'))
        vectors = mock.Mock(side_effect=AssertionError('vectors saw a mismatched save'))
        graph = mock.Mock(side_effect=AssertionError('graph projection saw a mismatched save'))
        refresh = mock.Mock(side_effect=AssertionError('world refresh saw a mismatched save'))
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(core, 'WF', SimpleNamespace(game_hour=lambda image: 9.,
                    light_period=lambda hour: 'day', map_pin=lambda image: None)), \
                mock.patch.object(act, 'frames_dir', return_value=directory), \
                mock.patch('game.observe.scan', return_value=[]), \
                mock.patch('game.observe.detect_frame', vectors), \
                mock.patch.object(snapshot, 'project_graph', graph), \
                mock.patch.object(world, 'refresh', refresh), \
                mock.patch.object(screen, 'read', return_value=screen.Screen('gameplay', [])):
            observed = primitives.GameAdapter(clue_provider=clues, observation_provider=provider).observe(
                Image.new('RGB', (1920, 1080), 'white'))
        self.assertEqual(observed['lineage_status'], 'save_lineage_mismatch')
        self.assertEqual(observed['observation_id'], 17)
        self.assertEqual(observed['graph_clues'], [])
        self.assertEqual(observed['vector_detections'], [])
        clues.assert_not_called()

    def test_preflight_revalidates_lineage_before_input_preparation(self):
        from PIL import Image
        good = ObservationSnapshot(1, 'coherent')
        bad = ObservationSnapshot(2, 'save_lineage_mismatch', mismatch={'reason': 'profile_changed'})
        provider = mock.Mock(side_effect=[good, bad])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(core, 'WF', SimpleNamespace(game_hour=lambda image: 9.,
                    light_period=lambda hour: 'day', map_pin=lambda image: None)), \
                mock.patch.object(act, 'frames_dir', return_value=directory), \
                mock.patch('game.observe.scan', return_value=[]), \
                mock.patch.object(screen, 'read', return_value=screen.Screen('gameplay', [])):
            adapter = primitives.GameAdapter(clue_provider=lambda context: {}, observation_provider=provider)
            image = Image.new('RGB', (1920, 1080), 'white')
            observed = adapter.observe(image)
            with self.assertRaisesRegex(ValueError, 'save_lineage_mismatch'):
                adapter.preflight({'kind': 'waypoint', 'point': [960, 700], 'walkable': True}, observed,
                                  current=image)
        self.assertEqual(provider.call_count, 2)


if __name__ == '__main__':
    unittest.main()
