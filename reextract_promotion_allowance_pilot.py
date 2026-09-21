# -*- coding: utf-8 -*-
"""報告57 任務C 第6組聚合題材（就業促進津貼多來源授權鏈+三類津貼金額對照）
Stage 0 targeted重抽。

框架：N0090025_就業促進津貼實施辦法（子法）§1明文「依就業服務法（以下簡稱
本法）第二十三條第二項及第二十四條第四項規定訂定之」——罕見的雙來源授權
（同一部母法的兩條不同條文共同授權同一子法），比先前各組的單一授權條文更
豐富。子法§4列舉三種就業促進津貼（求職交通補助金/臨時工作津貼/職業訓練
生活津貼），§8/§12/§20分別訂有具體金額與期限：
  - §8：求職交通補助金每次500元（特殊情形核實發給不超過1250元）
  - §12：臨時工作津貼按每小時最低工資核給，最長6個月
  - §20：職業訓練生活津貼每月按最低工資60%發給，最長6個月（身心障礙者1年）
三者都以「最低工資」為計算基準但比例/上限不同，是測試系統會不會混淆三種
津貼金額規則的天然聚合題材。

已直接讀`original.md`與對應svo-chunk-*.md逐字核對，內容與所引用條號一致。

targeted chunk（不重抽整份文件——子法28個SVO chunk、母法84個，只碰真正
需要的條文）：
  - N0090025 chunk 1/4/8/12/18/20（§1法源依據、§4津貼種類列舉、§8/§12/§20
    三種津貼金額）
  - N0090001 chunk 22/23（§23/§24，母法雙授權來源）

安全模式（同任務C第2-5組）：不走force_rebuild=True，改用
task_queue_service.enqueue()把終態重置為pending，逐一revoke_chunk_facts()
+_process_one()。

前置：主drain（drain_236903cf.py）必須確認未在跑。

用法：
    cd "D:/Users/666/Desktop/world knowledge graph rag/.claude/worktrees/kg-reextract"
    OLLAMA_EMBEDDING_NUM_GPU=0 nohup python -u reextract_promotion_allowance_pilot.py \
        >> "<job>/tmp/reextract_promotion_allowance_pilot.log" 2>&1 &
完成訊號：PILOT-DONE
"""
from __future__ import annotations

import asyncio
import os
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
from services.task_queue_service import enqueue  # noqa: E402
from services import document_record_service  # noqa: E402

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)

TARGETS: list[tuple[str, list[int]]] = [
    ("N0090025_就業促進津貼實施辦法", [1, 4, 8, 12, 18, 20]),
    ("N0090001_就業服務法", [22, 23]),
]


async def run_one(driver, source: str, chunk_indices: list[int]) -> tuple[int, int]:
    doc_id = str(document_record_service.document_uuid(source))
    t0 = time.monotonic()
    done = fail = 0
    for i, chunk_index in enumerate(chunk_indices, 1):
        try:
            await revoke_chunk_facts(driver, KG, doc_id, chunk_index)
            await _process_one(driver, KG_STR, source, chunk_index)
            done += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  !! {source} c{chunk_index} 例外：{e!r}", flush=True)
        elapsed = time.monotonic() - t0
        rate = (i / elapsed * 60) if elapsed > 0 else 0.0
        print(f"  [{source}][{i}/{len(chunk_indices)}] done={done} fail={fail}  {rate:.1f}/min", flush=True)
    dt = time.monotonic() - t0
    print(f"{source}：{done} 成功 / {fail} 失敗，耗時 {dt/60:.1f} 分\n", flush=True)
    return done, fail


async def main() -> None:
    db_path = task_queue_db_path()
    print(f"task_queue.db = {db_path}", flush=True)

    for source, chunk_indices in TARGETS:
        enqueue(db_path, KG_STR, source, chunk_indices)
        print(f"已把 {source} 的 {len(chunk_indices)} 個 SVO chunk 終態重置為 pending", flush=True)

    await connect()
    init_providers()
    driver = get_driver()

    total_done = total_fail = 0
    t0 = time.monotonic()
    for source, chunk_indices in TARGETS:
        print(f"\n=== 開始：{source}（{len(chunk_indices)} chunk）===", flush=True)
        done, fail = await run_one(driver, source, chunk_indices)
        total_done += done
        total_fail += fail

    dt = time.monotonic() - t0
    print(f"\n全部完成：{total_done} 成功 / {total_fail} 失敗，總耗時 {dt/60:.1f} 分", flush=True)
    print("\nPILOT-DONE", flush=True)
    await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
