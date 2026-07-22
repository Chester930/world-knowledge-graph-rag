"""3.4 §a 端到端前處理管線：句子清單 → 文件內別名登記（可選）→ 代名詞消解
→ SVO 專用切塊並落地。

對應 docs/論文/03_系統設計與方法論.md § 3.1.2 `CHUNKREADY` 節點——把先前
各自獨立實作、獨立測試的模組（`services/ingestion_service.py::
get_or_rebuild_sentences()`／`services/entity_registry_service.py`／
`services/pronoun_resolution_service.py`／`services/svo_chunking.py`）
串成一條真正可呼叫的管線。
"""
from __future__ import annotations

from pathlib import Path

from core.providers.base import LLMProvider
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
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> tuple[list[Path], list[SVOChunk]]:
    """`CHUNKREADY`：取得句子清單 → （若提供 `mentions`）套用文件內別名登記表
    → 代名詞消解 → SVO 專用切塊並落地。

    對應 3.4 §a 完整 Behavior Tree：`REGISTRY`／`ALIASCHECK`／`PROMOTE`
    （`entity_registry_service`，`mentions` 為 `None` 時跳過，見下方誠實
    侷限）→ `PRONCHECK`／`PRONLLM`（`pronoun_resolution_service`）→
    `STDSENTS` → `SVOGROUP`（`svo_chunking`）。

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

    chunks = build_svo_chunks(
        original_sentences, normalized_sentences,
        max_sentences=max_sentences, overlap_sentences=overlap_sentences,
    )
    paths = write_svo_chunks(chunks, source, output_dir)
    return paths, chunks
