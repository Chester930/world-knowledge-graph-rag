"""暫存區文件分類（比對各既有 KG，建議或自動分配歸屬）。

對應 docs/論文/03_系統設計與方法論.md § 3.1.1：KG prototype 仍採
**Prototypical Networks**（Snell, Swersky, Zemel, 2017, NeurIPS）的 centroid
精神，但新文件分類改用各 chunk 對 prototype 的 cosine 激活投票，允許一份完整
文件同時掛入多個 KG。

**不採用** v1（智慧知識庫）`concept_engine.compute_match_score()` 的兩兩配對＋
align/magnitude 加權公式：查證 v1 全 codebase 後發現，該公式的
`interest_score`／`professional_score` 兩個標量從初始化後從未被任何函式更新過，
代入公式後 `align`／`magnitude` 兩項恆為常數，整條公式數學上等價於「0.7 × 平均
cosine 相似度」，個人化/差異化的設計意圖從未實際生效（詳見
docs/報告/技術參考地圖.md）。

本模組刻意不依賴 ConceptNode 路由層（services/concept_engine.py，屬 3.2 節
RQ2 範圍，尚未實作）——KG prototype 直接從該 KG 資料夾底下的成員文件資料夾計算，
不需要額外的概念抽取/儲存基礎設施，讓 3.1.1 這個功能節點可以獨立於 3.2 完整
實作與測試。呼叫端（router）需自行組裝 `KGInfo` 清單（例如從尚未實作的
KGRepository 讀取），本模組不直接查詢 Neo4j。

本模組所有函式皆為同步（檔案 I/O 本身即為同步操作），FastAPI router 層呼叫
時需以 `run_in_executor` 包裝，避免阻塞事件迴圈（做法同
services/ingestion_service.py）。**2026-08-04 更新**：`EmbeddingProvider.encode`／
`encode_batch` 已改為 `async def`（見 core/providers/base.py docstring），本模組
`compute_document_vector()` 內用 `asyncio.run()` 橋接——安全前提是本模組所有
呼叫路徑最終都經由 `run_in_executor` 在獨立執行緒執行、該執行緒沒有自己的
執行中 event loop（見下方 `compute_document_vector` docstring）；若未來新增
直接在 FastAPI 事件迴圈上呼叫本模組函式的路徑，`asyncio.run()` 會拋出
`RuntimeError`，屆時需改走真正的 `await`／`run_in_executor` 包裝，不能沿用
這個橋接寫法。

2026-07-20 修正（對應 § 3.1.1 優化建議 #1／#2／#3／#5，見 03_系統設計與方法論.md）：
文件向量快取進資料夾記錄檔（`document_record_service.set_document_vector`）、
KG prototype 快取進 `_prototype_cache.json`（成員清單改變才失效重算）、
`classify_all` 批次內以移動平均就地更新剛自動分配的 KG 之 prototype（不再整批
共用同一份、可能過期的 prototype）、`assign_document_to_kg` 的舊式實體搬移與記錄檔
更新失敗時互相 rollback（不留下位置與記錄檔不一致的中間態；新流程改用 Manifest）、`classify_by_vector`
新增 `low_confidence` 標記成員數過少（< `CLUSTER_MIN_SIZE`）的 cold-start KG。
"""
# Traceability: 02 §2.4.1 -> 03 §3.1.1 -> 04 §4.3.2.
# Literature: Snell et al. (2017)／sentence-embedding literature.
# Project: semantic-router is an architecture reference only; centroid classification
# is this project's own implementation. Tests: tests/services/test_classify_service.py.
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID, NAMESPACE_URL, uuid5

from core.config import settings
from core.constants import (
    CHUNK_ACTIVATION_THRESHOLD,
    CHUNK_MIN_HITS,
    CHUNK_MIN_RATIO,
    CLASSIFY_AUTO_THRESHOLD,
    CLASSIFY_MIN_THRESHOLD,
    CLUSTER_MIN_SIZE,
    ENABLE_VIRTUAL_MANIFEST_ASSIGN,
)
from core.providers.factory import get_embedding_provider
from models.knowledge_graph import ClassifyResult, KGCandidate
from services import document_record_service

_PROTOTYPE_CACHE_FILENAME = "_prototype_cache.json"
_MEMBERS_MANIFEST_FILENAME = "_members.json"

