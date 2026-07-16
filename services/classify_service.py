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
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import UUID

from core.constants import CLASSIFY_AUTO_THRESHOLD, CLASSIFY_MIN_THRESHOLD
from core.providers.factory import get_embedding_provider
from models.knowledge_graph import ClassifyResult, KGCandidate
from services import document_record_service

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
    """計算文件代表向量：該文件所有 chunk 向量的平均。"""
    bodies = read_chunk_bodies(doc_folder)
    if not bodies:
        return None
    embedding = get_embedding_provider()
    vectors = embedding.encode_batch(bodies)
    return mean_vector(vectors)


def compute_kg_prototype(kg_folder: Path) -> list[float] | None:
    """計算 KG prototype 向量：該 KG 資料夾底下所有成員文件代表向量的平均。"""
    if not kg_folder.exists():
        return None
    member_vectors = []
    for member_folder in sorted(p for p in kg_folder.iterdir() if p.is_dir()):
        vec = compute_document_vector(member_folder)
        if vec is not None:
            member_vectors.append(vec)
    return mean_vector(member_vectors)


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
) -> ClassifyResult:
    """給定文件代表向量與各 KG 的 prototype 向量，計算候選排名（純函式，無 I/O）。"""
    if doc_vector is None:
        return ClassifyResult(filename=filename, status="unmatched")

    candidates: list[KGCandidate] = []
    for kg, prototype in kg_prototypes.items():
        if prototype is None:
            continue
        score = cosine_similarity(doc_vector, prototype)
        if score < min_threshold:
            continue
        candidates.append(KGCandidate(kg_id=kg.kg_id, kg_name=kg.kg_name, score=round(score, 4)))

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
    """
    kg.folder_path.mkdir(parents=True, exist_ok=True)
    dest = kg.folder_path / doc_folder.name
    shutil.move(str(doc_folder), str(dest))

    document_record_service.append_assignment(
        dest, kg_id=kg.kg_id, kg_name=kg.kg_name, method=method,
    )
    return dest


# ── 批次分類（I/O 入口）─────────────────────────────────────────────────────

def classify_document(doc_folder: Path, known_kgs: Iterable[KGInfo]) -> ClassifyResult:
    """對暫存區單一文件資料夾計算分類分數（重新計算所有 KG prototype，
    僅供單筆呼叫使用；批次請用 classify_all 以避免重複計算 prototype）。"""
    known_kgs = list(known_kgs)
    doc_vector = compute_document_vector(doc_folder)
    prototypes = {kg: compute_kg_prototype(kg.folder_path) for kg in known_kgs}
    return classify_by_vector(doc_folder.name, doc_vector, prototypes)


def classify_all(
    staging_folder: Path,
    known_kgs: Iterable[KGInfo],
    auto_assign: bool = False,
    auto_threshold: float = CLASSIFY_AUTO_THRESHOLD,
) -> list[ClassifyResult]:
    """對暫存區底下所有文件資料夾批次執行分類；每個 KG 的 prototype 只計算一次
    並在整批文件間重複使用，避免對同一個 KG 重複重新嵌入其成員文件。"""
    known_kgs = list(known_kgs)
    if not staging_folder.exists():
        return []

    prototypes = {kg: compute_kg_prototype(kg.folder_path) for kg in known_kgs}

    results: list[ClassifyResult] = []
    for doc_folder in sorted(p for p in staging_folder.iterdir() if p.is_dir()):
        try:
            doc_vector = compute_document_vector(doc_folder)
            result = classify_by_vector(doc_folder.name, doc_vector, prototypes)
        except Exception as e:
            logger.warning(f"分類失敗 [{doc_folder.name}]: {e}")
            results.append(ClassifyResult(filename=doc_folder.name, status="error"))
            continue

        if auto_assign and result.matched_kg_id and result.score >= auto_threshold:
            target = next(k for k in known_kgs if k.kg_id == result.matched_kg_id)
            assign_document_to_kg(doc_folder, target, method="auto")
            result.auto_assigned = True
            result.status = "assigned"

        results.append(result)

    return results
