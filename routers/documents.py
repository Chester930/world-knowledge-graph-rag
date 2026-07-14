from __future__ import annotations
import os
import shutil
import tempfile
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File

from core.database import get_driver
from models.document import Document, DocumentCreate
from repositories.document_repo import DocumentRepository
from services.ingestion_service import parse_document, parse_url_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/debug-parse-url")
async def debug_parse_url(payload: dict):
    """臨時下載並解析網頁或 YouTube 連結，返回純文字（僅供調試與前端展示）。"""
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="請提供 url 參數")
    try:
        text = await parse_url_service(url)
        return {"filename": url, "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"URL 解析失敗: {str(e)}")


@router.post("/debug-parse")
async def debug_parse_document(file: UploadFile = File(...)):
    """臨時上傳並解析文件，返回純文字（僅供調試與前端展示，不寫入圖資料庫）。"""
    suffix = os.path.splitext(file.filename)[1]
    # 建立臨時暫存檔，副檔名與上傳檔案一致以供 parser 路由
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    try:
        text = await parse_document(temp_path)
        return {"filename": file.filename, "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件解析失敗: {str(e)}")
    finally:
        # 確保刪除暫存檔
        if os.path.exists(temp_path):
            os.remove(temp_path)



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
