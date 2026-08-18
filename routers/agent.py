from __future__ import annotations
import json
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from neo4j import AsyncDriver

from core.database import get_driver
from core.providers.factory import get_embedding_provider, get_llm_provider
from models.document import ChatMessage, ChatRequest
from models.knowledge_graph import SVOTriple
from services.svo_service import bfs_query, resolve_query_relation_type, vector_search_facts

router = APIRouter(prefix="/agent", tags=["agent"])

_SEED_ENTITY_LIMIT = 8

# 2026-07-28 demo 測試發現：退回一般知識（或補充說明）時，LLM 有時會混入
# 中國大陸的法規／數值（例如「中華人民共和國勞動法」、退休金提繳比例誤答
# 成中國大陸的數字），即使有依事實回答的部分也可能在補充段落裡跑偏。加一句
# 明確的地區限定指示，降低這種跑偏機率——這是 prompt 層級的緩解，不是
# 100% 保證，仍需搭配「務必區分事實與補充」的既有指示一起看。
_TAIWAN_CONTEXT_INSTRUCTION = (
    "你是台灣勞動法規顧問，只根據台灣現行法規（例如勞動基準法、勞工保險條例、"
    "性別平等工作法等）回答，絕對不要引用中國大陸、香港、澳門或其他地區的法規、"
    "機關名稱或數值（例如「中華人民共和國勞動法」），也不要混用其他地區的制度或用語。"
)


async def _find_seed_entities(driver: AsyncDriver, kg_id: UUID, question: str) -> list[str]:
    """⚠️ 暫時方案（3.2 §a ConceptNode 路由層／RQ2 尚未設計，2026-07-28
    討論後先接的堪用版本，供 demo 使用）：沒有向量檢索或語意排序，只是把
    該 KG 底下所有既有 Entity 名稱，用最直接的字面比對（是否整段出現在
    問題字串中）挑出候選種子，取名稱最長（最具體）的前 `_SEED_ENTITY_LIMIT`
    個做為 BFS 起點。正式的路由層設計待後續討論後再取代這裡。
    """
    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id}) RETURN DISTINCT e.name AS name",
        kg_id=str(kg_id),
    )
    names = [r["name"] for r in result.records if r["name"]]
    matched = [name for name in names if name in question]
    matched.sort(key=len, reverse=True)
    return matched[:_SEED_ENTITY_LIMIT]


def _filter_triples_by_relation_type(triples: list[SVOTriple], rel_type: str | None) -> list[SVOTriple]:
    """§ 3.2 §c `QFILTER`（2026-08-18 定案）：對 `bfs_query()` 已回傳的三元組
    做**後篩選**，只保留 `rel_type` 型別——不改變 BFS 走訪路徑本身的語意，
    避免漏掉需先經過其他型別的邊才能抵達目標型別的路徑（見設計文件同名
    段落的 recall 風險說明）。`rel_type` 為 `None`（`QNOMATCH`）時原樣回傳，
    不篩選——優雅降級，不因型別解析失敗就讓查詢端拿不到任何結果。
    """
    if rel_type is None:
        return triples
    return [t for t in triples if t.rel_type == rel_type]


def _merge_fact_lines(triples: list[SVOTriple], fact_results: list[dict]) -> list[str]:
    """合併 BFS 圖遍歷三元組（`bfs_query`）與語意檢索到的 Fact（
    `vector_search_facts`，2026-08-18 接線）成單一份事實清單，供 prompt 使用。

    以 `(subject, rel_type, object)` 去重——兩條來源描述同一件事時只保留一筆
    （優先保留先出現的 BFS 版本）。`vector_search_facts()` 回傳的 `subject`／
    `object`／`rel_type` 只有 2026-08-18 之後建立、或已跑過 §b 回填批次任務
    的 `Fact` 節點才有值；缺席（`None`）時視為無法安全去重，一律原樣保留，
    不強行比對——寧可讓少數舊資料出現重複描述，也不要因為誤判「相同」而
    漏掉語意檢索才找得到的事實。
    """
    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []

    for t in triples:
        key = (t.subject, t.rel_type, t.object)
        seen.add(key)
        lines.append(f"- {t.subject}（{t.subject_type}）{t.verb}{t.object}（{t.object_type}）")

    for f in fact_results:
        key = (f.get("subject"), f.get("rel_type"), f.get("object"))
        if all(key) and key in seen:
            continue
        if all(key):
            seen.add(key)
        lines.append(f"- {f['fact_text']}")

    return lines


