import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class ConceptEntitySamplingPureTest(unittest.TestCase):
    def setUp(self):
        self.m = importlib.import_module("scripts.analysis.concept_entity_sampling")

    def test_import_does_not_touch_environment_or_load_neo4j(self):
        before_env = dict(os.environ)
        before = set(sys.modules)
        sys.modules.pop("scripts.analysis.concept_entity_sampling", None)
        importlib.import_module("scripts.analysis.concept_entity_sampling")
        self.assertEqual(before_env, dict(os.environ))
        loaded = set(sys.modules) - before
        self.assertFalse(any(name == "neo4j" or name.startswith("neo4j.") for name in loaded))

    def test_seeded_sample_is_reproducible_and_without_replacement(self):
        rows = [{"name": f"名稱{i:03d}", "type": "概念"} for i in range(100)]
        one = self.m.sample_entities(rows, seed=12, size=10)
        two = self.m.sample_entities(rows, seed=12, size=10)
        self.assertEqual([x["name"] for x in one], [x["name"] for x in two])
        self.assertEqual(len({x["name"] for x in one}), 10)

    def test_degree_counts_self_loop_twice(self):
        edges = [
            {"subject": "甲", "object": "乙"},
            {"subject": "乙", "object": "甲"},
            {"subject": "甲", "object": "甲"},
        ]
        self.assertEqual(self.m.degrees_for_entities({"甲", "乙"}, edges), {"甲": 4, "乙": 2})

    def test_facts_are_limited_per_entity_and_include_both_roles(self):
        rows = [{
            "subject": "甲", "object": "乙", "rel_type": "RELATED_TO",
            "citations": json.dumps([{"source_doc_id": "d", "source_svo_chunk_index": 1, "verb": "連結"}]),
        }]
        facts = self.m.facts_for_entities({"甲", "乙"}, rows, {"d": "doc"}, limit=12)
        self.assertEqual(facts["甲"][0]["entity_role"], "主詞")
        self.assertEqual(facts["乙"][0]["entity_role"], "受詞")

    def test_apply_annotations_defaults_to_question_u(self):
        rows = [{"sample_key": "x", "sample_number": 1, "name": "甲"}]
        out = self.m.apply_draft_annotations(rows, {})
        self.assertEqual(out[0]["label"], "U")
        self.assertTrue(out[0]["question"])

    def test_read_env_value_does_not_touch_environment(self):
        before = dict(os.environ)
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text('NEO4J_PASSWORD="secret"\n', encoding="utf-8")
            self.assertEqual(self.m.read_env_value(env, "NEO4J_PASSWORD"), "secret")
        self.assertEqual(before, dict(os.environ))


if __name__ == "__main__":
    unittest.main()
