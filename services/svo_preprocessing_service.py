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
from typing import Mapping, Sequence

from core.providers.base import EmbeddingProvider, LLMProvider
from parser.chunk_writer import document_folder_path
from services.entity_extraction_service import NerTagger, extract_mentions
from services.entity_registry_service import EntityRegistry, Mention, apply_registry
from services.ingestion_service import get_or_rebuild_sentences
from services.pronoun_resolution_service import (
    DEFAULT_PRONOUN_LEXICON,
    PosTagger,
    resolve_coreference_pipeline,
)
from services.svo_chunking import (
    DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
    ArticleAwareChunking,
    SVOChunk,
    build_svo_chunks,
    write_svo_chunks,
)

SENTENCE_EMBEDDINGS_FILENAME = "sentence_embeddings.json"


def write_sentence_embeddings(
    vectors: list[list[float]],
    source: str,
    output_dir: str | Path,
    *,
    sentences: list[str] | None = None,
) -> Path:
    """`SENTEMBED`：把標準化句子清單（STDSENTS）逐句算好的向量存成該文件
    資料夾內固定的 `sentence_embeddings.json`，比照
    `parser/chunk_writer.py::write_sentences_index()` 的落地模式。

    ✅ **2026-08-20 補上句子本身（`docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md`
    Phase 1）**：此前只存向量，沒有同步存對應的（已消解代名詞的）句子文字——
    Neo4j 向量索引查詢命中後需要回傳人類可讀的句子內容，若只有向量無法回頭
    對應。`sentences` 為選填（預設 `None` 時只存向量、`sentences` 欄位省略，
    與此前行為完全相容），呼叫端提供時依索引與 `vectors` 一一對應存入。
    """
    doc_folder = document_folder_path(source, output_dir)
    doc_folder.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "source": source,
        "total_sentences": len(vectors),
        "embeddings": vectors,
    }
    if sentences is not None:
        payload["sentences"] = sentences

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


def read_standardized_sentences(source: str, base_dir: str | Path) -> list[str] | None:
    """讀回 `write_sentence_embeddings()` 存的（已消解代名詞的）句子文字本身
    （2026-08-20 新增，見 §Phase 1）；檔案不存在，或是舊格式（`sentences` 欄位
    此次修正上線前寫入、缺席）時回傳 `None`——與 `read_sentence_embeddings()`
    分開提供，不強迫既有只需要向量的呼叫端多讀一份不需要的資料。"""
    doc_folder = document_folder_path(source, base_dir)
    path = doc_folder / SENTENCE_EMBEDDINGS_FILENAME
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("sentences")


