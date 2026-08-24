"""§ 3.1.2／3.1.3／3.1.4 抽取 Worker 背景迴圈。

對應 `docs/報告/11_抽取管線完整實作任務書.md` P0-3、
`docs/論文/03_系統設計與方法論.md` § 3.1.2「`WORKER` 執行模型定案
（2026-07-27）」：常駐背景 asyncio 任務，隨宿主行程啟動，真正消費
`task_queue_service.next_pending()`——在本模組新增之前，這個函式從未被
任何呼叫端使用過。同時是五態機制（`pending`／`processing`／`completed`／
`failed`／`pending_upload`）`PROC`／`RESULT`／`UPLOAD`／`DONE4`／`FAIL`
節點第一次被實際串接的地方。

Traceability: 02 §2.4.1 -> 03 §3.1.2／§3.1.3／§3.1.4 -> 04 §4.6.
Project: asyncio background worker is this project's own integration; the worker does
not claim to be a direct Spark or external queue implementation. Tests:
tests/services/test_extraction_worker.py.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from neo4j import AsyncDriver

from core.config import task_queue_db_path
from core.providers.factory import get_embedding_provider, get_llm_provider
from parser.chunk_writer import document_folder_path
from repositories.kg_repo import KGRepository
from services import document_record_service, task_queue_service
from services.svo_chunking import read_svo_index
from services.svo_service import extract_svo_triples, merge_triples_to_graph

logger = logging.getLogger(__name__)


def _find_chunk(kg_folder: Path, source: str, chunk_index: int) -> dict | None:
    """從 `svo_index.json`（`svo_chunking.write_svo_chunks()` 寫出）找出指定
    `chunk_index` 的內容與句子範圍中繼資料，供抽取與來源追溯使用。"""
    doc_folder = document_folder_path(source, kg_folder)
    index = read_svo_index(doc_folder)
    if index is None:
        return None
    for chunk in index["chunks"]:
        if chunk["index"] == chunk_index:
            return chunk
    return None


async def _process_one(driver: AsyncDriver, kg_id: str, source: str, chunk_index: int) -> None:
    db_path = task_queue_db_path()
    task_queue_service.update_status(db_path, kg_id, source, chunk_index, "processing")

    doc_folder: Path | None = None
    try:
        kg = await KGRepository(driver).get(UUID(kg_id))
        if kg is None:
            raise ValueError(f"找不到 KG：{kg_id}")

        kg_folder = Path(kg.folder_path)
        doc_folder = document_folder_path(source, kg_folder)
        chunk = _find_chunk(kg_folder, source, chunk_index)
        if chunk is None:
            raise ValueError(f"找不到 SVO chunk：source={source} chunk_index={chunk_index}")

        try:
            embedding_provider = get_embedding_provider()
        except RuntimeError:
            embedding_provider = None
        try:
            llm_provider = get_llm_provider()
        except RuntimeError:
            llm_provider = None

        triples = await extract_svo_triples(
            chunk["text"], llm_provider, embedding_provider,
            kg_id=kg_id, calibration_db_path=db_path,
        )
        # § 3.1.4 §c（2026-08-18 定案）：source_doc_id 先前從未被賦值，導致
        # HAS_ENTITY 邊／Fact 節點在正式環境從未真正建立過。document_uuid()
        # 對穩定的 source 決定性推導出 UUID，同一份文件每次都得到相同的值。
        source_doc_id = document_record_service.document_uuid(source)
        for triple in triples:
            triple.source_doc_id = source_doc_id
            # 2026-08-19：冗餘存下原始文件名稱字串，見 SVOTriple.source 欄位
            # docstring——source_doc_id 是單向雜湊，只存 UUID 在特定情境下
            # （例如 chunk 檔名跨文件撞名）無法可靠回溯原文。
            triple.source = source
            triple.source_svo_chunk_index = chunk["index"]
            triple.source_svo_chunk_file = chunk["filename"]
            triple.source_sentence_start = chunk["source_sentence_start"]
            triple.source_sentence_end = chunk["source_sentence_end"]
        if triples:
            await merge_triples_to_graph(
                driver, UUID(kg_id), triples,
                embedding_provider=embedding_provider, llm_provider=llm_provider,
            )
    except Exception:
        # 單一 chunk 的抽取失敗（LLM 逾時／格式錯誤／KG 或 chunk 遺失等）不應該
        # 讓整個背景 Worker 迴圈跟著中斷——記錄失敗狀態後繼續處理佇列中的下一項。
        logger.exception(
            "[ExtractionWorker] 抽取失敗 kg_id=%s source=%s chunk_index=%s", kg_id, source, chunk_index,
        )
        task_queue_service.update_status(db_path, kg_id, source, chunk_index, "failed")
        if doc_folder is not None:
            document_record_service.mark_extraction_failed(doc_folder)
        return

    # RESULT／UPLOAD／DONE4：merge 已寫入 Neo4j，依序轉為 pending_upload → completed。
    task_queue_service.update_status(db_path, kg_id, source, chunk_index, "pending_upload")
    task_queue_service.update_status(db_path, kg_id, source, chunk_index, "completed")
    document_record_service.record_chunk_completed(doc_folder, chunk_index)


async def run_extraction_worker(driver: AsyncDriver, poll_interval_idle: float = 2.0) -> None:
    """常駐背景任務主迴圈：查無待處理項目時輪詢等待，查到則依序處理
    （`PROC`→`LLM_SVO`→`RESULT`→`UPLOAD`／`FAIL`）。由 `main.py::lifespan`
    以 `asyncio.create_task()` 啟動，`task.cancel()` 優雅關閉——`asyncio.sleep()`
    在取消時會拋出 `asyncio.CancelledError`，直接向上傳遞，不在此攔截。
    """
    db_path = task_queue_db_path()
    while True:
        pending = task_queue_service.next_pending(db_path)
        if pending is None:
            await asyncio.sleep(poll_interval_idle)
            continue
        kg_id, source, chunk_index = pending
        await _process_one(driver, kg_id, source, chunk_index)
