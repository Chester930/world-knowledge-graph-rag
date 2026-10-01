import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODULE = "scripts.analysis.phase0_marking_baseline"


class ImportHasNoSideEffectTest(unittest.TestCase):
    def test_import_does_not_touch_environ_or_import_heavy_modules(self):
        before_env = dict(os.environ)
        before_mods = set(sys.modules)
        sys.modules.pop(MODULE, None)
        mod = importlib.import_module(MODULE)
        self.assertEqual(before_env, dict(os.environ))
        new = set(sys.modules) - before_mods
        for heavy in ("neo4j", "core", "services"):
            self.assertFalse(any(m == heavy or m.startswith(heavy + ".") for m in new), heavy)
        self.assertTrue(callable(mod.assert_read_only))

    def test_reuses_same_read_only_whitelist(self):
        m = importlib.import_module(MODULE)
        base = importlib.import_module("scripts.analysis.semantic_layer_invariants")
        self.assertIs(m.assert_read_only, base.assert_read_only)
        with self.assertRaises(ValueError):
            m.assert_read_only("MATCH (n) SET n.x = 1")


CORE = {"PERSON": "PERSON"}
EXT = {"ORGANIZATION": "ORGANIZATION"}


class EntityTypeTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module(MODULE)

    def test_categories(self):
        c = self.m.classify_entity_type
        self.assertEqual(c(None, CORE, EXT), "empty")
        self.assertEqual(c("  ", CORE, EXT), "empty")
        self.assertEqual(c("概念", CORE, EXT), "concept_only")
        self.assertEqual(c("PERSON", CORE, EXT), "standard")
        self.assertEqual(c("person,ORGANIZATION", CORE, EXT), "standard")
        self.assertEqual(c("概念,PERSON", CORE, EXT), "standard_with_concept")
        self.assertEqual(c("ACTIVITY", CORE, EXT), "outside_raw")
        self.assertEqual(c("概念,ACTIVITY", CORE, EXT), "outside_raw")

    def test_tally_and_marks_two_concept_schemes(self):
        cat = self.m.tally_entity_types([("PERSON", 3), ("概念", 5), ("", 2), ("X", 1), ("概念,PERSON", 4)], CORE, EXT)
        self.assertEqual(cat["standard"], 3)
        self.assertEqual(cat["concept_only"], 5)
        self.assertEqual(cat["empty"], 2)
        self.assertEqual(cat["outside_raw"], 1)
        self.assertEqual(cat["standard_with_concept"], 4)
        marks = self.m.entity_type_marks(cat)
        self.assertEqual(marks["total"], 15)
        self.assertEqual(marks["strict"]["無法由現有資料判定"], 5)
        self.assertEqual(marks["scheme_A_concept_as_unknown"]["未知"], 7)
        self.assertEqual(marks["scheme_B_concept_as_real"]["已解決"], 12)
        for scheme in ("strict", "scheme_A_concept_as_unknown", "scheme_B_concept_as_real"):
            self.assertEqual(sum(marks[scheme].values()), 15)


class RelAndArticleTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module(MODULE)

    def test_rel_tally(self):
        t = self.m.tally_rel_types([("HAS", False, 3), ("RELATED_TO", False, 5), ("RELATED_TO", True, 2), (None, False, 1)])
        self.assertEqual(t, {"declared_non_related_to": 3, "related_to_with_verb": 5, "related_to_empty_verb": 2, "rel_type_null": 1})
        marks = self.m.rel_type_marks(t)
        self.assertEqual(marks["strict"]["已解決"], 3)
        self.assertEqual(sum(marks["strict"].values()), 11)
        self.assertEqual(sum(marks["scheme_RD_related_to_as_unknown"].values()), 11)

    def test_ve_tally(self):
        t = self.m.tally_edge_verb_embedding([("RELATED_TO", True, 4), ("RELATED_TO", False, 1), ("HAS", False, 2)])
        self.assertEqual(t["related_to_with_ve"], 4)
        self.assertEqual(t["related_to_without_ve"], 1)
        self.assertEqual(t["other_without_ve"], 2)

    def test_article_scope_document_level_no_sentinel(self):
        by_doc = {"lawA": ["第1條", None, "第2條"], "plainB": [None, None, ""]}
        t = self.m.tally_article_scope(by_doc)
        self.assertEqual(t, {"known": 2, "unknown": 1, "not_applicable": 3})

    def test_citations_by_doc(self):
        out = self.m.citations_by_doc([[{"source_doc_id": "d1", "article_no": "1"}, {"article_no": None}], [{"source_doc_id": "d1", "article_no": None}]])
        self.assertEqual(out, {"d1": ["1", None], "None": [None]})


class EmptiesAndBaselineTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module(MODULE)

    def test_classify(self):
        c = self.m.classify_fact_empties
        self.assertEqual(c(False, False, False), "complete")
        self.assertEqual(c(False, True, True), "unknown_determinate")
        self.assertEqual(c(True, True, True), "unknown_determinate")
        self.assertEqual(c(False, True, False), "pending_needs_human_or_llm")
        self.assertEqual(c(True, False, False), "pending_needs_human_or_llm")
        self.assertEqual(c(False, False, True), "pending_needs_human_or_llm")

    def test_tally(self):
        t = self.m.tally_fact_empties([(False, False, False, 90), (False, True, True, 2), (False, True, False, 5), (True, False, False, 3)])
        self.assertEqual(t["facts_total"], 100)
        self.assertEqual(t["facts_with_any_empty"], 10)
        self.assertEqual(t["single_counts"], {"empty_subject": 3, "empty_object": 7, "empty_verb": 2})
        self.assertEqual(t["categories"]["unknown_determinate"], 2)

    def test_baseline_partition_and_shares(self):
        ent = {"empty": 1, "concept_only": 4, "standard": 3, "standard_with_concept": 1, "outside_raw": 1}
        rel = {"declared_non_related_to": 2, "related_to_with_verb": 7, "related_to_empty_verb": 1, "rel_type_null": 0}
        art = {"known": 8, "not_applicable": 2, "unknown": 0}
        emp = self.m.tally_fact_empties([(False, True, True, 1), (False, True, False, 3), (False, False, False, 6)])
        b = self.m.build_baseline(ent, rel, art, emp, {})
        for k, v in b.items():
            self.assertTrue(v["partition_ok"], k)
            self.assertEqual(v["already_explicitly_marked"], 0)
        self.assertEqual(b["entity_type"]["needs_human_or_llm"], 4)
        self.assertEqual(b["relation_type"]["derivable_read_only"], 2)
        self.assertEqual(b["source_article_no"]["derivable_read_only_share"], 1.0)
        self.assertEqual(b["empty_fields_among_facts_with_any_empty"]["population"], 4)
        self.assertEqual(b["empty_fields_among_facts_with_any_empty"]["derivable_read_only"], 1)

    def test_find_marker_keys(self):
        out = self.m.find_marker_keys([("Entity", "name", 5), ("Entity", "type_status", 2), ("Fact", "rel_origin", 1)])
        self.assertEqual([x["key"] for x in out], ["type_status", "rel_origin"])


class EnvReaderTest(unittest.TestCase):
    def test_read_env_value_does_not_touch_environ(self):
        import tempfile
        m = importlib.import_module(MODULE)
        before = dict(os.environ)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('A=1\nNEO4J_PASSWORD="s3cret"\n', encoding="utf-8")
            self.assertEqual(m.read_env_value(p, "NEO4J_PASSWORD"), "s3cret")
            self.assertIsNone(m.read_env_value(p, "MISSING"))
        self.assertEqual(before, dict(os.environ))


if __name__ == "__main__":
    unittest.main()
