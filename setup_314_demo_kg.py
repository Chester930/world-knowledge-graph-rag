"""建立一個全新、獨立的示範 KG，把幾份今天已人工核對過內容與標題相符
的短文件（單頁函釋）重新抽取進去——這次會走已修復的 § 3.1.4 §c 文件UUID
機制，讓 HAS_ENTITY 邊與 Fact 節點第一次真正被建立。

刻意不動既有的兩個 demo KG（排班與工時法規／請假與薪資法規），避免：
1. 干擾今天稍早驗證過、要在會議上示範的既有查詢結果。
2. 與會議期間的 demo 問答搶同一個本地 Ollama 資源。

用法：python setup_314_demo_kg.py
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from uuid import UUID

from core.config import settings, task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.knowledge_graph import KnowledgeGraphCreate
from repositories.kg_repo import KGRepository
from services import task_queue_service
from services.extraction_worker import _process_one
from services.svo_service import (
    create_chunk_vector_index,
    create_entity_index,
    create_related_to_vector_index,
    trigger_extraction,
)

KG_SCHEDULING = UUID("deb24e7c-c012-4398-9261-c813cb60b197")
KG_LEAVE_PAY = UUID("2ae9d28b-3c5e-424f-9ea4-c3cbe59a2934")

# (來源 KG, 文件資料夾名稱)——皆已於今天人工核對 original.md 內容與標題相符
SOURCE_DOCS = [
    (KG_SCHEDULING, "內政部_台內勞字第356410號函"),          # 出差交通時間
    (KG_SCHEDULING, "內政部_台內勞字第351220號函"),          # 春節補班加班費
    (KG_SCHEDULING, "內政部_台內勞字第351229號函"),          # 工作規則公開揭示
    (KG_SCHEDULING, "勞動部_勞動條3字第1060130250號函"),     # 生理假不併入病假
    (KG_LEAVE_PAY, "內政部_台內勞字第342080號"),             # 工資折抵限制
    (KG_LEAVE_PAY, "勞動部_勞動條2字第1070131100號函"),      # 伙食代金併入平均工資
]


async def main() -> None:
    await connect()
    embedding = init_providers()
    driver = get_driver()
    try:
        await create_entity_index(driver)
        await create_chunk_vector_index(driver, embedding.dim)
        await create_related_to_vector_index(driver, embedding.dim)
        # Fact 向量索引 2026-08-19 起改為每個 KG 各自一個、由
        # vector_search_facts() 在查詢當下惰性建立，此處不需再預先呼叫。

        kg = await KGRepository(driver).create(
            KnowledgeGraphCreate(
                name="示範強化語料（3.1.4驗證用）",
                description="2026-08-19 為驗證 §3.1.4 文件UUID修復後 HAS_ENTITY/Fact 是否真正生效而建立，"
                            "內容為既有兩個demo KG裡已人工核對過標題與內容相符的短文件。",
            )
        )
        print(f"新 KG 已建立：id={kg.id} folder={kg.folder_path}")

        new_folder = Path(kg.folder_path)
        for source_kg_id, doc_name in SOURCE_DOCS:
            src = Path(settings.workspace_dir) / str(source_kg_id) / doc_name
            dst = new_folder / doc_name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"已複製文件：{doc_name}")

            await trigger_extraction(driver, dst, kg.id)
            print(f"已觸發抽取（CHUNKREADY+ENQUEUE）：{doc_name}")

        # 沒有常駐背景 Worker 在跑（今天的 CLI 流程都是直接呼叫 chat()，
        # 未啟動 main.py 的 lifespan），這裡直接把佇列跑完，
        # 等同於背景 Worker 會做的事，只是同步、一次性執行。
        db_path = task_queue_db_path()
        processed = 0
        while True:
            pending = task_queue_service.next_pending(db_path, kg_id=str(kg.id))
            if pending is None:
                break
            pending_kg_id, source, chunk_index = pending
            await _process_one(driver, pending_kg_id, source, chunk_index)
            processed += 1
            print(f"已處理 {processed} 筆 chunk：{source} #{chunk_index}")

        print(f"\n全部完成，共處理 {processed} 筆 SVO chunk。新 KG id：{kg.id}")

        result = await driver.execute_query(
            "MATCH (f:Fact {kg_id: $kg_id}) RETURN count(f) AS c", kg_id=str(kg.id),
        )
        fact_count = result.records[0]["c"]
        result2 = await driver.execute_query(
            "MATCH ()-[r:HAS_ENTITY {kg_id: $kg_id}]->() RETURN count(r) AS c", kg_id=str(kg.id),
        )
        has_entity_count = result2.records[0]["c"]
        print(f"Fact 節點數：{fact_count}　HAS_ENTITY 邊數：{has_entity_count}")
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
