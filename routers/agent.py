from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from neo4j import AsyncDriver

from core.config import settings
from core.database import get_driver
from core.kg_config import ConfigLoader, KGConfig
from core.providers.base import EmbeddingProvider, LLMProvider
from core.providers.factory import get_embedding_provider, get_llm_provider
from models.document import ChatMessage, ChatRequest
from models.knowledge_graph import SVOTriple
from models.law_document import LawDocument
from repositories.law_document_repo import LawDocumentRepository
from services.classify_service import cosine_similarity
from services.svo_service import (
    _kg_source_charset,
    _to_traditional_selective,
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

# 2026-09-08（報告33 §3.9 第 2 步）：以下 `_SEED_ENTITY_LIMIT`／`_SEED_MAX_DEGREE`／
# `_BFS_PER_SEED_LIMIT`／`_DOC_SCOPE_TOP_N_FACTS` 現為 `KGConfig().bfs.*` 的預設值錨點
# （`tests/core/test_kg_config.py` golden test 逐欄位比對）。查詢端已改讀 `chat()` 傳入的
# `cfg`；直接改這裡的值仍生效（`KGConfig` 預設會跟著動、golden test 會提醒），但正式
# 調校應改 domain pack / per-KG profile。
_SEED_ENTITY_LIMIT = 8

# 報告27 L1：種子度數上限。度數（相連邊數）超過這個值的實體屬「樞紐」
# （勞動法語料裡的雇主／被保險人／投保單位），當作 BFS 起點會把走訪灌爆
# （報告26 §4 #4：Q5/6/7 各 330–440 秒）。只要還有非樞紐種子可用就剔除
# 樞紐；全部候選都是樞紐時才保留（否則沒有起點）。對應 CatRAG（Lau et al.,
# 2026，arXiv:2602.01965）「semantic drift into hub nodes」的簡化對策。
# ✅ **報告27 §6.2 敏感度測試校準（2026-09-05）**：初值 200，真實測試
# `deg=100` 對 Q6（N0050011，樞紐種子「被保險人」「投保單位」被剔除）
# BFS三元組從 51→30（下游過濾後預期 <30 目標），正確性維持（「二年內」仍
# 命中）。⚠️ 只針對 Q6 單題驗證，非窮舉 3×3×3 網格，待全量重抽完成後隨
# 報告27 §6.2 完整題組重驗證。
_SEED_MAX_DEGREE = 100

# 報告27 L1：`bfs_query()` 每個 seed 的展開路徑數上限（CALL 子查詢內 LIMIT）。
# 樞紐種子已由 `_SEED_MAX_DEGREE` 剔除，這是第二道扇出防線。
# ✅ **報告27 §6.2 敏感度測試校準（2026-09-05）**：初值 60，`limit=30` 與
# `deg=100` 併同驗證（見上），維持正確性。同一份「單題驗證，待全量重驗證」
# 的誠實侷限適用於此常數。
_BFS_PER_SEED_LIMIT = 30

# 2026-07-28 demo 測試發現：退回一般知識（或補充說明）時，LLM 有時會混入
# 中國大陸的法規／數值（例如「中華人民共和國勞動法」、退休金提繳比例誤答
# 成中國大陸的數字），即使有依事實回答的部分也可能在補充段落裡跑偏。加一句
# 明確的地區限定指示，降低這種跑偏機率——這是 prompt 層級的緩解，不是
# 100% 保證，仍需搭配「務必區分事實與補充」的既有指示一起看。
_TAIWAN_CONTEXT_INSTRUCTION = (
    "你是台灣勞動法規顧問，只根據台灣現行法規（例如勞動基準法、勞工保險條例、"
    "性別平等工作法等）回答，絕對不要引用中國大陸、香港、澳門或其他地區的法規、"
    "機關名稱或數值（例如「中華人民共和國勞動法」），也不要混用其他地區的制度或用語。"
    "請一律使用繁體中文回答，不要使用簡體字。"
)


async def _find_seed_entities(
    driver: AsyncDriver,
    kg_id: UUID,
    question: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    question_vector: list[float] | None = None,
    cfg: KGConfig | None = None,
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
    _cfg = cfg or KGConfig()
    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id}) RETURN DISTINCT e.name AS name",
        kg_id=str(kg_id),
    )
    names = [r["name"] for r in result.records if r["name"]]
    matched = [name for name in names if name in question]
    matched.sort(key=len, reverse=True)
    matched = matched[:_cfg.bfs.seed_entity_limit]

    if not matched and embedding_provider is not None:
        vector = question_vector if question_vector is not None else await embedding_provider.encode(question)
        matched = await vector_search_entities(driver, kg_id, vector, top_k=_cfg.bfs.seed_entity_limit)

    return await _drop_hub_seeds(driver, kg_id, matched, cfg=_cfg)


async def _drop_hub_seeds(
    driver: AsyncDriver, kg_id: UUID, names: list[str], *, cfg: KGConfig | None = None
) -> list[str]:
    """報告27 L1：剔除度數 > `cfg.bfs.seed_max_degree` 的樞紐種子——只要還有
    非樞紐種子可用就剔除，全部都是樞紐時原樣保留（BFS 需要至少一個起點）。
    候選 < 2 個時直接回傳、不多打一次查詢。

    報告33 §3.9（2026-09-08 第 2 步）：`cfg=None` → `KGConfig()` 預設 ==
    `_SEED_MAX_DEGREE`，行為零變化。"""
    if len(names) < 2:
        return names
    _cfg = cfg or KGConfig()
    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id})-[r]-() WHERE e.name IN $names "
        "RETURN e.name AS name, count(r) AS degree",
        kg_id=str(kg_id),
        names=names,
    )
    degree = {r["name"]: (r.get("degree") or 0) for r in result.records}
    non_hub = [n for n in names if degree.get(n, 0) <= _cfg.bfs.seed_max_degree]
    return non_hub if non_hub else names


# 從語意 Fact 推導文件範圍時，只取分數最高的前幾筆——`vector_search_facts()`
# 回傳已依 score 遞減排序。報告25 §4 發現1：`ChatRequest.top_k` 提高到 20 後，
# 若拿全部 20 筆的 `source_doc_id` 當範圍，會被相似度 0.80 左右的跨文件事實
# 稀釋（Q8 真實案例：20 筆裡 13 筆來自其他訓練/補助法規），範圍過濾形同失效。
# 取前 5 筆＝回到 2026-08-27 定案當時（`top_k` 預設本就是 5）的等效行為。
_DOC_SCOPE_TOP_N_FACTS = 5


def _relevant_doc_ids_from_facts(fact_results: list[dict], *, top_n: int | None = None) -> set[UUID]:
    """從語意 Fact 檢索結果（`vector_search_facts()`）取出出現過的
    `source_doc_id` 集合，供 `_filter_triples_by_source_doc_ids()`／
    `_filter_facts_by_source_doc_ids()` 當前置篩選範圍用。

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

    ✅ **`top_n`（2026-09-02，報告25 §4 發現1）**：只取分數最高的前 `top_n`
    筆推導範圍（`fact_results` 已依 score 遞減）。`top_n=None` 時沿用舊行為
    （全部）。理由見 `_DOC_SCOPE_TOP_N_FACTS` 常數註解。
    """
    considered = fact_results[:top_n] if top_n is not None else fact_results
    doc_ids: set[UUID] = set()
    for f in considered:
        raw = f.get("source_doc_id")
        if not raw:
            continue
        try:
            doc_ids.add(UUID(raw) if isinstance(raw, str) else raw)
        except ValueError:
            continue
    return doc_ids


