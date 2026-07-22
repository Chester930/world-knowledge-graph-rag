from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.config import staging_folder as _staging_folder
from core.config import task_queue_db_path
from core.database import get_driver
from models.knowledge_graph import (
    AssignRequest,
    ClassifyRequest,
    ClassifyResult,
    ClusterAnalyzeResult,
    ClusterConfirmRequest,
    KnowledgeGraphCreate,
)
from repositories.kg_repo import KGRepository
from services import classify_service, cluster_service, document_record_service, task_queue_service
from services.svo_preprocessing_service import prepare_svo_ready_chunks

router = APIRouter(prefix="/staging", tags=["staging"])


async def _trigger_extraction(doc_folder: Path, kg_id: UUID) -> None:
    """文件搬進 KG 資料夾後立即觸發抽取任務（§ 3.1.2「立即觸發抽取任務，
    不需要使用者另外按『開始建圖』」）：`CHUNKREADY`（前處理＋SVO 專用切塊）
    → `ENQUEUE`（登記進 `task_queue.db`）。同步直接呼叫（2026-07-21 使用者
    決策），而非背景排程或延後執行。

    ⚠️ 誠實侷限：`prepare_svo_ready_chunks()` 目前以 `mentions=None` 呼叫，
    跳過 §a 別名登記表階段（具名提及抽取／NER 仍是未解決的上游依賴），且
    未提供 LLM/embedding provider，代名詞消解與實體去重皆退化為最保守版本
    （見 `services/svo_preprocessing_service.py`／`services/svo_service.py`
    docstring）。Provider 注入待第四章實作接上 `core/providers/factory.py`
    時一併處理，非本次範圍。
    """
    record = document_record_service.read_record(doc_folder)
    if record is None:
        return

    kg_folder = doc_folder.parent
    _paths, chunks = await prepare_svo_ready_chunks(record.source, kg_folder, kg_folder)
    if not chunks:
        return

    document_record_service.set_svo_chunk_total(doc_folder, len(chunks))
    task_queue_service.enqueue(
        task_queue_db_path(), str(kg_id), record.source, list(range(1, len(chunks) + 1)),
    )


async def _known_kgs() -> list[classify_service.KGInfo]:
    """組裝 classify_service／cluster_service 所需的最小 KG 資訊清單。

    依賴 `KGRepository.list_all()`（Neo4j KG CRUD，v2 尚為 stub，屬另一個未
    實作的功能節點）——本路由層可以完整接線，但在 kg_repo 實作完成前，
    呼叫仍會拋出 NotImplementedError，這與本專案其餘 router（例如
    routers/knowledge_graph.py）目前已接好但仍依賴 stub 的狀態一致。
    """
    kgs = await KGRepository(get_driver()).list_all()
    return [
        classify_service.KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))
        for kg in kgs
    ]


@router.post("/classify", response_model=list[ClassifyResult])
async def classify(payload: ClassifyRequest):
    """批次分類暫存區文件：對應 § 3.1.1 功能 ①（自動分配）／②（留在未分配池）。

    自動分配成功的文件，資料夾已被 `classify_all` 內部的 `assign_document_to_kg`
    搬進目標 KG 資料夾，此處緊接著為每一份觸發抽取任務（見 `_trigger_extraction`）。
    """
    known_kgs = await _known_kgs()
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None,
        classify_service.classify_all,
        _staging_folder(), known_kgs, payload.auto_assign, payload.threshold,
    )

    kg_folders = {kg.kg_id: kg.folder_path for kg in known_kgs}
    for result in results:
        if result.auto_assigned and result.matched_kg_id in kg_folders:
            doc_folder = kg_folders[result.matched_kg_id] / result.filename
            await _trigger_extraction(doc_folder, result.matched_kg_id)

    return results


@router.post("/{filename}/assign", status_code=204)
async def assign(filename: str, payload: AssignRequest):
    """手動將暫存區單一文件資料夾分配至既有 KG：對應 § 3.1.1 功能 ③。"""
    doc_folder = _staging_folder() / filename
    if not doc_folder.exists():
        raise HTTPException(status_code=404, detail=f"暫存區找不到資料夾：{filename}")

    kg = await KGRepository(get_driver()).get(payload.kg_id)
    if kg is None:
        raise HTTPException(status_code=404, detail="KG 不存在")

    kg_info = classify_service.KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))
    loop = asyncio.get_running_loop()
    dest = await loop.run_in_executor(
        None, classify_service.assign_document_to_kg, doc_folder, kg_info, "manual",
    )
    await _trigger_extraction(dest, kg.id)


@router.post("/cluster/analyze", response_model=ClusterAnalyzeResult)
async def analyze_clusters():
    """分析未分配資料夾池，回傳候選分群建議：對應 § 3.1.1 功能 ④、§ 3.1.1 §a。

    回傳結果不在後端保存——`ClusterSuggestion` 的名稱／檔案清單由前端持有，
    使用者可各自獨立微調後，再透過 `/staging/cluster/confirm` 一次送出確認後
    的最終內容，後端不需要在兩次呼叫之間追蹤「審核到一半」的中間狀態。
    """
    return await cluster_service.analyze_staging_pool(_staging_folder())


@router.post("/cluster/confirm", status_code=201)
async def confirm_cluster(payload: ClusterConfirmRequest):
    """使用者審核（可能已微調名稱／檔案清單）後確認建立新 KG，並搬移確認後的
    文件資料夾清單：對應 § 3.1.1 功能 ④ 的最終落地步驟。"""
    staging = _staging_folder()
    missing = [f for f in payload.confirmed_folders if not (staging / f).exists()]
    if missing:
        raise HTTPException(status_code=404, detail=f"暫存區找不到資料夾：{missing}")

    kg_repo = KGRepository(get_driver())
    kg = await kg_repo.create(KnowledgeGraphCreate(
        name=payload.confirmed_name,
        description=payload.confirmed_description,
    ))

    kg_info = classify_service.KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))
    loop = asyncio.get_running_loop()
    for folder_name in payload.confirmed_folders:
        dest = await loop.run_in_executor(
            None,
            classify_service.assign_document_to_kg,
            staging / folder_name, kg_info, "ai_cluster",
        )
        await _trigger_extraction(dest, kg.id)

    return {"kg_id": kg.id, "kg_name": kg.name}
