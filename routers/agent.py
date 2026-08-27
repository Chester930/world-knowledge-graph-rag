from __future__ import annotations
import asyncio
import json
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from neo4j import AsyncDriver

from core.database import get_driver
from core.providers.base import EmbeddingProvider
from core.providers.factory import get_embedding_provider, get_llm_provider
from models.document import ChatMessage, ChatRequest
from models.knowledge_graph import SVOTriple
from models.law_document import LawDocument
from repositories.law_document_repo import LawDocumentRepository
from services.svo_service import (
    bfs_query,
    resolve_query_relation_type,
    vector_search_entities,
    vector_search_facts,
)
from services.verification_service import verify_fact_grounding

# Traceability: 02 §2.4.2／§2.4.3 -> 03 §3.2 -> 04 §4.7.
# RQ status: this router currently supports single-KG BFS + Fact retrieval (RQ1
# engineering path); ConceptNode routing (RQ2) and self-refinement (RQ3) are not
# connected here. Tests: tests/routers/test_agent.py.
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


async def _find_seed_entities(
    driver: AsyncDriver,
    kg_id: UUID,
    question: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    question_vector: list[float] | None = None,
) -> list[str]:
    """⚠️ 暫時方案（3.2 §a ConceptNode 路由層／RQ2 尚未設計，2026-07-28
    討論後先接的堪用版本，供 demo 使用）：沒有語意排序，只是把該 KG 底下
    所有既有 Entity 名稱，用最直接的字面比對（是否整段出現在問題字串中）
    挑出候選種子，取名稱最長（最具體）的前 `_SEED_ENTITY_LIMIT` 個做為
    BFS 起點。正式的路由層設計待後續討論後再取代這裡。

    ✅ **語意 fallback（2026-08-25 新增，見 `docs/報告/17`／
    `docs/論文/03_變更紀錄.md` 第五十二次調整）**：真實測試發現字面比對
    常因 SVO 抽取產生的實體名稱過長（即使已補上簡潔性 prompt 規則，
    `qwen2.5:7b` 這類小模型仍無法穩定遵守，見上一則調整誠實侷限）而找不到
    任何種子——7 題真實問題裡 7 題皆是這個情況。字面比對結果為空、且
    `embedding_provider` 有提供時，改用 `vector_search_entities()`
    （`services/svo_service.py`）對 `Entity.name_embedding` 做語意相似度
    比對作為 fallback；`embedding_provider=None`（既有呼叫端未升級）時
    行為與新增前完全一致。**字面比對優先**：能字面匹配代表精確命中，優先
    採用；只有完全找不到時才退而求其次改用語意近似，避免語意 fallback
    的雜訊蓋過精確匹配。
    """
    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id}) RETURN DISTINCT e.name AS name",
        kg_id=str(kg_id),
    )
    names = [r["name"] for r in result.records if r["name"]]
    matched = [name for name in names if name in question]
    matched.sort(key=len, reverse=True)
    matched = matched[:_SEED_ENTITY_LIMIT]

    if not matched and embedding_provider is not None:
        vector = question_vector if question_vector is not None else await embedding_provider.encode(question)
        matched = await vector_search_entities(driver, kg_id, vector, top_k=_SEED_ENTITY_LIMIT)

    return matched


def _relevant_doc_ids_from_facts(fact_results: list[dict]) -> set[UUID]:
    """從語意 Fact 檢索結果（`vector_search_facts()`）取出出現過的
    `source_doc_id` 集合，供 `_filter_triples_by_source_doc_ids()` 當前置
    篩選範圍用。

    ✅ **2026-08-27 新增（64筆規模真實測試發現）**：語意 Fact 檢索本身常常
    已經正確找到問題對應的文件（真實測試兩次都在 Top-5 排第一、score 約
    0.80），但 BFS 圖遍歷不會借用這個訊號、仍照樣走訪整個 KG——64 筆規模
    下因通用實體（雇主／保險人／投保單位）連結數高，BFS 因此撈出大量離題
    結果（同一問題 456 筆，其中多數不相關）。與其另外設計一套「自然語言
    問題→結構化篩選條件」的解析機制（複雜、需要另外決定支援哪些條件
    類型），這裡直接重複利用語意 Fact 檢索**已經算好、已驗證有效**的
    來源文件訊號，成本低、不需要新的設計決策。

    **不是自然語言條件解析器**：只在語意 Fact 檢索確實找到結果時才有
    篩選範圍；`fact_results` 為空（語意檢索本身沒找到東西）時回傳空集合，
    呼叫端應視為「無範圍限制」，不強加篩選——避免語意檢索本身失準時，
    篩選反而放大既有的檢索缺陷。
    """
    doc_ids: set[UUID] = set()
    for f in fact_results:
        raw = f.get("source_doc_id")
        if not raw:
            continue
        try:
            doc_ids.add(UUID(raw) if isinstance(raw, str) else raw)
        except ValueError:
            continue
    return doc_ids


