"""reextract-v2 匯入接續腳本——鎖定既有 KG 236903cf，只補「還沒入列」的文件。

背景：`create_clean_leave_scheduling_kg.py` 每次執行都鑄一個新 KG id，無法接續。
本腳本改成吃既有 KG，逐份檢查 `task_queue.db` 是否已有該文件的 chunk 列
（`enqueue()` 是 `trigger_extraction()` 的最後一步、單一交易原子寫入，所以
一份文件「要嘛全部入列、要嘛完全沒有」），沒有的就重跑該份的
merge_document → merge_law_articles → chunk_and_stage → assign → trigger_extraction。

用法：
    python resume_import_236903cf.py --status   # 只列出每份 done/待補，不寫入
    python resume_import_236903cf.py            # 實際補完未完成的文件

⚠️ 跑之前先確認原本的匯入行程（pid 523 之類）已經停了，別兩個同時寫。
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sqlite3
import time
from pathlib import Path

import httpx

from core.config import staging_folder, task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from import_leave_scheduling_dataset import (
    _derive_law_articles,
    _normalize_effective_date,
    _record_source_string,
)
from models.law_document import LawDocumentCreate
from parser.chunk_writer import document_folder_path, read_sentences_index
from repositories.kg_repo import KGRepository
from repositories.law_document_repo import LawDocumentRepository
from services.classify_service import KGInfo, assign_document_to_kg
from services.document_record_service import document_uuid
from services.ingestion_service import chunk_and_stage
from services.svo_service import trigger_extraction

# 同一支 create 腳本裡的 64 份目標清單 + 資料集迭代器，直接複用
from create_clean_leave_scheduling_kg import _iter_target_records, TARGET_SOURCES
from filter_leave_scheduling_dataset import DEFAULT_DATASET_PATH

KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"


def _tq_count(db_path: Path, source: str) -> int:
    with sqlite3.connect(db_path) as c:
        return c.execute(
            "SELECT COUNT(*) FROM task_queue WHERE kg_id=? AND source=?",
            (KG_ID, source),
        ).fetchone()[0]


def _tq_delete(db_path: Path, source: str) -> None:
    with sqlite3.connect(db_path) as c:
        c.execute("DELETE FROM task_queue WHERE kg_id=? AND source=?", (KG_ID, source))
        c.commit()


async def _delete_chunk_nodes(driver, source_doc_id: str) -> int:
    async with driver.session(database="neo4j") as s:
        res = await s.run(
            "MATCH (c:Chunk {kg_id:$k, source_doc_id:$s}) DETACH DELETE c RETURN count(c) AS n",
            k=KG_ID, s=source_doc_id,
        )
        rec = await res.single()
        return rec["n"] if rec else 0


async def _run(status_only: bool) -> None:
    dataset_path = DEFAULT_DATASET_PATH
    if not dataset_path.is_file():
        raise SystemExit(f"資料集不存在：{dataset_path}")

    candidates = list(_iter_target_records(dataset_path))
    print(f"目標清單 {len(TARGET_SOURCES)} 份，資料集實際找到 {len(candidates)} 份")

    db_path = task_queue_db_path()
    print(f"task_queue.db = {db_path}")

    await connect()
    init_providers()
    driver = get_driver()
    try:
        kg = await KGRepository(driver).get(__import__("uuid").UUID(KG_ID))
        if kg is None:
            raise SystemExit(f"KG {KG_ID} 不存在——請先確認 create 腳本至少建過 KG")
        print(f"接續 KG：id={kg.id} name={kg.name}")
        kg_info = KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))
        law_doc_repo = LawDocumentRepository(driver)

        done, todo = [], []
        for rec in candidates:
            source = _record_source_string(rec)
            n = _tq_count(db_path, source)
            (done if n > 0 else todo).append((source, n))

        print(f"\n已入列（跳過）：{len(done)} 份")
        print(f"待補：{len(todo)} 份")
        for s, _ in todo:
            print(f"  - {s}")
        if status_only:
            print("\n--status 模式：未寫入任何東西。")
            return

        todo_sources = {s for s, _ in todo}
        imported = redone = failed = 0
        for idx, rec in enumerate(candidates, start=1):
            source = _record_source_string(rec)
            if source not in todo_sources:
                continue
            source_doc_id = document_uuid(source)

            # 清掉可能的半套殘留：資料夾 + Chunk 節點 + task_queue 列
            folder = document_folder_path(source, kg_info.folder_path)
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
                redone += 1
                print(f"  [清] 移除半套資料夾：{source}", flush=True)
            deleted = await _delete_chunk_nodes(driver, str(source_doc_id))
            if deleted:
                print(f"  [清] DETACH DELETE {deleted} Chunk 節點：{source}", flush=True)
            _tq_delete(db_path, source)

            payload = rec.get("payload", {})
            articles = payload.get("articles", [])
            await law_doc_repo.merge_document(LawDocumentCreate(
                kg_id=kg.id,
                source_doc_id=source_doc_id,
                source=source,
                title=rec.get("title") or "unknown",
                record_type=rec.get("record_type") or "unknown",
                content_hash=rec.get("content_hash") or "",
                update_date=payload.get("update_date") or None,
                effective_date=_normalize_effective_date(payload.get("effective_date")),
                effective_note=payload.get("effective_note") or None,
                source_url=rec.get("provenance", {}).get("source_url"),
            ))
            await law_doc_repo.merge_law_articles(
                _derive_law_articles(kg.id, source_doc_id, articles)
            )

            text = rec.get("text", "").strip()
            if not text:
                print(f"  ⚠️ text 為空，略過：{source}", flush=True)
                failed += 1
                continue

            staging_doc_folder, _record = chunk_and_stage(text, source, staging_folder())
            dest = assign_document_to_kg(staging_doc_folder, kg_info, method="manual")
            t0 = time.monotonic()
            sentences = read_sentences_index(source, kg_info.folder_path) or []
            timeout_seconds = max(600, len(sentences) * 5)
            try:
                await asyncio.wait_for(
                    trigger_extraction(driver, dest, kg.id, articles=articles),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                failed += 1
                print(f"  ⚠️ 逾時（>{timeout_seconds}s），之後可再跑本腳本補：{source}", flush=True)
                continue
            except httpx.HTTPError as exc:
                failed += 1
                print(f"  ⚠️ LLM 呼叫失敗（{type(exc).__name__}），之後可再跑本腳本補：{source}", flush=True)
                continue
            imported += 1
            print(
                f"  [{idx}/{len(candidates)}] 補完並入列（{time.monotonic()-t0:.1f}s，"
                f"{len(articles)} 條）：{source}（{_tq_count(db_path, source)} chunk）",
                flush=True,
            )

        print(f"\n完成：補入 {imported} 份（其中清過半套殘留 {redone} 份），失敗/逾時 {failed} 份。")
        rows = 0
        with sqlite3.connect(db_path) as c:
            rows = c.execute(
                "SELECT COUNT(*) FROM task_queue WHERE kg_id=?", (KG_ID,)
            ).fetchone()[0]
        print(f"KG {KG_ID} 目前 task_queue 總列數：{rows}")
        if failed:
            print("有失敗/逾時——再跑一次本腳本即可只針對那幾份重試。")
    finally:
        await disconnect()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--status", action="store_true", help="只列出 done/待補，不寫入")
    args = p.parse_args()
    asyncio.run(_run(args.status))
