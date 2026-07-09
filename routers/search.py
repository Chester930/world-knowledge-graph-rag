from __future__ import annotations

from fastapi import APIRouter

from models.document import SearchRequest, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=list[SearchResult])
async def search(payload: SearchRequest):
    raise NotImplementedError