def _filter_triples_by_source_doc_ids(triples: list[SVOTriple], allowed_doc_ids: set[UUID]) -> list[SVOTriple]:
    """依 `allowed_doc_ids` 對 `bfs_query()` 已回傳的三元組做後篩選——排除
    篩選（exclusion filter）而非正向篩選：只排除**明確知道**來源文件、且
    不在允許範圍內的三元組；`source_doc_id` 為 `None`（無法判定來源）的
    一律保留，不因為「不知道」就當作「不符合」。`allowed_doc_ids` 為空
    （語意檢索沒有找到任何範圍訊號）時原樣回傳，不做任何篩選——優雅
    降級，不因為沒有篩選依據就讓查詢端拿不到結果。

    2026-08-27 真實測試：同一問題套用此篩選後 BFS 從 52 筆降到 8 筆，
    回答的三個核心重點全部正確且完全接地（先前未篩選版本混雜了推測
    內容，接地率明顯較低）。
    """
    if not allowed_doc_ids:
        return triples
    return [t for t in triples if t.source_doc_id is None or t.source_doc_id in allowed_doc_ids]


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


async def _fetch_document_map(
    driver: AsyncDriver, kg_id: UUID, triples: list[SVOTriple], fact_results: list[dict]
) -> dict[str, LawDocument]:
    """為本次檢索到的來源裡出現的每個 `source_doc_id` 各查一次 `Document`
    節點（§3.5「文件／法條層級的時序錨定」），供 `_serialize_sources()`
    把 `effective_date`／`effective_note` 等法規層級中繼資料附加到回答
    來源——只做到「這份來源整體現況如何」，不假裝有逐條精確度（見
    `LawDocumentRepository`／`services/svo_service.py::_create_fact_node()`
    docstring：`article_no` 目前只用於 `SUPPORTED_BY` 邊的 MATCH 目標，
    不是 Fact 節點自身的扁平屬性，無法在不改動既有查詢函式的情況下取得
    逐條資訊）。

    `Document` 節點是法規領域專屬設計，並非每個 KG 都有——查無資料的
    `source_doc_id`（一般文件，或尚未跑過本次匯入設計的舊 KG）不會出現在
    回傳的 map 裡，呼叫端需優雅處理缺席，不視為錯誤。
    """
    doc_ids: set[UUID] = set()
    for t in triples:
        if t.source_doc_id is not None:
            doc_ids.add(t.source_doc_id)
    for f in fact_results:
        raw = f.get("source_doc_id")
        if raw:
            doc_ids.add(UUID(raw) if isinstance(raw, str) else raw)

    if not doc_ids:
        return {}

    repo = LawDocumentRepository(driver)
    documents = await asyncio.gather(*(repo.get_document(kg_id, doc_id) for doc_id in doc_ids))
    return {str(doc.source_doc_id): doc for doc in documents if doc is not None}


def _serialize_document(doc: LawDocument | None) -> dict | None:
    if doc is None:
        return None
    return {
        "title": doc.title,
        "update_date": doc.update_date,
        "effective_date": doc.effective_date,
        "effective_note": doc.effective_note,
    }


