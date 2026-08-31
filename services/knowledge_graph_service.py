"""KG 建立、自動分群、路由層刷新。

TODO(v2 架構重整)：v1 的暫存區自動分群（LLM 分析 + 命名建議）待重新設計後遷移。
"""
from __future__ import annotations
from pathlib import Path
from uuid import UUID

from neo4j import AsyncDriver

from models.knowledge_graph import KnowledgeGraph, KnowledgeGraphCreate
from repositories.kg_repo import KGRepository
from services import document_record_service, svo_service
from services.svo_chunking import read_svo_index


class ArticleStructureLossError(RuntimeError):
    """`build_graph(force_rebuild=True)` 偵測到目標文件先前是用
    `ArticleAwareChunking`（`article_no` 有值）抽取，但本函式無法取得原始
    `articles` payload、只能改用一般的 `SVOGROUP` 切塊——見 `build_graph()`
    docstring §「誠實侷限」與 `docs/報告/21_抽取管線稽核與修正報告.md`。
    """


async def create_kg(driver: AsyncDriver, payload: KnowledgeGraphCreate) -> KnowledgeGraph:
    return await KGRepository(driver).create(payload)


async def delete_kg(driver: AsyncDriver, kg_id: UUID) -> None:
    await KGRepository(driver).delete(kg_id)


async def build_graph(
    driver: AsyncDriver,
    kg_id: UUID,
    doc_ids: list[str] | None = None,
    force_rebuild: bool = False,
) -> None:
    """觸發 KG 建圖／重建。

    對應 `docs/報告/11_抽取管線完整實作任務書.md` P0-2。v1
    （`智慧知識庫/services/svo_service.py::build_graph_for_kg`）的原始語意是
    同步、SSE 串流呼叫 LLM 逐一抽取；v2 已定案改採背景 Worker 執行模型
    （§ 3.1.2「立即觸發抽取任務」＋ P0-3 抽取 Worker），本函式因此**不**同步
    呼叫 LLM，只負責重設進度＋（重新）排入 `task_queue.db`，實際抽取交由
    P0-3 的背景 Worker 迴圈處理（2026-07-27 使用者確認採用此調整後語意）。

    `doc_ids`：目標文件資料夾清單（`DocumentRecord.source`，即檔名）；`None`
    代表 KG 底下所有文件資料夾。

    `force_rebuild=True`：
      - 逐一重設目標文件的抽取進度（`document_record_service.reset_extraction_progress`）
        並重新觸發 `svo_service.trigger_extraction`（完整重跑 CHUNKREADY）。
      - `doc_ids` 為 `None`（全庫重建）時，另外先清空該 KG 在 Neo4j 內既有的
        `kg_id` 屬性節點與邊，符合「重建」語意。
      - ⚠️ 誠實侷限：`doc_ids` 指定特定文件（局部重建）時，**不會**反向清除
        該文件先前貢獻的圖譜內容——事實層級去重的 MERGE 鍵只有
        `(kg_id, subject, rel_type, object)`（見
        `svo_service.merge_triples_to_graph` docstring），不含來源文件，
        同一條邊可能同時由其他未重建的文件共同貢獻，surgical 移除需要另外
        設計，非本次範圍。重新抽取後仍存在的事實會再次 MERGE（no-op 或新增
        citation），不會產生錯誤資料，只是不會主動清除該文件已被移除／修改
        後遺留的舊事實。

    `force_rebuild=False`：救援／恢復用途（例如 `task_queue.db` 曾遺失、
    Worker 曾中斷）。只對 `extraction_status` 尚未 `completed` 的文件重新
    觸發 `trigger_extraction`，已完成的文件略過，不清空既有圖譜內容。

    ⚠️ **誠實侷限（2026-08-31 稽核發現並加上防呆，見
    docs/報告/21_抽取管線稽核與修正報告.md）**：本函式呼叫
    `svo_service.trigger_extraction()` 時**不會**傳入 `articles=`——法規類
    文件（走 `ArticleAwareChunking`，一條文一個chunk，保留 `article_no`／
    `Fact→LawArticle` 連結）若透過本函式 `force_rebuild=True`，`trigger_
    extraction()` 會改用一般的 `SVOGROUP`（固定句數切塊）**靜默覆寫**掉
    `svo_index.json`，條文邊界全部消失——本函式沒有管道能取得或還原原始
    `articles` payload（未持久化在 `DocumentRecord` 或任何可查詢處）。
    為避免靜默資料劣化，`force_rebuild=True` 時會先檢查目標文件既有的
    `svo_index.json` 是否已用 `ArticleAwareChunking`（任一 chunk 有
    `article_no`）；偵測到就直接拋出 `ArticleStructureLossError`，不靜默
    進行——法規全文的完整重跑，應改用當初建立此 KG 的專用匯入腳本（例如
    `import_leave_scheduling_dataset.py`，已正確傳入 `articles=`），而非
    本函式。
    """
    kg = await KGRepository(driver).get(kg_id)
    if kg is None:
        raise ValueError(f"找不到 KG：{kg_id}")

    kg_folder = Path(kg.folder_path)
    if not kg_folder.is_dir():
        return

    if doc_ids is None:
        target_folders = [f for f in kg_folder.iterdir() if f.is_dir()]
    else:
        target_folders = [kg_folder / name for name in doc_ids if (kg_folder / name).is_dir()]

    if force_rebuild:
        # 2026-08-31 防呆（見本函式 docstring 誠實侷限）：在任何破壞性動作
        # （清空Neo4j／重設進度）之前，先檢查所有目標文件是否有任一份先前
        # 用 ArticleAwareChunking 抽取過——寧可整批直接失敗，也不要清空到
        # 一半才發現有文件會被靜默劣化。
        for doc_folder in target_folders:
            index = read_svo_index(doc_folder)
            if index and any(c.get("article_no") for c in index.get("chunks", [])):
                raise ArticleStructureLossError(
                    f"文件 {doc_folder.name} 先前用 ArticleAwareChunking 抽取（article_no 有值），"
                    "build_graph(force_rebuild=True) 無法還原 articles payload、會靜默改用一般切塊、"
                    "條文邊界全部消失。請改用當初建立此文件的專用匯入腳本重新觸發，而非本函式。"
                )

    if force_rebuild and doc_ids is None:
        await driver.execute_query("MATCH (n {kg_id: $kg_id}) DETACH DELETE n", kg_id=str(kg_id))

    for doc_folder in target_folders:
        record = document_record_service.read_record(doc_folder)
        if record is None:
            continue
        if force_rebuild:
            document_record_service.reset_extraction_progress(doc_folder)
        elif record.extraction_status == "completed":
            continue
        await svo_service.trigger_extraction(driver, doc_folder, kg_id)
