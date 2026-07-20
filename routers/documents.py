from __future__ import annotations
import asyncio
import os
import shutil
import tempfile
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File

from core.config import settings, staging_folder
from core.database import get_driver
from models.document import Document, DocumentCreate
from models.knowledge_graph import StagingIngestResult
from repositories.document_repo import DocumentRepository
from services.ingestion_service import chunk_and_stage, parse_document, parse_url_service

router = APIRouter(prefix="/documents", tags=["documents"])

_UPLOAD_CHUNK_BYTES = 1024 * 1024  # 讀取上傳檔案的串流區塊大小


async def _save_upload_to_temp(file: UploadFile, suffix: str) -> str:
    """把上傳檔案串流寫入暫存檔，邊寫邊檢查是否超過 `settings.max_upload_size_mb`，
    避免不設限的檔案上傳耗盡記憶體/磁碟（單純依賴 `UploadFile.size` 不可靠，
    部分用戶端以 chunked transfer 傳輸時該欄位可能未填）。超過上限會刪除已寫入
    的暫存檔並拋出 HTTPException(413)。
    """
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    total = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        temp_path = tmp.name
        while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                tmp.close()
                os.remove(temp_path)
                raise HTTPException(
                    status_code=413,
                    detail=f"檔案超過上限 {settings.max_upload_size_mb}MB",
                )
            tmp.write(chunk)
    return temp_path


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


@router.post("/upload", response_model=StagingIngestResult, status_code=201)
async def upload_document(file: UploadFile = File(...)):
    """上傳文件，完成解析＋句子感知切塊＋暫存區資料夾歸檔＋記錄檔初始化。

    對應 § 3.1.1 開頭「解析完成的文件資料夾（含切塊內容＋初始記錄檔）」這個
    前提狀態——本端點只負責把文件送到這個狀態，尚未指定歸屬 KG，後續分類/
    分群走 `POST /staging/classify` 等既有端點（見 `routers/staging.py`）。
    """
    suffix = os.path.splitext(file.filename)[1]
    temp_path = await _save_upload_to_temp(file, suffix)

    try:
        text = await parse_document(temp_path)
        loop = asyncio.get_running_loop()
        doc_folder, record = await loop.run_in_executor(
            None, chunk_and_stage, text, file.filename, staging_folder(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件解析/歸檔失敗: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return StagingIngestResult(folder_name=doc_folder.name, record=record)


@router.post("/ingest-url", response_model=StagingIngestResult, status_code=201)
async def ingest_url(payload: dict):
    """抓取 URL（含 YouTube 字幕），完成解析＋切塊＋暫存區歸檔＋記錄檔初始化。
    語意與 `POST /documents/upload` 一致，差別僅在來源是 URL 而非上傳檔案。
    """
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="請提供 url 參數")

    try:
        text = await parse_url_service(url)
        loop = asyncio.get_running_loop()
        doc_folder, record = await loop.run_in_executor(
            None, chunk_and_stage, text, url, staging_folder(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"URL 解析/歸檔失敗: {str(e)}")

    return StagingIngestResult(folder_name=doc_folder.name, record=record)


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