def _serialize_sources(
    triples: list[SVOTriple],
    fact_results: list[dict],
    resolved_rel_type: str | None,
    document_map: dict[str, LawDocument] | None = None,
) -> dict:
    """把本次檢索到的原始來源（BFS 三元組 + 語意 Fact）整理成可序列化的
    結構，隨 SSE `sources` 事件一併送出——讓呼叫端（CLI 工具、之後的前端）
    能顯示「答案根據哪些圖譜資料」，供人工審核，而不必只信任 LLM 自己在
    回答文字裡宣稱的來源。

    `document_map`（2026-08-25 新增，見 `_fetch_document_map()`）：選填。
    提供時依 `source_doc_id` 附加 `document`（法規層級 `effective_date`／
    現況），讓來源標註能顯示「此規定出自哪份法規、現行是否有效」，不需要
    人工再去查一次原始法規；`None`（既有呼叫端未升級）或查無對應
    `Document` 節點時該筆來源的 `document` 為 `None`，行為與新增前一致。
    """
    document_map = document_map or {}
    return {
        "resolved_rel_type": resolved_rel_type,
        "triples": [
            {
                "subject": t.subject,
                "subject_type": t.subject_type,
                "verb": t.verb,
                "object": t.object,
                "object_type": t.object_type,
                "rel_type": t.rel_type,
                "source": t.source,
                "source_svo_chunk_file": t.source_svo_chunk_file,
                "document": _serialize_document(
                    document_map.get(str(t.source_doc_id)) if t.source_doc_id is not None else None
                ),
            }
            for t in triples
        ],
        "facts": [
            {
                "fact_text": f.get("fact_text"),
                "subject": f.get("subject"),
                "object": f.get("object"),
                "rel_type": f.get("rel_type"),
                "score": f.get("score"),
                "document": _serialize_document(document_map.get(f.get("source_doc_id"))),
            }
            for f in fact_results
        ],
    }


