"""3.1.3 §a `EXPAND` 治理機制的整合函式——治理 Worker 判斷邏輯本體。

對應 `docs/報告/11_抽取管線完整實作任務書.md` P2-1、
`docs/論文/03_系統設計與方法論.md` § 3.1.3 §a 完整 Behavior Tree
（`POOLSIZE`→`CLUSTER`→`HASCLUSTER`→`LLMJUDGE`→`REGCHECK`→`REUSE`/`NEWTYPE`
→`GATE`→`HUMANCHECK`/`AUTOAPPROVE`→`COMMIT`→`BACKFILL`）。個別積木
（`expand_governance_service.py` 的候選池／登記表／提案 CRUD、
`cluster_service.py` 的 HDBSCAN 分群、`svo_service.py` 的 backfill 函式）
皆已存在，本模組只負責把它們串成完整判斷流程。

背景 Worker 迴圈本體（`run_governance_worker()`，P2-3）定期呼叫本模組的
`run_governance_cycle()`，隨 `main.py::lifespan` 與抽取 Worker（P0-3）一起
啟動。
"""
from __future__ import annotations

import asyncio
import logging
import re
from uuid import UUID

from neo4j import AsyncDriver

from core.config import task_queue_db_path
from core.constants import (
    EXPAND_GATE_THRESHOLD,
    EXPAND_GATE_WINDOW,
    EXPAND_POOL_MIN_SIZE,
    EXPAND_REGCHECK_THRESHOLD,
    EXPAND_WORKER_POLL_INTERVAL,
)
from core.providers.base import EmbeddingProvider, LLMProvider
from core.providers.factory import get_embedding_provider, get_llm_provider
from repositories.kg_repo import KGRepository
from services import expand_governance_service
from services.cluster_service import cluster_vectors

logger = logging.getLogger(__name__)
from services.svo_service import backfill_related_to_edges


def _llmjudge_prompt(verbs: list[str]) -> str:
    verb_list = "、".join(verbs)
    return (
        "以下是知識圖譜中多次出現、目前都被歸類為「其他關聯（RELATED_TO）」的動詞或"
        "關係描述，經向量分群後被判斷為彼此語意相近的一群：\n"
        f"{verb_list}\n\n"
        "請判斷：這群動詞是否共同代表一種內部一致、可類推到其他情境的新關係類型"
        "（就像既有的 CAUSES、PART_OF 這類正式關係型別），而不是各自獨立、"
        "恰好被向量誤判為相似的雜訊？\n\n"
        "若是，請按以下格式回答，並提出一個新的關係型別名稱與簡短說明：\n"
        "判斷：是\n"
        "名稱：<英文全大寫、以底線分隔的型別名稱，例如 INVESTS_IN>\n"
        "說明：<一句話說明 A 與 B 的關係，例如「A 投入資金支持 B 的營運或成長」>\n\n"
        "若否（不構成有意義的新類別），只需回答：\n"
        "判斷：否"
    )


def _parse_llmjudge_response(raw: str) -> tuple[bool, str, str]:
    """解析 `LLMJUDGE` 回應。判定為「否」或格式不完整時一律視為「否」——型別
    命名錯誤的代價（污染跨 KG 登記表、誤導未來抽取）遠高於漏判一個真正的
    新類別（漏判只是候選繼續留在池裡，下次治理週期還有機會再判斷一次）。
    """
    is_new_type = False
    type_name = ""
    description = ""
    for line in raw.strip().splitlines():
        line = line.strip()
        if line.startswith("判斷："):
            is_new_type = line.split("：", 1)[-1].strip().startswith("是")
        elif line.startswith("名稱："):
            type_name = line.split("：", 1)[-1].strip()
        elif line.startswith(("說明：", "说明：")):
            description = line.split("：", 1)[-1].strip()

    type_name = re.sub(r"[^A-Za-z0-9_]", "_", type_name).upper().strip("_")
    if not is_new_type or not type_name or not description:
        return False, "", ""
    return True, type_name, description


async def commit_and_backfill(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider,
    *,
    type_name: str,
    description: str,
    member_verbs: list[str],
    reused_from_registry: bool,
) -> int:
    """`COMMIT`＋`BACKFILL`：核准新型別後把候選標記為 `committed`、（若非沿用
    既有登記）寫入跨 KG 登記表，並在同一輪流程內接著觸發回溯重分類（見
    3.1.3 §a-1）。由 `run_governance_cycle()` 的 `AUTOAPPROVE` 分支呼叫，也
    供 `routers/expand.py` 的 `HUMANCHECK` 端點在人工核准後呼叫（P2-2）——
    兩條路徑最終都走到同一個 `COMMIT`／`BACKFILL` 邏輯，不重複實作，公開
    （無底線前綴）供 router 層直接匯入。回傳實際升級的邊數。
    """
    db_path = task_queue_db_path()
    kg_id_str = str(kg_id)

    if not reused_from_registry:
        description_embedding = embedding_provider.encode(description)
        expand_governance_service.register_type(
            db_path, type_name, description, description_embedding, kg_id_str,
        )

    expand_governance_service.mark_committed(db_path, kg_id_str, member_verbs)

    return await backfill_related_to_edges(
        driver, kg_id, type_name, description, embedding_provider, llm_provider=llm_provider,
    )


