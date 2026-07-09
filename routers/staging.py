from __future__ import annotations

from fastapi import APIRouter

from models.knowledge_graph import ClassifyRequest, ClassifyResult
from services import classify_service

router = APIRouter(prefix="/staging", tags=["staging"])


@router.post("/classify", response_model=list[ClassifyResult])
async def classify(payload: ClassifyRequest):
    return await classify_service.classify_all(payload.threshold, payload.auto_assign)