def _scope_by_source_doc_ids(items: list, allowed_doc_ids: set[UUID], get_doc_id) -> list:
    """依 `allowed_doc_ids` 做**排除篩選**的共用邏輯（`_filter_triples_by_
    source_doc_ids()`／`_filter_facts_by_source_doc_ids()` 共用）：

    - `allowed_doc_ids` 為空（語意檢索沒有找到任何範圍訊號）→ 原樣回傳，
      不強加篩選（優雅降級）。
    - 三值邏輯：`get_doc_id(item)` 回 `None`（無法判定來源）的一律保留，
      只排除**明確知道**來源、且不在允許範圍內的項目。
    - ⚠️ **歸零守衛（2026-09-02，報告25 §4 發現1）**：若套用篩選會把「原本
      非空的清單」清成空集合，代表語意檢索判定的來源範圍與這批項目完全
      不一致——不信任較小／較新的語意 top-K 訊號去零化，放棄篩選、原樣
      回傳。只擋「完全歸零」，部分重疊命中（2026-08-27 情境）仍照常篩選。
    """
    if not allowed_doc_ids:
        return items
    filtered = [it for it in items if get_doc_id(it) is None or get_doc_id(it) in allowed_doc_ids]
    if items and not filtered:
        return items
    return filtered


def _filter_triples_by_source_doc_ids(triples: list[SVOTriple], allowed_doc_ids: set[UUID]) -> list[SVOTriple]:
    """依 `allowed_doc_ids` 對 `bfs_query()` 已回傳的三元組做排除篩選（見
    `_scope_by_source_doc_ids()` 的共用邏輯與歸零守衛說明）。

    2026-08-27 真實測試：同一問題套用此篩選後 BFS 從 52 筆降到 8 筆，
    回答的三個核心重點全部正確且完全接地（先前未篩選版本混雜了推測
    內容，接地率明顯較低）。
    """
    return _scope_by_source_doc_ids(triples, allowed_doc_ids, lambda t: t.source_doc_id)


def _filter_facts_by_source_doc_ids(fact_results: list[dict], allowed_doc_ids: set[UUID]) -> list[dict]:
    """依 `allowed_doc_ids` 對 `vector_search_facts()` 回傳的語意 Fact 做排除
    篩選（見 `_scope_by_source_doc_ids()` 的共用邏輯與歸零守衛說明）。

    ✅ **2026-09-02（報告25 §4 發現1）**：先前只有 BFS 三元組會套文件範圍
    過濾、語意 Fact 不套。`ChatRequest.top_k` 提高到 20 後，語意 Fact 清單
    混入大量跨文件的相似事實（Q8 真實案例：LLM 抓了跨文件的「訓練時數
    不得低於八十小時」答成錯誤數字）。此函式讓語意 Fact 也收斂到語意
    自身判定的來源文件。`source_doc_id` 為字串，解析失敗／`None` 一律保留。
    """
    def _doc_id(f: dict) -> UUID | None:
        raw = f.get("source_doc_id")
        if not raw:
            return None
        try:
            return UUID(raw) if isinstance(raw, str) else raw
        except ValueError:
            return None

    return _scope_by_source_doc_ids(fact_results, allowed_doc_ids, _doc_id)


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


# 事實文字裡的型別標記——`（概念）` 或 `（PLACE）`／`（MonetaryAmount）` 這類
# schema.org 型別 token。報告25 § 4 發現5：`_verbalize_fact()` 新版已不再產生
# 這種標記、且 `backfill_fact_text_embeddings()` 會重寫既有 `Fact` 節點，但
# 尚未回填的 KG／殘留資料仍可能帶進 prompt（甚至洩漏到最終答案），這裡做
# 一道輸出前的防禦性清除。只吃「（純 ASCII 字母型別）」與「（概念）」，不會
# 誤刪 `（民國一百十年）` 這種正常的中文括號內容。
_TYPE_MARKER_RE = re.compile(r"\s*（(?:概念|[A-Za-z][A-Za-z0-9_]*)）")


def _strip_type_markers(text: str) -> str:
    return _TYPE_MARKER_RE.sub("", text).strip()


def _is_contentful_line(line: str, subject: str | None) -> bool:
    """判斷一行事實文字是否「有內容」——用於取代舊版直接看結構化 `object`
    欄位是否為空的殘缺過濾。

    ⚠️ **報告25 § 4 發現6 追查（2026-09-02）**：舊版 `if not object: continue`
    會把 `X -[RELATED_TO]-> (懸空概念)` 這種**payload 在 verb、object 為空**的
    合法事實一起丟掉——Q8 三筆答案事實（「訓練時數 以三百小時為度」等）正是
    這個形狀，被靜默丟棄、從頭到尾沒進過 prompt。改為看**渲染後的文字**：
    只有「空字串」或「只有 subject、沒有動詞/受詞內容」才算殘缺。
    """
    core = _strip_type_markers(line).lstrip("- ").strip()
    if not core:
        return False
    if subject and core == subject.strip():
        return False
    return True


def _split_fact_lines(
    triples: list[SVOTriple], fact_results: list[dict]
) -> tuple[list[str], list[str]]:
    """把 BFS 圖遍歷三元組與語意檢索 Fact 各自轉成 prompt 文字行，**分開回傳**
    `(bfs_lines, fact_lines)`，供 `_arrange_fact_lines()` 依來源分別處理——
    報告25 § 4 發現6：語意 Fact 經過 `vector_search_facts()` 的問題相關性
    KNN 檢索，BFS 三元組沒有任何問題相關性排序（`bfs_query()` 無 `LIMIT`／
    無評分），兩者不可等同看待、丟進同一個池子重排（會讓有相關性訊號的
    語意 Fact 被沒有訊號的 BFS 樣板列舉擠掉）。`_merge_fact_lines()` 保留
    為兩者相接的扁平版本，供接地核對等只需要「最終文字清單」的呼叫端。

    去重：優先按 `(subject, rel_type, object)`（三欄皆非空時，BFS 版優先）；
    object 為空時 `all(key)` 為 False、無法用 key 比對，改以**渲染後的行
    文字**比對涵蓋這個情況。

    ✅ **殘缺過濾改看渲染文字（2026-09-02，報告25 § 4 發現6 追查）**：見
    `_is_contentful_line()`——只丟空字串或「只有 subject」的行，`X verb (空)`
    這種 payload 在 verb 的合法事實保留（Q8 三筆答案事實正是這個形狀）。

    ✅ **自然語言化（2026-09-01，報告24 §5 階段3）**：BFS 三元組 `natural_text`
    有值時直接用，沒有時 fallback 回 `subject verb object` 直接串接（報告25
    § 4 發現5：不再塞 `（型別）`）。`fact_results` 的 `fact_text` 沿用
    `_verbalize_fact()` 簡單串接，輸出前用 `_strip_type_markers()` 清掉尚未
    回填 KG 殘留的型別標記。
    """
    seen_keys: set[tuple[str, str, str]] = set()
    seen_texts: set[str] = set()
    bfs_lines: list[str] = []
    for t in triples:
        if not t.subject:
            continue
        raw = t.natural_text if t.natural_text else f"{t.subject} {t.verb} {t.object}".rstrip()
        # 尚未跑過發現5 回填的 KG，其邊 `natural_text` 仍帶 `（型別）`——與
        # `fact_results` 側一致，輸出前一律過 `_strip_type_markers()`（順帶讓
        # 「帶標記的 BFS 版」與「乾淨的語意 Fact 版」文字一致、可被去重）。
        line = f"- {_strip_type_markers(raw)}"
        if not _is_contentful_line(line, t.subject) or line in seen_texts:
            continue
        if t.subject and t.rel_type and t.object:
            seen_keys.add((t.subject, t.rel_type, t.object))
        seen_texts.add(line)
        bfs_lines.append(line)

    fact_lines: list[str] = []
    for f in fact_results:
        subject = f.get("subject")
        if subject is not None and subject.strip() == "":
            continue
        key = (f.get("subject"), f.get("rel_type"), f.get("object"))
        if all(key) and key in seen_keys:
            continue
        line = f"- {_strip_type_markers(f['fact_text'])}"
        if not _is_contentful_line(line, subject) or line in seen_texts:
            continue
        if all(key):
            seen_keys.add(key)
        seen_texts.add(line)
        fact_lines.append(line)

    return bfs_lines, fact_lines


