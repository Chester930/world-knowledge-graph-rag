import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.frozen_baseline_stage import (
    build_run_command,
    ollama_version_matches,
    remaining_question_ids,
)


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


class OllamaVersionTests(unittest.TestCase):
    def test_unrecorded_version_is_not_checked(self):
        self.assertTrue(ollama_version_matches(None, "0.11.4"))
        self.assertTrue(ollama_version_matches(None, None))

    def test_recorded_version_must_match_exactly(self):
        self.assertTrue(ollama_version_matches("0.34.2", "0.34.2"))
        self.assertFalse(ollama_version_matches("0.34.2", "0.11.4"))
        self.assertFalse(ollama_version_matches("0.34.2", None))


class EmbeddingCacheCommandTests(unittest.TestCase):
    def test_default_run_command_has_no_embedding_cache_flag(self):
        command = build_run_command(
            {"kg_id": "kg", "scope_doc_ids": ["doc"]}, "questions.json", "out"
        )

        self.assertNotIn("--embedding-cache", command)

    def test_run_command_forwards_optional_embedding_cache(self):
        command = build_run_command(
            {"kg_id": "kg", "scope_doc_ids": ["doc"]},
            "questions.json",
            "out",
            embedding_cache="cache.json",
        )

        index = command.index("--embedding-cache")
        self.assertEqual(command[index + 1], "cache.json")

    def test_default_run_command_has_no_metric_judge_flags(self):
        command = build_run_command(
            {"kg_id": "kg", "scope_doc_ids": ["doc"]}, "questions.json", "out"
        )

        self.assertNotIn("--metric-judge-provider", command)
        self.assertNotIn("--metric-judge-model", command)

    def test_run_command_forwards_optional_metric_judge(self):
        command = build_run_command(
            {"kg_id": "kg", "scope_doc_ids": ["doc"]},
            "questions.json",
            "out",
            metric_judge_provider="ollama",
            metric_judge_model="qwen2.5:7b",
        )

        provider_index = command.index("--metric-judge-provider")
        model_index = command.index("--metric-judge-model")
        self.assertEqual(command[provider_index + 1], "ollama")
        self.assertEqual(command[model_index + 1], "qwen2.5:7b")


if __name__ == "__main__":
    unittest.main()
