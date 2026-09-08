# -*- coding: utf-8 -*-
"""報告32 §9 — Test B：定向補抽「窗口 5 份」剩餘 pending chunk。

⚠️ 前置：**主 drain（drain_236903cf.py）必須先停**。next_pending() 不標 processing，
   兩個 worker 併跑會對同一 chunk 重覆 merge、產生重覆/損壞 Fact。

做的事 = drain 迴圈本體照抄：對每個 (source, chunk_index)
   revoke_chunk_facts()  →  _process_one()（自己管 processing→completed / failed）

covered docs（覆蓋 Q3 / Q6 / Q8 / 窗口對照 + T1 Q2/E3 疑點）：
   N0060004  勞工作業場所容許暴露標準          （G2 / Q8 變量係數多跳）
   N0030025  勞基法第45條認定基準              （G3 / Q3 三段年齡工時）
   N0060065  女性勞工母性健康保護實施辦法        （G3 / Q6 血中鉛分級）
   N0050030  災區受災勞工保險費支應及傷病給付辦法  （窗口對照）
   N0030018  育嬰留職停薪實施辦法              （T1 Q2；E3「六個月→六個半月」疑點）

用法：
    # 1) 先確認 drain 已停：tasklist | findstr drain   （應無）
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    python targeted_extract_window.py --status      # 只列 pending 清單，不動
    nohup python -u targeted_extract_window.py >> "<job>/tmp/targeted_extract.log" 2>&1 &
    # 完成訊號： TARGETED-DONE  → 通知 [6de205] 重啟 drain_236903cf.py
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
import time
from uuid import UUID

WT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, WT)
os.chdir(WT)

from core.database import connect, disconnect, get_driver  # noqa: E402
from core.providers.factory import init_providers  # noqa: E402
from core.config import task_queue_db_path  # noqa: E402
from services.extraction_worker import _process_one  # noqa: E402
from services.svo_service import revoke_chunk_facts  # noqa: E402
from services import document_record_service  # noqa: E402

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)

DOC_PREFIXES = ["N0060004", "N0030025", "N0060065", "N0050030", "N0030018"]


def _pending_rows(db_path) -> list[tuple[str, int, str]]:
    c = sqlite3.connect(str(db_path))
    like = " OR ".join("source LIKE ?" for _ in DOC_PREFIXES)
    rows = c.execute(
        f"SELECT source, chunk_index, status FROM task_queue "
        f"WHERE kg_id=? AND status IN ('pending','processing') AND ({like}) "
        f"ORDER BY source, chunk_index",
        (KG_STR, *[p + "%" for p in DOC_PREFIXES]),
    ).fetchall()
    return rows


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只列 pending，不抽")
    args = ap.parse_args()

    db_path = task_queue_db_path()
    rows = _pending_rows(db_path)
    print(f"task_queue.db = {db_path}", flush=True)
    by_doc: dict[str, int] = {}
    for s, ci, st in rows:
        by_doc[s] = by_doc.get(s, 0) + 1
    print(f"待補 {len(rows)} chunk，分佈：", flush=True)
    for s, n in sorted(by_doc.items()):
        print(f"   {n:3d}  {s}", flush=True)

    if args.status:
        print("\n--status：未抽取任何東西。", flush=True)
        return
    if not rows:
        print("\n沒有待補 chunk，結束。", flush=True)
        return

    await connect()
    init_providers()
    driver = get_driver()

    t0 = time.monotonic()
    done = fail = 0
    for i, (source, chunk_index, _st) in enumerate(rows, 1):
        try:
            doc_id = str(document_record_service.document_uuid(source))
            await revoke_chunk_facts(driver, KG, doc_id, chunk_index)
            await _process_one(driver, KG_STR, source, chunk_index)
            done += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  !! {source} c{chunk_index} 例外：{e!r}", flush=True)
        if i % 5 == 0 or i == len(rows):
            rate = i / (time.monotonic() - t0)
            print(f"  [{i}/{len(rows)}] done={done} fail={fail}  {rate*60:.1f}/min", flush=True)

    # 驗證：這 5 份是否全歸零
    left = _pending_rows(db_path)
    print(f"\n完成：抽 {done} 成功 / {fail} 失敗，耗時 {(time.monotonic()-t0)/60:.1f} 分", flush=True)
    print(f"5 份剩餘 pending/processing：{len(left)}", flush=True)
    for s, ci, st in left:
        print(f"   還剩 {s} c{ci} ({st})", flush=True)
    print("\nTARGETED-DONE — 可通知 [6de205] 重啟 drain_236903cf.py", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