logger = logging.getLogger(__name__)


def embedding_signature() -> str:
    """目前 embedding 設定的簽章（`provider:model`），用來標記快取向量是用哪套
    設定算出來的。`settings.embedding_provider` 或對應的 model 欄位一被換掉，
    簽章就不同，快取（`_record.json` 的 `document_vector`／KG 資料夾的
    `_prototype_cache.json`）即失效重算——避免換模型後靜默拿舊向量做 cosine
    （維度可能剛好相同、不會報錯，但語意空間已不同）。
    """
    provider = settings.embedding_provider
    model = {
        "local": settings.local_embedding_model,
        "openai": settings.openai_embedding_model,
        "ollama": settings.ollama_embedding_model,
    }.get(provider, "unknown")
    return f"{provider}:{model}"


@dataclass(frozen=True)
class KGInfo:
    """classify_service 運作所需的最小 KG 資訊，由呼叫端組裝後傳入。"""
    kg_id: UUID
    kg_name: str
    folder_path: Path


# ── 向量計算（I/O + embedding provider）─────────────────────────────────────

def read_chunk_bodies(doc_folder: Path) -> list[str]:
    """讀取文件資料夾內所有切塊檔案的正文，略過 YAML frontmatter。"""
    bodies = []
    for chunk_file in sorted(doc_folder.glob("chunk-*-of-*.md")):
        content = chunk_file.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        body = parts[2] if len(parts) >= 3 else content
        bodies.append(body.strip())
    return bodies


def mean_vector(vectors: list[list[float]]) -> list[float] | None:
    """對一組向量取逐維度平均（centroid）。"""
    if not vectors:
        return None
    dim = len(vectors[0])
    return [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]


def compute_document_chunk_vectors(doc_folder: Path) -> list[list[float]] | None:
    """逐段取得文件向量，供 SDD-51 的 chunk voting 使用。

    這條路徑刻意不做 mean-pooling；`compute_document_vector()` 仍保留給既有
    prototype／相容呼叫端使用。provider 尚未初始化時回傳 ``None``，與既有文件
    向量計算的降級行為一致。
    """
    bodies = read_chunk_bodies(doc_folder)
    if not bodies:
        return None
    try:
        embedding = get_embedding_provider()
    except RuntimeError as e:
        logger.warning(f"embedding provider 尚未就緒，略過段落投票 [{doc_folder.name}]: {e}")
        return None
    return asyncio.run(embedding.encode_batch(bodies))


def compute_document_vector(doc_folder: Path) -> list[float] | None:
    """計算文件代表向量：該文件所有 chunk 向量的平均。

    優先讀取資料夾記錄檔（`_record.json`）內快取的 `document_vector`，命中則直接
    回傳，不重新呼叫 embedding provider；未命中（記錄檔不存在，或存在但尚未快取）
    才實際計算，計算後若記錄檔存在則寫回快取供下次呼叫使用。快取由
    `document_record_service.init_record()` 在切塊數改變（內容重新解析）時清空，
    見該函式與 `models.knowledge_graph.DocumentRecord.document_vector` 註解。

    **`asyncio.run()` 橋接（2026-08-04）**：`EmbeddingProvider.encode_batch()`
    已改為 `async def`（見 core/providers/base.py），本函式維持同步簽名（模組
    docstring「本模組所有函式皆為同步」的設計不變），用 `asyncio.run()` 呼叫
    非同步的 encode_batch——僅在本函式保證永遠透過 `run_in_executor`（獨立
    執行緒、無執行中的 event loop）呼叫時才安全，見模組 docstring 的警示。
    """
    signature = embedding_signature()
    record = document_record_service.read_record(doc_folder)
    if (
        record is not None
        and record.document_vector is not None
        and record.document_vector_signature == signature
    ):
        return record.document_vector

    bodies = read_chunk_bodies(doc_folder)
    if not bodies:
        return None
    try:
        embedding = get_embedding_provider()
    except RuntimeError as e:
        # provider 尚未初始化（例如在完整 app lifespan 之外呼叫）——比照
        # svo_service.embed_svo_chunks 的處理，優雅回 None，不讓分類端點 500。
        logger.warning(f"embedding provider 尚未就緒，略過文件向量計算 [{doc_folder.name}]: {e}")
        return None
    vectors = asyncio.run(embedding.encode_batch(bodies))
    vector = mean_vector(vectors)
    if vector is not None:
        document_record_service.set_document_vector(doc_folder, vector, signature)
    return vector


