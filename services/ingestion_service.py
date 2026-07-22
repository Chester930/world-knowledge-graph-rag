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
from parser.chunk_writer import (
    document_folder_path,
    read_original_text,
    read_sentences_index,
    write_chunks_as_markdown,
    write_original_text,
    write_sentences_index,
)
from parser.core import DocumentParser, URLParser, sentence_aware_chunking, split_into_sentences
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

    除了 RAG 用的分塊檔案，同時把切塊前的原始純文字另存一份（`original.md`，
    見 `parser.chunk_writer.write_original_text()`）——SVO 抽取不沿用這份 RAG
    切塊，需要對原文重新切塊/標準化，保留原文可避免下游需要時得重新解析原始
    上傳檔案（掃描 PDF 重跑 OCR 成本高）。同時也把句子切分結果存成
    `sentences.json`（見 `parser.chunk_writer.write_sentences_index()`）——
    句子切分本身雖是純規則運算、可隨時重算，但下游（3.4 §a 標準化、未來的
    斷點續傳、SVO Chunk 與原句子的對應索引）需要一份不會因規則調整而跑掉的
    穩定句子清單，此處一次算好存下來，避免下游各自重算導致邊界對不上。

    回傳 `(文件資料夾路徑, 記錄檔內容)`；重複呼叫同一 `source`（內容更新後重新
    處理）時的覆寫語意完全交由 `write_chunks_as_markdown()`／`write_original_text()`／
    `write_sentences_index()`／`document_record_service.init_record()` 既有行為
    處理，此函式不額外介入。
    """
    if not source.strip():
        raise ValueError("source 不可為空白")

    chunks = sentence_aware_chunking(text)
    if not chunks:
        raise ValueError(f"文件內容為空或無法切塊，略過歸檔：{source}")

    write_chunks_as_markdown(chunks, source, staging_dir)
    write_original_text(text, source, staging_dir)
    write_sentences_index(split_into_sentences(text), source, staging_dir)
    doc_folder = document_folder_path(source, staging_dir)
    record = document_record_service.init_record(doc_folder, source=source, total_chunks=len(chunks))
    return doc_folder, record


async def get_or_rebuild_sentences(source: str, base_dir: Path) -> list[str]:
    """§ 3.1.2 `GETSENT` 三層判斷：取得這份文件的句子清單，供 3.4 §a 標準化
    前處理使用。

    優先序：① `sentences.json` 存在就直接讀，最快；② 只有 `original.md`
    沒有 `sentences.json` 時，對其重新呼叫 `split_into_sentences()` 補回來
    （純規則運算，不需要 LLM 或重新解析文件，成本很低），並補寫
    `sentences.json` 供下次直接命中；③ 兩者皆不存在，只有 URL 來源（`source`
    本身是可重新請求的網址）能靠重新抓取＋解析復原，檔案上傳來源的暫存檔已在
    `routers/documents.py::upload_document()` 的 `finally` 區塊被刪除，這個
    分支對檔案上傳來源而言資料已無法復原，屬於需要人工介入的異常狀態，
    非正常運作路徑，直接拋出例外。

    `base_dir` 是這份文件目前所在的資料夾（暫存區或已歸檔的 KG 資料夾皆可，
    與 `document_folder_path()` 的通用參數命名一致）。
    """
    sentences = read_sentences_index(source, base_dir)
    if sentences is not None:
        return sentences

    original_text = read_original_text(source, base_dir)
    if original_text is not None:
        sentences = split_into_sentences(original_text)
        write_sentences_index(sentences, source, base_dir)
        return sentences

    if not source.startswith(("http://", "https://")):
        raise RuntimeError(
            f"文件「{source}」缺少 sentences.json 與 original.md，且非 URL 來源"
            "（檔案上傳的暫存檔已刪除，無法重新解析）——資料已無法復原，"
            "需人工介入，非正常運作路徑。"
        )

    text = await parse_url_service(source)
    sentences = split_into_sentences(text)
    write_original_text(text, source, base_dir)
    write_sentences_index(sentences, source, base_dir)
    return sentences

