"""建立 B0／B1 當代文字 RAG 強基準的**乾淨 chunk 索引**。

對應 `docs/報告/35_B1當代文字RAG強基準設計.md` §4／§8、`services/baseline_rag_service.py`。

與 `build_standardized_rag_index.py` 的差別（關鍵）：
- 那支讀 `sentence_embeddings.json`（指代消解**前**的句子向量）→ 折衷版、非中性 baseline。
- 本支讀 `workspace/<kg>/<doc>/original.md` 的**原文**，重新
  `sentence_aware_chunking(chunk_size, chunk_overlap)`（無標準化、無指代消解、
  無型別標籤），再呼叫 embedding provider 算向量——才是報告 35 要的乾淨
  「傳統 RAG」chunk 級索引。

`chunk_size` 是 §5.3 的校準變因：本腳本可對同一 KG 產出多份不同 chunk_size
的索引（檔名帶 `_cs<size>`），供 P1a 掃描 {150,300,500,800,1200}。

用法：
    python build_baseline_chunk_index.py <kg_id> [<kg_id> ...] [--chunk-size 500] [--chunk-overlap 50]

需要 embedding provider 可用（.env 的 EMBEDDING_PROVIDER；本機用 ollama，
見 memory：EMBEDDING_PROVIDER=local 壞的）。不碰 Neo4j、不碰抽取 drain。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from uuid import UUID

import numpy as np

from core.config import settings
from core.providers.factory import get_embedding_provider, init_providers
from parser.core import sentence_aware_chunking

_FRONTMATTER = re.compile(r"^---\n.*?\n---\n\n?", re.DOTALL)
_SOURCE_LINE = re.compile(r"^source:\s*(.+?)\s*$", re.MULTILINE)


def _read_original(doc_folder: Path) -> tuple[str, str] | None:
    """回傳 (source, 原文本文)；`original.md` 不存在時回傳 None。"""
    path = doc_folder / "original.md"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    m = _SOURCE_LINE.search(raw.split("---\n", 2)[1] if raw.startswith("---\n") else "")
    source = m.group(1) if m else doc_folder.name
    body = _FRONTMATTER.sub("", raw, count=1)
    return source, body[:-1] if body.endswith("\n") else body


async def _build_one(kg_id: UUID, chunk_size: int, chunk_overlap: int) -> None:
    kg_folder = Path(settings.workspace_dir) / str(kg_id)
    if not kg_folder.is_dir():
        print(f"⚠️  {kg_folder} 不存在，略過 {kg_id}")
        return

    embedding_provider = get_embedding_provider()
    records: list[dict] = []
    chunk_texts: list[str] = []

    for doc_folder in sorted(p for p in kg_folder.iterdir() if p.is_dir()):
        pair = _read_original(doc_folder)
        if pair is None:
            continue
        source, text = pair
        for i, chunk in enumerate(sentence_aware_chunking(text, chunk_size, chunk_overlap)):
            records.append({"source": source, "chunk_index": i, "chunk_text": chunk})
            chunk_texts.append(chunk)

    if not records:
        print(f"⚠️  {kg_id}：找不到任何 original.md／chunk，略過")
        return

    vectors = await embedding_provider.encode_batch(chunk_texts)
    arr = np.asarray(vectors, dtype=np.float32)

    stem = f"baseline_rag_index_{kg_id}_cs{chunk_size}"
    np.save(f"{stem}.npy", arr)
    Path(f"{stem}.json").write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )
    print(f"✅ {kg_id} cs={chunk_size} overlap={chunk_overlap}："
          f"{arr.shape[0]} chunk、dim={arr.shape[1]} → {stem}.npy / .json")


async def _main(kg_ids: list[UUID], chunk_size: int, chunk_overlap: int) -> None:
    init_providers()
    for kg_id in kg_ids:
        await _build_one(kg_id, chunk_size, chunk_overlap)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="B0/B1 乾淨 chunk 索引建立")
    ap.add_argument("kg_ids", nargs="+", type=UUID, help="一或多個 KG id")
    ap.add_argument("--chunk-size", type=int, default=500)
    ap.add_argument("--chunk-overlap", type=int, default=50)
    args = ap.parse_args()
    asyncio.run(_main(args.kg_ids, args.chunk_size, args.chunk_overlap))
