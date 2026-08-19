"""RAG 索引建立（改用既有向量，換取速度）。

⚠️ **誠實標註**：原始設計（docs/報告/08_...md §3「標準化RAG」）要求用
**指代消解後的標準化句子**算向量，才有「單句精確命中」的高精準度；但
既有的 `sentence_embeddings.json` 存的是**指代消解前的原始句子**向量
（已於今天稍早查證過，非本次臆測）。使用者權衡時間成本後選擇直接沿用
既有向量——這代表本次跑出來的結果嚴格來說更接近「軌道1：傳統RAG」
（chunk/句子級向量檢索，無指代消解前處理），而非設計文件裡的「軌道2：
標準化RAG」。上下文擴展（單句命中後拉出所屬 SVO chunk 全文）這一步驟
仍保留，不是純粹的句子級傳統RAG，是介於兩者之間的折衷版本——所有比較
報告書都會依此誠實標註，不冒充是標準化RAG的完整實作。

不呼叫 embedding provider、不需要 Ollama——純讀取既有 `sentences.json`／
`sentence_embeddings.json`／`svo_index.json`，速度應該是純 I/O 等級。

用法：python build_standardized_rag_index.py > build_standardized_rag_index_raw.txt 2>&1
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import numpy as np

from core.config import settings

KG_IDS = [
    UUID("deb24e7c-c012-4398-9261-c813cb60b197"),
    UUID("2ae9d28b-3c5e-424f-9ea4-c3cbe59a2934"),
]


def _chunk_for_sentence(chunks: list[dict], sentence_index_1based: int) -> dict | None:
    for chunk in chunks:
        if chunk["source_sentence_start"] <= sentence_index_1based <= chunk["source_sentence_end"]:
            return chunk
    return None


def _collect_records(kg_id: UUID) -> tuple[list[dict], list[list[float]]]:
    kg_folder = Path(settings.workspace_dir) / str(kg_id)
    records: list[dict] = []
    vectors: list[list[float]] = []

    for doc_folder in sorted(kg_folder.iterdir()):
        sent_path = doc_folder / "sentences.json"
        emb_path = doc_folder / "sentence_embeddings.json"
        idx_path = doc_folder / "svo_index.json"
        if not (sent_path.exists() and emb_path.exists() and idx_path.exists()):
            continue

        sentences = json.loads(sent_path.read_text(encoding="utf-8"))
        embeddings = json.loads(emb_path.read_text(encoding="utf-8"))
        index = json.loads(idx_path.read_text(encoding="utf-8"))
        source = sentences.get("source", doc_folder.name)
        sent_list = sentences.get("sentences", [])
        emb_list = embeddings.get("embeddings", [])
        chunks = index.get("chunks", [])

        if len(sent_list) != len(emb_list):
            continue  # 資料不一致，略過此文件，不假裝能對齊

        for i, (sentence, vector) in enumerate(zip(sent_list, emb_list), start=1):
            s = sentence.strip()
            if len(s) < 4:
                continue
            chunk = _chunk_for_sentence(chunks, i)
            if chunk is None:
                continue
            records.append({
                "source": source,
                "chunk_index": chunk["index"],
                "chunk_filename": chunk["filename"],
                "sentence_text": s,
                "chunk_text": chunk.get("text", ""),
            })
            vectors.append(vector)

    return records, vectors


def main() -> None:
    for kg_id in KG_IDS:
        print(f"\n{'=' * 70}\nKG {kg_id}：讀取既有向量")
        records, vectors = _collect_records(kg_id)
        print(f"共 {len(records)} 筆可索引的句子（沿用既有向量，未重新嵌入）")
        if not records:
            continue

        arr = np.array(vectors, dtype=np.float32)
        np.save(f"standardized_rag_index_{kg_id}.npy", arr)
        Path(f"standardized_rag_meta_{kg_id}.json").write_text(
            json.dumps(records, ensure_ascii=False), encoding="utf-8"
        )
        print(f"已存索引：standardized_rag_index_{kg_id}.npy（shape={arr.shape}）"
              f" + standardized_rag_meta_{kg_id}.json")


if __name__ == "__main__":
    main()
