import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.frozen_baseline_stage import remaining_question_ids


class RemainingQuestionTests(unittest.TestCase):
    def test_returns_eligible_without_results_in_eligible_order(self):
        tmp = Path(tempfile.mkdtemp())
        a = tmp / "a.json"
        b = tmp / "b.json"
        a.write_text(json.dumps([{"question_id": "Q1"}, {"question_id": "Q3"}]), encoding="utf-8")
        b.write_text(json.dumps([{"question_id": "Q2"}]), encoding="utf-8")

        self.assertEqual(remaining_question_ids(["Q1", "Q2", "Q3", "Q4", "Q5"], [a, b]), ["Q4", "Q5"])

    def test_no_records_means_everything_remains(self):
        self.assertEqual(remaining_question_ids(["Q1", "Q2"], []), ["Q1", "Q2"])

    def test_errored_records_still_count_as_attempted(self):
        # 逾時／錯誤的紀錄仍是「已嘗試」；是否補跑由 adaptive_repeat 依無效執行規則決定。
        tmp = Path(tempfile.mkdtemp())
        a = tmp / "a.json"
        a.write_text(json.dumps([{"question_id": "Q1", "error": "harness_timeout_after_900s"}]), encoding="utf-8")

        self.assertEqual(remaining_question_ids(["Q1", "Q2"], [a]), ["Q2"])


if __name__ == "__main__":
    unittest.main()