def _prototype_cache_path(kg_folder: Path) -> Path:
    return kg_folder / _PROTOTYPE_CACHE_FILENAME


def _members_manifest_path(kg_folder: Path) -> Path:
    return kg_folder / _MEMBERS_MANIFEST_FILENAME


def _read_members_manifest(kg_folder: Path) -> dict:
    path = _members_manifest_path(kg_folder)
    if not path.exists():
        return {"kg_id": None, "assigned_documents": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Manifest 讀取失敗 [{path}]: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("assigned_documents", []), list):
        raise ValueError(f"Manifest 格式錯誤 [{path}]")
    data.setdefault("assigned_documents", [])
    return data


def _write_members_manifest(kg_folder: Path, manifest: dict) -> None:
    """以同目錄暫存檔＋replace 原子更新 Manifest，不複製文件實體。"""
    path = _members_manifest_path(kg_folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{_MEMBERS_MANIFEST_FILENAME}.", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
        os.replace(temp_name, path)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _manifest_member_sources(kg_folder: Path) -> list[tuple[str, Path]]:
    """取得虛擬成員的中央來源路徑；同時相容舊式實體子資料夾。"""
    sources: list[tuple[str, Path]] = []
    manifest = _read_members_manifest(kg_folder)
    for item in manifest.get("assigned_documents", []):
        if not isinstance(item, dict) or not item.get("doc_id"):
            continue
        source_path = item.get("source_path")
        if source_path:
            sources.append((str(item["doc_id"]), Path(source_path)))

    virtual_ids = {doc_id for doc_id, _ in sources}
    if kg_folder.exists():
        for folder in sorted(p for p in kg_folder.iterdir() if p.is_dir()):
            if folder.name not in virtual_ids:
                sources.append((folder.name, folder))
    return sources


def _read_prototype_cache(
    kg_folder: Path, member_folders: list[str],
) -> tuple[list[float] | None, int] | None:
    """快取命中條件：快取檔存在，記錄的成員資料夾清單與目前磁碟現況完全相同，
    快取內含 `vector_count`（2026-08-19 修復前寫入的舊格式快取沒有這個欄位，
    視為未命中、強制重新計算一次，之後即為新格式，見下方 `vector_count` 註解），
    且 `embedding_signature` 與目前 embedding 設定相同（換 provider／model 後
    舊 prototype 失效，見 `embedding_signature()`）。

    任何解析失敗（快取檔損毀、格式不符）都視為未命中、退回重新計算，不拋例外
    中斷分類流程——快取只是效能優化，正確性永遠以「重新計算」為準。

    回傳 `(prototype, vector_count)`：後者是實際被平均進 prototype 的向量數，
    可能小於 `len(member_folders)`（部份成員文件的 `compute_document_vector()`
    可能回傳 `None`），與 `count_kg_members()` 的資料夾總數是兩個不同的量。
    """
    cache_path = _prototype_cache_path(kg_folder)
    if not cache_path.exists():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            cached.get("member_folders") == member_folders
            and "vector_count" in cached
            and cached.get("embedding_signature") == embedding_signature()
        ):
            return cached.get("prototype"), cached["vector_count"]
    except Exception as e:
        logger.warning(f"KG prototype 快取讀取失敗，改為重新計算 [{kg_folder}]: {e}")
    return None


def _write_prototype_cache(
    kg_folder: Path, member_folders: list[str], prototype: list[float] | None, vector_count: int,
) -> None:
    try:
        _prototype_cache_path(kg_folder).write_text(
            json.dumps({
                "member_folders": member_folders,
                "prototype": prototype,
                "vector_count": vector_count,
                "embedding_signature": embedding_signature(),
            }),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"KG prototype 快取寫入失敗，不影響本次分類結果 [{kg_folder}]: {e}")


def compute_kg_prototype(kg_folder: Path) -> list[float] | None:
    """計算 KG prototype 向量：該 KG 資料夾底下所有成員文件代表向量的平均。

    先比對成員資料夾清單與 `_prototype_cache.json` 快取是否一致，一致則直接回傳
    快取值，跳過所有成員文件的向量計算；一旦任何成員文件被加入/移出該 KG 資料夾
    （清單不再相同），快取自動失效、重新計算並覆寫快取。
    """
    return compute_kg_prototype_with_count(kg_folder)[0]


