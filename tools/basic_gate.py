"""Fast offline release gate for the essential user-visible contracts.

This intentionally does not discover the large fake-heavy suite. Pair it with a
bounded live-game check. Run it with:
    .venv/bin/python tools/basic_gate.py
"""
import unittest

from test_play import Play, PlayCase, MapModalProof
from test_turn import Turns
from test_runwatch import Trace
from test_experience import Boundary


TESTS = (
    (Turns, 'test_production_observation_runs_vectors_on_the_exact_saved_grab'),
    (Turns, 'test_vector_failure_is_explicit_instead_of_looking_like_no_match'),
    (Turns, 'test_every_context_prints_the_compact_receipt_first_view'),
    (Turns, 'test_capture_reuses_the_final_full_settle_frame_without_another_grab'),
    (Boundary, 'test_journal_write_failure_propagates_and_never_marks_experience_applied'),
    (PlayCase, 'test_new_task_reuses_its_vector_observation_in_the_first_next'),
    (Play, 'test_every_public_gameplay_alias_returns_before_input'),
    (Play, 'test_one_decision_performs_at_most_one_input'),
    (MapModalProof, 'test_confirmed_interaction_missing_vector_requests_model_appearance_sample'),
    (Trace, 'test_reasoning_cycle_is_visible_in_the_single_trace'),
)


if __name__ == '__main__':
    suite = unittest.TestSuite(cls(name) for cls, name in TESTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
