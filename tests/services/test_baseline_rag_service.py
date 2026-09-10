"""services/baseline_rag_service.py（B0／B1 檢索側）單元測試。

不碰 Neo4j／embedding provider／檔案系統——用確定性的假向量與假 meta。
"""
import numpy as np
import pytest

from services import baseline_rag_service as svc


# ── tokenize_zh ────────────────────────────────────────────────────

def test_tokenize_zh_produces_char_bigrams():
    assert svc.tokenize_zh("四十公斤") == ["四十", "十公", "公斤"]


def test_tokenize_zh_strips_whitespace():
    assert svc.tokenize_zh("三十 日") == ["三十", "十日"]


def test_tokenize_zh_short_input():
    assert svc.tokenize_zh("日") == ["日"]
    assert svc.tokenize_zh("") == []


# ── rrf_fuse ───────────────────────────────────────────────────────

def test_rrf_fuse_single_ranking_is_identity():
    assert svc.rrf_fuse([[2, 0, 1]]) == [2, 0, 1]


def test_rrf_fuse_combines_two_rankings_by_cormack_formula():
    # dense 偏好 0,1,2；bm25 偏好 2,1,0。k=60：
    #   idx0 = 1/60 + 1/62 ≈ 0.032796
    #   idx1 = 1/61 + 1/61 ≈ 0.032787  ← 因 1/x 凸性，兩邊都 rank1 反而最低
    #   idx2 = 1/62 + 1/60 ≈ 0.032796  ← 與 idx0 同分
    # → idx0、idx2 同分居前，由第一個 ranking（dense）順序 tie-break（0 在 2 前）。
    fused = svc.rrf_fuse([[0, 1, 2], [2, 1, 0]])
    assert fused == [0, 2, 1]


def test_rrf_fuse_missing_from_one_ranking_still_scored():
    fused = svc.rrf_fuse([[0, 1], [1]])
    assert fused[0] == 1  # 1 兩路都有、分數最高
    assert set(fused) == {0, 1}


# ── search_baseline ───────────────────────────────────────────────

@pytest.fixture
def index():
    meta = [
        {"source": "N0000001", "chunk_index": 0, "chunk_text": "勞工特別休假日數規定"},
        {"source": "N0000002", "chunk_index": 0, "chunk_text": "雇主應給予謀職假"},
        {"source": "N0000003", "chunk_index": 0, "chunk_text": "四十公斤以上物體之人力搬運屬重體力勞動"},
        {"source": "N0000004", "chunk_index": 0, "chunk_text": "高溫作業黑球溫度五十度"},
    ]
    # question_vector 固定為 [1,0,0]；cosine 由第一分量主導 → dense 排序 0,1,3,2
    vectors = np.array([
        [0.9, 0.1, 0.0],
        [0.8, 0.2, 0.0],
        [0.1, 0.9, 0.0],
        [0.2, 0.8, 0.0],
    ], dtype=np.float32)
    return vectors, meta


def test_search_baseline_b0_dense_only(index):
    vectors, meta = index
    hits = svc.search_baseline(
        "任意問題", [1.0, 0.0, 0.0], vectors, meta, top_k=2, hybrid=False
    )
    assert [h["chunk_index"] for h in hits] == [0, 0]
    assert [h["source"] for h in hits] == ["N0000001", "N0000002"]
    assert hits[0]["score"] > hits[1]["score"]  # dense cosine 由高到低
    assert hits[0]["bm25_rank"] is None  # 沒跑 BM25
    assert hits[0]["reranked"] is False


def test_search_baseline_b1_hybrid_bm25_pulls_up_lexical_match(index):
    vectors, meta = index
    # 問句 dense 仍偏好 0,1（question_vector 不變），但 BM25 因逐字重疊強推 idx2。
    hits = svc.search_baseline(
        "四十公斤 人力搬運", [1.0, 0.0, 0.0], vectors, meta, top_k=2, hybrid=True
    )
    sources = {h["source"] for h in hits}
    assert "N0000003" in sources  # 純 dense 的 top-2 不含它，RRF 融合把它拉進來
    idx2_hit = next(h for h in hits if h["source"] == "N0000003")
    assert idx2_hit["bm25_rank"] == 0
    assert idx2_hit["dense_rank"] == 3


def test_search_baseline_reranker_reorders_top_candidates(index):
    vectors, meta = index

    class FakeReranker:
        """把 idx3（黑球溫度）評為最高分，其餘遞減。"""
        def predict(self, pairs):
            return [10.0 if "黑球溫度" in passage else float(-i)
                    for i, (_q, passage) in enumerate(pairs)]

    hits = svc.search_baseline(
        "溫度", [1.0, 0.0, 0.0], vectors, meta, top_k=1,
        hybrid=False, reranker=FakeReranker(),
    )
    assert hits[0]["source"] == "N0000004"
    assert hits[0]["reranked"] is True
    assert hits[0]["score"] == 10.0


def test_search_baseline_empty_index_returns_empty():
    assert svc.search_baseline("q", [1.0], np.empty((0, 1), dtype=np.float32), []) == []


def test_search_baseline_hybrid_without_rank_bm25_falls_back_to_dense(index, monkeypatch):
    vectors, meta = index
    monkeypatch.setattr(svc, "BM25Okapi", None)
    hits = svc.search_baseline("四十公斤", [1.0, 0.0, 0.0], vectors, meta, top_k=2, hybrid=True)
    assert [h["source"] for h in hits] == ["N0000001", "N0000002"]  # 退回純 dense
    assert all(h["bm25_rank"] is None for h in hits)


# ── build_context_lines ───────────────────────────────────────────

def test_build_context_lines_format():
    hits = [{"source": "N0030006", "chunk_index": 7, "chunk_text": "事假一年不得超過十四日"}]
    assert svc.build_context_lines(hits) == ["【來源：N0030006，第7段】\n事假一年不得超過十四日"]