def compute_kg_prototype_with_count(kg_folder: Path) -> tuple[list[float] | None, int]:
    """`compute_kg_prototype()` 的完整版本，額外回傳實際被平均進去的向量數。

    2026-08-19（真實審查發現並修復）：`classify_all()` 原本用
    `count_kg_members()`（資料夾內的成員總數）當作 `_incremental_prototype_update()`
    的 `old_count`，但 `compute_kg_prototype()` 計算平均時會跳過
    `compute_document_vector()` 回傳 `None` 的成員（見下方迴圈）——若任何成員
    文件無法向量化，兩者定義的「成員數」就不一致，移動平均公式
    `(o * old_count + n) / (old_count + 1)` 的 `old_count` 會偏高，算出數學上
    錯誤的加權平均。呼叫端（`classify_document`／`classify_all`）改用本函式
    回傳的真實向量數，不再用 `count_kg_members()` 頂替。
    """
    if not kg_folder.exists():
        return None, 0
    member_sources = _manifest_member_sources(kg_folder)
    member_folders = [member_id for member_id, _ in member_sources]

    cached = _read_prototype_cache(kg_folder, member_folders)
    if cached is not None:
        return cached

    member_vectors = []
    for _, source_path in member_sources:
        vec = compute_document_vector(source_path)
        if vec is not None:
            member_vectors.append(vec)
    prototype = mean_vector(member_vectors)
    vector_count = len(member_vectors)
    _write_prototype_cache(kg_folder, member_folders, prototype, vector_count)
    return prototype, vector_count


def count_kg_members(kg_folder: Path) -> int:
    """計算 KG 的實體子資料夾與 Manifest 虛擬成員聯集數。"""
    if not kg_folder.exists():
        return 0
    manifest = _read_members_manifest(kg_folder)
    member_ids = {
        str(item["doc_id"])
        for item in manifest.get("assigned_documents", [])
        if isinstance(item, dict) and item.get("doc_id")
    }
    member_ids.update(p.name for p in kg_folder.iterdir() if p.is_dir())
    return len(member_ids)


# ── 純分數計算（不涉及 I/O，方便以合成向量單元測試）───────────────────────────

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, dot / (n1 * n2)))


@dataclass(frozen=True)
class _ChunkVote:
    """單一 KG 的段落投票結果（內部資料，保留完整命中資訊供 Manifest 使用）。"""

    key: object
    similarities: tuple[float, ...]
    hit_indices: tuple[int, ...]

    @property
    def max_similarity(self) -> float:
        return max(self.similarities, default=0.0)


def _evaluate_chunk_votes(
    chunk_vectors: list[list[float]],
    kg_prototypes: dict[object, list[float]],
    threshold: float,
    min_hits: int,
    min_ratio: float,
) -> list[_ChunkVote]:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold 必須介於 0 與 1 之間")
    if min_hits < 1:
        raise ValueError("min_hits 必須至少為 1")
    if not 0.0 <= min_ratio <= 1.0:
        raise ValueError("min_ratio 必須介於 0 與 1 之間")
    if not chunk_vectors:
        return []

    votes: list[_ChunkVote] = []
    for key, prototype in kg_prototypes.items():
        if not prototype:
            continue
        similarities = tuple(cosine_similarity(chunk, prototype) for chunk in chunk_vectors)
        hit_indices = tuple(
            index for index, similarity in enumerate(similarities)
            if similarity >= threshold
        )
        hit_ratio = len(hit_indices) / len(chunk_vectors)
        if len(hit_indices) >= min_hits or hit_ratio >= min_ratio:
            votes.append(_ChunkVote(key, similarities, hit_indices))

    return sorted(votes, key=lambda vote: vote.max_similarity, reverse=True)


def _kg_uuid(value: object) -> UUID:
    """將公開 API 的字串 KG key 穩定轉成既有模型需要的 UUID。"""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError):
        return uuid5(NAMESPACE_URL, f"world-knowledge-graph:kg:{value}")


