"""Fast offline release gate for the essential user-visible contracts.

This intentionally does not discover the large fake-heavy suite. Pair it with a
bounded live-game check. Run it with:
    .venv/bin/python tools/basic_gate.py
"""
import unittest

from test_engine import ModelDecides, StreamingGarden
from test_runwatch import Trace


TESTS = (
    (StreamingGarden, 'test_harvested_crop_is_replanted_and_watered_in_place_before_advancing'),
    (StreamingGarden, 'test_a_target_answer_finishes_a_known_nonflower_even_when_collect_ocr_is_blank'),
    (StreamingGarden, 'test_a_target_answer_never_collects_a_named_flower'),
    (StreamingGarden, 'test_one_garden_pass_inspects_every_hive_and_collects_ready_honey'),
    (StreamingGarden, 'test_a_walk_answer_inside_a_projected_bed_is_rejected_before_input'),
    (ModelDecides, 'test_no_direct_action_asks_one_decide_question_with_the_brief'),
    (Trace, 'test_reasoning_cycle_is_visible_in_the_single_trace'),
)


if __name__ == '__main__':
    suite = unittest.TestSuite(cls(name) for cls, name in TESTS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