async def prepare_svo_ready_chunks(
    source: str,
    base_dir: Path,
    output_dir: Path,
    *,
    articles: Sequence[Mapping[str, str]] | None = None,
    article_no_key: str = "ArticleNo",
    article_content_key: str = "ArticleContent",
    mentions: list[list[Mention]] | None = None,
    ner_tagger: NerTagger | None = None,
    entity_llm_provider: LLMProvider | None = None,
    entity_registry: EntityRegistry | None = None,
    entity_registry_start_idx: int = 0,
    pronoun_llm_provider: LLMProvider | None = None,
    pronoun_lexicon: frozenset[str] | None = None,
    pos_tagger: PosTagger | None = None,
    lexicon_auditor_provider: LLMProvider | None = None,
    custom_lexicon_path: Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> tuple[list[Path], list[SVOChunk]]:
    """`CHUNKREADY`：取得句子清單 → （若有 `mentions` 可用）套用文件內別名登記表
    → 代名詞消解 → （若提供 `embedding_provider`）逐句 embedding → SVO 專用
    切塊並落地。

    對應 3.4 §a 完整 Behavior Tree：`REGISTRY`／`ALIASCHECK`／`PROMOTE`
    （`entity_registry_service`，`mentions` 與 `ner_tagger` 皆為 `None` 時
    跳過，見下方誠實侷限）→ `PRONCHECK`／`PRONLLM`（`pronoun_resolution_service`）→
    `STDSENTS` → `SENTEMBED`（`write_sentence_embeddings()`，`embedding_provider`
    為 `None` 時跳過）→ `SVOGROUP`（`svo_chunking`）。

    `mentions`／`ner_tagger` 兩者是「已知具名提及」與「交給本函式現場抽取」
    的兩種輸入方式，互斥使用：明確傳入 `mentions` 時優先採用（呼叫端已自行
    跑過 NER 或有其他來源）；`mentions=None` 但傳入 `ner_tagger` 時，改用
    `entity_extraction_service.extract_mentions()` 對 `original_sentences`
    現場抽取（見 `services/entity_extraction_service.py`，spaCy NER＋正則
    代號兜底的混合式抽取）；兩者皆為 `None` 時退化為現行行為，整個 §a 別名
    登記表階段被跳過。

    `SENTEMBED` 只是標準化句子清單的一個平行輸出（供未來 08 報告的「標準化
    RAG」檢索軌道使用），不影響、也不依賴別名登記或代名詞消解本身——即使
    跳過（`embedding_provider=None`），下游 `build_svo_chunks()` 收到的
    `normalized_sentences` 完全不受影響。

    `pronoun_lexicon`（2026-08-20 新增，見 § Phase 1 KG 專屬調整）：`None`
    時沿用 `resolve_coreference_pipeline()` 自身的預設詞庫
    （`DEFAULT_PRONOUN_LEXICON`）；呼叫端（`trigger_extraction()`）依 KG 節點
    的 `pronoun_lexicon_exclude` 組出排除特定字後的詞庫傳入，讓個別 KG（例如
    法律全文，「其」「該」在其中幾乎都是自我完備的正式泛稱而非模糊代名詞）
    可以有專屬的消解標準，不影響其他 KG 沿用完整預設詞庫。

    `entity_registry`／`entity_registry_start_idx` 支援斷點續傳：傳入既有
    登記表快照與中斷處的句子索引即可從中斷處繼續別名登記，不需整份文件
    重跑（見 `entity_registry_service.apply_registry()`）。代名詞消解目前
    未提供對應的句子級 checkpoint（見 `docs/報告/06_SVO抽取管線調整任務書.md`
    第 3.3 節，尚待決定是否要做），本函式呼叫代名詞消解時一律處理完整的
    句子清單。

    ⚠️ **誠實侷限（2026-07-23 部分解除）**：`services/entity_extraction_service.py`
    已補上 NER 模組（`SpacyNerTagger`＋正則代號兜底），介面已就緒可傳入
    `ner_tagger` 啟用；但 spaCy／`zh_core_web_sm` 在本專案環境仍未安裝驗證
    （與 `pronoun_resolution_service.SpacyPosTagger` 同樣的既有風險），
    `trigger_extraction()`（`services/svo_service.py`）目前仍以 `mentions=None`／
    `ner_tagger=None` 呼叫本函式——此時 §a 別名登記表階段整個跳過，行為與
    NER 模組補上之前相同，非本函式刻意簡化，待 spaCy 依賴於第四章實際安裝
    驗證後才會在 `trigger_extraction()` 接上 `ner_tagger`。

    `articles`（2026-08-24 新增，法規領域專屬路徑，對應
    `docs/論文/03_系統設計與方法論.md` § 3.5「實作範圍定案」）：提供時直接
    採用 `services.svo_chunking.ArticleAwareChunking`（按 `ArticleNo` 邊界
    切，一條對一塊），略過 `SVOGROUP`／別名登記表／代名詞消解／embedding
    這幾個步驟——條文本身是法規定義好的自我完備語意單位，且本專案既有法規
    KG 已用 `pronoun_lexicon_exclude=["其","該"]` 排除最常見的代名詞誤判
    來源。⚠️ **誠實侷限**：這代表法規全文目前不套用代名詞消解，若之後實測
    發現有跨條文指代需求，需回頭擴充本路徑；`None`（預設）維持既有
    `SVOGROUP` 行為完全不變，本參數只新增一條路徑，不影響任何既有呼叫端。
    """
    if articles is not None:
        chunks = ArticleAwareChunking(
            articles=articles,
            article_no_key=article_no_key,
            article_content_key=article_content_key,
        ).build_chunks()
        paths = write_svo_chunks(chunks, source, output_dir)
        return paths, chunks

    original_sentences = await get_or_rebuild_sentences(source, base_dir)

    if mentions is None and ner_tagger is not None:
        mentions = extract_mentions(original_sentences, ner_tagger)

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
        lexicon=pronoun_lexicon if pronoun_lexicon is not None else DEFAULT_PRONOUN_LEXICON,
        pos_tagger=pos_tagger,
        lexicon_auditor_provider=lexicon_auditor_provider,
        custom_lexicon_path=custom_lexicon_path,
    )

    if embedding_provider is not None:
        vectors = await embedding_provider.encode_batch(normalized_sentences)
        write_sentence_embeddings(vectors, source, output_dir, sentences=normalized_sentences)

    chunks = build_svo_chunks(
        original_sentences, normalized_sentences,
        max_sentences=max_sentences, overlap_sentences=overlap_sentences,
    )
    paths = write_svo_chunks(chunks, source, output_dir)
    return paths, chunks