def classify_by_chunk_voting(
    chunk_vectors: list[list[float]],
    kg_prototypes: dict[str, list[float]],
    threshold: float = CHUNK_ACTIVATION_THRESHOLD,
    min_hits: int = CHUNK_MIN_HITS,
    min_ratio: float = CHUNK_MIN_RATIO,
) -> list[ClassifyResult]:
    """計算各 Chunk 對各 KG prototype 的 cosine，以激活投票決定多重歸屬。

    回傳一個 ``ClassifyResult``／每個被激活的 KG；未通過投票的 KG 不會出現在
    清單中。因本低階 API 沒有文件名稱參數，結果的 ``filename`` 為空字串；批次
    入口會使用同一套核心邏輯建立帶有實際文件名稱的聚合結果。
    """
    votes = _evaluate_chunk_votes(
        chunk_vectors, kg_prototypes, threshold, min_hits, min_ratio,
    )
    results: list[ClassifyResult] = []
    for vote in votes:
        kg_name = str(vote.key)
        candidate = KGCandidate(
            kg_id=_kg_uuid(vote.key),
            kg_name=kg_name,
            score=round(vote.max_similarity, 4),
            top_matched_concepts=[f"chunk_{index + 1}" for index in vote.hit_indices],
        )
        results.append(ClassifyResult(
            filename="",
            candidates=[candidate],
            matched_kg_id=candidate.kg_id,
            matched_kg_name=kg_name,
            score=candidate.score,
            status="pending",
        ))
    return results


def _classify_chunk_votes_for_kgs(
    filename: str,
    chunk_vectors: list[list[float]] | None,
    kg_prototypes: dict[KGInfo, list[float] | None],
    kg_member_counts: dict[KGInfo, int] | None = None,
) -> tuple[ClassifyResult, dict[KGInfo, _ChunkVote]]:
    if not chunk_vectors:
        return ClassifyResult(filename=filename, status="unmatched"), {}

    available = {
        kg: prototype for kg, prototype in kg_prototypes.items() if prototype is not None
    }
    votes = _evaluate_chunk_votes(
        chunk_vectors, available, CHUNK_ACTIVATION_THRESHOLD, CHUNK_MIN_HITS, CHUNK_MIN_RATIO,
    )
    vote_by_kg = {vote.key: vote for vote in votes}
    candidates = [
        KGCandidate(
            kg_id=kg.kg_id,
            kg_name=kg.kg_name,
            score=round(vote.max_similarity, 4),
            top_matched_concepts=[f"chunk_{index + 1}" for index in vote.hit_indices],
            member_count=(kg_member_counts or {}).get(kg, 0),
            low_confidence=bool(kg_member_counts)
            and (kg_member_counts or {}).get(kg, 0) < CLUSTER_MIN_SIZE,
        )
        for kg, vote in ((kg, vote_by_kg[kg]) for kg in available if kg in vote_by_kg)
    ]
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    if not candidates:
        # 保留舊 API 的 pending 語意：有一般語意相關性但未達段落激活門檻時，
        # 可供人工審核，卻絕不會進入自動 Manifest 指派。
        fallback = classify_by_vector(
            filename,
            mean_vector(chunk_vectors),
            kg_prototypes,
            kg_member_counts=kg_member_counts,
        )
        return fallback, vote_by_kg

    top = candidates[0]
    return ClassifyResult(
        filename=filename,
        candidates=candidates,
        matched_kg_id=top.kg_id,
        matched_kg_name=top.kg_name,
        score=top.score,
        status="pending",
    ), vote_by_kg


def classify_by_vector(
    filename: str,
    doc_vector: list[float] | None,
    kg_prototypes: dict[KGInfo, list[float] | None],
    min_threshold: float = CLASSIFY_MIN_THRESHOLD,
    kg_member_counts: dict[KGInfo, int] | None = None,
) -> ClassifyResult:
    """給定文件代表向量與各 KG 的 prototype 向量，計算候選排名（純函式，無 I/O）。

    `kg_member_counts`（選填，不傳則所有候選皆視為正常信心）：各 KG 目前的成員
    文件數，用於標記 `KGCandidate.low_confidence`——成員數低於 `CLUSTER_MIN_SIZE`
    時，prototype 是由極少數文件平均而成的 cold-start 結果，統計上不穩定，讓呼叫
    端能區分「高分但樣本太少」與「高分且樣本充足」兩種情況，不是靜默地一視同仁。
    """
    if doc_vector is None:
        return ClassifyResult(filename=filename, status="unmatched")

    candidates: list[KGCandidate] = []
    for kg, prototype in kg_prototypes.items():
        if prototype is None:
            continue
        score = cosine_similarity(doc_vector, prototype)
        if score < min_threshold:
            continue
        member_count = (kg_member_counts or {}).get(kg, 0)
        candidates.append(KGCandidate(
            kg_id=kg.kg_id,
            kg_name=kg.kg_name,
            score=round(score, 4),
            member_count=member_count,
            low_confidence=bool(kg_member_counts) and member_count < CLUSTER_MIN_SIZE,
        ))

    candidates.sort(key=lambda c: c.score, reverse=True)

    result = ClassifyResult(filename=filename, candidates=candidates, status="pending")
    if not candidates:
        result.status = "unmatched"
        return result

    top = candidates[0]
    result.matched_kg_id = top.kg_id
    result.matched_kg_name = top.kg_name
    result.score = top.score
    return result


