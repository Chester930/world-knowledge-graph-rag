"""文件解析（PDF/DOCX/PPTX/TXT/MD → 純文字）。

TODO(v2 架構重整)：v1 的三層 OCR 備援（pypdf → pdfminer → PaddleOCR）與
sentence-aware chunking 待重新設計後遷移，設計紀錄見 docs/ARCHITECTURE.md。
"""
from __future__ import annotations


async def parse_document(file_path: str) -> str:
    raise NotImplementedError
