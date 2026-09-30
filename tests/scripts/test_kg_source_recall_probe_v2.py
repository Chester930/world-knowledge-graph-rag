import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.eval.kg_source_recall_probe_v2 import triple_candidates  # noqa: E402


class TripleCandidatesTest(unittest.TestCase):
    CITES = [
        {"source_doc_id": "d1", "source_svo_chunk_index": 2, "article_no": "第 2 條"},
        {"source_doc_id": "d2", "source_svo_chunk_index": 5, "article_no": None},
        {"source_doc_id": "d2", "source_svo_chunk_index": 5, "article_no": None},
    ]

    def test_last_takes_only_latest_citation(self):
        out = triple_candidates({"citations": self.CITES}, "last")
        self.assertEqual([(c["source_doc_id"], c["source_svo_chunk_index"]) for c in out], [("d2", 5)])

    def test_all_dedups_citations(self):
        out = triple_candidates({"citations": self.CITES}, "all")
        self.assertEqual([(c["source_doc_id"], c["source_svo_chunk_index"]) for c in out], [("d1", 2), ("d2", 5)])
        self.assertEqual(out[0]["article_no"], "第 2 條")

    def test_no_citations_gives_no_candidates(self):
        self.assertEqual(triple_candidates({"citations": []}, "last"), [])


if __name__ == "__main__":
    unittest.main()