# ── 歸檔動作（SSOT 實體來源＋Manifest 虛擬歸屬）───────────────────────────────

def assign_document_to_kg(
    doc_folder: Path,
    kg: KGInfo,
    method: str = "manual",
    move_physical: bool = False,
    matched_reasons: Iterable[str] | None = None,
    max_similarity: float | None = None,
) -> Path:
    """將文件掛入 KG，預設只更新 Manifest，不改變文件實體路徑。

    ``move_physical=True`` 是舊版呼叫端的明確相容開關；新流程預設為虛擬歸屬，
    因此同一份 ``doc_folder`` 可以依序登記到多個 KG。Manifest 只保存 doc_id、
    原始來源指標與命中中繼資料，絕不以 copy 或 move 產生第二份文件。
    """
    if not doc_folder.is_dir():
        raise FileNotFoundError(f"文件資料夾不存在：{doc_folder}")

    use_virtual_manifest = ENABLE_VIRTUAL_MANIFEST_ASSIGN and not move_physical
    if not use_virtual_manifest:
        kg.folder_path.mkdir(parents=True, exist_ok=True)
        dest = kg.folder_path / doc_folder.name
        shutil.move(str(doc_folder), str(dest))
        try:
            document_record_service.append_assignment(
                dest, kg_id=kg.kg_id, kg_name=kg.kg_name, method=method,
            )
        except Exception:
            shutil.move(str(dest), str(doc_folder))
            raise
        return dest

    kg.folder_path.mkdir(parents=True, exist_ok=True)
    manifest_path = _members_manifest_path(kg.folder_path)
    had_manifest = manifest_path.exists()
    old_manifest_text = manifest_path.read_text(encoding="utf-8") if had_manifest else None
    manifest = _read_members_manifest(kg.folder_path)
    manifest["kg_id"] = str(kg.kg_id)
    documents = manifest.setdefault("assigned_documents", [])
    entry = {
        "doc_id": doc_folder.name,
        "source_path": str(doc_folder.resolve()),
        "matched_reasons": list(matched_reasons or []),
        "max_similarity": round(max_similarity, 4) if max_similarity is not None else 0.0,
        "assigned_at": datetime.now(timezone.utc).isoformat(),
    }
    existing_index = next(
        (index for index, item in enumerate(documents)
         if isinstance(item, dict) and item.get("doc_id") == doc_folder.name),
        None,
    )
    if existing_index is None:
        documents.append(entry)
    else:
        documents[existing_index] = entry

    _write_members_manifest(kg.folder_path, manifest)
    try:
        document_record_service.append_assignment(
            doc_folder, kg_id=kg.kg_id, kg_name=kg.kg_name, method=method,
        )
    except Exception:
        if old_manifest_text is None:
            manifest_path.unlink(missing_ok=True)
        else:
            manifest_path.write_text(old_manifest_text, encoding="utf-8")
        raise

    # Manifest membership changed; invalidate any prototype cache immediately.
    _prototype_cache_path(kg.folder_path).unlink(missing_ok=True)
    return doc_folder


# ── 批次分類（I/O 入口）─────────────────────────────────────────────────────

def classify_document(doc_folder: Path, known_kgs: Iterable[KGInfo]) -> ClassifyResult:
    """以段落投票為單位分類單一文件，允許同時命中多個 KG。"""
    known_kgs = list(known_kgs)
    chunk_vectors = compute_document_chunk_vectors(doc_folder)
    prototypes = {kg: compute_kg_prototype(kg.folder_path) for kg in known_kgs}
    member_counts = {kg: count_kg_members(kg.folder_path) for kg in known_kgs}
    result, _ = _classify_chunk_votes_for_kgs(
        doc_folder.name, chunk_vectors, prototypes, kg_member_counts=member_counts,
    )
    return result