def _merge_fact_lines(triples: list[SVOTriple], fact_results: list[dict]) -> list[str]:
    """合併 BFS 圖遍歷三元組（`bfs_query`）與語意檢索到的 Fact（
    `vector_search_facts`，2026-08-18 接線）成單一份事實清單，供 prompt 使用。

    以 `(subject, rel_type, object)` 去重——兩條來源描述同一件事時只保留一筆
    （優先保留先出現的 BFS 版本）。`vector_search_facts()` 回傳的 `subject`／
    `object`／`rel_type` 只有 2026-08-18 之後建立、或已跑過 §b 回填批次任務
    的 `Fact` 節點才有值；缺席（`None`）時視為無法安全去重，一律原樣保留，
    不強行比對——寧可讓少數舊資料出現重複描述，也不要因為誤判「相同」而
    漏掉語意檢索才找得到的事實。

    ✅ **殘缺三元組過濾（2026-08-27 新增，見報告 17 後續 64 筆規模抽查發現）**：
    SVO 抽取偶爾會產生 subject／object 任一為空字串的殘缺三元組（多為列舉式
    條文抽取失敗的殘留，見 `_svo_prompt()` 規則 8／9），這類三元組送進 prompt
    對回答毫無幫助，只會佔用 context 並稀釋真正相關的事實（真實測試曾見
    BFS 456 筆裡混入大量 `→（）` 的殘缺結果）。這裡只過濾**明確的空字串**，
    不過濾 `None`（`fact_results` 的 `subject`／`object` 為 `None` 代表舊資料
    尚未跑過 §b 回填、不代表 `fact_text` 本身有問題，仍應保留，理由同上）。
    """
    def _is_blank(value: str | None) -> bool:
        return value is not None and value.strip() == ""

    seen: set[tuple[str, str, str]] = set()
    lines: list[str] = []

    for t in triples:
        if not t.subject or not t.object:
            continue
        key = (t.subject, t.rel_type, t.object)
        seen.add(key)
        lines.append(f"- {t.subject}（{t.subject_type}）{t.verb}{t.object}（{t.object_type}）")

    for f in fact_results:
        if _is_blank(f.get("subject")) or _is_blank(f.get("object")):
            continue
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

    ✅ **事實接地性核對（2026-08-24 新增，v1：偵測用，不自動重試）**：串流
    結束後，逐句核對完整回答是否被 `_merge_fact_lines()`（BFS 三元組 ＋
    語意 Fact 合併後的 context，與 `_build_prompt()` 實際餵給生成模型的
    內容一致）支持（`services/verification_service.py::verify_fact_grounding()`），
    額外送出 `event: grounding`。⚠️ 核對範圍務必與生成時的 context 一致——
    真實測試曾發現只核對 `fact_results`（略過 BFS 三元組）會把「由 BFS
    三元組提供、正確的陳述」誤判為未接地（假陽性），已修正為統一使用
    `_merge_fact_lines()` 的輸出。對應 `docs/報告/16_事實接地性核對機制設計報告.md`
    ／`docs/論文/03_系統設計與方法論.md` § 3.6：既有的圖遍歷信心訊號（種子
    命中數／BFS 路徑長度）拓不到「證據已檢索到、生成階段仍捏造內容」這種
    失效模式，真實測試已重現過此失效案例。**誠實侷限（刻意縮小的 v1 範圍）**：
    這一版**只偵測、不自動重新生成**——串流已經即時輸出給使用者看過，此時
    在背後另外生成一個答案去覆蓋會是更混亂的體驗；核對結果只是額外附加的
    診斷資訊。是否要做完整版（核對通過前不開始串流、抓到未接地就自動重新
    生成），留待下一步獨立評估。
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
        resolved_rel_type: str | None = None
        if payload.use_svo:
            # 2026-08-25：embedding_provider／question_vector 提前算好，供
            # _find_seed_entities() 的語意 fallback 與下方 vector_search_facts()
            # 共用同一個問題向量，不多花一次 embedding 呼叫（見該函式 docstring）。
            embedding_provider = get_embedding_provider()
            question_vector = await embedding_provider.encode(payload.question)

            seeds = await _find_seed_entities(
                driver, payload.kg_id, payload.question,
                embedding_provider=embedding_provider, question_vector=question_vector,
            )
            triples = await bfs_query(driver, payload.kg_id, seeds, hops=payload.svo_hops)

            resolved_rel_type = await resolve_query_relation_type(
                payload.question, embedding_provider, llm_provider=llm_provider
            )
            triples = _filter_triples_by_relation_type(triples, resolved_rel_type)

            fact_results = await vector_search_facts(
                driver, payload.kg_id, question_vector, top_k=payload.top_k
            )
            # 2026-08-27：語意 Fact 檢索找到的來源文件，反過來當 BFS 三元組的
            # 前置篩選範圍（見 _relevant_doc_ids_from_facts() docstring）。
            relevant_doc_ids = _relevant_doc_ids_from_facts(fact_results)
            triples = _filter_triples_by_source_doc_ids(triples, relevant_doc_ids)

        prompt = _build_prompt(payload.question, triples, fact_results, payload.history)
        answer_parts: list[str] = []
        async for token in llm_provider.stream(prompt):
            answer_parts.append(token)
            data = json.dumps({"token": token})
            yield f"data: {data}\n\n"

        document_map = await _fetch_document_map(driver, payload.kg_id, triples, fact_results)
        sources_json = json.dumps(
            _serialize_sources(triples, fact_results, resolved_rel_type, document_map), ensure_ascii=False
        )
        yield f"event: sources\ndata: {sources_json}\n\n"

        # 核對範圍須與 `_build_prompt()` 實際餵給生成模型的 context 一致
        # （`_merge_fact_lines()` 合併後的 BFS 三元組＋語意 Fact），只用
        # `fact_results` 會漏掉 BFS 三元組來源的正確陳述，造成假陽性
        # （2026-08-24 真實測試發現：「每週總時數四十小時」由 BFS 三元組
        # 提供，只核對 `fact_results` 會誤判為未接地）。
        grounding = await verify_fact_grounding(
            "".join(answer_parts),
            [line.lstrip("- ") for line in _merge_fact_lines(triples, fact_results)],
            llm_provider,
        )
        grounding_json = json.dumps(
            [{"statement": c.statement, "supported": c.supported, "reason": c.reason} for c in grounding],
            ensure_ascii=False,
        )
        yield f"event: grounding\ndata: {grounding_json}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