async def run_governance_cycle(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider,
) -> None:
    """對單一 KG 跑一輪完整的 `EXPAND` 治理判斷（`POOLSIZE`→...→`COMMIT`→
    `BACKFILL`）。由治理 Worker（P2-3，尚未接上背景迴圈）定期對每個 KG 呼叫
    一次。

    ⚠️ 已知、刻意留白的缺口（見 `03_系統設計與方法論.md` § 3.1.3 §a 決策
    脈絡第 6 點「候選群集在 `LLMJUDGE`→`REGCHECK`→`GATE`→`HUMANCHECK` 這串
    流程中的狀態尚未有對應資料表」）：進入 `HUMANCHECK`（未畢業）分支時，
    本函式**不會**把該群集的候選動詞從 `expand_pool` 移出 `pending` 狀態——
    代表在人工審核完成前，若治理 Worker 又跑了下一輪週期，同一群候選可能
    被重複分群、重複建立 `awaiting_review` 提案。此為設計文件明確標註「留待
    `HUMANCHECK` 介面設計時一併處理」的已知限制，非本次疏漏；`AUTOAPPROVE`
    （已畢業）分支沒有這個問題，因為候選當下就被 `mark_committed()` 移出
    候選池。
    """
    db_path = task_queue_db_path()
    kg_id_str = str(kg_id)

    # POOLSIZE
    if expand_governance_service.pool_size(db_path, kg_id_str) < EXPAND_POOL_MIN_SIZE:
        return

    # CLUSTER（沿用 3.1.1 §a 同一套 HDBSCAN 機制）
    candidates = expand_governance_service.pending_candidates(db_path, kg_id_str)
    vectors = [c["verb_embedding"] for c in candidates]
    labels = cluster_vectors(vectors)

    # HASCLUSTER
    cluster_ids = sorted({label for label in labels if label != -1})
    if not cluster_ids:
        return

    for cluster_id in cluster_ids:
        member_verbs = [candidates[i]["verb"] for i, label in enumerate(labels) if label == cluster_id]

        # LLMJUDGE
        is_new_type, type_name, description = _parse_llmjudge_response(
            await llm_provider.generate(_llmjudge_prompt(member_verbs))
        )
        if not is_new_type:
            expand_governance_service.mark_discarded(db_path, kg_id_str, member_verbs)
            continue

        # REGCHECK（比對描述句 embedding，不比對型別名稱字串本身，同一原則
        # 見 SIM 節點；REUSE 情境下直接沿用既有描述句作 BACKFILL 查詢向量，
        # 因為 REGCHECK 命中本身就代表兩份描述已足夠語意相近，不另外查回
        # 登記表原始描述文字）
        description_embedding = embedding_provider.encode(description)
        existing = expand_governance_service.find_similar_registered_type(
            db_path, description_embedding, EXPAND_REGCHECK_THRESHOLD,
        )
        reused = existing is not None
        final_type_name = existing[0] if existing is not None else type_name

        # GATE
        agreement = expand_governance_service.recent_agreement_rate(db_path, kg_id_str, EXPAND_GATE_WINDOW)
        graduated = agreement is not None and agreement >= EXPAND_GATE_THRESHOLD

        expand_governance_service.create_proposal(
            db_path, kg_id_str, member_verbs, final_type_name, description,
            reused_from_registry=reused, auto_approved=graduated,
        )

        if graduated:
            await commit_and_backfill(
                driver, kg_id, embedding_provider, llm_provider,
                type_name=final_type_name, description=description,
                member_verbs=member_verbs, reused_from_registry=reused,
            )


async def run_governance_worker(
    driver: AsyncDriver,
    poll_interval: float = EXPAND_WORKER_POLL_INTERVAL,
) -> None:
    """常駐背景任務（P2-3）：對應 § 3.1.2／3.1.3 §a『WORKER 執行模型定案』
    的治理 Worker 分支——**寬鬆迴圈**，每隔 `poll_interval` 秒巡視一次所有
    KG，對每個 KG 呼叫 `run_governance_cycle()`。由 `main.py::lifespan` 以
    `asyncio.create_task()` 啟動，`task.cancel()` 優雅關閉，與抽取 Worker
    （P0-3，`services/extraction_worker.py::run_extraction_worker()`）是同一
    宿主行程內兩個獨立的背景任務，節奏不同：抽取 Worker 緊湊迴圈、治理
    Worker 寬鬆迴圈（見決策脈絡第 5 點）。

    單一 KG 的治理週期失敗（LLM 逾時、Neo4j 連線問題等）只記錄例外並繼續
    處理下一個 KG，不會讓整個背景迴圈跟著中斷——比照抽取 Worker 對單一
    chunk 失敗的隔離處理精神。
    """
    while True:
        try:
            embedding_provider = get_embedding_provider()
            llm_provider = get_llm_provider()
        except RuntimeError:
            await asyncio.sleep(poll_interval)
            continue

        kgs = await KGRepository(driver).list_all()
        for kg in kgs:
            try:
                await run_governance_cycle(driver, kg.id, embedding_provider, llm_provider)
            except Exception:
                logger.exception("[GovernanceWorker] KG %s 治理週期失敗", kg.id)

        await asyncio.sleep(poll_interval)
