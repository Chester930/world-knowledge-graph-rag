"""§ Phase 2 標準化 RAG 雙階檢索服務（軌道 2，見
`docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md` §3）。

雙階流程：① 單句級向量檢索（`svo_service.vector_search_sentences()`，per-KG
`Sentence` 向量索引 KNN）取得高精準度的候選句子；② 依候選句子所屬的
`chunk_index`，讀取 `svo_index.json`（`services.svo_chunking.read_svo_index()`）
做上下文擴展（取整個 chunk 的原文文字），多筆候選落在同一 chunk 時只保留
分數最高的一筆。

**與既有折衷版 MVP（`standardized_rag.py`／`build_standardized_rag_index.py`）
的關係**：MVP 沿用未經指代消解的 `sentence_embeddings.json`、用 numpy
brute-force 對本機存的 `.npy` 檔案做 cosine 相似度，嚴格來說是「軌道1＋
上下文擴展」的折衷版（見該檔案 docstring 誠實聲明）。本模組是正式版本——
`Sentence` 節點的 `sentence_embedding` 來自 § Phase 0（2026-08-20）已接上
`pronoun_llm_provider` 後才產生的、真正消解過代名詞的句子；查詢改用 Neo4j
原生向量索引，不需要另外維護本機 `.npy`／`.json` 索引檔案的建置腳本。

不涉及知識圖譜／BFS／Fact 節點——與 `routers/agent.py::chat()` 的知識圖譜
路徑、`standardized_rag.py` 的折衷版路徑皆彼此獨立，三者可平行比較（呼應
08 號報告 §4 消融實驗規劃）。
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from neo4j import AsyncDriver

from parser.chunk_writer import document_folder_path
from services.svo_chunking import read_svo_index
from services.svo_service import vector_search_sentences

# 候選池倍數——同一 chunk 內相鄰句子很可能同時命中，比照
# `core/constants.py::FACT_SEARCH_CANDIDATE_MULTIPLIER` 同一套「先取足夠候選
# 池，去重後再截斷回 top_k」設計精神，避免去重把 top_k 名額吃光。暫定值，
# 未經校準，留待第五章消融實驗評估合適倍數。
STANDARDIZED_RAG_CANDIDATE_MULTIPLIER = 4


async def search_standardized_rag(
    driver: AsyncDriver, kg_id: UUID, kg_folder: Path, query_vector: list[float], *, top_k: int = 5,
) -> list[dict]:
    """雙階標準化 RAG 檢索：單句精確命中 → 依所屬 chunk 擴展為完整上下文。

    回傳依分數排序、去重（依 `(source, chunk_index)`，同一 chunk 只保留
    分數最高的一句）後的前 `top_k` 筆，每筆含 `source`／`chunk_index`／
    `matched_sentence`（命中的標準化句子本身）／`chunk_text`（該 chunk 完整
    原文，供 LLM 生成引用）／`score`。

    `chunk_text` 讀不到時（例如 `svo_index.json` 缺席，理論上不應發生於
    `Sentence` 節點已存在的文件，防禦性處理）留空字串，不拋例外中斷整批
    查詢結果——單一文件的索引缺失不該讓其餘候選也查不到。
    """
    candidate_k = top_k * STANDARDIZED_RAG_CANDIDATE_MULTIPLIER
    records = await vector_search_sentences(driver, kg_id, query_vector, candidate_k)

    seen_chunks: dict[tuple, dict] = {}
    order: list[tuple] = []
    for record in records:
        chunk_key = (record["source"], record["chunk_index"])
        existing = seen_chunks.get(chunk_key)
        if existing is None:
            seen_chunks[chunk_key] = record
            order.append(chunk_key)
        elif record["score"] > existing["score"]:
            seen_chunks[chunk_key] = record

    hits: list[dict] = []
    for chunk_key in order:
        record = seen_chunks[chunk_key]
        source, chunk_index = chunk_key
        chunk_text = _read_chunk_text(kg_folder, source, chunk_index)
        hits.append({
            "source": source,
            "chunk_index": chunk_index,
            "matched_sentence": record["sentence_text"],
            "chunk_text": chunk_text,
            "score": record["score"],
        })
        if len(hits) >= top_k:
            break
    return hits


def _read_chunk_text(kg_folder: Path, source: str, chunk_index: int) -> str:
    doc_folder = document_folder_path(source, kg_folder)
    svo_index = read_svo_index(doc_folder)
    if svo_index is None:
        return ""
    return next(
        (chunk.get("text", "") for chunk in svo_index["chunks"] if chunk["index"] == chunk_index),
        "",
    )
