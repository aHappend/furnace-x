"""Synthetic orchestration sensitivity; not RTL or Linux execution evidence."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_segmentation import validate_segment


class SegmentValidationTest(unittest.TestCase):
    def setUp(self):
        self.metrics = {
            "start_cycle": 40000000, "end_cycle": 80000000, "context_time": 800000000,
            "complete_boot": False, "outcome": "continuation", "retired": 200,
            "equal_comparisons": 500, "require_comparisons": 1000,
            "output_bytes_compared": 8, "coverage": {"s_mode": 1}, "uart_bytes": 64,
        }
        self.previous = {
            "retired": 100, "equal_comparisons": 250, "require_comparisons": 500,
            "output_bytes_compared": 4, "coverage": {"s_mode": 1}, "uart_bytes": 32,
        }
        self.observed = {k: v for k, v in self.metrics.items() if k in (
            "retired", "equal_comparisons", "require_comparisons", "output_bytes_compared", "coverage")}
        self.observed.update(simulation_exit=1, cycles=80000000)

    def validate(self, metrics=None, observed=None):
        validate_segment(self.metrics if metrics is None else metrics,
                         self.observed if observed is None else observed,
                         40000000, 80000000, self.previous)

    def test_valid_continuation_is_not_completion(self):
        self.validate()
        self.assertFalse(self.metrics["complete_boot"])
        self.assertEqual(self.observed["simulation_exit"], 1)

    def test_cycle_and_context_mutants(self):
        for field, value in (("start_cycle", 40000001), ("end_cycle", 79999999),
                             ("context_time", 799999999), ("end_cycle", 80000001)):
            with self.subTest(field=field, value=value):
                mutant = {**self.metrics, field: value}
                with self.assertRaises(ValueError):
                    self.validate(mutant)

    def test_false_success_and_observation_mutants(self):
        for field, value in (("simulation_exit", 0), ("cycles", 79999999),
                             ("retired", 199), ("equal_comparisons", 499),
                             ("require_comparisons", 999), ("output_bytes_compared", 7),
                             ("coverage", {})):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.validate(observed={**self.observed, field: value})
        with self.assertRaises(ValueError):
            self.validate({**self.metrics, "outcome": "complete"})

    def test_cumulative_state_loss(self):
        for field, value in (("retired", 100), ("equal_comparisons", 249),
                             ("require_comparisons", 499), ("output_bytes_compared", 3),
                             ("coverage", {}), ("uart_bytes", 31)):
            with self.subTest(field=field):
                mutant = copy.deepcopy(self.metrics)
                mutant[field] = value
                observed = {**self.observed}
                if field in observed:
                    observed[field] = value
                with self.assertRaises(ValueError):
                    self.validate(mutant, observed)


if __name__ == "__main__":
    unittest.main()
