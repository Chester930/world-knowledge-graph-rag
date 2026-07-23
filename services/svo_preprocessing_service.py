"""3.4 §a 端到端前處理管線：句子清單 → 文件內別名登記（可選）→ 代名詞消解
→ 逐句 embedding（可選）→ SVO 專用切塊並落地。

對應 docs/論文/03_系統設計與方法論.md § 3.1.2 `CHUNKREADY` 節點——把先前
各自獨立實作、獨立測試的模組（`services/ingestion_service.py::
get_or_rebuild_sentences()`／`services/entity_registry_service.py`／
`services/pronoun_resolution_service.py`／`services/svo_chunking.py`）
串成一條真正可呼叫的管線。
"""
from __future__ import annotations

import json
from pathlib import Path

from core.providers.base import EmbeddingProvider, LLMProvider
from parser.chunk_writer import document_folder_path
from services.entity_registry_service import EntityRegistry, Mention, apply_registry
from services.ingestion_service import get_or_rebuild_sentences
from services.pronoun_resolution_service import PosTagger, resolve_coreference_pipeline
from services.svo_chunking import (
    DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
    SVOChunk,
    build_svo_chunks,
    write_svo_chunks,
)

SENTENCE_EMBEDDINGS_FILENAME = "sentence_embeddings.json"


def write_sentence_embeddings(
    vectors: list[list[float]],
    source: str,
    output_dir: str | Path,
) -> Path:
    """`SENTEMBED`：把標準化句子清單（STDSENTS）逐句算好的向量存成該文件
    資料夾內固定的 `sentence_embeddings.json`，比照
    `parser/chunk_writer.py::write_sentences_index()` 的落地模式——這裡只
    負責「算好存起來」，向未來（不在本次範圍）08 報告的「標準化 RAG」檢索
    軌道提供基礎建設，不在此實作任何檢索/查詢邏輯。
    """
    doc_folder = document_folder_path(source, output_dir)
    doc_folder.mkdir(parents=True, exist_ok=True)

    payload = {
        "source": source,
        "total_sentences": len(vectors),
        "embeddings": vectors,
    }

    file_path = doc_folder / SENTENCE_EMBEDDINGS_FILENAME
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return file_path


def read_sentence_embeddings(source: str, base_dir: str | Path) -> list[list[float]] | None:
    """讀回 `write_sentence_embeddings()` 寫入的逐句向量；檔案不存在時回傳
    `None`。"""
    doc_folder = document_folder_path(source, base_dir)
    path = doc_folder / SENTENCE_EMBEDDINGS_FILENAME
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["embeddings"]


async def prepare_svo_ready_chunks(
    source: str,
    base_dir: Path,
    output_dir: Path,
    *,
    mentions: list[list[Mention]] | None = None,
    entity_llm_provider: LLMProvider | None = None,
    entity_registry: EntityRegistry | None = None,
    entity_registry_start_idx: int = 0,
    pronoun_llm_provider: LLMProvider | None = None,
    pos_tagger: PosTagger | None = None,
    lexicon_auditor_provider: LLMProvider | None = None,
    custom_lexicon_path: Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> tuple[list[Path], list[SVOChunk]]:
    """`CHUNKREADY`：取得句子清單 → （若提供 `mentions`）套用文件內別名登記表
    → 代名詞消解 → （若提供 `embedding_provider`）逐句 embedding → SVO 專用
    切塊並落地。

    對應 3.4 §a 完整 Behavior Tree：`REGISTRY`／`ALIASCHECK`／`PROMOTE`
    （`entity_registry_service`，`mentions` 為 `None` 時跳過，見下方誠實
    侷限）→ `PRONCHECK`／`PRONLLM`（`pronoun_resolution_service`）→
    `STDSENTS` → `SENTEMBED`（`write_sentence_embeddings()`，`embedding_provider`
    為 `None` 時跳過）→ `SVOGROUP`（`svo_chunking`）。

    `SENTEMBED` 只是標準化句子清單的一個平行輸出（供未來 08 報告的「標準化
    RAG」檢索軌道使用），不影響、也不依賴別名登記或代名詞消解本身——即使
    跳過（`embedding_provider=None`），下游 `build_svo_chunks()` 收到的
    `normalized_sentences` 完全不受影響。

    `entity_registry`／`entity_registry_start_idx` 支援斷點續傳：傳入既有
    登記表快照與中斷處的句子索引即可從中斷處繼續別名登記，不需整份文件
    重跑（見 `entity_registry_service.apply_registry()`）。代名詞消解目前
    未提供對應的句子級 checkpoint（見 `docs/報告/06_SVO抽取管線調整任務書.md`
    第 3.3 節，尚待決定是否要做），本函式呼叫代名詞消解時一律處理完整的
    句子清單。

    ⚠️ **誠實侷限**：`mentions`（具名提及清單，每句一份候選別名列表）目前
    沒有任何模組產生——具名提及抽取（NER）不在本函式或任何既有模組的職責
    範圍內，是尚待補齊的上游依賴。`mentions=None`（現行唯一可行的呼叫方式）
    時，本函式跳過整個 §a 文件內別名登記表階段，直接從句子清單進入代名詞
    消解，此時輸出的「標準化句子」只完成代名詞消解、未完成別名收斂——這是
    目前系統的真實狀態，非本函式刻意簡化，待 NER 模組就緒後才能真正啟用
    別名登記表整合。
    """
    original_sentences = await get_or_rebuild_sentences(source, base_dir)

    normalized_sentences = original_sentences
    if mentions is not None:
        normalized_sentences, _registry = await apply_registry(
            normalized_sentences,
            mentions,
            llm_provider=entity_llm_provider,
            registry=entity_registry,
            start_idx=entity_registry_start_idx,
        )

    normalized_sentences = await resolve_coreference_pipeline(
        normalized_sentences,
        pronoun_llm_provider,
        pos_tagger=pos_tagger,
        lexicon_auditor_provider=lexicon_auditor_provider,
        custom_lexicon_path=custom_lexicon_path,
    )

    if embedding_provider is not None:
        vectors = embedding_provider.encode_batch(normalized_sentences)
        write_sentence_embeddings(vectors, source, output_dir)

    chunks = build_svo_chunks(
        original_sentences, normalized_sentences,
        max_sentences=max_sentences, overlap_sentences=overlap_sentences,
    )
    paths = write_svo_chunks(chunks, source, output_dir)
    return paths, chunks
