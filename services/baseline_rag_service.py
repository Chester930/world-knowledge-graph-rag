"""B0／B1 當代文字 RAG 強基準的**檢索側**（RQ1 非圖對照組）。

對應 `docs/報告/35_B1當代文字RAG強基準設計.md` §4／§8 與論文 §5.4.1。此模組
只負責「問題 → 排序後的 chunk 候選」這一段，**與知識圖譜路徑
（`routers/agent.py::chat()` 的 BFS＋Fact）完全獨立**，供 P0d 的
`run_rq1_comparison.py` 做真實路徑對照。

分層（報告 35 §4）：

    B0（floor）  ：原文 → sentence_aware_chunking → chunk 級 dense KNN → top-k
    B1（strong） ：B0 ＋ ① dense + BM25 混合、RRF 融合
                        ＋ ② 選配 cross-encoder 重排（預設關）
                        ＋ ③ chunk_size 取 §5.3 勝出值（由 build_baseline_chunk_index.py 決定）
                        ＋ ④ top_k 校準（{3,5,10}）

`B0` = `search_baseline(..., hybrid=False, reranker=None)`；
`B1` = `search_baseline(..., hybrid=True, reranker=<選配>)`。

## 為什麼是自建 `.npy` 索引、而非重用 Neo4j `chunk_embedding_vector`

報告 35 §2.4／§8 原假設可直接重用 Neo4j 的 `chunk_embedding_vector` 索引。
查證後排除：`embed_svo_chunks()` embed 的是 `SVOChunk.text`＝
`"\n".join(normalized_slice)`（**標準化句子**，見 `services/svo_chunking.py`
第 105 行）——這正是報告 08「軌道 2＝專案貢獻」，報告 35 §5／§7 明確要求
B1 排除。因此本基準改為對 `workspace/<kg>/<doc>/original.md` 的**原文**
重新 `sentence_aware_chunking()`（無標準化、無指代消解），建一份乾淨的
`.npy` 索引（`build_baseline_chunk_index.py`）。demo 規模（數千 chunk）下
brute-force cosine 足夠，不需要 Neo4j 原生索引。

## 生成端

本模組**不做生成**。`build_context_lines()` 把排序後的 chunk 轉成
`context_lines`，交給「與 `chat()` 共用的 post-retrieval pipeline」
（P0b 第 2 項重構，尚未完成）——B0／B1／Full System 生成端逐位元相同是
§3.8 單一變因控制的硬需求。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import UUID

import numpy as np

try:  # rank-bm25 為 dev 依賴（requirements-dev.txt）；缺席時 hybrid 檢索自動退回 dense-only
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover - 僅在未安裝 dev 依賴時觸發
    BM25Okapi = None  # type: ignore[assignment]


# ── 索引檔命名（build_baseline_chunk_index.py 寫、本模組讀）───────────

def _index_stem(kg_id: UUID, chunk_size: int) -> str:
    return f"baseline_rag_index_{kg_id}_cs{chunk_size}"


def load_baseline_index(
    kg_id: UUID, chunk_size: int = 500, *, base_dir: str | Path = "."
) -> tuple[np.ndarray, list[dict]]:
    """讀取 `build_baseline_chunk_index.py` 產生的乾淨 chunk 索引。

    回傳 `(vectors, meta)`：`vectors` shape = (N, dim)，`meta[i]` =
    `{"source", "chunk_index", "chunk_text"}`。索引不存在時拋 FileNotFoundError
    （呼叫端應先跑 build 腳本）。
    """
    stem = Path(base_dir) / _index_stem(kg_id, chunk_size)
    vectors = np.load(f"{stem}.npy")
    meta = json.loads(Path(f"{stem}.json").read_text(encoding="utf-8"))
    return vectors, meta


# ── 中文斷詞（BM25 用）──────────────────────────────────────────────

def tokenize_zh(text: str) -> list[str]:
    """字元二元組（character bigram）斷詞。

    選擇理由：本語料以中文法規為主，`rank_bm25` 需要預先斷好的 token 清單。
    字元 bigram 不需要額外的斷詞器依賴（jieba 等），對「四十公斤」「三十日」
    這類數量詞的子字串比對友善，且與專案他處既有的 bigram 做法一致
    （`resolve_entity_name()` 的 `_edit_ratio` 前身）。是否改用詞級斷詞
    留待 §5.3 校準時評估，非本基準的核心變因。
    """
    cleaned = "".join(ch for ch in text if not ch.isspace())
    if len(cleaned) < 2:
        return [cleaned] if cleaned else []
    return [cleaned[i:i + 2] for i in range(len(cleaned) - 1)]


# ── Reciprocal Rank Fusion（Cormack, Clarke & Büttcher, 2009, SIGIR）──

def rrf_fuse(rankings: list[list[int]], *, k: int = 60) -> list[int]:
    """把多個「由佳到差的候選 index 排序」用 RRF 融合成單一排序。

    `RRFscore(d) = Σ_i 1/(k + rank_i(d))`，k 預設 60（Cormack et al. 原文值）。
    只用 rank、不用原始分數 → 解決 dense cosine 與 BM25 分數尺度不一致。
    與 `routers/agent.py::_rrf_order()` 同一演算法；此處為避免 services 反向
    import routers，另寫一份泛用（吃 index 清單、任意路數）的版本。
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank)
    # 穩定排序：同分時保留首個 ranking 的相對順序
    order_hint = {idx: pos for pos, idx in enumerate(rankings[0])} if rankings else {}
    return sorted(scores, key=lambda i: (-scores[i], order_hint.get(i, math.inf)))


