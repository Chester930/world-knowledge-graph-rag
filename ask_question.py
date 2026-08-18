"""終端機單題問答工具。

給定一個真實問題，透過 `routers/agent.py::chat()` 走與正式 `/agent/chat`
端點完全相同的程式碼路徑（BFS 圖遍歷 + 3.2 §c 關係連結 + 3.1.4 §a 語意
Fact 檢索 + LLM 串流），對真實的 Neo4j / Ollama 執行一次查詢，印出：

1. LLM 串流回答全文
2. 本次實際檢索到的來源（BFS 三元組、語意 Fact），供人工核對答案是否
   真的有圖譜依據——不是只信任 LLM 自己宣稱的來源

不經過 HTTP，直接呼叫 FastAPI 路由函式本身，省去另外啟動 uvicorn 的步驟；
初始化只做查詢路徑真正需要的兩步（`connect()` + `init_providers()`），
略過索引建立與背景 worker 啟動（查詢是唯讀操作，不需要它們）。

用法：
    python ask_question.py --kg-id <uuid> "問題文字"
    python ask_question.py --list-kg          # 列出目前所有 KG 供選擇
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.document import ChatRequest
from repositories.kg_repo import KGRepository
from routers.agent import chat


async def _list_kgs() -> None:
    kgs = await KGRepository(get_driver()).list_all()
    if not kgs:
        print("（目前沒有任何 KG）")
        return
    for kg in kgs:
        print(f"{kg.id}  {kg.name}")


async def _ask(kg_id: UUID, question: str, *, top_k: int, use_svo: bool, hops: int) -> dict:
    payload = ChatRequest(question=question, kg_id=kg_id, top_k=top_k, use_svo=use_svo, svo_hops=hops)
    response = await chat(payload)

    answer_parts: list[str] = []
    sources: dict | None = None
    error: str | None = None

    async for chunk in response.body_iterator:
        if chunk.startswith("event: error"):
            data_line = chunk.split("\n", 1)[1]
            error = json.loads(data_line[len("data: "):])["message"]
        elif chunk.startswith("event: sources"):
            data_line = chunk.split("\n", 1)[1]
            sources = json.loads(data_line[len("data: "):])
        elif chunk.startswith("data: "):
            answer_parts.append(json.loads(chunk[len("data: "):])["token"])

    return {"answer": "".join(answer_parts), "sources": sources, "error": error}


def _print_result(question: str, result: dict) -> None:
    print(f"\n【問題】{question}\n")
    if result["error"]:
        print(f"【錯誤】{result['error']}")
        return

    print(f"【回答】\n{result['answer']}\n")

    sources = result["sources"] or {}
    triples = sources.get("triples", [])
    facts = sources.get("facts", [])
    resolved_rel_type = sources.get("resolved_rel_type")

    print(f"【解析出的關係型別】{resolved_rel_type or '（未解析出／QNOMATCH）'}")
    print(f"【BFS 圖遍歷三元組】共 {len(triples)} 筆")
    for t in triples:
        print(
            f"  - {t['subject']}（{t['subject_type']}）"
            f"-[{t['rel_type']}]{t['verb']}→"
            f"{t['object']}（{t['object_type']}）"
            f"  來源檔案：{t.get('source_svo_chunk_file') or '（無）'}"
        )
    print(f"【語意 Fact 檢索】共 {len(facts)} 筆")
    for f in facts:
        print(f"  - {f['fact_text']}  (score={f.get('score')})")


async def _main() -> None:
    parser = argparse.ArgumentParser(description="終端機單題問答工具（真實查詢，非模擬）")
    parser.add_argument("question", nargs="?", help="問題文字")
    parser.add_argument("--kg-id", help="目標 KG 的 UUID")
    parser.add_argument("--list-kg", action="store_true", help="列出目前所有 KG")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--hops", type=int, default=2, help="BFS 跳數（1-3，預設 2）")
    parser.add_argument("--no-svo", action="store_true", help="關閉 SVO 檢索（純 LLM 回答）")
    args = parser.parse_args()

    await connect()
    init_providers()
    try:
        if args.list_kg:
            await _list_kgs()
            return

        if not args.question or not args.kg_id:
            print("用法：python ask_question.py --kg-id <uuid> \"問題文字\"", file=sys.stderr)
            print("      python ask_question.py --list-kg", file=sys.stderr)
            sys.exit(1)

        result = await _ask(
            UUID(args.kg_id), args.question, top_k=args.top_k, use_svo=not args.no_svo, hops=args.hops
        )
        _print_result(args.question, result)
    finally:
        await disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
