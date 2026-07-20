"""文件解析（PDF/DOCX/PPTX/TXT/MD → 純文字）＋ 切塊與暫存區歸檔銜接。

已對接到獨立的 parser 模組。

`chunk_and_stage()` 是 `parse_document()`／`parse_url_service()`（純文字擷取）
之後、`services/classify_service.py`（§ 3.1.1 暫存區分類）之前的銜接步驟——
對應 docs/論文/03_系統設計與方法論.md § 3.1.1 開頭「解析完成的文件資料夾（含
切塊內容＋初始記錄檔）」這個前提狀態。在此函式補上之前，`_staging_folder()`
底下不會有任何真正從使用者上傳文件產生的資料夾，`classify_service`／
`cluster_service` 的測試皆是直接手動偽造好切塊檔案繞過這一段，尚未有端到端
的真實管線把兩者串起來。
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from models.knowledge_graph import DocumentRecord
from parser.chunk_writer import document_folder_path, write_chunks_as_markdown
from parser.core import DocumentParser, URLParser, sentence_aware_chunking
from services import document_record_service


async def parse_document(file_path: str) -> str:
    """解析文件，支援 PDF (三層備援), DOCX (表格 Markdown 化), PPTX, TXT, MD, 音訊/影片。

    因為實體解析與 OCR 為 CPU-bound 任務，使用 run_in_executor 於線程池中執行，避免阻塞 FastAPI 主執行緒。
    """
    parser = DocumentParser()
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, parser.parse_file, file_path)
    return text


async def parse_url_service(url: str) -> str:
    """抓取 URL，支援 YouTube 字幕提取與一般網頁正文 Markdown 轉換。

    非同步執行，避免阻塞主執行緒。
    """
    parser = URLParser()
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, parser.parse_url, url)
    return text


def chunk_and_stage(text: str, source: str, staging_dir: Path) -> tuple[Path, DocumentRecord]:
    """對已解析出的純文字做句子感知分塊，寫入暫存區獨立資料夾並初始化記錄檔。

    同步函式（切塊與檔案 I/O 皆為同步操作），FastAPI router 層呼叫時需以
    `run_in_executor` 包裝，避免阻塞事件迴圈（做法同 `services/classify_service.py`）。

    `source` 為空白或切塊結果為空（例如空白文件、擷取失敗僅得空字串）時拋出
    `ValueError`——不建立暫存區資料夾，避免產生一個 0 個切塊、之後分類/分群
    永遠無法計算代表向量的「空殼」暫存項目。

    回傳 `(文件資料夾路徑, 記錄檔內容)`；重複呼叫同一 `source`（內容更新後重新
    處理）時的覆寫語意完全交由 `write_chunks_as_markdown()`／
    `document_record_service.init_record()` 既有行為處理，此函式不額外介入。
    """
    if not source.strip():
        raise ValueError("source 不可為空白")

    chunks = sentence_aware_chunking(text)
    if not chunks:
        raise ValueError(f"文件內容為空或無法切塊，略過歸檔：{source}")

    write_chunks_as_markdown(chunks, source, staging_dir)
    doc_folder = document_folder_path(source, staging_dir)
    record = document_record_service.init_record(doc_folder, source=source, total_chunks=len(chunks))
    return doc_folder, record

