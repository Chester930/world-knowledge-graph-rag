from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from core.config import staging_folder as _staging_folder
from core.database import get_driver
from models.knowledge_graph import (
    AssignRequest,
    ClassifyRequest,
    ClassifyResult,
    ClusterAnalyzeResult,
    ClusterConfirmRequest,
    KnowledgeGraphCreate,
    StagingPoolItem,
)
from repositories.kg_repo import KGRepository
from services import classify_service, cluster_service, document_record_service, svo_service

router = APIRouter(prefix="/staging", tags=["staging"])


async def _known_kgs() -> list[classify_service.KGInfo]:
    """組裝 classify_service／cluster_service 所需的最小 KG 資訊清單。

    依賴 `KGRepository.list_all()`（Neo4j KG CRUD）——已為實作完成的 Cypher
    查詢（`docs/報告/11_抽取管線完整實作任務書.md` P0-1），查無資料回傳空清單。
    """
    kgs = await KGRepository(get_driver()).list_all()
    return [
        classify_service.KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))
        for kg in kgs
    ]


@router.get("", response_model=list[StagingPoolItem])
async def list_pool():
    """列出未分配資料夾池（§ 3.1.1 POOL 節點）目前有哪些文件在等分類。

    只讀不寫；供 UI 呈現「暫存區堆了哪些東西」，並判斷哪些可對其單獨重新
    觸發分類（`POST /staging/{filename}/classify`）。資料夾內沒有合法記錄檔
    時 `record` 為 `None`（異常狀態，通常是舊資料夾或人工放入的）。
    """
    staging = _staging_folder()
    if not staging.exists():
        return []

    items: list[StagingPoolItem] = []
    for folder in sorted(p for p in staging.iterdir() if p.is_dir()):
        record = document_record_service.read_record(folder)
        items.append(StagingPoolItem(
            folder_name=folder.name,
            record=record,
            chunk_files=sum(1 for _ in folder.glob("chunk-*-of-*.md")),
            has_document_vector=record is not None and record.document_vector is not None,
        ))
    return items


@router.post("/{filename}/classify", response_model=ClassifyResult)
async def classify_one(filename: str):
    """對未分配池中的單一文件重新計算分類分數（§ 3.1.1 POOL 節點「之後任何
    時間手動重新觸發個別分類」）。只回候選排名，不自動搬移——要採用某個候選
    仍走 `POST /staging/{filename}/assign`。
    """
    doc_folder = _staging_folder() / filename
    if not doc_folder.exists():
        raise HTTPException(status_code=404, detail=f"暫存區找不到資料夾：{filename}")

    known_kgs = await _known_kgs()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, classify_service.classify_document, doc_folder, known_kgs,
    )


@router.post("/classify", response_model=list[ClassifyResult])
async def classify(payload: ClassifyRequest):
    """批次分類暫存區文件：對應 § 3.1.1 功能 ①（自動分配）／②（留在未分配池）。

    自動分配成功的文件，資料夾已被 `classify_all` 內部的 `assign_document_to_kg`
    搬進目標 KG 資料夾，此處緊接著為每一份觸發抽取任務（見
    `services.svo_service.trigger_extraction`）。
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
            await svo_service.trigger_extraction(get_driver(), doc_folder, result.matched_kg_id)

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
    await svo_service.trigger_extraction(get_driver(), dest, kg.id)


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
        await svo_service.trigger_extraction(get_driver(), dest, kg.id)

    return {"kg_id": kg.id, "kg_name": kg.name}
