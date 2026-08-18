"""針對 docs/報告/12_知識圖譜抽取與問答Demo操作手冊.md 完整題庫（10 題）
執行一次真實、非模擬的端到端查詢，逐題記錄：

- 真實 LLM 串流回答全文
- 本次實際檢索到的來源（BFS 三元組筆數、語意 Fact 筆數、解析出的關係型別）
- 每題耗時

所有結果直接來自對真實 Neo4j（bolt://localhost:17990）與真實 Ollama
（qwen2.5:7b／nomic-embed-text）的呼叫，走與正式 `/agent/chat` 端點完全
相同的程式碼路徑（`routers/agent.py::chat()`）——不模擬、不臆測、不編造。

用法：python run_demo_report.py > demo_report_raw.txt 2>&1
"""
from __future__ import annotations

import asyncio
import json
import time
from uuid import UUID

from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.document import ChatRequest
from routers.agent import chat

KG_SCHEDULING = UUID("deb24e7c-c012-4398-9261-c813cb60b197")  # 排班與工時法規
KG_LEAVE_PAY = UUID("2ae9d28b-3c5e-424f-9ea4-c3cbe59a2934")   # 請假與薪資法規

QUESTIONS = [
    (1, KG_SCHEDULING, "二人制飛航組員每日執勤與飛航時間上限各是多少？"),
    (2, KG_SCHEDULING, "住院醫師的排班需要符合哪些前提條件？"),
    (3, KG_SCHEDULING, "保全業適用勞基法第84-1條，正常工時與延長工時上限各是多少？"),
    (4, KG_SCHEDULING, "台鐵列車乘務人員的輪班間隔休息時間規定是什麼？"),
    (5, KG_SCHEDULING, "生理假一年最多可以請幾天，會不會併入病假計算？"),
    (6, KG_SCHEDULING, "勞動基準法第三十六條第四項指定行業，可以在什麼條件下調整例假？"),
    (7, KG_LEAVE_PAY, "颱風天員工未出勤，雇主是否需要給付當日工資？"),
    (8, KG_LEAVE_PAY, "試用期間的工資是否可以低於基本工資？"),
    (9, KG_LEAVE_PAY, "全勤獎金在產假期間是否可以被扣除？"),
    (10, KG_LEAVE_PAY, "拒絕配戴安全帽會導致什麼法律後果？"),
]


async def _run_one(kg_id: UUID, question: str) -> dict:
    payload = ChatRequest(question=question, kg_id=kg_id)  # 全部使用預設值：hops=2, top_k=5, use_svo=True
    t0 = time.monotonic()
    response = await chat(payload)

    answer_parts: list[str] = []
    sources: dict | None = None
    error: str | None = None
    async for chunk in response.body_iterator:
        if chunk.startswith("event: error"):
            error = json.loads(chunk.split("\n", 1)[1][len("data: "):])["message"]
        elif chunk.startswith("event: sources"):
            sources = json.loads(chunk.split("\n", 1)[1][len("data: "):])
        elif chunk.startswith("data: "):
            answer_parts.append(json.loads(chunk[len("data: "):])["token"])
    elapsed = time.monotonic() - t0

    return {
        "answer": "".join(answer_parts),
        "sources": sources,
        "error": error,
        "elapsed_seconds": round(elapsed, 1),
    }


async def main() -> None:
    await connect()
    init_providers()
    try:
        for idx, kg_id, question in QUESTIONS:
            print(f"\n{'=' * 70}")
            print(f"# 題 {idx}｜KG={kg_id}")
            print(f"【問題】{question}")
            result = await _run_one(kg_id, question)
            print(f"【耗時】{result['elapsed_seconds']} 秒")
            if result["error"]:
                print(f"【錯誤】{result['error']}")
                continue
            print(f"【回答】\n{result['answer']}")
            sources = result["sources"] or {}
            triples = sources.get("triples", [])
            facts = sources.get("facts", [])
            print(f"【解析出的關係型別】{sources.get('resolved_rel_type') or '（未解析出／QNOMATCH）'}")
            print(f"【BFS 三元組筆數】{len(triples)}")
            print(f"【語意 Fact 筆數】{len(facts)}")
            # 只列前 15 筆三元組供人工檢視，避免大量雜訊淹沒報告（完整筆數已如上列出）
            for t in triples[:15]:
                print(
                    f"  - {t['subject']}（{t['subject_type']}）-[{t['rel_type']}]{t['verb']}→"
                    f"{t['object']}（{t['object_type']}）  來源：{t.get('source_svo_chunk_file') or '（無）'}"
                )
            if len(triples) > 15:
                print(f"  ...（另有 {len(triples) - 15} 筆，未列出）")
            for f in facts:
                print(f"  - [Fact] {f['fact_text']}  (score={f.get('score')})")
            print(f"{'=' * 70}\n")
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(main())