def _merge_fact_lines(triples: list[SVOTriple], fact_results: list[dict]) -> list[str]:
    """`_split_fact_lines()` 的扁平版本（BFS 行在前、語意 Fact 行在後），供
    接地核對（`verify_fact_grounding()`）等只需要「本輪最終送進 prompt 的
    事實文字清單」、不關心來源分層的呼叫端使用。**排序／截斷／來源分層
    邏輯在 `_arrange_fact_lines()`，不在這裡。**"""
    bfs_lines, fact_lines = _split_fact_lines(triples, fact_results)
    return bfs_lines + fact_lines


# ── 報告32 §9 G3 completeness guard（2026-09-08）─────────────────────────────
# T1 Q3/Q6 型「分 N 段回答」：三條同謂語、object 互異的事實（三段年齡工時
# 二/三/四小時、三級血中鉛管理），生成端偶爾整段漏掉一段、或重生成走「逐句
# 重建」路徑補不回。guard 在 chat() 最終答案產出後檢查每個「分段事實族」的
# 每個 object 都出現在答案裡，缺席就強制走能補全的重生成路徑、再不行就逐字附。

_TIER_MIN_MEMBERS = 3

# 問題是否要求「把每一段/每一級都列出來」——只有這種問題才跑 completeness
# guard。Q3「依年齡分三段規定」要全列；Q8「5 ppm 時係數是多少」只要一段
# （查表），不能被 guard 逼著把整張對照表都貼上。
_FULL_ENUM_RE = re.compile(
    r"分\s*[一二三四五六七八九十兩0-9]{0,3}\s*(?:段|級|類|階|種|項)"
    r"|分別|各[自別]|逐一|逐項|哪些|所有(?:的)?(?:規定|情形|情況|類別)|完整(?:列出|清單)"
)


def _wants_full_enumeration(question: str) -> bool:
    return bool(_FULL_ENUM_RE.search(question or ""))


def _fact_verb(f: dict) -> str:
    """`fact_results` dict 沒有獨立 verb 欄——從 `fact_text` 去掉 subject 前綴、
    object 後綴，取中段當謂語簽章（純為分組用，抓不準就回空字串）。"""
    text = str(f.get("fact_text") or "")
    subj = str(f.get("subject") or "")
    obj = str(f.get("object") or "")
    if subj and text.startswith(subj):
        text = text[len(subj):]
    if obj and text.endswith(obj):
        text = text[: len(text) - len(obj)]
    return text.strip()


def _detect_tier_families(
    triples: list[SVOTriple], fact_results: list[dict]
) -> list[list[tuple[str, str, str]]]:
    """把本輪檢索到的事實依 `(rel_type, 謂語)` 分組；成員 ≥ `_TIER_MIN_MEMBERS`
    且各成員 object 互異、subject 互異者視為一個「分段/分級事實族」。
    回傳每族的 `(subject, verb, object)` 清單。"""
    groups: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for t in triples:
        if not (t.subject and t.verb and t.object):
            continue
        groups.setdefault((t.rel_type or "", t.verb), []).append((t.subject, t.verb, t.object))
    for f in fact_results:
        subj, obj = f.get("subject"), f.get("object")
        verb = _fact_verb(f)
        if not (subj and obj and verb):
            continue
        groups.setdefault((f.get("rel_type") or "", verb), []).append((subj, verb, obj))

    families: list[list[tuple[str, str, str]]] = []
    for members in groups.values():
        # 同族內去重
        uniq = list(dict.fromkeys(members))
        objs = {m[2] for m in uniq}
        subs = {m[0] for m in uniq}
        if len(uniq) >= _TIER_MIN_MEMBERS and len(objs) == len(uniq) and len(subs) == len(uniq):
            families.append(uniq)
    return families


def _missing_tier_members(
    answer: str, families: list[list[tuple[str, str, str]]]
) -> list[tuple[str, str, str]]:
    """回傳「object 沒出現在 answer 裡」的分段事實族成員（去掉空白後比對）。"""
    flat = answer.replace(" ", "").replace("　", "")
    missing: list[tuple[str, str, str]] = []
    for members in families:
        for subj, verb, obj in members:
            if obj.replace(" ", "") not in flat:
                missing.append((subj, verb, obj))
    return missing


# 事實清單截斷／條件式重排的門檻常數（見 `docs/報告/23_生成端事實清單排序機制
# 優化設計報告.md` § 3.4）。皆為理論推導的初始建議值，尚未實測校準——K 參考
# LangChain `EmbeddingsFilter` 的預設值（k=20，與此處獨立推導的15-20建議值
# 巧合吻合，見報告23 § 3.5）取整數18；K' 取報告23建議的「明顯大於K」下限30
# 再留一些餘裕。留待報告23 §4測試計畫（多次重跑＋K值敏感度比較）校準。
_FACT_LINE_TRUNCATE_K = 18
_FACT_LINE_REORDER_THRESHOLD_K = 35

# 報告25 § 4 發現6：BFS 鄰居剪枝與 rank fusion 的參數（皆未實測校準，除 RRF k）。
# `_BFS_KEEP_MAX`：BFS 三元組行先對問題 embedding 排序，只留前這麼多筆——
#   SAGE（Titiya et al., 2026）「expand → 用 dense retrieval 過濾鄰居、只選 k'」
#   的簡化對應；BFS 本身無問題相關性排序（`bfs_query()` 無 LIMIT），不剪枝會
#   讓一條文的列舉樣板（如 N0080016 第5條「訓練計畫書應包括…」8 行）佔滿清單。
# `_MIN_BFS_SLOTS`：截斷時保底給 BFS 的名額，避免「答案由 BFS 三元組提供」
#   （報告22「每週總時數四十小時」案例）被語意 Fact 全數擠掉。
# `_RRF_K`：Reciprocal Rank Fusion 常數，Cormack, Clarke & Büttcher (2009) 定 60、
#   後續驗證未改（Table 1：k=10~100 幾乎持平），本專案沿用。
_BFS_KEEP_MAX = 18
_MIN_BFS_SLOTS = 4
_RRF_K = 60


async def _score_lines_by_embedding(
    question: str,
    lines: list[str],
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None = None,
) -> list[str]:
    """依 embedding cosine similarity 由高到低排序事實清單。

    取代舊版 `_sort_lines_by_relevance()`（字元二元組 bigram 重疊度）——報告22
    題3真實重跑證實 bigram 訊號太弱，只把目標事實從第16名（28筆中）推進到
    第11名，兩次真實重跑仍未被引用。改用 embedding 相似度，能捕捉同義詞、
    指代等 bigram 抓不到的語意相似性。

    ✅ **成本重新估算（2026-09-01，見報告23 § 3.3）**：舊版 docstring 曾誤估
    「逐筆呼叫 encode() 會顯著拖慢延遲」——`EmbeddingProvider.encode_batch()`
    可一次批次算完全部 `lines` 的向量，不需要逐行呼叫；`question_vector` 若
    呼叫端已算過（`chat()` 已為 `_find_seed_entities()`／`vector_search_facts()`
    算過一次），可直接傳入複用，不重算。

    `embedding_provider` 允許 `None`——但僅限 `lines` 為空清單時安全（此時
    提前回傳，保證不觸碰 `embedding_provider`）。`chat()` 依此設計維持既有
    「`payload.use_svo=False` 時完全不呼叫 `get_embedding_provider()`」的
    不變量（見 `test_chat_skips_semantic_search_when_use_svo_is_false`）——
    該模式下 `triples`／`fact_results` 恆為空，`_merge_fact_lines()` 輸出
    `lines` 因此恆為空，這裡的提前回傳自然成立，無需另外判斷 `use_svo`。
    """
    if not lines:
        return []
    assert embedding_provider is not None, "lines 非空時 embedding_provider 不應為 None"
    if question_vector is None:
        question_vector = await embedding_provider.encode(question)
    line_vectors = await embedding_provider.encode_batch(lines)
    scored = sorted(
        zip(lines, line_vectors),
        key=lambda pair: cosine_similarity(question_vector, pair[1]),
        reverse=True,
    )
    return [line for line, _ in scored]


