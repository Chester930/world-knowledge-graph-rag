"""暫存區文件分類（比對各既有 KG，建議或自動分配歸屬）。

對應 docs/論文/03_系統設計與方法論.md § 3.1.1：分類分數計算採 **Prototypical
Networks**（Snell, Swersky, Zemel, 2017, NeurIPS）的 centroid 相似度精神——
每個 KG 的 prototype 向量是其所有成員文件代表向量的平均，新文件的代表向量
（該文件所有 chunk 向量的平均）與各 KG prototype 的 cosine 相似度即為分類分數。

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

本模組所有函式皆為同步（embedding provider 與檔案 I/O 本身即為同步操作），
FastAPI router 層呼叫時需以 `run_in_executor` 包裝，避免阻塞事件迴圈
（做法同 services/ingestion_service.py）。

2026-07-20 修正（對應 § 3.1.1 優化建議 #1／#2／#3／#5，見 03_系統設計與方法論.md）：
文件向量快取進資料夾記錄檔（`document_record_service.set_document_vector`）、
KG prototype 快取進 `_prototype_cache.json`（成員清單改變才失效重算）、
`classify_all` 批次內以移動平均就地更新剛自動分配的 KG 之 prototype（不再整批
共用同一份、可能過期的 prototype）、`assign_document_to_kg` 的資料夾搬移與記錄檔
更新失敗時互相 rollback（不留下位置與記錄檔不一致的中間態）、`classify_by_vector`
新增 `low_confidence` 標記成員數過少（< `CLUSTER_MIN_SIZE`）的 cold-start KG。
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import UUID

from core.constants import CLASSIFY_AUTO_THRESHOLD, CLASSIFY_MIN_THRESHOLD, CLUSTER_MIN_SIZE
from core.providers.factory import get_embedding_provider
from models.knowledge_graph import ClassifyResult, KGCandidate
from services import document_record_service

_PROTOTYPE_CACHE_FILENAME = "_prototype_cache.json"

logger = logging.getLogger(__name__)


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


def compute_document_vector(doc_folder: Path) -> list[float] | None:
    """計算文件代表向量：該文件所有 chunk 向量的平均。

    優先讀取資料夾記錄檔（`_record.json`）內快取的 `document_vector`，命中則直接
    回傳，不重新呼叫 embedding provider；未命中（記錄檔不存在，或存在但尚未快取）
    才實際計算，計算後若記錄檔存在則寫回快取供下次呼叫使用。快取由
    `document_record_service.init_record()` 在切塊數改變（內容重新解析）時清空，
    見該函式與 `models.knowledge_graph.DocumentRecord.document_vector` 註解。
    """
    record = document_record_service.read_record(doc_folder)
    if record is not None and record.document_vector is not None:
        return record.document_vector

    bodies = read_chunk_bodies(doc_folder)
    if not bodies:
        return None
    embedding = get_embedding_provider()
    vectors = embedding.encode_batch(bodies)
    vector = mean_vector(vectors)
    if vector is not None:
        document_record_service.set_document_vector(doc_folder, vector)
    return vector


def _prototype_cache_path(kg_folder: Path) -> Path:
    return kg_folder / _PROTOTYPE_CACHE_FILENAME


def _read_prototype_cache(kg_folder: Path, member_folders: list[str]) -> list[float] | None:
    """快取命中條件：快取檔存在，且記錄的成員資料夾清單與目前磁碟現況完全相同。

    任何解析失敗（快取檔損毀、格式不符）都視為未命中、退回重新計算，不拋例外
    中斷分類流程——快取只是效能優化，正確性永遠以「重新計算」為準。
    """
    cache_path = _prototype_cache_path(kg_folder)
    if not cache_path.exists():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("member_folders") == member_folders:
            return cached.get("prototype")
    except Exception as e:
        logger.warning(f"KG prototype 快取讀取失敗，改為重新計算 [{kg_folder}]: {e}")
    return None


def _write_prototype_cache(kg_folder: Path, member_folders: list[str], prototype: list[float] | None) -> None:
    try:
        _prototype_cache_path(kg_folder).write_text(
            json.dumps({"member_folders": member_folders, "prototype": prototype}),
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
    if not kg_folder.exists():
        return None
    member_folders = sorted(p.name for p in kg_folder.iterdir() if p.is_dir())

    cached = _read_prototype_cache(kg_folder, member_folders)
    if cached is not None:
        return cached

    member_vectors = []
    for name in member_folders:
        vec = compute_document_vector(kg_folder / name)
        if vec is not None:
            member_vectors.append(vec)
    prototype = mean_vector(member_vectors)
    _write_prototype_cache(kg_folder, member_folders, prototype)
    return prototype


def count_kg_members(kg_folder: Path) -> int:
    """該 KG 資料夾底下的成員文件數，供分類信心判斷（見 `classify_by_vector`
    的 `kg_member_counts` 參數）使用，與 prototype 計算邏輯分開、各自獨立。"""
    if not kg_folder.exists():
        return 0
    return sum(1 for p in kg_folder.iterdir() if p.is_dir())


# ── 純分數計算（不涉及 I/O，方便以合成向量單元測試）───────────────────────────

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, dot / (n1 * n2)))


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


# ── 歸檔動作（實體資料夾搬移＋記錄檔更新）───────────────────────────────────

def assign_document_to_kg(doc_folder: Path, kg: KGInfo, method: str = "manual") -> Path:
    """把文件資料夾實際搬移到目標 KG 資料夾底下，並更新記錄檔的歸屬歷史。

    搬移是同一磁碟分割內的 rename（`shutil.move` 在來源/目的地同分割時即為
    原子操作），不是複製再刪除，不會有「搬到一半」的中間態。回傳搬移後的
    新資料夾路徑。

    搬移與記錄檔更新兩步視為一個整體：若記錄檔更新失敗（例如磁碟已滿、權限
    問題），會把資料夾移回原位再拋出例外，確保「資料夾實際位置」與「記錄檔
    歸屬歷史」不會不一致——呼叫端看到例外時，資料夾必定還在原本呼叫前的位置，
    不會出現「已經搬過去但記錄檔沒寫」的中間態。
    """
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


# ── 批次分類（I/O 入口）─────────────────────────────────────────────────────

def classify_document(doc_folder: Path, known_kgs: Iterable[KGInfo]) -> ClassifyResult:
    """對暫存區單一文件資料夾計算分類分數（重新計算所有 KG prototype，
    僅供單筆呼叫使用；批次請用 classify_all 以避免重複計算 prototype）。"""
    known_kgs = list(known_kgs)
    doc_vector = compute_document_vector(doc_folder)
    prototypes = {kg: compute_kg_prototype(kg.folder_path) for kg in known_kgs}
    member_counts = {kg: count_kg_members(kg.folder_path) for kg in known_kgs}
    return classify_by_vector(doc_folder.name, doc_vector, prototypes, kg_member_counts=member_counts)


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

    prototypes = {kg: compute_kg_prototype(kg.folder_path) for kg in known_kgs}
    member_counts = {kg: count_kg_members(kg.folder_path) for kg in known_kgs}

    results: list[ClassifyResult] = []
    for doc_folder in sorted(p for p in staging_folder.iterdir() if p.is_dir()):
        try:
            doc_vector = compute_document_vector(doc_folder)
            result = classify_by_vector(
                doc_folder.name, doc_vector, prototypes, kg_member_counts=member_counts,
            )
        except Exception as e:
            logger.warning(f"分類失敗 [{doc_folder.name}]: {e}")
            results.append(ClassifyResult(filename=doc_folder.name, status="error"))
            continue

        if auto_assign and result.matched_kg_id and result.score >= auto_threshold:
            target = next(k for k in known_kgs if k.kg_id == result.matched_kg_id)
            assign_document_to_kg(doc_folder, target, method="auto")
            result.auto_assigned = True
            result.status = "assigned"

            if doc_vector is not None:
                prototypes[target] = _incremental_prototype_update(
                    prototypes.get(target), member_counts.get(target, 0), doc_vector,
                )
                member_counts[target] = member_counts.get(target, 0) + 1

        results.append(result)

    return results
