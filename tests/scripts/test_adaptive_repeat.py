import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.adaptive_repeat import (
    audit_reliability,
    classify,
    meets_standard,
    pick_audit_sample,
    summarize,
)


def _rec(perfect=True, error=None, scope_passed=None):
    record = {"question_id": "Q", "error": error, "atomic_score": {"is_perfect": perfect}}
    if scope_passed is not None:
        record["scope_audit"] = {"passed": scope_passed}
    return record


class MeetsStandardTests(unittest.TestCase):
    def test_requires_perfect_and_scope_audit_when_present(self):
        self.assertTrue(meets_standard(_rec(True)))
        self.assertTrue(meets_standard(_rec(True, scope_passed=True)))
        self.assertFalse(meets_standard(_rec(False)))
        self.assertFalse(meets_standard(_rec(True, scope_passed=False)))

    def test_error_or_timeout_never_meets_standard(self):
        self.assertFalse(meets_standard(_rec(True, error="harness_timeout_after_900s")))


class ClassifyTests(unittest.TestCase):
    def test_decision_table(self):
        self.assertEqual(classify([], 0), ("pending", True))
        self.assertEqual(classify([True], 0), ("single_pass", False))
        self.assertEqual(classify([False], 0), ("needs_second_run", True))
        self.assertEqual(classify([True, True], 0), ("stable_pass", False))
        self.assertEqual(classify([False, False], 0), ("stable_fail", False))
        self.assertEqual(classify([True, False], 0), ("needs_third_run", True))
        self.assertEqual(classify([False, True], 0), ("needs_third_run", True))
        self.assertEqual(classify([True, False, True], 0), ("unstable", False))

    def test_two_invalid_runs_is_infra_failure_not_quality_verdict(self):
        self.assertEqual(classify([], 1), ("pending", True))
        self.assertEqual(classify([], 2), ("infra_failure", False))

    def test_invalid_runs_do_not_count_toward_valid_results(self):
        summary = summarize(["Q"], {"Q": [_rec(True, error="timeout"), _rec(False)]})
        self.assertEqual(summary["Q"]["valid_results"], [False])
        self.assertEqual(summary["Q"]["invalid_runs"], 1)
        self.assertEqual(summary["Q"]["status"], "needs_second_run")


class AuditTests(unittest.TestCase):
    def test_sample_is_deterministic_and_bounded(self):
        ids = [f"Q{i}" for i in range(40)]
        first = pick_audit_sample(ids, 7)
        self.assertEqual(first, pick_audit_sample(list(reversed(ids)), 7))
        self.assertEqual(len(first), 10)
        self.assertEqual(len(pick_audit_sample(["a", "b"], 1)), 2)
        self.assertEqual(pick_audit_sample([], 1), [])

    def test_reliability_uses_second_valid_result_only(self):
        summary = {
            "a": {"valid_results": [True, True]},
            "b": {"valid_results": [True, False]},
            "c": {"valid_results": [True]},
        }
        result = audit_reliability(summary, ["a", "b", "c"])
        self.assertEqual(result["sampled"], 3)
        self.assertEqual(result["rerun_completed"], 2)
        self.assertEqual(result["passed_again"], 1)
        self.assertEqual(result["reliability"], 0.5)


if __name__ == "__main__":
    unittest.main()