def _litm_reorder(lines: list[str]) -> list[str]:
    """依 Jin et al. (2025, ICLR)《Long-Context LLMs Meet RAG》式1的 zigzag
    重排，把依相關性遞減排序的清單重新排列成「最相關的交替置於首尾」，讓
    最不相關的項目自然被擠到中段——對應 Liu et al. (2023/2024) *Lost in the
    Middle* 的 U 形長上下文效能曲線（相關資訊在開頭/結尾效能最好、中段
    顯著下降）。演算法邏輯與 LangChain `langchain_community.document_
    transformers.LongContextReorder` 的開源實作一致（見 `docs/參考文獻/
    19_生成端長清單事實遺漏與位置偏誤/README.md`，MIT授權，僅參考演算法
    邏輯、不依賴 LangChain 套件本身）。

    `lines` 必須已依相關性由高到低排序（呼叫端負責）。
    """
    reversed_lines = list(reversed(lines))
    reordered: list[str] = []
    for i, line in enumerate(reversed_lines):
        if i % 2 == 1:
            reordered.append(line)
        else:
            reordered.insert(0, line)
    return reordered


def _rrf_order(sem_ranked: list[str], bfs_ranked: list[str], lines: list[str]) -> list[str]:
    """Reciprocal Rank Fusion（Cormack, Clarke & Büttcher, 2009, SIGIR）：把
    `lines` 依兩個排序清單的 RRF 分數由高到低重排——`RRFscore(l) = Σ 1/(k +
    rank_i(l))`，k=`_RRF_K`。只用 rank、不用原始分數，因此不需要 `vector_
    search_facts()` 的 KNN 分數與 `_score_lines_by_embedding()` 的 cosine
    在同一個尺度上（RRF 原文：「combines ranks without regard to the
    arbitrary scores returned by particular ranking methods」）。Python `sorted`
    穩定，RRF 同分時保留傳入 `lines` 的既有順序。"""
    rank_sem = {line: i for i, line in enumerate(sem_ranked)}
    rank_bfs = {line: i for i, line in enumerate(bfs_ranked)}

    def _score(line: str) -> float:
        s = 0.0
        if line in rank_sem:
            s += 1.0 / (_RRF_K + rank_sem[line])
        if line in rank_bfs:
            s += 1.0 / (_RRF_K + rank_bfs[line])
        return s

    return sorted(lines, key=_score, reverse=True)


async def _arrange_fact_lines(
    question: str,
    bfs_lines: list[str],
    fact_lines: list[str],
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None = None,
) -> list[str]:
    """事實清單的完整排列邏輯。**2026-09-02 改版（報告25 § 4 發現6）**：
    先前把 BFS 三元組與語意 Fact 合併成一份清單、整批用
    `_score_lines_by_embedding()` 重排＋截斷——這一步丟棄了
    `vector_search_facts()` 已算好的問題相關性 KNN 排名，改用一個對「短
    答案事實 vs 冗長條文列舉」不利的第二次 embedding pass，導致 Q8 三筆
    已檢索到的答案事實被 N0080016 第5條的 8 行「訓練計畫書應包括…」樣板
    擠出前 18 名、完全沒進 prompt。

    改為分來源處理（文獻見 `docs/參考文獻/21_圖遍歷與向量檢索結果融合/`）：

    1. **BFS 鄰居剪枝**（SAGE, Titiya et al., 2026）：`bfs_lines` 本身無問題
       相關性排序（`bfs_query()` 無 LIMIT），先用 `_score_lines_by_embedding()`
       對問題排序、只留前 `_BFS_KEEP_MAX` 筆。
    2. **語意 Fact 為主、BFS 為輔的名額分配**（Han et al. 2024/2025 綜述：
       BFS 鄰居爆炸稀釋 LLM 焦點、需重排優先化；SAGE：k' additional on top
       of primary retrieval）：截斷目標 K（或 K'）內，語意 Fact 依
       `vector_search_facts()` 檢索順序優先佔位，BFS 至少保底 `_MIN_BFS_SLOTS`
       席（避免報告22「答案由 BFS 提供」案例被擠掉）；任一側不足時把餘額
       讓給另一側。
    3. **RRF 融合排序**（`_rrf_order()`，Cormack et al. 2009）：對留下來的 K 筆
       依兩個 rank 清單的 RRF 分數重排，決定 zigzag 時哪些落在首尾（最相關）。
    4. **zigzag 重排**（`_litm_reorder()`，Jin et al. 2025 / Liu et al. 2023）：
       清單 > K 時套用；≤ K 的小清單 Jin et al. 證實重排效果不明顯，不套。

    ⚠️ **`_BFS_KEEP_MAX`／`_MIN_BFS_SLOTS`／K／K' 皆未實測校準**（`_RRF_K=60`
    有 Cormack et al. 背書），留待報告25 §6 的 K 值敏感度測試與擴大題組
    重測校準。
    """
    bfs_ranked = await _score_lines_by_embedding(
        question, bfs_lines, embedding_provider=embedding_provider, question_vector=question_vector
    )
    bfs_ranked = bfs_ranked[:_BFS_KEEP_MAX]
    sem_ranked = list(fact_lines)  # 已是 vector_search_facts() 檢索順序

    total = len(sem_ranked) + len(bfs_ranked)
    if total <= _FACT_LINE_TRUNCATE_K:
        return _rrf_order(sem_ranked, bfs_ranked, sem_ranked + bfs_ranked)

    target = _FACT_LINE_TRUNCATE_K if total <= _FACT_LINE_REORDER_THRESHOLD_K else _FACT_LINE_REORDER_THRESHOLD_K
    n_bfs = min(len(bfs_ranked), max(_MIN_BFS_SLOTS, target - len(sem_ranked)))
    n_sem = min(len(sem_ranked), target - n_bfs)
    kept = sem_ranked[:n_sem] + bfs_ranked[:n_bfs]
    return _litm_reorder(_rrf_order(sem_ranked, bfs_ranked, kept))


# 報告27 C#2 M1（2026-09-04）：複合問題的子問題數上限——極端情況（問題本文
# 混進大量問號，例如貼上一整段條文）防止炸開過多次獨立生成呼叫。
_MAX_SUBQUESTIONS = 6


def _split_into_subquestions(question: str) -> list[str]:
    """規則式問題分解，按句末問號切分複合問題成獨立子問題——報告26 §4 #2
    真實案例：`qwen2.5:7b` 對「連續僱用滿多久…？獎勵金最多發給幾個月？…
    分別完成報備與申請？」這類 3 個「？」的複合問題單次生成時，會在回答
    第 3 點正確引用某條事實後，收尾摘要卻自我矛盾地說該事實「未記載」
    （報告27 C#2 前置查證，2026-09-04：4 次真實呼叫重現 1 次，3 次乾淨）。

    ✅ **零額外 LLM 呼叫的簡化設計**：Least-to-Most Prompting（Zhou et al.,
    ICLR 2023，arXiv:2205.10625）與 Self-Ask（Press et al., 2022，
    arXiv:2210.03350）皆用 LLM 做問題分解、且子答案**循序依賴**（後一題的
    解答建立在前一題答案之上）。本專案的子問題彼此**獨立**——`_build_prompt()`
    已把完整事實清單一次餵給每個子問題，不需要「上一子問題答案」當輸入，
    也就不需要文獻裡的循序求解機制，改用最簡單的規則式分句取代其「分解」
    階段：中文問句以「？」／「?」結尾這個慣例本身就是現成的子問題邊界，
    不必另花一次 LLM 呼叫做語意分解。

    只有 ≥2 個非空子句時才視為複合問題，否則原樣回傳 `[question]`
    （單一問題行為完全不變，不觸發下方 `_generate_decomposed_answer()`）。
    """
    parts = re.split(r"([？?])", question)
    segments: list[str] = []
    for i in range(0, len(parts) - 1, 2):
        text = parts[i].strip()
        if text:
            segments.append(text + parts[i + 1])
    if len(parts) % 2 == 1:
        trailing = parts[-1].strip()
        if trailing:
            segments.append(trailing)
    if len(segments) < 2:
        return [question]
    return segments[:_MAX_SUBQUESTIONS]


