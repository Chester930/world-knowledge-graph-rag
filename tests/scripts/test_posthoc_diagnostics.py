"""事後重算與檢索失敗診斷工具的純函式測試（報告57 §4.20／§4.21）。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.diagnose_retrieval_failures import cosine, normalize_article, persistently_missed
from scripts.eval.rescore_refusal_posthoc import EXTRA_REFUSAL_PATTERNS, rescore_record


def _run(missed, error=None):
    return {"error": error, "lineage": {"stage1_retrieval": {"missed_exact_spans": missed}}}


class DiagnoseHelperTests(unittest.TestCase):
    def test_normalize_article_strips_paragraph_and_spaces(self):
        self.assertEqual(normalize_article("第6條第2項"), "第6條")
        self.assertEqual(normalize_article("第 19 條"), "第19條")
        self.assertEqual(normalize_article("第84-2條"), "第84-2條")

    def test_normalize_article_returns_none_for_appendix(self):
        self.assertIsNone(normalize_article("附表一 項次一"))
        self.assertIsNone(normalize_article(""))

    def test_persistently_missed_requires_missing_in_every_valid_run(self):
        runs = [_run(["a", "b"]), _run(["b", "c"])]
        self.assertEqual(persistently_missed(runs), ["b"])

    def test_persistently_missed_ignores_errored_runs(self):
        runs = [_run(["a"]), _run([], error="timeout")]
        self.assertEqual(persistently_missed(runs), ["a"])

    def test_persistently_missed_no_valid_runs(self):
        self.assertEqual(persistently_missed([_run(["a"], error="x")]), [])

    def test_cosine(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)


class RescoreTests(unittest.TestCase):
    CASE = {"scenario_type": "Type-E", "atomic_gold_facts": [], "trap_claim_spans": []}

    def test_substantive_refusal_flips_to_pass(self):
        rec = {"question_id": "Q", "answer": "事實清單中沒有相關資訊可以作答。"}
        res = rescore_record(rec, self.CASE, EXTRA_REFUSAL_PATTERNS)
        self.assertFalse(res["before_perfect"])
        self.assertTrue(res["after_perfect"])
        self.assertTrue(res["changed"])

    def test_non_type_e_is_skipped(self):
        rec = {"question_id": "Q", "answer": "x"}
        self.assertIsNone(rescore_record(rec, {"scenario_type": "Type-C"}, EXTRA_REFUSAL_PATTERNS))

    def test_errored_record_is_skipped(self):
        rec = {"question_id": "Q", "answer": "", "error": "timeout"}
        self.assertIsNone(rescore_record(rec, self.CASE, EXTRA_REFUSAL_PATTERNS))

    def test_trap_claim_still_fails_after_extension(self):
        case = dict(self.CASE, trap_claim_spans=["精密作業需要檢查"])
        rec = {"question_id": "Q", "answer": "精密作業需要檢查。其餘沒有相關資訊。"}
        res = rescore_record(rec, case, EXTRA_REFUSAL_PATTERNS)
        self.assertFalse(res["after_perfect"])


if __name__ == "__main__":
    unittest.main()