# ── 核心檢索 ────────────────────────────────────────────────────────

def _dense_ranking(question_vector: list[float], vectors: np.ndarray) -> tuple[list[int], np.ndarray]:
    """對 `vectors` 做 cosine 相似度，回傳 (由高到低的 index 清單, 分數陣列)。"""
    if vectors.shape[0] == 0:
        return [], np.empty(0, dtype=np.float32)
    q = np.asarray(question_vector, dtype=np.float32)
    q = q / (np.linalg.norm(q) + 1e-12)
    v = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-12)
    scores = v @ q
    return list(np.argsort(-scores)), scores


def _bm25_ranking(question: str, meta: list[dict]) -> list[int]:
    """對 `meta` 的 chunk_text 建 BM25Okapi，回傳由高到低的 index 清單。
    未安裝 rank-bm25 時回傳空清單（呼叫端據此退回 dense-only）。"""
    if BM25Okapi is None or not meta:
        return []
    corpus = [tokenize_zh(m["chunk_text"]) for m in meta]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize_zh(question))
    return list(np.argsort(-np.asarray(scores)))


def search_baseline(
    question: str,
    question_vector: list[float],
    vectors: np.ndarray,
    meta: list[dict],
    *,
    top_k: int = 5,
    hybrid: bool = True,
    reranker=None,
    rerank_candidates: int = 20,
) -> list[dict]:
    """B0／B1 檢索：dense（＋選配 BM25 RRF ＋選配 cross-encoder 重排）→ top_k。

    參數
    ----
    hybrid : True＝B1 的 dense+BM25 RRF 融合；False＝B0 的純 dense。
             未安裝 rank-bm25 或 meta 為空時自動退回 dense-only。
    reranker : 選配 cross-encoder，需有 `.predict(list[tuple[str, str]]) -> list[float]`
               介面（`sentence_transformers.CrossEncoder` 相容）。None＝不重排。
               只對融合後的前 `rerank_candidates` 筆重排。
    rerank_candidates : 送進 reranker 的候選數上限。

    回傳
    ----
    list[dict]，每筆 `{"source", "chunk_index", "chunk_text", "score",
    "dense_rank", "bm25_rank", "reranked"}`；`score` 為該筆在最終排序法下的
    原始分數（dense cosine／BM25／rerank，視最後一步而定）。
    """
    if vectors.shape[0] == 0 or not meta:
        return []

    dense_order, dense_scores = _dense_ranking(question_vector, vectors)
    dense_rank = {idx: r for r, idx in enumerate(dense_order)}

    bm25_order = _bm25_ranking(question, meta) if hybrid else []
    bm25_rank = {idx: r for r, idx in enumerate(bm25_order)}

    if bm25_order:
        fused = rrf_fuse([dense_order, bm25_order])
        base_score = None  # 融合後無單一原始分數，下面視是否重排決定
    else:
        fused = dense_order
        base_score = dense_scores

    reranked = False
    if reranker is not None and fused:
        cand = fused[:rerank_candidates]
        pairs = [(question, meta[i]["chunk_text"]) for i in cand]
        rr_scores = list(reranker.predict(pairs))
        cand_sorted = [i for _, i in sorted(zip(rr_scores, cand), key=lambda t: -t[0])]
        rr_lookup = {i: s for i, s in zip(cand, rr_scores)}
        fused = cand_sorted + [i for i in fused if i not in set(cand)]
        reranked = True

    hits: list[dict] = []
    for idx in fused[:top_k]:
        if reranked and idx in rr_lookup:
            score = float(rr_lookup[idx])
        elif base_score is not None:
            score = float(base_score[idx])
        else:  # 融合但未重排：用 dense cosine 當顯示分數（僅供人看，排序已由 RRF 定）
            score = float(dense_scores[idx])
        hits.append({
            "source": meta[idx]["source"],
            "chunk_index": meta[idx]["chunk_index"],
            "chunk_text": meta[idx]["chunk_text"],
            "score": score,
            "dense_rank": dense_rank.get(idx),
            "bm25_rank": bm25_rank.get(idx),
            "reranked": reranked,
        })
    return hits


def build_context_lines(hits: list[dict]) -> list[str]:
    """把 `search_baseline()` 的結果轉成餵給「共用 post-retrieval pipeline」的
    context 行。格式比照 `standardized_rag.build_prompt()` 的來源標註慣例，
    但回傳 list[str]（非組好的 prompt）——生成端 prompt 組裝由共用函式負責，
    B0／B1／Full System 逐位元相同（§3.8）。"""
    return [
        f"【來源：{h['source']}，第{h['chunk_index']}段】\n{h['chunk_text']}"
        for h in hits
    ]