def _incremental_prototype_update(
    old_prototype: list[float] | None, old_count: int, new_vector: list[float],
) -> list[float]:
    """新文件加入 KG 後，以移動平均就地更新 prototype，不必重新掃描整個 KG
    資料夾——`compute_kg_prototype()` 之後若被重新呼叫仍會依磁碟現況重新計算並
    覆寫快取，此處只是讓同一批次內、緊接著的其他文件不會拿到過期的 prototype。
    """
    if old_prototype is None or old_count == 0:
        return list(new_vector)
    new_count = old_count + 1
    return [(o * old_count + n) / new_count for o, n in zip(old_prototype, new_vector)]


def classify_all(
    staging_folder: Path,
    known_kgs: Iterable[KGInfo],
    auto_assign: bool = False,
    auto_threshold: float = CLASSIFY_AUTO_THRESHOLD,
) -> list[ClassifyResult]:
    """對暫存區底下所有文件資料夾批次執行分類；每個 KG 的 prototype 一開始只算
    一次（`compute_kg_prototype` 本身有跨呼叫的磁碟快取，見該函式），但批次內一旦
    某份文件被自動分配進某個 KG，會立即以移動平均就地更新該 KG 在記憶體中的
    prototype 與成員數，讓同一批次內排在後面的文件不會拿舊 prototype 比對
    ——修正原本「整批共用同一份 prototype、批次內後到的文件看不到批次內先到的
    文件已產生的變化」的問題。
    """
    known_kgs = list(known_kgs)
    if not staging_folder.exists():
        return []

    prototypes_with_counts = {kg: compute_kg_prototype_with_count(kg.folder_path) for kg in known_kgs}
    prototypes = {kg: pc[0] for kg, pc in prototypes_with_counts.items()}
    prototype_vector_counts = {kg: pc[1] for kg, pc in prototypes_with_counts.items()}
    # member_counts 是資料夾總數，供 KGCandidate.low_confidence 判斷 cold-start
    # 用（見 classify_by_vector docstring）——刻意與上面的 prototype_vector_counts
    # 分開，兩者定義不同，不可互相頂替，見 compute_kg_prototype_with_count() docstring。
    member_counts = {kg: count_kg_members(kg.folder_path) for kg in known_kgs}

    results: list[ClassifyResult] = []
    for doc_folder in sorted(p for p in staging_folder.iterdir() if p.is_dir()):
        try:
            chunk_vectors = compute_document_chunk_vectors(doc_folder)
            result, vote_by_kg = _classify_chunk_votes_for_kgs(
                doc_folder.name, chunk_vectors, prototypes, kg_member_counts=member_counts,
            )
        except Exception as e:
            logger.warning(f"分類失敗 [{doc_folder.name}]: {e}")
            results.append(ClassifyResult(filename=doc_folder.name, status="error"))
            continue

        if auto_assign and result.candidates and vote_by_kg:
            assignments = [
                candidate for candidate in result.candidates if candidate.score >= auto_threshold
            ]
            for candidate in assignments:
                target = next(k for k in known_kgs if k.kg_id == candidate.kg_id)
                vote = vote_by_kg[target]
                assign_document_to_kg(
                    doc_folder,
                    target,
                    method="auto",
                    matched_reasons=[f"chunk_{index + 1}" for index in vote.hit_indices],
                    max_similarity=vote.max_similarity,
                )
                if chunk_vectors:
                    # 只用於同一批次內的冷啟動更新；正式 prototype 仍由完整成員
                    # 文件重算，避免把任何單一段落誤當成文件的唯一代表。
                    doc_vector = mean_vector(chunk_vectors)
                    prototypes[target] = _incremental_prototype_update(
                        prototypes.get(target), prototype_vector_counts.get(target, 0), doc_vector,
                    )
                    prototype_vector_counts[target] = prototype_vector_counts.get(target, 0) + 1
                member_counts[target] = member_counts.get(target, 0) + 1

            if assignments:
                result.auto_assigned = True
                result.status = "assigned"

        results.append(result)

    return results
