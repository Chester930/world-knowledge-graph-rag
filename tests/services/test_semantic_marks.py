import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODULE = "services.semantic_marks"
CORE = {"PERSON": "Person", "PLACE": "Place"}
EXT = {"ORGANIZATION": "Organization", "LEGISLATION": "Legislation"}


def _m():
    return importlib.import_module(MODULE)


class ImportIsolationTest(unittest.TestCase):
    def test_import_has_no_side_effect_and_no_heavy_dependency(self):
        before_env = dict(os.environ)
        before_mods = set(sys.modules)
        sys.modules.pop(MODULE, None)
        importlib.import_module(MODULE)
        self.assertEqual(before_env, dict(os.environ))
        new = set(sys.modules) - before_mods
        for heavy in ("neo4j", "core", "routers", "repositories"):
            self.assertFalse(any(x == heavy or x.startswith(heavy + ".") for x in new), heavy)
        other_services = {x for x in new if x.startswith("services.") and x != MODULE}
        self.assertEqual(other_services, set())

    def test_provisional_and_value_domain(self):
        m = _m()
        self.assertIs(m.PROVISIONAL, True)
        self.assertEqual(set(m.MARKS), {"已解決", "不適用", "未知", "尚未處理", "無法由現有資料判定"})
        self.assertEqual(m.CONCEPT_SCHEMES, ("A", "B", "strict"))


class IsBlankTest(unittest.TestCase):
    def test_cases(self):
        m = _m()
        self.assertTrue(m.is_blank(None))
        self.assertTrue(m.is_blank(""))
        self.assertTrue(m.is_blank("   \t\n"))
        self.assertTrue(m.is_blank("　"))
        self.assertFalse(m.is_blank("x"))
        self.assertFalse(m.is_blank(0))


class EntityTypeTest(unittest.TestCase):
    def test_classify_branches(self):
        c = _m().classify_entity_type_value
        self.assertEqual(c(None, CORE, EXT), "empty")
        self.assertEqual(c("", CORE, EXT), "empty")
        self.assertEqual(c("  ", CORE, EXT), "empty")
        self.assertEqual(c(" , ,", CORE, EXT), "empty")
        self.assertEqual(c("概念", CORE, EXT), "concept_only")
        self.assertEqual(c(" 概念 ", CORE, EXT), "concept_only")
        self.assertEqual(c("概念,概念", CORE, EXT), "concept_only")
        self.assertEqual(c("Person", CORE, EXT), "standard")
        self.assertEqual(c("Organization", CORE, EXT), "standard")
        self.assertEqual(c("概念,Person", CORE, EXT), "standard_with_concept")
        self.assertEqual(c("ACTIVITY", CORE, EXT), "outside_raw")
        self.assertEqual(c("Person,ACTIVITY", CORE, EXT), "outside_raw")
        self.assertEqual(c("概念,ACTIVITY", CORE, EXT), "outside_raw")

    def test_case_underscore_and_multivalue_variants(self):
        c = _m().classify_entity_type_value
        self.assertEqual(c("person", CORE, EXT), "standard")
        self.assertEqual(c("PERSON", CORE, EXT), "standard")
        self.assertEqual(c("Legis_lation", CORE, EXT), "standard")
        self.assertEqual(c("place, organization", CORE, EXT), "standard")
        self.assertEqual(c("Person , Place", CORE, EXT), "standard")

    def test_mark_default_scheme_is_A(self):
        m = _m()
        self.assertEqual(m.mark_entity_type("概念", CORE, EXT), m.UNKNOWN)

    def test_mark_all_schemes_for_concept_only(self):
        m = _m()
        self.assertEqual(m.mark_entity_type("概念", CORE, EXT, "A"), m.UNKNOWN)
        self.assertEqual(m.mark_entity_type("概念", CORE, EXT, "B"), m.RESOLVED)
        self.assertEqual(m.mark_entity_type("概念", CORE, EXT, "strict"), m.INDETERMINATE)

    def test_mark_non_concept_independent_of_scheme(self):
        m = _m()
        for scheme in m.CONCEPT_SCHEMES:
            self.assertEqual(m.mark_entity_type(None, CORE, EXT, scheme), m.UNKNOWN)
            self.assertEqual(m.mark_entity_type("", CORE, EXT, scheme), m.UNKNOWN)
            self.assertEqual(m.mark_entity_type("Person", CORE, EXT, scheme), m.RESOLVED)
            self.assertEqual(m.mark_entity_type("概念,Person", CORE, EXT, scheme), m.RESOLVED)
            self.assertEqual(m.mark_entity_type("法律法规", CORE, EXT, scheme), m.PENDING)

    def test_invalid_scheme_rejected(self):
        with self.assertRaises(ValueError):
            _m().mark_entity_type("概念", CORE, EXT, "C")


