import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class SemanticMarksCoveragePureTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module("scripts.analysis.semantic_marks_coverage")
        self.sm = importlib.import_module("services.semantic_marks")

    def test_import_does_not_touch_environment_or_load_neo4j(self):
        before_env = dict(os.environ)
        before = set(sys.modules)
        sys.modules.pop("scripts.analysis.semantic_marks_coverage", None)
        importlib.import_module("scripts.analysis.semantic_marks_coverage")
        self.assertEqual(before_env, dict(os.environ))
        loaded = set(sys.modules) - before
        self.assertFalse(any(name == "neo4j" or name.startswith("neo4j.") for name in loaded))

    def test_entity_categories_and_all_schemes(self):
        rows = [("Person", 2), ("概念", 3), ("", 1), ("OUTSIDE", 4)]
        categories = self.m.entity_categories(rows, {"PERSON": "Person"}, {})
        self.assertEqual(categories["standard"], 2)
        self.assertEqual(categories["concept_only"], 3)
        self.assertEqual(categories["empty"], 1)
        self.assertEqual(categories["outside_raw"], 4)
        marks = self.m.entity_scheme_marks(rows, {"PERSON": "Person"}, {})
        self.assertEqual(marks["strict"][self.sm.INDETERMINATE], 3)
        self.assertEqual(marks["A"][self.sm.UNKNOWN], 4)
        self.assertEqual(marks["B"][self.sm.RESOLVED], 5)

    def test_relation_and_empty_distributions_use_l2(self):
        rel = self.m.relation_scheme_marks([("RELATED_TO", 3), ("USED_FOR", 2)])
        for scheme in self.m.SCHEMES:
            self.assertEqual(rel[scheme][self.sm.INDETERMINATE], 3)
            self.assertEqual(rel[scheme][self.sm.RESOLVED], 2)
        empty = self.m.empty_field_marks([(False, False, False, 5), (False, True, True, 2), (False, True, False, 3)])
        self.assertEqual(empty[self.sm.RESOLVED], 5)
        self.assertEqual(empty[self.sm.UNKNOWN], 2)
        self.assertEqual(empty[self.sm.PENDING], 3)

    def test_coverage_row_keeps_storage_and_derived_separate(self):
        row = self.m.coverage_row(10, 0, 7)
        self.assertEqual(row["storage_explicit_share"], 0.0)
        self.assertEqual(row["derived_non_indeterminate_share"], 0.7)
        self.assertIn("不代表已寫入", row["note"])

    def test_read_env_value_does_not_touch_environment(self):
        before = dict(os.environ)
        with self.subTest("missing"), self.assertRaises(FileNotFoundError):
            self.m.read_env_value(Path("__not_existing_env__"), "NEO4J_PASSWORD")
        self.assertEqual(before, dict(os.environ))


if __name__ == "__main__":
    unittest.main()