def _build_prompt(
    question: str,
    triples: list[SVOTriple],
    fact_results: list[dict],
    history: list[ChatMessage] | None,
) -> str:
    fact_lines = _merge_fact_lines(triples, fact_results)
    if fact_lines:
        facts = "\n".join(fact_lines)
        context_block = f"以下是從知識圖譜檢索到、可能與問題相關的事實：\n{facts}\n"
        instruction = "請優先根據上述事實回答問題；若事實不足以完整回答，可以補充你自己的知識，但務必清楚區分哪些是根據圖譜事實、哪些是你自己的補充。"
    else:
        context_block = ""
        # 2026-07-28 demo 測試發現：地區限定的指示解決不了「同一法域內數字記錯」
        # 的問題（例如退休金提繳比例答成 8%，台灣實際為 6%）——這類具體數值若
        # 沒有圖譜依據，LLM 自己的訓練知識可能不準確，與其讓它自信地給出可能
        # 錯誤的數字，不如明確要求它承認不知道、指引使用者查證，避免误导。
        instruction = (
            "知識圖譜中沒有檢索到與問題直接相關的事實，請依你自己的知識回答，並提醒使用者這個答案"
            "未經圖譜資料驗證。若問題涉及具體數字、比例或期限（例如提繳比例、天數上限、罰則金額），"
            "在沒有圖譜依據的情況下不要臆測具體數值，應明確說明「圖譜中無此數據，建議查閱最新法規或"
            "官方公告確認」，避免提供未經驗證、可能有誤的數字。"
        )

    history_block = ""
    if history:
        history_lines = "\n".join(f"{m.role}：{m.content}" for m in history[-6:])
        history_block = f"對話歷史：\n{history_lines}\n\n"

    return f"{_TAIWAN_CONTEXT_INSTRUCTION}\n\n{context_block}\n{history_block}問題：{question}\n\n{instruction}"


@router.post("/chat")
async def chat(payload: ChatRequest):
    """SSE 串流問答。

    ⚠️ **暫時方案（2026-07-28；2026-08-18 補上語意 Fact 檢索與查詢時關係
    連結）**：正式的雙層 RAG 流程（`ConceptNode` 路由 → `BFS` 圖遍歷 → 圖譜
    驅動文件取回 → 自我精煉迴圈 → LLM 串流）待 3.2 §a（RQ2）設計討論完成
    後才會實作。這裡先接一個跳過路由層的堪用版本：BFS 種子仍是字面比對
    （`_find_seed_entities`），但額外接上 3.1.4 §a 已完成的
    `vector_search_facts()`——問題向量化後在已選定的 `kg_id` 內做語意檢索，
    補足字面比對找不到、但語意相關的事實（例如問題用「資遣」、圖譜存的是
    「解僱」）；並接上 3.2 §c `resolve_query_relation_type()`——把整個問題
    文字（非額外抽取出的動詞片語，見下方誠實侷限）解析為對應的 canonical
    關係型別，對 `bfs_query()` 的結果做後篩選。仍然沒有語意排序、沒有
    自我精煉，檢索品質不代表正式版本的水準；`ConceptNode` 跨 KG 路由本身
    （RQ2）仍未實作，此處的語意檢索與關係連結皆侷限在使用者已手動指定的
    單一 `kg_id` 範圍內。

    ⚠️ **誠實侷限（關係連結的輸入）**：3.2 §c 設計文件的 Behavior Tree 以
    「使用者查詢中的動詞措辭」為 `QSIM` 輸入，但沒有指定如何從問題全文中
    抽取出這個動詞措辭——本次接線選擇最小改動：直接把整個問題字串餵給
    `resolve_query_relation_type()`（而非另外呼叫 LLM 抽取核心動詞），代價
    是問題裡的實體/名詞也會混進比對的 embedding、可能稀釋比對精準度；好處
    是不多一次 LLM 呼叫、不增加延遲與成本。是否要改為先抽取動詞片語再比對，
    留待第五章消融實驗評估是否值得多一次 LLM 呼叫的代價，非本次範圍。
    """

    async def _stream():
        if payload.kg_id is None:
            error_json = json.dumps({"message": "請先選擇一個知識圖譜（尚未實作跨 KG 自動路由）"})
            yield f"event: error\ndata: {error_json}\n\n"
            return

        driver = get_driver()
        llm_provider = get_llm_provider()
        triples: list[SVOTriple] = []
        fact_results: list[dict] = []
        if payload.use_svo:
            seeds = await _find_seed_entities(driver, payload.kg_id, payload.question)
            triples = await bfs_query(driver, payload.kg_id, seeds, hops=payload.svo_hops)

            embedding_provider = get_embedding_provider()
            resolved_rel_type = await resolve_query_relation_type(
                payload.question, embedding_provider, llm_provider=llm_provider
            )
            triples = _filter_triples_by_relation_type(triples, resolved_rel_type)

            question_vector = await embedding_provider.encode(payload.question)
            fact_results = await vector_search_facts(
                driver, payload.kg_id, question_vector, top_k=payload.top_k
            )

        prompt = _build_prompt(payload.question, triples, fact_results, payload.history)
        async for token in llm_provider.stream(prompt):
            data = json.dumps({"token": token})
            yield f"data: {data}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
