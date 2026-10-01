import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ConceptAnnotationStatsTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module("scripts.analysis.concept_entity_annotation_stats")

    def test_summary_counts_and_wilson(self):
        out = self.m.summarize_counts({"P": 10, "C": 30, "U": 10})
        self.assertEqual(out["total"], 50)
        self.assertEqual(out["labels"]["C"]["count"], 30)
        self.assertAlmostEqual(out["labels"]["C"]["share"], 0.6)
        self.assertEqual(len(out["labels"]["U"]["wilson_95"]), 2)

    def test_record_labels_are_normalized(self):
        out = self.m.counts_from_records([{"label": "p"}, {"草稿標註": "C"}, {"label": "u"}])
        self.assertEqual(dict(out), {"P": 1, "C": 1, "U": 1})

    def test_question_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            p.write_text("草稿標註,疑問\nP,是\nC,否\nU,是\n", encoding="utf-8-sig")
            self.assertEqual(self.m.read_question_count(p), 2)

    def test_import_does_not_touch_environment(self):
        before_env = dict(os.environ)
        self.assertEqual(self.m.LABELS, ("P", "C", "U"))
        self.assertEqual(before_env, dict(os.environ))


if __name__ == "__main__":
    unittest.main()
