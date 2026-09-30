import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.eval.kg_source_recall_probe import (  # noqa: E402
    SourceResolver,
    b1_texts,
    dedup_sources,
    measure,
    strip_len,
    take_by_budget,
)
from services.document_record_service import document_uuid  # noqa: E402


def _make_kg(root: Path) -> None:
    for doc, chunks in {
        "DOC_A": [
            {"index": 1, "text": "第 1 條 甲事項應辦理。", "article_no": "第 1 條"},
            {"index": 2, "text": "第 2 條 乙事項得辦理。", "article_no": "第 2 條"},
        ],
        "DOC_B": [{"index": 1, "text": "無條號的一般段落。", "article_no": None}],
    }.items():
        d = root / doc
        d.mkdir(parents=True)
        (d / "svo_index.json").write_text(json.dumps({"source": doc, "chunks": chunks}, ensure_ascii=False), encoding="utf-8")


def _cand(doc, **kw):
    base = {"kind": "fact", "rank": 0, "text": "x", "source_doc_id": str(document_uuid(doc)),
            "source_svo_chunk_index": None, "article_no": None, "in_prompt": True}
    base.update(kw)
    return base


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _make_kg(self.root)
        self.r = SourceResolver(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_chunk_index_path(self):
        res = self.r.resolve(_cand("DOC_A", source_svo_chunk_index=2))
        self.assertTrue(res.ok)
        self.assertEqual(res.reason, "chunk_index")
        self.assertIn("乙事項", res.text)

    def test_article_no_path_wins_over_index(self):
        res = self.r.resolve(_cand("DOC_A", article_no="第 2 條", source_svo_chunk_index=1))
        self.assertTrue(res.ok)
        self.assertEqual(res.reason, "article_no")
        self.assertIn("乙事項", res.text)

    def test_unresolved_reasons_are_distinct(self):
        self.assertEqual(self.r.resolve(_cand("DOC_A")).reason, "no_chunk_index")
        self.assertEqual(self.r.resolve(_cand("DOC_A", source_svo_chunk_index=99)).reason, "chunk_index_not_found")
        self.assertEqual(self.r.resolve(_cand("NOPE", source_svo_chunk_index=1)).reason, "doc_not_found")
        self.assertEqual(self.r.resolve(_cand("DOC_A", source_doc_id=None)).reason, "no_source_doc_id")

    def test_dedup_keeps_first_rank_and_counts_unresolved(self):
        cands = [
            _cand("DOC_A", rank=0, source_svo_chunk_index=2),
            _cand("DOC_B", rank=1, source_svo_chunk_index=1),
            _cand("DOC_A", rank=2, source_svo_chunk_index=2),  # 重複
            _cand("DOC_A", rank=3),  # 無 chunk index
        ]
        paras, unresolved = dedup_sources(cands, self.r)
        self.assertEqual([(p["doc_id"], p["chunk_index"]) for p in paras], [("DOC_A", 2), ("DOC_B", 1)])
        self.assertEqual(paras[0]["first_rank"], 0)
        self.assertEqual([u["reason"] for u in unresolved], ["no_chunk_index"])


class MeasureTest(unittest.TestCase):
    def test_strict_substring_ignores_whitespace(self):
        m = measure(["甲 事項\n應辦理"], ["甲事項應辦理", "不存在"], [])
        self.assertEqual(m["hit"], ["甲事項應辦理"])
        self.assertEqual(m["missed"], ["不存在"])
        self.assertEqual(m["recall_rate"], 0.5)
        self.assertEqual(m["char_count"], strip_len("甲 事項\n應辦理"))

    def test_take_by_budget_stops_before_exceeding(self):
        paras = [{"text": "a" * 10}, {"text": "b" * 10}, {"text": "c" * 10}]
        self.assertEqual(len(take_by_budget(paras, 25)), 2)
        self.assertEqual(take_by_budget(paras, 5), [])

    def test_b1_texts_parses_chunk_ids(self):
        index = {("N0030006_勞工請假規則", 0): "T0", ("N0030006_勞工請假規則", 1): "T1"}
        rec = {"lineage": {"stage1_retrieval": {"retrieved_chunk_ids": ["N0030006_勞工請假規則_1", "X_9", "N0030006_勞工請假規則_0"]}}}
        texts, missing = b1_texts(rec, index)
        self.assertEqual(texts, ["T1", "T0"])
        self.assertEqual(missing, ["X_9"])


if __name__ == "__main__":
    unittest.main()
