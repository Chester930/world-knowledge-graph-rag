"""標準化RAG（改良RAG）MVP：檢索與回答組裝。

雙階流程（見 docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md §3）：
① 單句級向量檢索（brute-force cosine，對 build_standardized_rag_index.py
   建立的標準化句子索引）取得高精準度的候選句子；
② 依候選句子所屬的 chunk，透過 svo_index.json 既有的分塊結構做上下文
   擴展（直接取整個 chunk 的原文文字），多筆候選落在同一 chunk 時去重。

不涉及知識圖譜／BFS／Fact 節點——與 routers/agent.py::chat() 的知識圖譜
路徑完全獨立，供 run_rag_comparison.py 做真實的路徑對照。
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import numpy as np


def load_index(kg_id: UUID) -> tuple[np.ndarray, list[dict]]:
    vectors = np.load(f"standardized_rag_index_{kg_id}.npy")
    meta = json.loads(Path(f"standardized_rag_meta_{kg_id}.json").read_text(encoding="utf-8"))
    return vectors, meta


def search(
    question_vector: list[float], vectors: np.ndarray, meta: list[dict], *, top_k: int = 5
) -> list[dict]:
    """單句級 cosine 相似度檢索，回傳去重（依 chunk）後的前 `top_k` 筆候選，
    每筆附上該 chunk 的完整原文（上下文擴展），並保留命中句子本身供顯示。
    """
    if vectors.shape[0] == 0:
        return []
    q = np.array(question_vector, dtype=np.float32)
    q_norm = q / (np.linalg.norm(q) + 1e-12)
    v_norm = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-12)
    scores = v_norm @ q_norm

    order = np.argsort(-scores)  # 分數由高到低

    seen_chunks: set[tuple[str, int]] = set()
    hits: list[dict] = []
    for i in order:
        record = meta[i]
        chunk_key = (record["source"], record["chunk_index"])
        if chunk_key in seen_chunks:
            continue
        seen_chunks.add(chunk_key)
        hits.append({
            "source": record["source"],
            "chunk_index": record["chunk_index"],
            "chunk_filename": record["chunk_filename"],
            "matched_sentence": record["sentence_text"],
            "chunk_text": record["chunk_text"],
            "score": float(scores[i]),
        })
        if len(hits) >= top_k:
            break
    return hits


def build_prompt(question: str, hits: list[dict]) -> str:
    """比照 routers/agent.py::_build_prompt() 的誠實侷限敘事風格——有依據時
    優先依據回答，沒依據時明確要求承認不知道、不臆測具體數字。"""
    taiwan_context = (
        "你是台灣勞動法規顧問，只根據台灣現行法規回答，絕對不要引用中國大陸、"
        "香港、澳門或其他地區的法規、機關名稱或數值，也不要混用其他地區的制度或用語。"
    )
    if hits:
        context_lines = "\n\n".join(
            f"【來源：{h['source']}，第{h['chunk_index']}段，相似度{h['score']:.3f}】\n{h['chunk_text']}"
            for h in hits
        )
        instruction = (
            "請優先根據上述原文回答問題；若原文不足以完整回答，可以補充你自己的知識，"
            "但務必清楚區分哪些是根據原文、哪些是你自己的補充。若原文沒有依據，"
            "在沒有依據的情況下不要臆測具體數字、比例或期限，應明確說明「原文中無此數據，"
            "建議查閱最新法規或官方公告確認」。"
        )
        context_block = f"以下是從文件中檢索到、可能與問題相關的原文段落：\n{context_lines}\n"
    else:
        context_block = ""
        instruction = (
            "文件中沒有檢索到與問題直接相關的段落，請依你自己的知識回答，並提醒使用者這個答案"
            "未經文件資料驗證。若問題涉及具體數字、比例或期限，在沒有依據的情況下不要臆測具體"
            "數值，應明確說明「文件中無此數據，建議查閱最新法規或官方公告確認」。"
        )

    return f"{taiwan_context}\n\n{context_block}\n問題：{question}\n\n{instruction}"