async def _generate_decomposed_answer(
    sub_questions: list[str],
    triples: list[SVOTriple],
    fact_results: list[dict],
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None,
    llm_provider: LLMProvider,
) -> str:
    """報告27 C#2 M1：每個子問題各自獨立生成一次完整答案（同一份已檢索事實
    清單、不重新檢索），彼此在生成當下互相看不到——這正是避免「回答子問題
    A 時看到子問題 B 已寫的內容、進而互相汙染／矛盾」的機制核心（單次生成
    處理複合問題時，模型會在同一段輸出裡前後不一致，見上方 docstring 的
    真實案例）。依原問題的子問題順序組裝，不做額外的整合式摘要 LLM 呼叫
    （省一次呼叫；子答案已依原順序編號，可讀性足夠）。

    ⚠️ **成本**：N 個子問題 = N 次完整生成呼叫，取代原本 1 次——本專案的
    子問題數通常 2-4（報告26 Q3 為 3），生成端延遲會相應增加，換取正確性。
    下游的 `verify_fact_grounding()`／限制性重新生成沿用既有機制，對組裝後
    的完整文字整體核對一次，不逐子答案核對（維持既有接地核對介面不變）。
    """
    parts: list[str] = []
    for i, sub_q in enumerate(sub_questions, start=1):
        # 報告32 §9 G4（2026-09-08）：`question_vector` 傳 None——強制 `_build_prompt()`
        # → `_arrange_fact_lines()` 對「這個子問題」重新編碼排序，而不是沿用整個
        # 複合問題的向量。真實案例（Q6 子問3「相關文件及紀錄至少保存幾年」）：
        # 「相關文件及紀錄至少保存三年」對整題（期間＋血中鉛分級＋保存）相關性
        # 低、排不進事實清單前段，但對子問題本身高度相關、應排 index 0。子問題
        # 彼此獨立、事實清單不重新檢索，只是排序基準要換成子問題自己。
        sub_prompt = await _build_prompt(
            sub_q, triples, fact_results, history=None,
            embedding_provider=embedding_provider, question_vector=None,
        )
        tokens = [tok async for tok in llm_provider.stream(sub_prompt)]
        answer = "".join(tokens).strip()
        parts.append(f"{i}. {sub_q}\n{answer}")
    return "\n\n".join(parts)


async def _generate_decomposed_constrained_answer(
    sub_questions: list[str],
    triples: list[SVOTriple],
    fact_results: list[dict],
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None,
    llm_provider: LLMProvider,
) -> str:
    """`_generate_decomposed_answer()` 的限制性重新生成版本——方案B（見
    `_build_constrained_prompt()` docstring）判定草稿有未接地陳述、需要重新
    生成時，若草稿本身是分解出來的，修正版**也要保留分解結構**，逐子問題
    各自用 `_build_constrained_prompt()` 重生一次。

    ⚠️ **2026-09-05 真實測試抓到的 bug**：`chat()` 原本不分這個情況，一律用
    `_build_constrained_prompt(payload.question, ...)` 對整個複合問題單次
    重新生成——一旦接地核對觸發重生（`qwen2.5:7b` 非決定性下常發生），
    分解機制在最需要它的路徑上完全失效，退回報告26 §4 #2 原本的失效模式
    （真實輸出：修正版格式跟分解草稿不一致、多個子答案內容混在一起）。
    此函式修正這個缺口，讓重生路徑跟草稿路徑用同一套分解結構。
    """
    parts: list[str] = []
    for i, sub_q in enumerate(sub_questions, start=1):
        # 報告32 §9 G4：同 `_generate_decomposed_answer()`——`question_vector` 傳
        # None，讓事實清單排序基準換成「這個子問題」而非整個複合問題。
        sub_prompt = await _build_constrained_prompt(
            sub_q, triples, fact_results, history=None,
            embedding_provider=embedding_provider, question_vector=None,
        )
        tokens = [tok async for tok in llm_provider.stream(sub_prompt)]
        answer = "".join(tokens).strip()
        parts.append(f"{i}. {sub_q}\n{answer}")
    return "\n\n".join(parts)


_TARGETED_FIX_RE = re.compile(r"^\s*修正\s*\d+\s*[:：]\s*(.+?)\s*$")


async def _targeted_correction(
    question: str,
    ungrounded_statements: list[str],
    triples: list[SVOTriple],
    fact_results: list[dict],
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None,
    llm_provider: LLMProvider,
) -> list[str] | None:
    """報告32 §9 G1（2b 定向修訂）：只重寫草稿裡未接地的主張句，一次 LLM 呼叫。

    回傳與 `ungrounded_statements` 等長、順序對應的修正句清單；LLM 輸出行數對
    不上（解析失敗）時回傳 `None`，由呼叫端退回整份限制性重生成。

    ⚠️ **與 `_build_constrained_prompt()` 的 CoVe factored 取捨的關係**：這裡把
    未接地片段放進 prompt（CoVe「joint」的一面），但 prompt 明確禁止沿用片段裡
    未經查核的具體數字／期限／金額——CoVe（Dhuliawala et al., 2023）擔心的
    「修正步驟看得到草稿→傾向重複草稿的錯誤」對象正是這些值；保留的只是片段
    的問題框架。草稿裡已接地的句子完全不進這個呼叫、零重複風險。整段重寫
    （`grounded_claim_count == 0` 時）仍走 `_build_constrained_prompt()` 的 factored。
    """
    if not ungrounded_statements:
        return []
    bfs_lines, fact_lines = _split_fact_lines(triples, fact_results)
    if bfs_lines or fact_lines:
        arranged = await _arrange_fact_lines(
            question, bfs_lines, fact_lines,
            embedding_provider=embedding_provider, question_vector=question_vector,
        )
        facts = "\n".join(arranged)
    else:
        facts = "（本輪未檢索到任何事實）"
    fragments = "\n".join(f"{i}. {s}" for i, s in enumerate(ungrounded_statements, start=1))
    prompt = f"""{_TAIWAN_CONTEXT_INSTRUCTION}

以下是從知識圖譜檢索到的事實，這是你這次「唯一」能引用的資訊來源：
{facts}

原問題：{question}

下列片段來自一份草稿答案，未通過事實查核（片段裡的具體數字／期限／金額在上方事實清單找不到依據）：
{fragments}

請針對每一個片段輸出一行修正，嚴格遵守：
1. 若事實清單裡有該片段所問內容的正確依據 → 只用事實清單的內容，把它改寫成正確的一句。
2. 若事實清單裡沒有 → 輸出「（此部分）資料未明確記載，無法確認」，並簡短指出缺的是問題的哪個部分。
3. 不要沿用原片段裡任何未經查核的具體數字／期限／金額／結論。
4. 一個片段一行、順序對應，每行格式固定為「修正N：<內容>」（N 為片段編號）。
5. 若片段是「分段清單／分級」裡的其中一段（片段提到某個年齡段、某個級別、某個類別加上一個門檻），請先鎖定它是哪一段，再到事實清單裡找「正是這一段」的那條事實、取它的值——這種情況通常事實清單裡有對應那一段的正確值，只是原草稿把段別配錯了（例如把「未滿六歲」的值寫成「未滿六個月」的值）。此時依規則 1 用事實清單的正確值改寫，不算違反規則 3。只有在事實清單確實沒有這一段時才走規則 2。
"""
    raw = "".join([tok async for tok in llm_provider.stream(prompt)])
    fixes: list[str] = [
        m.group(1).strip()
        for line in raw.splitlines()
        if (m := _TARGETED_FIX_RE.match(line))
    ]
    if len(fixes) != len(ungrounded_statements):
        return None
    return fixes


