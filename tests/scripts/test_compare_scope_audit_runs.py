import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.compare_scope_audit_runs import compare_runs


def _records(accuracy, recall, snr, scope_passed):
    rows = []
    for question_id in ("Q1", "Q2"):
        for run in range(1, 4):
            rows.append(
                {
                    "question_id": question_id,
                    "run": run,
                    "atomic_score": {"atomic_accuracy": accuracy[question_id]},
                    "lineage": {
                        "stage1_retrieval": {
                            "recall_rate": recall[question_id],
                            "snr": snr[question_id],
                        }
                    },
                    "scope_audit": {"passed": scope_passed[question_id]},
                }
            )
    return rows


def _manifest(dataset_sha256="same-dataset"):
    return {
        "kg_id": "kg-test",
        "doc_ids": ["doc-a"],
        "chunk_size": 500,
        "runs": 3,
        "dataset_sha256": dataset_sha256,
        "generator_provider": "test-provider",
        "generator_model": "test-generator",
        "judge_provider": "test-provider",
        "judge_model": "test-judge",
        "embedding_provider": "test-provider",
        "embedding_model": "test-embedding",
        "query_timeout_s": 60,
        "formal_evaluation": True,
        "allow_shared_judge": False,
    }


def _compare(baseline, control, candidate, baseline_hash="same-dataset"):
    return compare_runs(
        baseline,
        control,
        candidate,
        baseline_manifest=_manifest(baseline_hash),
        control_manifest=_manifest(),
        candidate_manifest=_manifest(),
    )


class CompareScopeAuditRunsTests(unittest.TestCase):
    def test_rejects_accuracy_gain_when_scope_risk_remains(self):
        recalls = {"Q1": 1.0, "Q2": 1.0}
        snrs = {"Q1": 0.1, "Q2": 0.1}
        safe_scopes = {"Q1": True, "Q2": True}
        baseline = _records({"Q1": 0.5, "Q2": 1.0}, recalls, snrs, safe_scopes)
        control = _records({"Q1": 0.5, "Q2": 1.0}, recalls, snrs, safe_scopes)
        candidate = _records(
            {"Q1": 1.0, "Q2": 1.0}, recalls, snrs, {"Q1": False, "Q2": True}
        )

        result = _compare(baseline, control, candidate)

        self.assertEqual(result["decision"], "NO-GO")
        self.assertEqual(result["candidate_vs_control"]["accuracy_gain_questions"], ["Q1"])
        self.assertEqual(result["candidate_vs_control"]["scope_failures"], ["Q1: scope audit 0/3"])

    def test_rejects_candidate_if_matched_control_regresses_snr(self):
        accuracies = {"Q1": 0.5, "Q2": 1.0}
        recalls = {"Q1": 1.0, "Q2": 1.0}
        safe_scopes = {"Q1": True, "Q2": True}
        baseline = _records(accuracies, recalls, {"Q1": 0.1, "Q2": 0.1}, safe_scopes)
        control = _records(accuracies, recalls, {"Q1": 0.09, "Q2": 0.09}, safe_scopes)
        candidate = _records(
            {"Q1": 1.0, "Q2": 1.0}, recalls, {"Q1": 0.09, "Q2": 0.09}, safe_scopes
        )

        result = _compare(baseline, control, candidate)

        self.assertEqual(result["decision"], "NO-GO")
        self.assertTrue(result["control_vs_baseline"]["regressions"])

    def test_go_requires_all_gates_and_an_accuracy_gain(self):
        recalls = {"Q1": 1.0, "Q2": 1.0}
        snrs = {"Q1": 0.1, "Q2": 0.1}
        safe_scopes = {"Q1": True, "Q2": True}
        baseline = _records({"Q1": 0.5, "Q2": 1.0}, recalls, snrs, safe_scopes)
        control = _records({"Q1": 0.5, "Q2": 1.0}, recalls, snrs, safe_scopes)
        candidate = _records({"Q1": 1.0, "Q2": 1.0}, recalls, snrs, safe_scopes)

        self.assertEqual(_compare(baseline, control, candidate)["decision"], "GO")

    def test_manifest_mismatch_blocks_go_and_baseline_comparison(self):
        accuracy = {"Q1": 0.5, "Q2": 1.0}
        recalls = {"Q1": 1.0, "Q2": 1.0}
        snrs = {"Q1": 0.1, "Q2": 0.1}
        scopes = {"Q1": True, "Q2": True}
        baseline = _records(accuracy, recalls, snrs, scopes)
        control = _records(accuracy, recalls, snrs, scopes)
        candidate = _records({"Q1": 1.0, "Q2": 1.0}, recalls, snrs, scopes)

        result = _compare(baseline, control, candidate, baseline_hash="older-dataset")

        self.assertEqual(result["decision"], "NO-GO")
        self.assertFalse(result["baseline_comparable"])
        self.assertIsNone(result["control_vs_baseline"])

    def test_model_mismatch_blocks_candidate_comparison(self):
        baseline = _manifest()
        control = _manifest()
        candidate = _manifest()
        candidate["generator_model"] = "different-generator"
        rows = _records(
            {"Q1": 0.5, "Q2": 1.0},
            {"Q1": 1.0, "Q2": 1.0},
            {"Q1": 0.1, "Q2": 0.1},
            {"Q1": True, "Q2": True},
        )

        with self.assertRaisesRegex(ValueError, "matched control and candidate manifests"):
            compare_runs(
                rows,
                rows,
                rows,
                baseline_manifest=baseline,
                control_manifest=control,
                candidate_manifest=candidate,
            )

    def test_non_finite_score_is_rejected(self):
        rows = _records(
            {"Q1": float("nan"), "Q2": 1.0},
            {"Q1": 1.0, "Q2": 1.0},
            {"Q1": 0.1, "Q2": 0.1},
            {"Q1": True, "Q2": True},
        )

        with self.assertRaisesRegex(ValueError, r"finite and within \[0, 1\]"):
            compare_runs(rows, rows, rows)


if __name__ == "__main__":
    unittest.main()
