import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.analysis.compare_p2_snapshots import compare_runs


QUESTION_IDS = ("Q1", "Q2")


def _record(question_id, *, answer="same answer", trace=None, error=None):
    return {
        "question_id": question_id,
        "answer": answer,
        "error": error,
        "atomic_score": {
            "is_perfect": True,
            "supported_spans": ["span"],
            "missing_spans": [],
        },
        "lineage": {
            "stage1_retrieval": {
                "retrieved_fact_ids": ["fact-1"],
                "retrieved_chunk_ids": ["chunk-1"],
                "retrieval_trace": trace if trace is not None else [{"fact_id": "fact-1"}],
                "retrieval_latency_ms": 1,
            },
            "stage2_context": {
                "prompt_context_lines": ["context line"],
                "total_context_tokens": 3,
            },
            "stage3_generation": {
                "raw_draft": "draft",
                "final_output": "same answer",
                "grounding_passed": True,
                "regenerated": False,
                "generation_latency_ms": 2,
            },
        },
    }


def _write_run(root, name, records):
    run_dir = root / name
    run_dir.mkdir()
    (run_dir / "records.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


class CompareP2SnapshotsTests(unittest.TestCase):
    def test_identical_runs_are_equal_at_all_three_layers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            records = [_record(question_id) for question_id in QUESTION_IDS]
            result = compare_runs(
                _write_run(root, "a", records), _write_run(root, "b", records)
            )

        self.assertTrue(result["overall"]["l1"])
        self.assertTrue(result["overall"]["l2"])
        self.assertTrue(result["overall"]["l3"])
        self.assertEqual(result["exit_code"], 0)

    def test_answer_only_change_is_l2_difference_but_not_l1_difference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = [_record(question_id) for question_id in QUESTION_IDS]
            changed = [_record(question_id) for question_id in QUESTION_IDS]
            changed[0]["answer"] = "different answer"
            result = compare_runs(
                _write_run(root, "a", baseline), _write_run(root, "b", changed)
            )

        self.assertTrue(result["questions"]["Q1"]["l1"]["equal"])
        self.assertFalse(result["questions"]["Q1"]["l2"]["equal"])
        self.assertEqual(result["exit_code"], 0)

    def test_retrieval_trace_order_change_fails_l1_and_exit_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = [_record(question_id) for question_id in QUESTION_IDS]
            changed = [_record(question_id) for question_id in QUESTION_IDS]
            changed[0]["lineage"]["stage1_retrieval"]["retrieval_trace"] = [
                {"fact_id": "fact-2"},
                {"fact_id": "fact-1"},
            ]
            result = compare_runs(
                _write_run(root, "a", baseline), _write_run(root, "b", changed)
            )

        self.assertFalse(result["questions"]["Q1"]["l1"]["equal"])
        self.assertFalse(result["overall"]["l1"])
        self.assertEqual(result["exit_code"], 1)

    def test_missing_question_is_reported_explicitly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = [_record(question_id) for question_id in QUESTION_IDS]
            missing = [_record("Q1")]
            with self.assertRaisesRegex(ValueError, "missing question IDs.*Q2"):
                compare_runs(
                    _write_run(root, "a", baseline), _write_run(root, "b", missing)
                )

    def test_error_record_is_no_data_and_fails_overall_judgment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = [_record(question_id) for question_id in QUESTION_IDS]
            errored = [_record("Q1", error="timeout"), _record("Q2")]
            result = compare_runs(
                _write_run(root, "a", baseline), _write_run(root, "b", errored)
            )

        self.assertEqual(result["questions"]["Q1"]["status"], "無資料")
        self.assertFalse(result["overall"]["l1"])
        self.assertFalse(result["overall"]["l2"])
        self.assertFalse(result["overall"]["l3"])
        self.assertEqual(result["exit_code"], 1)


class TripleSourceFieldOptionTests(unittest.TestCase):
    """報告164 V3：選用旗標忽略 retrieval_trace 三元組條目的 source_svo_chunk_index／article_no。"""

    def _runs(self, root, old_idx, new_idx, fact_text_new="甲"):
        def trace(idx, fact_text):
            return [
                {"kind": "fact", "rank": 0, "text": fact_text, "source_svo_chunk_index": 1, "article_no": None},
                {"kind": "triple", "rank": 0, "text": "乙", "source_svo_chunk_index": idx, "article_no": None},
            ]
        a = _write_run(root, "a", [_record("Q1", trace=trace(old_idx, "甲"))])
        b = _write_run(root, "b", [_record("Q1", trace=trace(new_idx, fact_text_new))])
        return a, b

    def test_default_flags_triple_source_field_difference(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = self._runs(Path(d), None, 3)
            self.assertFalse(compare_runs(a, b)["overall"]["l1"])

    def test_option_ignores_only_triple_source_fields(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = self._runs(Path(d), None, 3)
            self.assertTrue(compare_runs(a, b, ignore_trace_triple_source_fields=True)["overall"]["l1"])

    def test_option_still_detects_other_trace_differences(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = self._runs(Path(d), None, 3, fact_text_new="不同")
            self.assertFalse(compare_runs(a, b, ignore_trace_triple_source_fields=True)["overall"]["l1"])


if __name__ == "__main__":
    unittest.main()