async def _build_prompt(
    question: str,
    triples: list[SVOTriple],
    fact_results: list[dict],
    history: list[ChatMessage] | None,
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None = None,
) -> str:
    bfs_lines, fact_lines = _split_fact_lines(triples, fact_results)
    if bfs_lines or fact_lines:
        arranged = await _arrange_fact_lines(
            question, bfs_lines, fact_lines,
            embedding_provider=embedding_provider, question_vector=question_vector,
        )
        facts = "\n".join(arranged)
        context_block = f"以下是從知識圖譜檢索到、可能與問題相關的事實：\n{facts}\n"
        instruction = (
            "請優先根據上述事實回答問題；若事實不足以完整回答，可以補充你自己的知識，"
            "但務必清楚區分哪些是根據圖譜事實、哪些是你自己的補充。"
            "回答前請逐條檢視上方事實清單中每一項，判斷是否與問題相關，不要遺漏任何一項可用的事實。"
            # 報告32 §9 G2（2026-09-08；A/B 收緊 2026-09-08）：Q8 型「查表 + 區間
            # 比對」組合推論——事實清單給了分段對照表、問題給了一個具體數值，模型
            # 常不做「落在哪一段」這步而直接答「未記載」。明確允許這一種確定性推論
            # （且只有這一種），但只在數值「嚴格落在某一明列列的上下界內」時允許——
            # 不准取最近的一列、不准外插到沒檢索到的級距（RefusalBench
            # GranularityMismatch：模型最常把「級距缺一段」誤當成可查表而硬答）。
            "若上述事實清單裡有一組「數值區間 → 對應值」的分段對照（例如"
            "「1 以上未滿 10 → 變量係數 2」「10 以上未滿 100 → 變量係數 1.5」），"
            "而問題給了一個具體數值，請判斷該數值落在哪一個區間；只有當它「嚴格"
            "落在某一列明列的上下界之內」時，才取該區間在清單裡明列的對應值作答、"
            "並註明用了哪一列——這種把清單明列的分段對照表套用到題目數值的推論"
            "是允許的，不算臆測。"
            "但若該數值沒有落在任何一列明列的區間內，或清單只檢索到部分區間／"
            "部分分級（你無法確認是否還有沒被檢索到的級距），不要挑最接近的一列"
            "硬套，這部分請回答「事實清單只有部分級距，查不到題目數值對應的那一段」。"
            # 報告32 §9 G3（2026-09-08）：Q3/Q6 型「分 N 段回答」——三段年齡工時、
            # 三級血中鉛管理。真實失效：把「未滿六歲」與「未滿六個月」（字樣相近）
            # 混段、或整段漏掉一段。逐段對照、每段獨立配自己那條事實。
            "若問題要求分段回答（例如依年齡分三段、依濃度分三級），請把每一段"
            "當成獨立的一問：逐段到事實清單裡找「屬於這一段」的那條事實，取它的值。"
            "特別注意字樣相近但不同段的標籤（例如「未滿六歲」與「未滿六個月」、"
            "「六歲以上未滿十二歲」與「十二歲以上未滿十五歲」）不可混用；"
            "問題列出幾段就要回答幾段，不可以只答其中一部分。"
            # 報告27 C#2 M0（2026-09-04）：真實案例（報告26 §4 #2、報告27 §C2
            # 前置查證）發現模型會在回答的某一部分正確引用某條事實，卻在收尾
            # 摘要時又說該事實「未記載／無法確認」，自我矛盾——多半發生於
            # 事實清單裡有多條「形狀相近」（同單位數字、同類期限）的事實時。
            "若你在回答的任何一部分已經引用某條事實作答，後面的摘要或結論"
            "不可以再說這項資訊「未記載」或「無法確認」——同一份事實清單內，"
            "已經用過的事實視為確定可用，前後結論必須一致。"
        )
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


