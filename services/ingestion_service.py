"""文件解析（PDF/DOCX/PPTX/TXT/MD → 純文字）。

已對接到獨立的 parser 模組。
"""
from __future__ import annotations
import asyncio
from parser.core import DocumentParser


async def parse_document(file_path: str) -> str:
    """解析文件，支援 PDF (三層備援), DOCX (表格 Markdown 化), PPTX, TXT, MD。

    因為實體解析與 OCR 為 CPU-bound 任務，使用 run_in_executor 於線程池中執行，避免阻塞 FastAPI 主執行緒。
    """
    parser = DocumentParser()
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, parser.parse_file, file_path)
    return text
