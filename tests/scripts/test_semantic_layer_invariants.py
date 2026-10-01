import importlib
import json
import os
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MODULE = "scripts.analysis.semantic_layer_invariants"


def _fresh_import():
    saved = sys.modules.pop(MODULE, None)
    try:
        return importlib.import_module(MODULE)
    finally:
        if saved is not None:
            sys.modules[MODULE] = saved


class ImportHasNoSideEffectTest(unittest.TestCase):
    """匯入不得改 os.environ、不得匯入 neo4j／core／services（B1／C3／D2 的教訓）。"""

    def test_import_does_not_touch_environ_or_import_heavy_modules(self):
        before_env = dict(os.environ)
        before_mods = set(sys.modules)
        sys.modules.pop(MODULE, None)
        try:
            importlib.import_module(MODULE)
        finally:
            sys.modules.pop(MODULE, None)
        self.assertEqual(before_env, dict(os.environ))
        new_mods = set(sys.modules) - before_mods
        heavy = [m for m in new_mods if m == "neo4j" or m.startswith(("neo4j.", "core.", "services.", "routers."))]
        self.assertEqual(heavy, [])


class ReadOnlyGuardTest(unittest.TestCase):
    def setUp(self):
        self.m = _fresh_import()

    def test_allowed_queries_pass(self):
        for q in (
            "MATCH (n) RETURN count(n) AS v",
            "  MATCH (e:Entity {kg_id: $k}) WHERE e.offset = 1 RETURN e",  # offset 不是 SET
            "UNWIND $rows AS r MATCH (n) RETURN n",
            "CALL db.labels() YIELD label RETURN label",
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType",
            "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey",
            "SHOW CONSTRAINTS",
            "SHOW INDEXES",
        ):
            self.m.assert_read_only(q)

    def test_write_and_non_whitelisted_calls_are_rejected(self):
        for q in (
            "CREATE (n:X)",
            "MERGE (n:X {a: 1})",
            "MATCH (n) SET n.x = 1",
            "MATCH (n) DELETE n",
            "MATCH (n) DETACH DELETE n",
            "DROP INDEX foo",
            "MATCH (n) REMOVE n.x",
            "CALL db.createLabel('X')",
            "CALL db.create.setNodeVectorProperty(1, 'a', [1.0])",
            "CALL db.index.fulltext.createNodeIndex('a', ['B'], ['c'])",
            "CALL db.index.vector.queryNodes('i', 1, [1.0])",
            "CALL db.labels() YIELD label CALL db.createLabel(label)",
            "RETURN 1",
            "LOAD CSV FROM 'file:///x' AS r RETURN r",
        ):
            with self.assertRaises(ValueError, msg=q):
                self.m.assert_read_only(q)


class PureFunctionsTest(unittest.TestCase):
    def setUp(self):
        self.m = _fresh_import()

    def test_percentile_and_describe(self):
        d = self.m.describe([1, 1, 2, 10])
        self.assertEqual((d["n"], d["min"], d["max"], d["median"]), (4, 1, 10, 1.5))
        self.assertEqual(d["share_eq_1"], 0.5)
        self.assertEqual(self.m.percentile([1, 2, 3, 4, 5], 0.9), 5)
        self.assertEqual(self.m.describe([]), {"n": 0})

    def test_parse_citations_and_key_stats(self):
        good = json.dumps([{"source_doc_id": "d1", "verb": "依", "article_no": None}, {"source_doc_id": "d2", "verb": "應"}])
        self.assertEqual(len(self.m.parse_citations(good)), 2)
        self.assertEqual(self.m.parse_citations("not json"), [])
        self.assertEqual(self.m.parse_citations(None), [])
        stats = self.m.citation_key_stats([self.m.parse_citations(good)])
        self.assertEqual(stats["citations"], 2)
        self.assertEqual(stats["keys"]["article_no"], {"present": 1, "non_null": 0})
        self.assertEqual(stats["keys"]["verb"], {"present": 2, "non_null": 2})

    def test_distinct_verbs_and_opposing(self):
        cits = [{"verb": "得"}, {"verb": " 得 "}, {"verb": "不得"}, {"verb": ""}]
        self.assertEqual(self.m.distinct_verbs(cits), ["得", "不得"])
        self.assertTrue(self.m.has_opposing_verbs(["得請假", "不得拒絕"]))
        self.assertFalse(self.m.has_opposing_verbs(["應", "得"]))
        self.assertEqual(self.m.verb_polarity("屬於"), "neutral")

    def test_normalize_entity_name(self):
        self.assertEqual(self.m.normalize_entity_name("ＡＢＣ 公司"), "abc公司")
        self.assertEqual(self.m.normalize_entity_name(" 勞工　"), "勞工")

    def test_aliases_stats(self):
        s = self.m.aliases_stats([("a", ["a", "b"]), ("c", None), ("d", ["x", "x"]), ("e", [])])
        self.assertEqual(s["entities"], 4)
        self.assertEqual(s["aliases_null"], 1)
        self.assertEqual(s["name_not_in_aliases"], 2)  # d、e
        self.assertEqual(s["aliases_has_duplicates"], 1)
        self.assertEqual(s["aliases_empty_list"], 1)

    def test_classify_type_tokens(self):
        core = {self.m.normalize_type_key("Person"): "Person"}
        ext = {self.m.normalize_type_key("LocalBusiness"): "LocalBusiness"}
        self.assertEqual(self.m.classify_type_tokens("Person, local_business,公司", core, ext),
                         [("Person", "core"), ("local_business", "extended"), ("公司", "outside")])
        self.assertEqual(self.m.classify_type_tokens("  ", core, ext), [])
        self.assertEqual(self.m.classify_type_tokens(None, core, ext), [])

    def test_value_flags(self):
        f = self.m.value_flags("新臺幣四千元")
        self.assertTrue(f["quantity"] and f["any"])
        self.assertTrue(self.m.value_flags("年齡六歲以上未滿十二歲者")["comparator"])
        self.assertTrue(self.m.value_flags("第二十七條")["ordinal"])
        self.assertTrue(self.m.value_flags("第一類事業")["any"])
        self.assertFalse(self.m.value_flags("雇主")["any"])

    def test_degrees_and_vocab_check(self):
        deg = self.m.degrees_from_edges([("a", "b"), ("a", "c"), ("d", "d")])
        self.assertEqual((deg["a"], deg["b"], deg["c"], deg["d"]), (2, 1, 1, 2))
        chk = self.m.rel_type_vocab_check({"RELATED_TO": 5, "FOO": 2}, {"RELATED_TO"})
        self.assertEqual(chk["outside_count"], 2)
        self.assertEqual(chk["outside_declared"], {"FOO": 2})


if __name__ == "__main__":
    unittest.main()
