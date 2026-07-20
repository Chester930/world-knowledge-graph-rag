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
)
from repositories.kg_repo import KGRepository
from services import classify_service, cluster_service

router = APIRouter(prefix="/staging", tags=["staging"])


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
    """批次分類暫存區文件：對應 § 3.1.1 功能 ①（自動分配）／②（留在未分配池）。"""
    known_kgs = await _known_kgs()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        classify_service.classify_all,
        _staging_folder(), known_kgs, payload.auto_assign, payload.threshold,
    )


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
    await loop.run_in_executor(
        None, classify_service.assign_document_to_kg, doc_folder, kg_info, "manual",
    )


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
        await loop.run_in_executor(
            None,
            classify_service.assign_document_to_kg,
            staging / folder_name, kg_info, "ai_cluster",
        )

    return {"kg_id": kg.id, "kg_name": kg.name}
