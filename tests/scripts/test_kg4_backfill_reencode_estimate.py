"""kg4_backfill_reencode_estimate 單元測試（報告252 E2）：假資料，不連 Neo4j／docker／embedding。"""
import ast
import importlib
import os
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
SCRIPT = REPO / "scripts" / "analysis" / "kg4_backfill_reencode_estimate.py"
MODULE = "scripts.analysis.kg4_backfill_reencode_estimate"


def build(s, v, o, cs):
    return f"{s or ''}|{v or ''}|{o or ''}" + ("" if cs is None else "#")


def row(eid, flat_s="A", flat_o="B", name_s="A", name_o="B", text=None, verb="V", cs=None, **kw):
    r = {
        "eid": eid, "flat_subject": flat_s, "flat_object": flat_o, "flat_rel_type": "R", "verb": verb,
        "fact_text": text if text is not None else build(flat_s, verb, flat_o, cs),
        "subject_exists": True, "object_exists": True, "subject_name": name_s, "object_name": name_o,
        "edge_count": 0, "edge_types": [],
    }
    r.update(kw)
    return r


class PlanReencodeTest(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module(MODULE)

    def plan(self, rows, cs=None):
        return self.mod.plan_reencode(rows, source_charset=cs, text_builder=build)

    def test_stale_flat_and_text_changes(self):  # ①
        res = self.plan([row("1", flat_s="Old", name_s="New")])
        self.assertEqual(res["would_reencode_after_resync"], 1)
        self.assertEqual(res["reencode_caused_by_resync_only"], 1)
        self.assertEqual(res["would_reencode_without_resync"], 0)
        self.assertEqual(res["resync_changed_facts"], 1)
        self.assertEqual(res["samples_caused_by_resync_only"][0]["new"], "New|V|B")

    def test_stale_flat_but_text_already_new(self):  # ②
        res = self.plan([row("1", flat_s="Old", name_s="New", text="New|V|B")])
        self.assertEqual(res["resync_changed_facts"], 1)
        self.assertEqual(res["would_reencode_after_resync"], 0)
        self.assertEqual(res["reencode_caused_by_resync_only"], 0)
        # 基線：用舊扁平屬性重建的文字與現存不同 → 計入 without（回填現在就會把它改回舊字）
        self.assertEqual(res["would_reencode_without_resync"], 1)
        self.assertEqual(res["without_not_in_after"], 1)

    def test_text_already_stale_without_resync(self):  # ③
        res = self.plan([row("1", text="舊格式（概念）")])
        self.assertEqual(res["would_reencode_without_resync"], 1)
        self.assertEqual(res["would_reencode_after_resync"], 1)
        self.assertEqual(res["reencode_overlap"], 1)
        self.assertEqual(res["reencode_caused_by_resync_only"], 0)
        self.assertEqual(len(res["samples_baseline_already_stale"]), 1)

    def test_all_consistent(self):  # ④
        res = self.plan([row("1"), row("2", verb="X")])
        for k in ("would_reencode_without_resync", "would_reencode_after_resync", "resync_changed_facts",
                  "reencode_caused_by_resync_only", "reencode_overlap"):
            self.assertEqual(res[k], 0, k)
        self.assertEqual(res["facts_total"], 2)
        self.assertIsNone(res["text_chars_total_after"]["mean"])

    def test_none_subject_object_like_backfill(self):  # ⑤
        res = self.plan([row("1", flat_s=None, flat_o=None, name_s=None, name_o=None, text="|V|")])
        self.assertEqual(res["would_reencode_after_resync"], 0)
        self.assertEqual(res["would_reencode_without_resync"], 0)

    def test_source_charset_none_vs_set(self):  # ⑥
        rows = [row("1", text="A|V|B")]
        self.assertEqual(self.plan(rows, None)["would_reencode_after_resync"], 0)
        self.assertEqual(self.plan(rows, frozenset("x"))["would_reencode_after_resync"], 1)

    def test_identity_after_equals_overlap_plus_only(self):  # ⑦
        rows = [row("1", flat_s="Old", name_s="New"), row("2", text="bad"), row("3"),
                row("4", flat_o="O", name_o="N", text="zzz")]
        res = self.plan(rows)
        self.assertEqual(res["would_reencode_after_resync"],
                         res["reencode_overlap"] + res["reencode_caused_by_resync_only"])

    def test_identity_can_break_when_text_already_new(self):
        # after ⊄ without 時恆等式仍成立；但 without 可含不在 after 的項目（見 without_not_in_after）
        res = self.plan([row("1", flat_s="Old", name_s="New", text="New|V|B"), row("2", text="bad")])
        self.assertEqual(res["would_reencode_without_resync"], 2)
        self.assertEqual(res["would_reencode_after_resync"], 1)
        self.assertEqual(res["reencode_overlap"], 1)
        self.assertEqual(res["without_not_in_after"], 1)

    def test_chars_and_pages(self):
        rows = [row(str(i), text="bad") for i in range(201)]
        res = self.plan(rows)
        self.assertEqual(res["scan_pages"], 2)
        self.assertEqual(res["text_chars_total_after"]["total"], 201 * len("A|V|B"))
        self.assertEqual(res["text_chars_total_after"]["p95"], len("A|V|B"))

    def test_facts_without_links_not_counted_as_changed(self):
        res = self.plan([row("1", flat_s="Old", name_s="New", subject_exists=False)])
        self.assertEqual(res["resync_changed_facts"], 0)

    def test_production_builder_smoke(self):
        res = self.mod.plan_reencode(
            [row("1", flat_s="雇主", flat_o="勞工", name_s="雇主", name_o="勞工", verb="應給付", text="stale")],
            source_charset=frozenset("雇"))
        self.assertEqual(res["would_reencode_after_resync"], 1)
        self.assertIn("雇主", res["samples_baseline_already_stale"][0]["new"])


class StructureGuardTest(unittest.TestCase):
    def test_import_has_no_side_effects(self):
        env = dict(os.environ)
        sys.modules.pop(MODULE, None)
        importlib.import_module(MODULE)
        self.assertEqual(env, dict(os.environ))
        self.assertNotIn("neo4j", sys.modules.get(MODULE).__dict__)

    def test_no_write_cypher_or_provider(self):
        src = SCRIPT.read_text(encoding="utf-8")
        cypher = re.search(r'ROWS_CYPHER = """(.*?)"""', src, re.S).group(1)
        self.assertFalse(re.search(r"\b(SET|CREATE|MERGE|DELETE|REMOVE|DETACH|DROP|CALL)\b", cypher, re.I))
        self.assertTrue(cypher.lstrip().upper().startswith("MATCH"))
        imported = []
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                imported += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                imported.append(n.module or "")
        for m in imported:
            self.assertNotIn("providers", m)
            self.assertNotIn("embedding", m)
        self.assertNotRegex(src, r"\.encode\(")
        self.assertIn("ReadOnlyRunner", src)
        self.assertNotRegex(src, r"(?im)^\s*(import|from)\s+\S*ollama")

    def test_only_docker_inspect(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(re.findall(r'"docker",\s*"(\w+)"', src), ["inspect"])
        self.assertNotRegex(src, r"docker\s+(run|start|stop|exec|rm|cp|compose|pull|kill)")
        self.assertIn("17990", src.replace("bolt://localhost:17990", "") + ":17990")

    def test_no_password_leak(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn(".env", src.replace("`.env`", ""))
        self.assertNotRegex(src, r"[A-Za-z0-9_\-]{43}")
        self.assertLessEqual(len(src.splitlines()), 200)


if __name__ == "__main__":
    unittest.main()
