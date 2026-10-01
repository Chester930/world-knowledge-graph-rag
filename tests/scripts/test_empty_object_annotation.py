import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class EmptyObjectSamplingTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module("scripts.analysis.empty_object_annotation")

    def test_import_does_not_touch_environment_or_load_neo4j(self):
        before_env = dict(os.environ)
        before = set(sys.modules)
        sys.modules.pop("scripts.analysis.empty_object_annotation", None)
        importlib.import_module("scripts.analysis.empty_object_annotation")
        self.assertEqual(before_env, dict(os.environ))
        loaded = set(sys.modules) - before
        self.assertFalse(any(x == "neo4j" or x.startswith("neo4j.") for x in loaded))

    def test_citations_to_records_splits_every_reference(self):
        rows = [{"document": "x", "subject": "主", "rel_type": "RELATED_TO", "object": "", "citations": json.dumps([
            {"source_doc_id": "d", "source_svo_chunk_index": 2, "source_sentence_start": 1, "source_sentence_end": 1, "verb": "應做"},
            {"source_doc_id": "d", "source_svo_chunk_index": 3, "source_sentence_start": 1, "source_sentence_end": 1, "verb": "不得做"},
        ], ensure_ascii=False)}]
        out = self.m.citations_to_records(rows, {"d": "doc"})
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["document"], "doc")
        self.assertEqual(out[1]["chunk"], 3)
        self.assertNotEqual(out[0]["sample_key"], out[1]["sample_key"])

    def test_sampling_is_seeded_and_excludes_existing_chunks(self):
        rows = []
        for i in range(200):
            rows.append({"document": "doc", "chunk": i + 1, "subject": str(i), "verb": "v", "rel_type": "R", "sample_key": str(i)})
        one = self.m.sample_new_records(rows, seed=7, size=10)
        two = self.m.sample_new_records(rows, seed=7, size=10)
        self.assertEqual([r["sample_key"] for r in one], [r["sample_key"] for r in two])
        self.assertTrue(all(r["chunk"] not in {c for d, c in self.m.EXISTING_30_CHUNKS if d == "doc"} for r in one))

    def test_apply_and_review_order_put_questions_first(self):
        rows = [
            {"sample_key": "b", "document": "d", "chunk": 2},
            {"sample_key": "a", "document": "d", "chunk": 1},
        ]
        out = self.m.apply_annotations(rows, {"a": {"label": "b", "question": False, "reason": "r"}})
        ordered = self.m.order_for_review(out)
        self.assertEqual([x["sample_key"] for x in ordered], ["b", "a"])
        self.assertEqual([x["review_number"] for x in ordered], [1, 2])
        self.assertEqual(ordered[0]["label"], "c")


class EmptyObjectStatsTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module("scripts.analysis.empty_object_annotation_stats")

    def test_wilson_known_zero_and_full(self):
        lo, hi = self.m.wilson_interval(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.0)
        lo2, hi2 = self.m.wilson_interval(10, 10)
        self.assertLess(lo2, 1.0)
        self.assertEqual(hi2, 1.0)

    def test_summary_counts_and_partition(self):
        out = self.m.summarize_counts({"a": 11, "b": 14, "c": 5})
        self.assertEqual(out["total"], 30)
        self.assertEqual(sum(x["count"] for x in out["labels"].values()), 30)
        self.assertAlmostEqual(out["labels"]["b"]["share"], 14 / 30)
        self.assertEqual(len(out["labels"]["c"]["wilson_95"]), 2)

    def test_csv_and_combination(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            p.write_text("草稿標註\na\nb\nc\na\n", encoding="utf-8-sig")
            counts = self.m.read_csv_counts(p)
        self.assertEqual(dict(counts), {"a": 2, "b": 1, "c": 1})
        self.assertEqual(self.m.combined_counts(counts, {"a": 11, "b": 14, "c": 5}), {"a": 13, "b": 15, "c": 6})


if __name__ == "__main__":
    unittest.main()
