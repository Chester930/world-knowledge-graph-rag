from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, HTTPException

from core.database import get_driver
from models.document import Document, DocumentCreate
from repositories.document_repo import DocumentRepository

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=Document, status_code=201)
async def create_document(payload: DocumentCreate):
    return await DocumentRepository(get_driver()).create(payload)


@router.get("/{doc_id}", response_model=Document)
async def get_document(doc_id: UUID):
    doc = await DocumentRepository(get_driver()).get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return doc


@router.get("", response_model=list[Document])
async def list_documents(kg_id: UUID):
    return await DocumentRepository(get_driver()).list_by_kg(kg_id)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID):
    await DocumentRepository(get_driver()).delete(doc_id)