async def _build_constrained_prompt(
    question: str,
    triples: list[SVOTriple],
    fact_results: list[dict],
    history: list[ChatMessage] | None,
    *,
    embedding_provider: EmbeddingProvider | None,
    question_vector: list[float] | None = None,
) -> str:
    """方案 B「限制性重新生成」用的強約束 prompt（見 `docs/報告/16_事實接地性核對機制設計報告.md` § 3、9）。

    只在 `verify_fact_grounding()` 抓到未接地陳述時才呼叫。跟 `_build_prompt()`
    的差異：不再給「事實不足可補充自己知識」的空間，改為明確禁止，事實不足
    時要求答「資料未明確記載」並簡短說明具體缺什麼，對應使用者「寧願說不
    知道，也不要亂回答」的明確要求。**要求附帶原因說明**（2026-08-28，見
    Wen et al., 2025《Know Your Limits》綜述引用 Deng et al., 2024 的發現：拒答
    時附帶不可回答的原因說明，除了提升可解釋性，實測也能提升整體回答準
    確度）——不是單純的「資料未明確記載」四個字了事，而是要求指出缺的是
    問題的哪個部分。

    ⚠️ **刻意不把上一版（草稿）或其未接地陳述放進這個 prompt**——2026-08-28
    讀 Dhuliawala et al. (2023) Chain-of-Verification 全文後的設計修正：該論文
    明確指出「joint」作法（修正步驟的 context 裡包含原始草稿）會讓修正結果
    傾向重複草稿裡的錯誤內容（"verification answers have to condition on the
    initial response... may increase the likelihood of repetition"），因此改採
    論文建議的「2-step／factored」作法——修正步驟的 context **只有**事實清單
    與問題本身，看不到有幻覺風險的草稿或其中的錯誤陳述，避免文字錨定效應
    讓模型忍不住抄自己剛講過的內容。舊版曾把未接地陳述列出來要求「不要
    重複」，反而正是論文警告的反面案例——先讓模型看到錯誤內容，再指望它
    自己避開。
    """
    bfs_lines, fact_lines = _split_fact_lines(triples, fact_results)
    if bfs_lines or fact_lines:
        arranged = await _arrange_fact_lines(
            question, bfs_lines, fact_lines,
            embedding_provider=embedding_provider, question_vector=question_vector,
        )
        facts = "\n".join(arranged)
    else:
        facts = "（本輪未檢索到任何事實）"

    history_block = ""
    if history:
        history_lines = "\n".join(f"{m.role}：{m.content}" for m in history[-6:])
        history_block = f"對話歷史：\n{history_lines}\n\n"

    return f"""{_TAIWAN_CONTEXT_INSTRUCTION}

以下是從知識圖譜檢索到的事實，這是你這次「唯一」能引用的資訊來源：
{facts}

{history_block}問題：{question}

請回答上述問題，並嚴格遵守：
1. 只能陳述上方事實清單裡明確出現過的內容，不可以用推論或你自己的知識補充任何具體數字、天數、期限、結論。唯一例外（報告32 §9 G2）：事實清單裡有「數值區間 → 對應值」的分段對照表（例如「1 以上未滿 10 → 變量係數 2」）、問題又給了一個具體數值、且該數值嚴格落在某一列明列的上下界之內時，可以取該區間在清單裡明列的對應值作答，並註明用了哪一列；此例外僅限這種分段查表。若該數值沒有落在任何一列明列的區間內，或清單只有部分級距（缺了中間或兩端某一段），仍依規則 2 回答「資料未明確記載，無法確認」，不可挑最接近的一列硬套。其他任何推論一律禁止。
2. 若事實清單不足以完整回答問題的某個部分，該部分請回答「資料未明確記載，無法確認」，並簡短說明具體是哪個部分找不到依據（例如：「事實清單中沒有提到婚假的天數」），不要臆測或用自己的知識填補。
3. 回答前請逐條檢視上方事實清單中每一項，確認是否有跟問題相關卻被你遺漏的事實——事實清單已依與問題的相關性排序，最相關的通常在清單前段。
4. 若你在回答的任何一部分已經引用某條事實作答，後面的摘要或結論不可以再說這項資訊「未記載」或「無法確認」——同一份事實清單內，已經用過的事實視為確定可用，前後結論必須一致。
"""


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

    ✅ **事實接地性核對（2026-08-24 v1；2026-08-28 升級為方案 B「限制性重新
    生成」）**：對應 `docs/報告/16_事實接地性核對機制設計報告.md` § 3、6／
    `docs/論文/03_系統設計與方法論.md` § 3.6。既有的圖遍歷信心訊號（種子
    命中數／BFS 路徑長度）拓不到「證據已檢索到、生成階段仍捏造內容」這種
    失效模式，真實測試已重現過此失效案例（見報告第 1 節）。

    v1（2026-08-24）只偵測、不糾正：使用者已經即時看過第一版回答，事後才
    送出 `event: grounding` 當診斷資訊，即使抓到幻覺也不會改變使用者看到
    的內容。**2026-08-28 依使用者明確要求（「寧願說不知道，也禁止亂回答」）
    升級為方案 B 最小可行版**：不再逐 token 即時串流第一版答案給使用者；
    先在背後生成完整草稿、核對（`services/verification_service.py::
    verify_fact_grounding()`，核對範圍統一用 `_merge_fact_lines()` 的輸出，
    與 `_build_prompt()` 實際餵給生成模型的 context 一致，避免假陽性），若
    有任一陳述未接地，用 `_build_constrained_prompt()`（明確禁止臆測、要求
    答不知道）重新生成一次，只把核對過的最終版本送給使用者。過程中送出
    `event: status`（`phase`: `generating` / `verifying` / `done`，`done` 額外
    帶 `regenerated: bool`）供前端顯示「正在核實中…」佔位，使用者依此次決策
    **永遠不會看到未核對過的版本**——對應成本：只有真的抓到未接地內容時才
    多付一次完整 LLM 生成的延遲，沒有幻覺的情況下只多一次核對呼叫。
    **誠實侷限**：只重新生成一次，不做多輪迭代收斂；修正版本身理論上仍可能
    包含新的未接地內容（核對機制本身也可能誤判），未做「核對到收斂為止」的
    上限迴圈，留待第五章消融實驗評估是否需要。
    """

    async def _stream():
        if payload.kg_id is None:
            error_json = json.dumps({"message": "請先選擇一個知識圖譜（尚未實作跨 KG 自動路由）"})
            yield f"event: error\ndata: {error_json}\n\n"
            return

        driver = get_driver()
        llm_provider = get_llm_provider()
        # 報告33 §3.9 / 論文 04 §4.10（設定分層，2026-09-08 第 2 步）：載入這個
        # 知識圖譜的 KGConfig。目前未接任何 ConfigSource → `cfg` == `KGConfig()`
        # == 重構前的模組常數值，行為零變化；查詢端 θ 家族（seed 上限、樞紐度數、
        # per-seed、懶惰擴展門檻）改為讀 `cfg`，之後接 domain pack / per-KG profile
        # 即生效。
        cfg = ConfigLoader().load(payload.kg_id)
        # 2026-09-01：embedding_provider／question_vector 宣告移到 if 區塊外
        # （保持 None），供事實清單排列（`_arrange_fact_lines()`）在
        # `_build_prompt()` 呼叫點（區塊外）有變數可傳；但取得動作
        # （`get_embedding_provider()`）本身仍留在 use_svo 分支內——
        # payload.use_svo=False 時 fact_lines 必為空，_arrange_fact_lines()
        # 對空清單直接回傳、保證不會實際使用 embedding_provider，維持既有
        # 「use_svo=False 完全不觸碰 embedding provider」的測試不變量
        # （test_chat_skips_semantic_search_when_use_svo_is_false）。
        embedding_provider: EmbeddingProvider | None = None
        question_vector: list[float] | None = None
        triples: list[SVOTriple] = []
        fact_results: list[dict] = []
        resolved_rel_type: str | None = None
        if payload.use_svo:
            embedding_provider = get_embedding_provider()
            question_vector = await embedding_provider.encode(payload.question)

            # 報告27 L1（2026-09-04）：語意 Fact 檢索提前到 `bfs_query()` 之前，
            # 推出的文件範圍當走訪的**前置**約束（下推到 Cypher），而非只做
            # 事後排除篩選——原順序讓昂貴的無界路徑枚舉先發生、範圍訊號用不上
            # （報告26 §4 #4：Q5/6/7 各 330–440 秒）。
            fact_results = await vector_search_facts(
                driver, payload.kg_id, question_vector, top_k=payload.top_k
            )
            # 2026-08-27：語意 Fact 檢索找到的來源文件，反過來當前置篩選範圍。
            # 2026-09-02（報告25 §4 發現1）：範圍只取分數最高的前 N 筆推導
            # （`top_k` 提高到 20 後，全 20 筆會被 ~0.80 的跨文件事實稀釋）；
            # 且範圍同時套用到 BFS 三元組與語意 Fact 清單本身（先前只套前者，
            # 導致 Q8 的語意 Fact 清單混入跨文件雜訊、被 LLM 採用成錯誤數字）。
            relevant_doc_ids = _relevant_doc_ids_from_facts(
                fact_results, top_n=cfg.bfs.doc_scope_top_n_facts
            )

            seeds = await _find_seed_entities(
                driver, payload.kg_id, payload.question,
                embedding_provider=embedding_provider, question_vector=question_vector,
                cfg=cfg,
            )
            triples = await bfs_query(
                driver, payload.kg_id, seeds,
                hops=payload.svo_hops,
                scope_doc_ids=(relevant_doc_ids or None),
                per_seed_limit=cfg.bfs.per_seed_limit,
                cfg=cfg,
            )

            resolved_rel_type = await resolve_query_relation_type(
                payload.question, embedding_provider, llm_provider=llm_provider
            )
            triples = _filter_triples_by_relation_type(triples, resolved_rel_type)

            # 事後排除篩選仍保留：`bfs_query()` 的 Cypher 範圍下推有「空結果
            # → 退回無範圍」的 fallback（相容無 HAS_ENTITY 邊的舊 KG），該
            # 情況下仍可能放行離題三元組，這裡兜底。
            triples = _filter_triples_by_source_doc_ids(triples, relevant_doc_ids)
            fact_results = _filter_facts_by_source_doc_ids(fact_results, relevant_doc_ids)

        # 報告27 C#2 M1（2026-09-04）：複合問題（句末問號 ≥2）先按規則拆成獨立
        # 子問題，各自對同一份事實清單生成答案，避免單次生成內跨子答案互相
        # 汙染／矛盾（見 `_split_into_subquestions()` docstring 的真實案例）。
        # `payload.use_svo=False` 或檢索為空時沒有事實清單可分工，維持原單次
        # 生成路徑；`_split_into_subquestions()` 對非複合問題原樣回傳單元素
        # 清單，行為與修改前完全一致。
        sub_questions = _split_into_subquestions(payload.question)

        yield f"event: status\ndata: {json.dumps({'phase': 'generating'})}\n\n"
        if payload.use_svo and len(sub_questions) > 1 and (triples or fact_results):
            draft_answer = await _generate_decomposed_answer(
                sub_questions, triples, fact_results,
                embedding_provider=embedding_provider, question_vector=question_vector,
                llm_provider=llm_provider,
            )
        else:
            prompt = await _build_prompt(
                payload.question, triples, fact_results, payload.history,
                embedding_provider=embedding_provider, question_vector=question_vector,
            )
            # 方案 B：不逐 token 即時轉發第一版草稿——先在背後生成完整答案，
            # 核對過（必要時重新生成）才把最終版本送給使用者（見上方 docstring）。
            draft_parts: list[str] = []
            async for token in llm_provider.stream(prompt):
                draft_parts.append(token)
            draft_answer = "".join(draft_parts)

        # 核對範圍須與 `_build_prompt()` 實際餵給生成模型的 context 一致
        # （`_merge_fact_lines()` 合併後的 BFS 三元組＋語意 Fact），只用
        # `fact_results` 會漏掉 BFS 三元組來源的正確陳述，造成假陽性
        # （2026-08-24 真實測試發現：「每週總時數四十小時」由 BFS 三元組
        # 提供，只核對 `fact_results` 會誤判為未接地）。
        fact_lines = _merge_fact_lines(triples, fact_results)
        fact_texts = [line.lstrip("- ") for line in fact_lines]

        yield f"event: status\ndata: {json.dumps({'phase': 'verifying'})}\n\n"
        grounding = await verify_fact_grounding(
            draft_answer, fact_texts, llm_provider, question=payload.question
        )

        final_answer = draft_answer
        regenerated = False
        # payload.use_svo=False 時 _build_prompt() 本來就明確允許 LLM 用自己的
        # 知識回答（見該函式 else 分支的 instruction）——這種模式下完全沒有
        # fact_texts 可供核對，verify_fact_grounding() 會把每一句都判定未接地
        # （見其 docstring：無 Fact 時直接標記，不呼叫 LLM），若不排除會導致
        # 每次 use_svo=False 的回答都被錯誤觸發限制性重新生成、答成「資料未
        # 明確記載」，違背該模式本身「允許補充自身知識」的設計。只在
        # use_svo=True（有 KG 事實可供核對）時才觸發重新生成。
        #
        # 2026-09-02（報告25 § 4 發現6→⑥ 診斷）：觸發條件從「任一句未接地」
        # 收緊為「任一句**是事實主張、且**未接地」——`qwen2.5:7b` 常把使用者
        # 的問題當 markdown 標題原樣回貼、或加引言句，這類非主張句天生不會被
        # 事實清單支持，舊條件會對它們誤觸發重生成、把兩部分全對的正確草稿
        # 改壞成「資料未明確記載」（3 輪真實診斷確認）。見 `ClaimGrounding.
        # is_claim` docstring。
        ungrounded_claims = [c for c in grounding if c.is_claim and not c.supported]
        if payload.use_svo and ungrounded_claims:
            # 報告32 §9 G1（2b 定向修訂）：先看草稿有沒有可保留的接地主張——
            # `grounded_claim_count = is_claim 句數 − 未接地 is_claim 句數`。T1 證實
            # 「觸發後整段重寫」的粒度本身有問題：~75% 觸發率、且常把草稿裡已接地
            # 的正確部分一併改成「資料未明確記載」（見 03 §3.6 §2b 段）。
            claim_count = sum(1 for c in grounding if c.is_claim)
            grounded_claim_count = claim_count - len(ungrounded_claims)
            corrections: list[str] | None = None
            if grounded_claim_count > 0:
                # 草稿部分正確 → 只重寫未接地的主張句，一次 LLM 呼叫；接地句與
                # 非主張句原樣保留。解析失敗回傳 None → 下面退回整份重生。
                corrections = await _targeted_correction(
                    payload.question,
                    [c.statement for c in ungrounded_claims],
                    triples, fact_results,
                    embedding_provider=embedding_provider, question_vector=question_vector,
                    llm_provider=llm_provider,
                )
            if corrections is not None:
                # 從 grounding 逐句清單重組（不用字串取代——回傳的 statement 可能與
                # 草稿原字不完全一致）；未接地主張句換成對應修正，其餘原樣。
                fix_i = 0
                out_lines: list[str] = []
                for c in grounding:
                    if c.is_claim and not c.supported:
                        out_lines.append(corrections[fix_i])
                        fix_i += 1
                    else:
                        out_lines.append(c.statement)
                final_answer = "\n".join(out_lines)
            elif len(sub_questions) > 1 and (triples or fact_results):
                # 整份草稿沒有接地主張可保留（或定向修訂解析失敗）＋分解草稿 →
                # 分解式整份重生（報告27 C#2 M1，保留分解結構）。
                final_answer = await _generate_decomposed_constrained_answer(
                    sub_questions, triples, fact_results,
                    embedding_provider=embedding_provider, question_vector=question_vector,
                    llm_provider=llm_provider,
                )
            else:
                # 整份重寫 → 刻意不把草稿或未接地陳述傳進去，見 _build_constrained_prompt()
                # docstring（CoVe 的 joint vs. factored 發現）。
                constrained_prompt = await _build_constrained_prompt(
                    payload.question, triples, fact_results, payload.history,
                    embedding_provider=embedding_provider, question_vector=question_vector,
                )
                corrected_parts: list[str] = []
                async for token in llm_provider.stream(constrained_prompt):
                    corrected_parts.append(token)
                final_answer = "".join(corrected_parts)
            regenerated = True
            # 重新核對修正版，讓 event: grounding 反映使用者實際看到的內容，
            # 而非已經被取代的草稿。
            grounding = await verify_fact_grounding(
                final_answer, fact_texts, llm_provider, question=payload.question
            )

        # 報告32 §9 G3 completeness guard：分段/分級問題（三段年齡工時、三級
        # 血中鉛管理）——最終答案偶爾整段漏掉一段，且接地核對抓不到「缺內容」
        # （缺的段不是未接地的主張、是根本沒寫）。檢查每個「分段事實族」的每個
        # object 都在答案裡，缺就先強制走「分解式整段重生」（能補全的路徑，跟
        # 逐句重建不同），仍缺就逐字附上——保證分段清單完整。
        if payload.use_svo and (triples or fact_results) and _wants_full_enumeration(payload.question):
            tier_families = _detect_tier_families(triples, fact_results)
            missing = _missing_tier_members(final_answer, tier_families)
            if missing and len(sub_questions) > 1:
                final_answer = await _generate_decomposed_constrained_answer(
                    sub_questions, triples, fact_results,
                    embedding_provider=embedding_provider, question_vector=question_vector,
                    llm_provider=llm_provider,
                )
                regenerated = True
                grounding = await verify_fact_grounding(
                    final_answer, fact_texts, llm_provider, question=payload.question
                )
                missing = _missing_tier_members(final_answer, tier_families)
            if missing:
                supplement = "\n".join(
                    f"補充（依事實清單）：{s} {v} {o}".strip() for s, v, o in missing
                )
                final_answer = f"{final_answer}\n\n{supplement}"
                regenerated = True

        # 報告26 §4 #5：生成端（`qwen2.5:7b`）偶爾在自己的答案文字裡混簡體，
        # 跟已修的抽取端發現4（SVO 三元組欄位）是不同呼叫點的同一類問題。
        # 沿用發現4的字元級選擇性轉繁（來源語料當白名單，避免「雇」「托」
        # 這類法規原文正當用字被誤轉）；`_TAIWAN_CONTEXT_INSTRUCTION` 的
        # 「請一律使用繁體中文回答」是 prompt 層防線，這裡是保底。
        kg_folder = str(Path(settings.workspace_dir) / str(payload.kg_id))
        final_answer = _to_traditional_selective(final_answer, _kg_source_charset(kg_folder))

        yield f"data: {json.dumps({'token': final_answer})}\n\n"

        document_map = await _fetch_document_map(driver, payload.kg_id, triples, fact_results)
        sources_json = json.dumps(
            _serialize_sources(triples, fact_results, resolved_rel_type, document_map), ensure_ascii=False
        )
        yield f"event: sources\ndata: {sources_json}\n\n"

        grounding_json = json.dumps(
            [
                {"statement": c.statement, "is_claim": c.is_claim,
                 "supported": c.supported, "reason": c.reason}
                for c in grounding
            ],
            ensure_ascii=False,
        )
        yield f"event: grounding\ndata: {grounding_json}\n\n"

        yield f"event: status\ndata: {json.dumps({'phase': 'done', 'regenerated': regenerated})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
