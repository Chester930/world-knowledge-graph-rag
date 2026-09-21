"""方案 A 收尾腳本：針對 9 筆 failed chunk 執行破迴圈設定重抽。

- 適用 KG: 236903cf-055a-40a8-8923-b9d06601f3b7
- 目標：對 9 筆因 qwen2.5:7b 貪婪解碼迴圈導致截斷失敗的 failed chunk，
  使用「破迴圈設定」（temperature=0.45, repeat_penalty=1.4, repeat_last_n=256，去固定 seed）
  逐筆執行 revoke_chunk_facts() + _process_one()。
- 保證：若初次嘗試失敗，自動以階梯式擴大參數（提高 repeat_penalty/temperature/num_ctx）重試。
- 終態：task_queue.db 達到 completed=3303 / failed=0 / pending=0。
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from uuid import UUID

import httpx

from core.config import settings, task_queue_db_path
from core.database import connect, disconnect, get_driver
from core.providers import factory
from core.providers.factory import init_providers
from core.providers.llm.ollama import OllamaLLMProvider
from services import document_record_service
from services.extraction_worker import _process_one
from services.svo_service import revoke_chunk_facts

KG_STR = "236903cf-055a-40a8-8923-b9d06601f3b7"
KG = UUID(KG_STR)


class LoopBreakingOllamaLLMProvider(OllamaLLMProvider):
    """自訂破迴圈 Ollama LLM Provider，不帶固定 seed，並加入重複懲罰與取樣溫度。"""

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.45,
        repeat_penalty: float = 1.4,
        repeat_last_n: int = 256,
        num_predict: int = 4096,
        num_ctx: int = 8192,
    ):
        super().__init__(base_url=base_url, model=model, num_predict=num_predict)
        self.temperature = temperature
        self.repeat_penalty = repeat_penalty
        self.repeat_last_n = repeat_last_n
        self._num_ctx = num_ctx

    def update_params(
        self,
        temperature: float | None = None,
        repeat_penalty: float | None = None,
        repeat_last_n: int | None = None,
        num_predict: int | None = None,
        num_ctx: int | None = None,
    ) -> None:
        if temperature is not None:
            self.temperature = temperature
        if repeat_penalty is not None:
            self.repeat_penalty = repeat_penalty
        if repeat_last_n is not None:
            self.repeat_last_n = repeat_last_n
        if num_predict is not None:
            self._num_predict = num_predict
        if num_ctx is not None:
            self._num_ctx = num_ctx

    async def generate(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            options = {
                "num_ctx": self._num_ctx,
                "temperature": self.temperature,
                "repeat_penalty": self.repeat_penalty,
                "repeat_last_n": self.repeat_last_n,
                "num_predict": self._num_predict,
            }
            res = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": options,
                },
            )
            res.raise_for_status()
            return res.json().get("response", "")

    async def generate_json(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=self._TIMEOUT) as client:
            options = {
                "num_ctx": self._num_ctx,
                "temperature": self.temperature,
                "repeat_penalty": self.repeat_penalty,
                "repeat_last_n": self.repeat_last_n,
                "num_predict": self._num_predict,
            }
            res = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": options,
                },
            )
            res.raise_for_status()
            return res.json().get("response", "")


def get_chunk_status(db_path: Path | str, kg_id: str, source: str, chunk_index: int) -> str | None:
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT status FROM task_queue WHERE kg_id = ? AND source = ? AND chunk_index = ?",
            (kg_id, source, chunk_index),
        ).fetchone()
        return row[0] if row else None


def get_queue_summary(db_path: Path | str) -> dict[str, int]:
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute("SELECT status, count(*) FROM task_queue GROUP BY status").fetchall()
        return {r[0]: r[1] for r in rows}


# 參數階梯策略：初階 -> 進階 -> 強制
PARAM_TIERS = [
    {"name": "Tier 1 (標準破迴圈)", "temperature": 0.45, "repeat_penalty": 1.40, "repeat_last_n": 256, "num_predict": 4096, "num_ctx": 8192},
    {"name": "Tier 2 (強化破迴圈)", "temperature": 0.50, "repeat_penalty": 1.45, "repeat_last_n": 256, "num_predict": 6144, "num_ctx": 16384},
    {"name": "Tier 3 (高懲罰+大視窗)", "temperature": 0.55, "repeat_penalty": 1.50, "repeat_last_n": 512, "num_predict": 8192, "num_ctx": 16384},
]


async def main() -> None:
    t_start = time.monotonic()
    db_path = task_queue_db_path()
    print("=" * 70)
    print(f"🚀 方案 A 收尾啟動：KG={KG_STR}")
    print(f"📁 task_queue.db: {db_path}")
    print("=" * 70)

    # 1. 查詢待處理 failed 清單
    with sqlite3.connect(str(db_path)) as conn:
        failed_tasks = conn.execute(
            "SELECT source, chunk_index FROM task_queue WHERE kg_id = ? AND status = 'failed' ORDER BY source, chunk_index",
            (KG_STR,),
        ).fetchall()

    if not failed_tasks:
        print("✅ 目前沒有 failed chunk 需要處理！")
        print("佇列現況：", get_queue_summary(db_path))
        return

    print(f"📋 找到 {len(failed_tasks)} 筆待收尾 failed chunk：")
    for i, (source, c_idx) in enumerate(failed_tasks, 1):
        print(f"  {i}. {source} (chunk {c_idx})")
    print("-" * 70)

    # 2. 連線與初始化 Provider
    await connect()
    init_providers()
    driver = get_driver()

    custom_llm = LoopBreakingOllamaLLMProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_llm_model,
        temperature=PARAM_TIERS[0]["temperature"],
        repeat_penalty=PARAM_TIERS[0]["repeat_penalty"],
        repeat_last_n=PARAM_TIERS[0]["repeat_last_n"],
        num_predict=PARAM_TIERS[0]["num_predict"],
        num_ctx=PARAM_TIERS[0]["num_ctx"],
    )
    # 注入自訂破迴圈 provider
    factory._llm = custom_llm

    success_count = 0
    failed_count = 0

    try:
        for idx, (source, chunk_index) in enumerate(failed_tasks, 1):
            print(f"\n[{idx}/{len(failed_tasks)}] 處理 {source} chunk {chunk_index} ...")
            doc_id = str(document_record_service.document_uuid(source))

            chunk_success = False
            for tier in PARAM_TIERS:
                custom_llm.update_params(
                    temperature=tier["temperature"],
                    repeat_penalty=tier["repeat_penalty"],
                    repeat_last_n=tier["repeat_last_n"],
                    num_predict=tier["num_predict"],
                    num_ctx=tier["num_ctx"],
                )
                print(f"  -> 套用 {tier['name']} (temp={tier['temperature']}, rep_pen={tier['repeat_penalty']}, num_ctx={tier['num_ctx']})")

                # Step A: 撤銷先前殘留
                t_sub = time.monotonic()
                revoke_res = await revoke_chunk_facts(driver, KG, doc_id, chunk_index)
                print(f"     已撤銷殘留：facts_del={revoke_res.get('facts_deleted', 0)}, edges_upd={revoke_res.get('edges_updated', 0)}, edges_del={revoke_res.get('edges_deleted', 0)}")

                # Step B: 執行抽取與寫入
                try:
                    await _process_one(driver, KG_STR, source, chunk_index)
                except Exception as e:
                    print(f"     ⚠️ _process_one 拋出未捕獲例外: {e!r}")

                # Step C: 核對狀態
                status = get_chunk_status(db_path, KG_STR, source, chunk_index)
                dt = time.monotonic() - t_sub
                if status == "completed":
                    print(f"     ✅ 成功重抽完成！耗時 {dt:.1f}s")
                    chunk_success = True
                    break
                else:
                    print(f"     ❌ 狀態仍為 {status}（耗時 {dt:.1f}s），準備嘗試下一層階梯...")

            if chunk_success:
                success_count += 1
            else:
                failed_count += 1
                print(f"  ❌❌ {source} chunk {chunk_index} 在所有階梯策略皆未成功！")

    finally:
        await disconnect()

    total_time = time.monotonic() - t_start
    print("\n" + "=" * 70)
    print("🏁 方案 A 收尾完成！")
    print(f"總耗時: {total_time/60:.2f} 分鐘 ({total_time:.1f} 秒)")
    print(f"成功: {success_count} / {len(failed_tasks)} 筆")
    print(f"失敗: {failed_count} / {len(failed_tasks)} 筆")
    print("目前佇列最新分佈:")
    summary = get_queue_summary(db_path)
    for s, cnt in summary.items():
        print(f"  - {s}: {cnt}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
