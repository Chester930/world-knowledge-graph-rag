from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.database import get_driver
from models.knowledge_graph import (
    BuildGraphRequest,
    KnowledgeGraph,
    KnowledgeGraphCreate,
    KnowledgeGraphUpdate,
)
from repositories.kg_repo import KGRepository
from services import knowledge_graph_service

router = APIRouter(prefix="/knowledge-graphs", tags=["knowledge-graphs"])


@router.get("", response_model=list[KnowledgeGraph])
async def list_kgs():
    return await KGRepository(get_driver()).list_all()


@router.post("", response_model=KnowledgeGraph, status_code=201)
async def create_kg(payload: KnowledgeGraphCreate):
    return await knowledge_graph_service.create_kg(payload)


@router.get("/{kg_id}", response_model=KnowledgeGraph)
async def get_kg(kg_id: UUID):
    kg = await KGRepository(get_driver()).get(kg_id)
    if kg is None:
        raise HTTPException(status_code=404, detail="KG 不存在")
    return kg


@router.patch("/{kg_id}", response_model=KnowledgeGraph)
async def update_kg(kg_id: UUID, patch: KnowledgeGraphUpdate):
    return await KGRepository(get_driver()).update(kg_id, patch)


@router.delete("/{kg_id}", status_code=204)
async def delete_kg(kg_id: UUID):
    await knowledge_graph_service.delete_kg(kg_id)


@router.post("/{kg_id}/build-graph", status_code=202)
async def build_graph(kg_id: UUID, payload: BuildGraphRequest):
    await knowledge_graph_service.build_graph(kg_id, payload.force_rebuild)
    return {"status": "accepted"}