class RelationTypeTest(unittest.TestCase):
    def test_branches(self):
        m = _m()
        self.assertEqual(m.mark_relation_type("HAS"), m.RESOLVED)
        self.assertEqual(m.mark_relation_type("PERMITS"), m.RESOLVED)
        self.assertEqual(m.mark_relation_type("RELATED_TO"), m.INDETERMINATE)
        self.assertEqual(m.mark_relation_type(" RELATED_TO "), m.INDETERMINATE)
        self.assertEqual(m.mark_relation_type(None), m.INDETERMINATE)
        self.assertEqual(m.mark_relation_type(""), m.INDETERMINATE)
        self.assertEqual(m.mark_relation_type("  "), m.INDETERMINATE)

    def test_signature_has_no_verb_embedding_input(self):
        import inspect
        params = inspect.signature(_m().mark_relation_type).parameters
        self.assertEqual(list(params), ["rel_type"])


class ArticleNoTest(unittest.TestCase):
    def test_has_article_no_does_not_use_truthiness(self):
        m = _m()
        self.assertTrue(m.has_article_no("第1條"))
        self.assertTrue(m.has_article_no("0"))  # 真值字串即使看似「假」也是有內容
        self.assertFalse(m.has_article_no(""))
        self.assertFalse(m.has_article_no("  "))
        self.assertFalse(m.has_article_no(None))
        self.assertFalse(m.has_article_no(0))  # 非字串不是條號
        self.assertFalse(m.has_article_no(["第1條"]))

    def test_document_has_any(self):
        m = _m()
        self.assertTrue(m.document_has_any_article_no([None, "", "第2條"]))
        self.assertFalse(m.document_has_any_article_no([None, "", " "]))
        self.assertFalse(m.document_has_any_article_no([]))

    def test_mark_article_no(self):
        m = _m()
        self.assertEqual(m.mark_article_no("第1條", True), m.RESOLVED)
        self.assertEqual(m.mark_article_no("第1條", False), m.RESOLVED)
        self.assertEqual(m.mark_article_no(None, True), m.UNKNOWN)
        self.assertEqual(m.mark_article_no("", True), m.UNKNOWN)
        self.assertEqual(m.mark_article_no(None, False), m.NOT_APPLICABLE)
        self.assertEqual(m.mark_article_no("", False), m.NOT_APPLICABLE)

    def test_sentinel_strings_are_never_produced_or_special_cased(self):
        m = _m()
        # 哨兵字串（如 "N/A"）只是一般字串：被當成「有條號」，且標示值不會被當成資料回寫
        self.assertEqual(m.mark_article_no("N/A", False), m.RESOLVED)
        for mark in m.MARKS:
            self.assertEqual(m.mark_article_no(mark, False), m.RESOLVED)

    def test_by_document(self):
        m = _m()
        out = m.mark_citations_by_document({"lawA": ["第1條", None, "第2條"], "plainB": [None, None, ""]})
        self.assertEqual(out[m.RESOLVED], 2)
        self.assertEqual(out[m.UNKNOWN], 1)
        self.assertEqual(out[m.NOT_APPLICABLE], 3)
        self.assertEqual(sum(out.values()), 6)


class FactFieldsTest(unittest.TestCase):
    def test_all_eight_combinations(self):
        m = _m()
        f = m.mark_fact_fields
        self.assertEqual(f("甲", "乙", "丙"), m.RESOLVED)
        self.assertEqual(f("甲", "乙", ""), m.PENDING)
        self.assertEqual(f("甲", "", "丙"), m.PENDING)
        self.assertEqual(f("甲", "", ""), m.UNKNOWN)
        self.assertEqual(f("", "乙", "丙"), m.PENDING)
        self.assertEqual(f("", "乙", ""), m.PENDING)
        self.assertEqual(f("", "", "丙"), m.PENDING)
        self.assertEqual(f("", "", ""), m.UNKNOWN)

    def test_none_and_whitespace_equal_empty(self):
        m = _m()
        self.assertEqual(m.mark_fact_fields(None, None, None), m.UNKNOWN)
        self.assertEqual(m.mark_fact_fields("甲", "  ", "\t"), m.UNKNOWN)
        self.assertEqual(m.mark_fact_fields("甲", None, "丙"), m.PENDING)


if __name__ == "__main__":
    unittest.main()
