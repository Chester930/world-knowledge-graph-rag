"""SVO 三元組提取、Neo4j MERGE、BFS 查詢。

Traceability: 02 §2.4.2／§2.4.4／§2.4.5／§2.4.7 ->
03 §3.1.3／§3.1.4／§3.2§b -> 04 §4.4／§4.5／§4.7.
Literature: OpenIE、ConceptNet／Schema.org、entity-alignment、GraphRAG 脈絡。
Project: Neo4j is a direct dependency; AutoRE、KGGen、PathRAG 等是方法或架構參考，
不是本模組的直接程式來源。Tests: tests/services/test_svo_service.py、
tests/routers/test_agent.py.
"""
from __future__ import annotations
import asyncio
import difflib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence
from uuid import UUID

from neo4j import AsyncDriver
from neo4j.exceptions import ConstraintError

from core.constants import (
    COMPARE_COSINE_THRESHOLD,
    ENTITY_DEDUP_COSINE_THRESHOLD,
    ENTITY_DEDUP_EDIT_RATIO_THRESHOLD,
    ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD,
    ENTITY_TYPES,
    FACT_SEARCH_CANDIDATE_MULTIPLIER,
    QSIM_ASSIGN_THRESHOLD,
    QSIM_ESCALATE_LOW_THRESHOLD,
    SVO_REL_TYPE_DESCRIPTIONS,
    SVO_REL_TYPES,
    VECTOR_DIM,
)
from core.config import task_queue_db_path
from core.providers.base import EmbeddingProvider, LLMProvider
from core.providers.factory import get_embedding_provider, get_llm_provider
from models.knowledge_graph import SVOTriple
from repositories.kg_repo import KGRepository
from services import document_record_service, expand_governance_service, sim_calibration_service, task_queue_service
from services.classify_service import cosine_similarity
from services.entity_registry_service import should_promote_by_frequency
from services.pronoun_resolution_service import DEFAULT_PRONOUN_LEXICON
from services.svo_chunking import SVOChunk
from services.svo_preprocessing_service import (
    prepare_svo_ready_chunks,
    read_sentence_embeddings,
    read_standardized_sentences,
)


async def create_entity_index(driver: AsyncDriver | None = None) -> None:
    """建立 Entity 節點唯一約束（app 啟動時呼叫一次）。

    ✅ **2026-08-27 修正（64筆規模真實資料發現）**：原本只建立普通索引
    （`CREATE INDEX ... ON (e.kg_id, e.name)`），不保證唯一性——`merge_entity()`
    的 `MERGE (e:Entity {{kg_id, name}})` 在沒有唯一約束背書時，並發寫入
    （不同 chunk 幾乎同時抽取到同一個高頻實體，如「雇主」）可能各自檢查
    「不存在」後各自建立，產生屬性完全相同（連 name 的 UTF-8 bytes都一樣）
    的重複節點——64 筆規模的 KG 實測發現 14 組、共 16 個重複節點，且因為
    重複節點各自累積少量連結，會讓 BFS 從其中一個節點出發時漏掉另一個
    節點上的事實。改用 `CREATE CONSTRAINT ... IS UNIQUE`，Neo4j 對唯一約束
    的 MERGE 有原子性保證，能解決並發寫入下的重複問題；約束會自動建立
    對應索引，不需要額外的 `CREATE INDEX`。**若資料庫裡已存在違反此約束
    的重複節點，`CREATE CONSTRAINT` 會失敗**——套用前必須先清理既有重複
    （見手動合併腳本，本次已對現有 KG 執行過一次性清理，測試環境走
    `IF NOT EXISTS` 全新資料庫不受影響）。
    """
    if driver is None:
        return
    await driver.execute_query(
        "CREATE CONSTRAINT entity_kg_name_unique IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE (e.kg_id, e.name) IS UNIQUE"
    )


async def create_chunk_vector_index(driver: AsyncDriver | None = None, dim: int = VECTOR_DIM) -> None:
    """建立 Chunk 節點向量索引（app 啟動時呼叫一次），供未來回答階段的來源
    篩選使用（見 `embed_svo_chunks` docstring）。"""
    if driver is None:
        return
    await driver.execute_query(
        """
        CREATE VECTOR INDEX chunk_embedding_vector IF NOT EXISTS
        FOR (c:Chunk) ON c.embedding
        OPTIONS { indexConfig: { `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' } }
        """,
        dim=dim,
    )


def _strip_json_fence(raw: str) -> str:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else cleaned


def _parse_triples_payload(raw: str) -> list[dict]:
    payload = json.loads(_strip_json_fence(raw))
    if isinstance(payload, dict):
        payload = payload.get("triples", [])
    if not isinstance(payload, list):
        raise ValueError("SVO 抽取結果必須是 JSON list 或含 triples 的 object")
    return [item for item in payload if isinstance(item, dict)]


# 實體型別參考清單——由 core.constants.ENTITY_TYPES（schema.org 實測最常見類型，
# 見該常數 docstring 的文獻依據）動態組出，避免與該常數重複維護兩份清單。僅供 LLM
# 判斷參考，不強制驗證——subject_type/object_type 選填、可多值（見 3.1.4），清單中
# 找不到合適選項時可自訂名稱，或留空字串代表無法判斷。
_ENTITY_TYPE_GUIDE = "、".join(f"{tag}（{desc}）" for tag, desc in ENTITY_TYPES.items())

# 實體型別擴充庫（schema.org 官方完整清單，939 類）的讀取/比對邏輯——核心庫
# （ENTITY_TYPES，52 類）優先比對，查不到才查這裡；兩者皆查無對應時保留 LLM
# 原始輸出，不拋出例外、不拒絕，對應 3.1.4「實體型別選填、不做強制驗證」定案。
_EXTENDED_ENTITY_TYPES_PATH = Path(__file__).resolve().parent.parent / "data" / "schema_org_entity_types.json"


def _normalize_type_key(value: str) -> str:
    """把型別字串正規化成不分大小寫、不分空白/底線/駝峰的比對 key，
    讓「Local Business」「local_business」「LOCAL_BUSINESS」都能對到同一個候選。"""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


_CORE_TYPE_LOOKUP: dict[str, str] = {_normalize_type_key(key): key for key in ENTITY_TYPES}


@lru_cache(maxsize=1)
def _load_extended_entity_type_lookup() -> dict[str, str]:
    """讀取 data/schema_org_entity_types.json，回傳 {正規化 key: schema.org 官方
    CamelCase id} 供核心庫查不到時查閱。讀取失敗（檔案缺失/格式錯誤）時回傳空
    dict，讓呼叫端安全退回保留原始字串，不影響抽取流程本身。"""
    try:
        with open(_EXTENDED_ENTITY_TYPES_PATH, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {_normalize_type_key(t["label"]): t["id"] for t in payload.get("types", [])}


def resolve_entity_type(raw_type: str) -> str:
    """正規化 LLM 抽取出的 subject_type／object_type：核心庫（52 類）優先比對，
    查不到才查擴充庫（939 類）；可多值（逗號分隔，見 3.1.3 § LLM_SVO 節點），
    逐一正規化後以逗號重組；兩者皆查無對應的 token 保留原始字串——選填、不強制
    驗證，任何一步查無結果都不拋出例外或拒絕整條三元組。"""
    if not raw_type or not raw_type.strip():
        return raw_type

    extended_lookup = _load_extended_entity_type_lookup()
    resolved_tokens = []
    for token in raw_type.split(","):
        token = token.strip()
        if not token:
            continue
        key = _normalize_type_key(token)
        if key in _CORE_TYPE_LOOKUP:
            resolved_tokens.append(_CORE_TYPE_LOOKUP[key])
        elif key in extended_lookup:
            resolved_tokens.append(extended_lookup[key])
        else:
            resolved_tokens.append(token)
    return ",".join(resolved_tokens)


def _svo_prompt(text: str) -> str:
    rel_types = ", ".join(sorted(SVO_REL_TYPES))
    return f"""你是知識圖譜 SVO 抽取器。
請只輸出 JSON，不要輸出解釋。從文本抽取符合受控關係詞彙的三元組。

合法 rel_type：
{rel_types}

實體型別參考清單（非強制，僅供判斷參考）：
{_ENTITY_TYPE_GUIDE}

輸出格式：
{{"triples":[{{"subject":"", "subject_type":"", "rel_type":"RELATED_TO", "verb":"", "object":"", "object_type":"", "confidence":1}}]}}

規則：
1. rel_type 必須完全等於合法清單中的一個值。
2. verb 保留原文中的自然語言關係描述。
3. confidence 使用 1 到 5 的整數。
4. subject_type／object_type 優先從參考清單挑選最貼切的一個；同時符合多個時用逗號分隔（如「PERSON,PRODUCT」）；清單中無合適選項時可自訂名稱，或留空字串代表無法判斷；不強制驗證。
5. 沒有可判定三元組時輸出 {{"triples":[]}}。
6. subject／object 必須是簡潔、可重複使用的名詞或名詞片語（如「勞工」「雇主」「特別休假」「留職停薪」），不可整段抄錄條文子句或完整句子。條件、期限、例外情形等細節應放進 verb 或拆成多筆三元組，不要塞進 subject／object 本身。
7. 一句話常常包含不只一件事實。除了主要動作之外，若句子還提到數量上限、次數限制、期限、或給付／工資狀態等附加規定，這些都要各自拆成獨立的三元組完整抽出，不可以只抽主要動作、把附加規定省略掉——即使某個三元組的 subject 跟其他三元組重複，也要各自輸出。

反例（不要這樣做）：
subject: "適用勞動基準法之外國人於聘僱許可有效期間內，向雇主請求以特別休假以外之假別返國時，應依勞動基準法、性別平等工作法規定及勞動契約之約定辦理。"

正確做法（拆成簡潔實體 + 完整關係描述放 verb）：
{{"subject":"外國人", "verb":"於聘僱許可有效期間內向雇主請求以特別休假以外之假別返國時，應依規定辦理", "object":"勞動基準法及性別平等工作法規定"}}

反例（不要這樣做——只抽了主要動作，漏掉數量上限與給付狀態）：
原文："勞工因有事故必須親自處理，得請事假，一年內合計不得超過十四日。事假期間不給工資。"
只輸出 {{"subject":"勞工", "verb":"因有事故必須親自處理，得請", "object":"事假"}}，漏掉了十四日上限與不給工資這兩件事實。

正確做法（同一句話的每一項附加規定都各自拆成三元組）：
{{"subject":"勞工", "verb":"因有事故必須親自處理，得請", "object":"事假"}}
{{"subject":"事假", "verb":"一年內合計不得超過", "object":"十四日"}}
{{"subject":"事假期間", "verb":"不給", "object":"工資"}}

反例（不要這樣做——數量緊貼在名詞後面時，把數量黏進 object，導致之後查「婚假」查不到天數）：
原文："勞工結婚者給予婚假八日，工資照給。"
只輸出 {{"subject":"勞工", "verb":"結婚者給予", "object":"婚假八日"}}，把「婚假」跟「八日」黏成一個詞塞進 object，天數變成查不到的死資訊。

正確做法（即使數量緊貼在名詞後面、看起來像一個詞，也要拆成獨立三元組，不要黏在一起；subject／verb／object 必須反映這段原文本身的措辭，不可以照抄其他範例的用字）：
{{"subject":"勞工", "verb":"結婚者給予", "object":"婚假"}}
{{"subject":"婚假", "verb":"天數為", "object":"八日"}}
{{"subject":"婚假", "verb":"照給", "object":"工資"}}

8. 若文本是「共同前提＋下列各款列舉項目」的結構（如「……下列各款……均不計入：一、……。二、……。」），每個列舉項目都要各自形成一筆完整的三元組，繼承共同的動詞與另一端實體，不可以 subject 填了、object 卻留空（或反過來）。

反例（不要這樣做——列舉項目的 object 留空，資訊不完整）：
原文："依本法第二條第四款計算平均工資時，下列各款期日或期間均不計入：一、發生計算事由之當日。二、因職業災害尚在醫療中者。五、依勞工請假規則請普通傷病假者。"
只輸出 {{"subject":"依勞工請假規則請普通傷病假者", "verb":"", "object":""}}，object 是空的，這筆三元組沒有意義。

正確做法（每個列舉項目都繼承共同的動詞與對象，各自形成完整三元組）：
{{"subject":"發生計算事由之當日", "verb":"不計入", "object":"平均工資計算期間"}}
{{"subject":"因職業災害尚在醫療中者", "verb":"不計入", "object":"平均工資計算期間"}}
{{"subject":"依勞工請假規則請普通傷病假者", "verb":"不計入", "object":"平均工資計算期間"}}
（其餘列舉項目依此類推，每一項都各自產生一筆完整三元組，不留空欄位）

9. 若文本是「分類列舉」結構（如「……分下列N種：一、……。二、……。」），每個列舉項目是類別名稱本身，不是條件——不要照抄前提句的動詞，應推論「屬於」關係，object 用前提句主詞改寫成的類別名稱。

反例（不要這樣做——分類列舉全部留空，因為前提句本身沒有可直接借用的動詞受詞）：
原文："本保險之給付，分下列五種：一、失業給付。二、提早就業獎助津貼。三、職業訓練生活津貼。四、育嬰留職停薪津貼。五、失業之被保險人及隨同被保險人辦理加保之眷屬全民健康保險保險費補助。"
只輸出 {{"subject":"失業給付", "verb":"", "object":""}} 這類全空的三元組。

正確做法（每個類別項目都用「屬於」連到推論出的類別名稱）：
{{"subject":"失業給付", "verb":"屬於", "object":"本保險之給付種類"}}
{{"subject":"提早就業獎助津貼", "verb":"屬於", "object":"本保險之給付種類"}}
{{"subject":"職業訓練生活津貼", "verb":"屬於", "object":"本保險之給付種類"}}
{{"subject":"育嬰留職停薪津貼", "verb":"屬於", "object":"本保險之給付種類"}}
（其餘列舉項目依此類推，每一項都各自產生一筆完整三元組，不留空欄位）

文本：
{text}
"""


# SIM 節點的型別描述句 embedding 快取——依 embedding_provider.model_name 為 key，
# 35 個型別的描述句 embedding 在同一個 provider/model 底下固定不變，避免每次
# extract_svo_triples() 呼叫都重新對全部 35 筆描述句呼叫一次 embedding provider。
_TYPE_DESCRIPTION_EMBEDDING_CACHE: dict[str, dict[str, list[float]]] = {}


async def _type_description_embeddings(embedding_provider: EmbeddingProvider) -> dict[str, list[float]]:
    cache = _TYPE_DESCRIPTION_EMBEDDING_CACHE.get(embedding_provider.model_name)
    if cache is None:
        rel_types = sorted(SVO_REL_TYPE_DESCRIPTIONS)
        vectors = await embedding_provider.encode_batch([SVO_REL_TYPE_DESCRIPTIONS[t] for t in rel_types])
        cache = dict(zip(rel_types, vectors))
        _TYPE_DESCRIPTION_EMBEDDING_CACHE[embedding_provider.model_name] = cache
    return cache


async def classify_relation_by_embedding(
    verb: str, embedding_provider: EmbeddingProvider
) -> tuple[str, float]:
    """SIM：`verb` embedding 與 35 個關係型別**描述句**（非識別碼字串本身，見
    `SVO_REL_TYPE_DESCRIPTIONS` docstring）embedding 算 cosine 相似度，取最相似者。
    回傳 (最相似的型別, 該型別的相似度分數)。"""
    type_vectors = await _type_description_embeddings(embedding_provider)
    verb_vec = await embedding_provider.encode(verb)
    best_type = ""
    best_score = -1.0
    for rel_type, vec in type_vectors.items():
        score = cosine_similarity(verb_vec, vec)
        if score > best_score:
            best_score = score
            best_type = rel_type
    return best_type, best_score


async def resolve_query_relation_type(
    verb_phrase: str,
    embedding_provider: EmbeddingProvider,
    *,
    llm_provider: LLMProvider | None = None,
) -> str | None:
    """§ 3.2 §c `QSIM`／`QESCALATE`／`QNOMATCH`（2026-08-18 定案）：把查詢端的
    動詞措辭解析為對應的 canonical 關係型別，供呼叫端對 `bfs_query()` 的結果
    做後篩選（§ 3.2 §c `QFILTER`，本函式不做篩選，只負責解析型別）。

    重用 3.1.3 `classify_relation_by_embedding()`（`SIM`）——與 35 個型別描述句
    的 embedding 比對，同一顆 cache 之後不必重算。三區判斷（與 `COMPARE`／
    `ESCALATE3` 的二元一致性檢查不同，見設計文件同名段落誠實訂正）：

    - 最高分 ≥ `QSIM_ASSIGN_THRESHOLD`：直接採用該型別。
    - 最高分介於 `QSIM_ESCALATE_LOW_THRESHOLD` 與 `QSIM_ASSIGN_THRESHOLD` 之間
      （灰色地帶）：`llm_provider` 提供時交由 LLM 仲裁「此查詢措辭是否對應
      候選型別」；未提供 `llm_provider` 時視為無法確認，直接回傳 `None`。
    - 最高分 ＜ `QSIM_ESCALATE_LOW_THRESHOLD`：直接判定為無 match，不浪費一次
      LLM 呼叫。

    `QNOMATCH`（回傳 `None`）由呼叫端決定後續處理——設計定案為退回不篩選，
    本函式本身不內建這個退回邏輯，只負責解析。
    """
    best_type, best_score = await classify_relation_by_embedding(verb_phrase, embedding_provider)

    if best_score >= QSIM_ASSIGN_THRESHOLD:
        return best_type

    if best_score < QSIM_ESCALATE_LOW_THRESHOLD or llm_provider is None:
        return None

    prompt = (
        f"使用者查詢中的措辭「{verb_phrase}」，是否對應關係類型「{best_type}」"
        f"（{SVO_REL_TYPE_DESCRIPTIONS[best_type]}）？只回答「是」或「否」，不要有其他文字。"
    )
    answer = (await llm_provider.generate(prompt)).strip()
    return best_type if answer.startswith("是") else None


async def _reconcile_rel_type(
    verb: str,
    llm_rel_type: str,
    *,
    embedding_provider: EmbeddingProvider | None,
    llm_provider: LLMProvider | None,
    kg_id: str | None = None,
    calibration_db_path: Path | None = None,
) -> str:
    """COMPARE＋ESCALATE3：`SIM` 判斷是否與 LLM 自報的 rel_type 一致，見
    docs/論文/03_系統設計與方法論.md § 3.1.3 主圖。

    無 `embedding_provider` 時直接採信 LLM 自報值，不強行比對。`COMPARE` 一致
    （embedding 最相似型別＝LLM 自報值，且分數 ≥ `COMPARE_COSINE_THRESHOLD`）時，
    兩個獨立訊號互相驗證，直接採用 LLM 自報值；不一致（含分數不足門檻，視為
    embedding 對所有型別都不夠相似）時，交由 `ESCALATE3` 第二次 LLM 呼叫仲裁
    「究竟是原答案、embedding 建議的候選，還是兩者皆非」。**兩者皆非**（判定為
    候選新類別）先退回 `RELATED_TO` 兜底（三元組本身不因型別未定案而遺失），
    `kg_id`／`calibration_db_path` 皆提供時同步把該動詞記入 `EXPAND` 候選池
    （`expand_governance_service.add_candidate()`），供治理 Worker
    （`services/expand_worker.py::run_governance_cycle()`，P2-1，2026-07-27
    實作）判斷是否構成新關係類型。

    **`SIM` 學習/校正機制（2026-07-27 新增，見設計文件同名段落）**：`kg_id`
    與 `calibration_db_path` 皆提供時，每次真正觸發 `ESCALATE3`（COMPARE 不
    一致）就記錄一筆仲裁事件（`sim_calibration_service.log_escalation()`），
    供未來逐型別計算 `SIM` 建議與最終判定的一致率，校正對 `SIM` 的信任度。
    只記錄真正升級仲裁的事件——`COMPARE` 一致、未觸發 `ESCALATE3` 的情況
    沒有「最終仲裁結果」可比對，不需要記錄。任一參數缺席時完全跳過記錄，
    行為與先前版本一致（向後相容）。
    """
    if embedding_provider is None:
        return llm_rel_type

    best_type, best_score = await classify_relation_by_embedding(verb, embedding_provider)
    if best_type == llm_rel_type and best_score >= COMPARE_COSINE_THRESHOLD:
        return llm_rel_type

    if llm_provider is None:
        return llm_rel_type

    prompt = (
        f"動詞片語「{verb}」在知識圖譜三元組中最貼切的關係型別，"
        f"應該是「{llm_rel_type}」還是「{best_type}」？"
        "若兩者皆不貼切，回答「皆非」。只回答其中一個型別名稱或「皆非」，不要有其他文字。"
    )
    answer = (await llm_provider.generate(prompt)).strip()
    if answer == best_type:
        final = best_type
    elif answer == llm_rel_type:
        final = llm_rel_type
    else:
        # ESCALATE3 判定兩者皆非（候選新類別）：比照 REJECT 兜底邏輯先退回
        # RELATED_TO，三元組本身仍保留、不靜默丟棄；同步記入 EXPAND 候選池，
        # 供治理 Worker 之後判斷是否真的構成新類別。
        final = "RELATED_TO"
        if kg_id is not None and calibration_db_path is not None:
            expand_governance_service.add_candidate(
                calibration_db_path, kg_id, verb, await embedding_provider.encode(verb),
            )

    if kg_id is not None and calibration_db_path is not None:
        sim_calibration_service.log_escalation(
            calibration_db_path, kg_id, llm_rel_type, best_type, best_score, final,
        )
    return final


async def extract_svo_triples(
    text: str,
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    *,
    kg_id: str | None = None,
    calibration_db_path: Path | None = None,
) -> list[SVOTriple]:
    """用 LLM 抽取受控關係 SVO triples。

    未提供 provider 時回傳空清單，讓離線管線與單元測試可以安全呼叫；實際抽取
    Worker 應明確傳入本地或雲端 LLMProvider。`embedding_provider` 為選填——
    提供時才會執行 `SIM`／`COMPARE`／`ESCALATE3` 事後驗證（見 `_reconcile_rel_type`），
    未提供時直接採用 LLM 自報的 rel_type，行為與先前版本一致。`kg_id`／
    `calibration_db_path` 皆提供時，`ESCALATE3` 觸發的仲裁事件會記錄進
    `SIM` 學習/校正機制的持久化層（見 `_reconcile_rel_type` docstring），
    皆為選填、預設不記錄，向後相容。
    """
    if not text.strip() or llm_provider is None:
        return []

    raw = await llm_provider.generate_json(_svo_prompt(text))
    triples: list[SVOTriple] = []
    for item in _parse_triples_payload(raw):
        rel_type = str(item.get("rel_type", "RELATED_TO")).strip()
        # 3.1.3 REJECT：不在受控詞彙表內的 rel_type 退回 RELATED_TO 兜底，
        # 三元組本身保留（不可靜默丟棄整條事實），原始語意仍留在 verb 欄位。
        rel_type = rel_type if rel_type in SVO_REL_TYPES else "RELATED_TO"
        verb = str(item.get("verb", "")).strip()
        if verb and embedding_provider is not None:
            rel_type = await _reconcile_rel_type(
                verb,
                rel_type,
                embedding_provider=embedding_provider,
                llm_provider=llm_provider,
                kg_id=kg_id,
                calibration_db_path=calibration_db_path,
            )
        item["rel_type"] = rel_type
        # 3.1.3 §a-1 BACKFILL：僅 RELATED_TO 兜底的三元組才需要保留 verb embedding，
        # 供 EXPAND 核准新型別後的回溯重分類向量索引查詢使用；已有明確型別的
        # 三元組不需要，省下多餘的儲存。
        if rel_type == "RELATED_TO" and verb and embedding_provider is not None:
            item["verb_embedding"] = await embedding_provider.encode(verb)
        # 核心庫優先、查不到才查擴充庫的正規化——見 resolve_entity_type() docstring。
        if item.get("subject_type"):
            item["subject_type"] = resolve_entity_type(str(item["subject_type"]))
        if item.get("object_type"):
            item["object_type"] = resolve_entity_type(str(item["object_type"]))
        try:
            triples.append(SVOTriple(**item))
        except Exception:
            continue
    return triples


_SAFE_REL_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _relationship_type(rel_type: str) -> str:
    """把 `rel_type` 準備成可安全內插進 Cypher 查詢的關係型別字面值。

    Neo4j 關係型別無法參數化（只能字面內插），這裡是唯一的注入防線。允許
    靜態受控詞彙表 `SVO_REL_TYPES` 內的值，也允許格式合法（大寫字母／數字／
    底線）但不在表內的值——後者對應 3.1.3 §a `EXPAND` 治理機制動態核准的新
    型別（`services/expand_worker.py`，P2-1，2026-07-27 實作）：其語意合法性
    已由 `LLMJUDGE`／`GATE`／`HUMANCHECK` 流程把關，這裡只再做一層格式層級
    的注入防護，不重複語意判斷。一般抽取路徑（`extract_svo_triples()` 的
    `REJECT` 邏輯）本來就只會產生 `SVO_REL_TYPES` 內的值，這裡放寬的格式
    分支只有 `backfill_related_to_edges()` 的動態新型別會實際用到。
    """
    if rel_type not in SVO_REL_TYPES and not _SAFE_REL_TYPE_PATTERN.match(rel_type):
        raise ValueError(f"不合法的 SVO rel_type: {rel_type}")
    return f"`{rel_type}`"


# ── 實體對齊/去重（3.1.4 DEDUP4／3.4 §b ESCALATE＋RECHECK，2026-07-21 新增；
#    2026-07-21 再修訂：改用 (Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)
#    邊聚合頻率，取代原本存在 Entity 節點上的 alias_counts_json，與
#    docs/論文/03_系統設計與方法論.md § 3.4 §b 的文字描述（含 RECORD3B／
#    RECHECK 的 Cypher 範例）保持一致，不再是兩套不同的資料模型）─────────────

def _type_set(type_str: str | None) -> set[str]:
    """把型別欄位拆成集合——型別選填、可多值（逗號分隔），見 3.1.4。"""
    if not type_str:
        return set()
    return {t.strip() for t in type_str.split(",") if t.strip()}


async def _fetch_entity_candidates(
    driver: AsyncDriver, kg_id: UUID, entity_type: str, name: str | None = None
) -> list[dict]:
    """查詢同 KG 的既有 Entity 節點，依型別集合交集篩選（名稱＋已持久化的
    `name_embedding`，供編輯距離/cosine 比對）。

    對應 3.4 §b `DEDUP3`：型別集合有交集，或查詢/既有節點任一方型別缺席，
    皆視為候選（不強行排除）；只有雙方都有型別、且集合無交集時才排除——
    型別選填/可多值的定案下，完全相等篩選會誤刪本該比對的候選（見 3.1.4）。

    一併撈出 `name_embedding`（2026-08-03 新增，見 3.1.4 `DEDUP4` 節點向量化
    效能改造）：舊資料尚未回填時此欄位為 `None`，`resolve_entity_name()` 會
    針對缺漏者 fallback 即時 `encode()`，新舊資料混存不影響正確性。

    ⚠️ **2026-08-30 修正（真實抽取發現的真實 bug）**：`name` 參數提供時，
    只要 `e.name` 與其**精確字串相符**，無論型別是否有交集都一律納入候選。
    真實案例：「中央主管機關」同一實體，不同次抽取判斷出的型別不一致
    （有時是 `ORGANIZATION`，有時 LLM 沒給明確型別、落到通用的「概念」），
    型別交集篩選把兩者當成互不相干的候選——導致 `resolve_entity_name()`
    的精確相符短路完全看不到既有的正確節點，退化成用編輯距離/cosine比對
    到錯誤的候選（例如比對到「中央主管機關備查」），後續跨文件標準名提升
    邏輯再把這個錯誤候選改名成正確名稱時，撞上本來就叫這個名稱的既有
    節點，觸發 `ConstraintError`（見 `merge_entity()` 該段落與
    `docs/論文/03_變更紀錄.md` 對應條目）。
    """
    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id}) RETURN e.name AS name, e.type AS type, e.name_embedding AS name_embedding",
        kg_id=str(kg_id),
    )
    query_types = _type_set(entity_type)
    if not query_types:
        return [{"name": r["name"], "name_embedding": r.get("name_embedding")} for r in result.records]
    return [
        {"name": r["name"], "name_embedding": r.get("name_embedding")}
        for r in result.records
        if r["name"] == name or not _type_set(r["type"]) or query_types & _type_set(r["type"])
    ]


def _edit_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


async def resolve_entity_name(
    name: str,
    candidates: list[dict],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> str:
    """DEDUP4＋ESCALATE：決定這次提及該歸屬到哪個既有 Entity 名稱。

    依序：① 與既有名稱編輯距離高度相似（如「台積電」對「台積電公司」）直接
    視為同一實體；② 無命中則做 cosine 相似度比對（需 `embedding_provider`，
    未提供時視為新實體，不強行比對）；③ cosine 落在 ESCALATE 灰色地帶
    （既有門檻與更低下限之間）時，若有 `llm_provider` 則呼叫 LLM 仲裁；
    皆未命中則回傳原名，代表應建立新節點。門檻定義見 core/constants.py。

    **2026-08-03 效能改造（見 3.1.4 `DEDUP4` 節點向量化定案）**：候選若已在
    `_fetch_entity_candidates()` 帶回持久化的 `name_embedding`，直接沿用，
    不重新呼叫 `embedding_provider.encode()`；只有尚未回填的舊候選才
    fallback 即時編碼——比對邏輯與門檻本身不變，純粹省去重複編碼成本。
    """
    if not candidates:
        return name

    # 2026-08-19（真實審查發現並修復）：`_fetch_entity_candidates()` 的 Cypher
    # 查詢沒有 ORDER BY，Neo4j 回傳順序非決定性——若多個候選同時超過編輯距離
    # 門檻，原本「回傳第一個超過門檻的候選」在不同次執行間可能選到不同名稱，
    # 導致同一批資料的實體合併結果不可重現，與下方 cosine 相似度區塊、以及
    # 本專案其他地方（如 UMAP 固定 random_state=42）一貫的可重現性要求不一致。
    # 改為與 cosine 區塊同樣的寫法：走訪所有候選，取分數最高者，同分時保留
    # 先遇到的（Python min/max 對等值採穩定的「保留第一個」語意，但候選順序
    # 本身仍非決定性——此修復只保證「選到分數最高者」，不保證同分平局時的
    # 決定性，該情況本身即代表兩個候選對這次提及同樣合適，不影響合併正確性）。
    best_edit_name: str | None = None
    best_edit_ratio = 0.0
    for c in candidates:
        if c["name"] == name:
            return name
        ratio = _edit_ratio(name, c["name"])
        if ratio >= ENTITY_DEDUP_EDIT_RATIO_THRESHOLD and ratio > best_edit_ratio:
            best_edit_ratio = ratio
            best_edit_name = c["name"]
    if best_edit_name is not None:
        return best_edit_name

    if embedding_provider is None:
        return name

    name_vec = await embedding_provider.encode(name)
    best_name: str | None = None
    best_score = 0.0
    for c in candidates:
        candidate_vec = c.get("name_embedding") or (await embedding_provider.encode(c["name"]))
        score = cosine_similarity(name_vec, candidate_vec)
        if score > best_score:
            best_score = score
            best_name = c["name"]

    if best_name is None:
        return name
    if best_score >= ENTITY_DEDUP_COSINE_THRESHOLD:
        return best_name

    if llm_provider is not None and best_score >= ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD:
        prompt = (
            f"「{name}」與「{best_name}」是否為同一個真實世界的實體/對象？"
            "只回答「是」或「否」，不要有其他文字。"
        )
        answer = (await llm_provider.generate(prompt)).strip()
        if answer.startswith("是"):
            return best_name

    return name


async def _execute_with_constraint_retry(
    driver: AsyncDriver, query: str, *, max_attempts: int = 3, retry_delay_seconds: float = 0.2, **params
):
    """執行含 `MERGE (e:Entity {kg_id, name})` 的查詢，撞上 `entity_kg_name_unique`
    唯一約束（見 `create_entity_index()`）時重試（2026-08-30 新增，真實抽取
    發現）。

    **背景**：`MERGE` 搭配唯一約束理論上是原子的，但這是 Neo4j 官方文件本身
    記載的已知模式——即使呼叫端是循序執行（本專案的抽取 Worker 對每個
    chunk、每筆 triple 皆為循序 `await`，無內部併發），仍可能在極端時機下讓
    「嘗試建立同一個新節點」的操作撞上約束，拋出 `ConstraintError`。
    2026-08-27 新增唯一約束前，這種情況是**靜默產生重複節點**（已修正的
    真實 bug，見 `docs/論文/03_變更紀錄.md` 該則）；加了約束後變成**直接
    拋出例外、讓整個 chunk 抽取判定失敗**——真實跑一輪長時間抽取後發現，
    這個新副作用本身也需要處理，否則失敗率會被這個假陽性拉高。

    ⚠️ **誠實侷限（2026-08-30 補充查證）**：第一版只重試一次，真實觀測發現
    仍有少量案例連重試都撞同一個約束（例如「中央主管機關」這種極高頻的
    跨文件實體）——手動用相同查詢＋已知已存在的節點單獨重現，MERGE 都能
    正常命中既有節點、不會拋出例外，代表問題只在真實 pipeline 的實際執行
    節奏下才會出現，確切機制未查明（已排除：並發 session、多個 drain 程序
    同時寫入）。這次改成最多 3 次嘗試、每次重試前短暫等待
    （`retry_delay_seconds`，預設 0.2 秒），降低發生率但不保證完全消除；
    仍會撞上的極少數 chunk，依既有做法定期把 `failed` 狀態重置回 `pending`
    重跑即可（`task_queue` 本身就是為了容忍這類可重試失敗而設計）。
    """
    last_error: ConstraintError | None = None
    for attempt in range(max_attempts):
        try:
            return await driver.execute_query(query, **params)
        except ConstraintError as e:
            last_error = e
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay_seconds)
    raise last_error


async def _merge_chunk_mention(
    driver: AsyncDriver,
    kg_id: UUID,
    entity_name: str,
    entity_type: str,
    surface_form: str,
    source_doc_id: UUID | None,
    source_svo_chunk_index: int | None,
    source_svo_chunk_file: str | None,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> None:
    """RECORD3B：建立/合併 `(Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)` 邊。

    Chunk 節點以 `(kg_id, source_doc_id, chunk_index)` 為識別鍵；`surface_form`
    是 `HAS_ENTITY` 邊 MERGE 樣式的一部分，同一 chunk 內重複提及同一別名不會
    產生多筆邊，跨 chunk 才會累積出不同的邊，供 `_aggregate_alias_counts()`
    做跨文件頻率聚合（3.4 §b RECHECK 的資料來源）。

    **2026-08-03 新增（見 3.1.4 `DEDUP4` 節點向量化定案）**：`embedding_provider`
    提供時，新建（`ON CREATE`）的 Entity 節點順便存 `name_embedding`，供未來
    `resolve_entity_name()` 比對時直接沿用、不必重新編碼；既有節點（已存在，
    只是 `MERGE` 命中）不會被覆寫。`embedding_provider` 未提供時維持原行為
    （不寫入該屬性，行為與改造前完全一致）。
    """
    entity_set_clause = "e.type = $entity_type"
    params = {
        "kg_id": str(kg_id),
        "source_doc_id": str(source_doc_id),
        "chunk_index": source_svo_chunk_index,
        "chunk_file": source_svo_chunk_file,
        "entity_name": entity_name,
        "entity_type": entity_type,
        "surface_form": surface_form,
    }
    if embedding_provider is not None:
        entity_set_clause += ", e.name_embedding = $name_embedding"
        params["name_embedding"] = await embedding_provider.encode(entity_name)

    await _execute_with_constraint_retry(
        driver,
        f"""
        MERGE (c:Chunk {{kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: $chunk_index}})
        ON CREATE SET c.chunk_file = $chunk_file
        MERGE (e:Entity {{kg_id: $kg_id, name: $entity_name}})
        ON CREATE SET {entity_set_clause}
        MERGE (c)-[r:HAS_ENTITY {{surface_form: $surface_form}}]->(e)
        """,
        **params,
    )


async def _aggregate_alias_counts(driver: AsyncDriver, kg_id: UUID, entity_name: str) -> dict[str, int]:
    """依 3.4 §b 文字描述的 Cypher 範例，聚合該實體所有 `HAS_ENTITY` 邊的
    `surface_form` 出現次數。

    **2026-07-21 修訂（使用者提出）**：計數單位是**獨立文件數**
    （`count(DISTINCT c.source_doc_id)`），不是邊的總數（`count(*)`）——
    §a 已把單一文件內的所有變體收斂成一個「文件內暫定標準名」，若按邊數
    計（每個 chunk 各算一次），單一文件只要 chunk 數量多，就會讓它選中的
    別名在跨文件頻率上被灌票，不代表真正有更多文件認同這個稱呼。改成數
    獨立文件數，才是「一份文件一票」的跨文件共識，對應 Wikidata／CESI
    文獻描述的頻率概念（見模組層級 docstring）。
    """
    result = await driver.execute_query(
        """
        MATCH (c:Chunk {kg_id: $kg_id})-[r:HAS_ENTITY]->(e:Entity {kg_id: $kg_id, name: $entity_name})
        RETURN r.surface_form AS alias, count(DISTINCT c.source_doc_id) AS freq
        """,
        kg_id=str(kg_id), entity_name=entity_name,
    )
    return {record["alias"]: record["freq"] for record in result.records}


async def merge_entity(
    driver: AsyncDriver,
    kg_id: UUID,
    name: str,
    entity_type: str,
    surface_form: str,
    *,
    source_doc_id: UUID | None = None,
    source_svo_chunk_index: int | None = None,
    source_svo_chunk_file: str | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> str:
    """解析並合併一個實體節點，回傳這次寫入後的最終 Entity.name。

    對應 3.1.4 DEDUP4／3.4 §b ESCALATE＋RECORD3B＋RECHECK：先決定這次提及該
    歸屬到哪個既有實體（`resolve_entity_name`，或視為新實體），記錄
    `(Chunk)-[:HAS_ENTITY {surface_form}]->(Entity)` 邊，再依跨文件累積的
    `surface_form` 頻率（`_aggregate_alias_counts`，以獨立文件數計，見該函式
    docstring）決定是否需要把 `Entity.name` 更新為更常見的別名——**主規則與
    3.4 §a 文件內『暫定標準名』不同**（2026-07-21 使用者提出修訂）：§a
    （`entity_registry_service.should_promote_by_length`）以長度優先為主規則，
    這裡（`should_promote_by_frequency`）以跨文件頻率優先為主規則，兩者衡量
    範圍不同、權威層級也不同（§a 僅供文件內部處理參考，這裡才是寫入圖譜的
    權威判斷）；頻率優先規則的文獻依據（Wikidata／CESI）本來就是跨文件/跨
    編者尺度的概念，套用在這一層（§b）比先前套用在單一文件內（§a）更貼切。

    `source_doc_id`／`source_svo_chunk_index` 缺席時（例如呼叫端尚未提供
    chunk 追溯資訊），跳過 `HAS_ENTITY` 邊建立與頻率提升判斷，只單純
    MERGE 實體節點——此時無法判斷是否要提升標準名，保留現狀最保守。

    ⚠️ **效能待決策**：`_fetch_entity_candidates`／`_aggregate_alias_counts`
    對每次呼叫都重新查詢，Hub 型 KG 規模變大後可能有效能疑慮，留待第四章
    實作與第五章消融實驗評估，非本設計階段的阻斷性問題（比照 3.1.1 §a
    未分配池 O(n²) 的既有處理方式）。
    """
    candidates = await _fetch_entity_candidates(driver, kg_id, entity_type, name)
    resolved_name = await resolve_entity_name(
        name, candidates, embedding_provider=embedding_provider, llm_provider=llm_provider
    )

    if source_doc_id is None or source_svo_chunk_index is None:
        entity_set_clause = "e.type = $entity_type"
        params = {"kg_id": str(kg_id), "name": resolved_name, "entity_type": entity_type}
        if embedding_provider is not None:
            entity_set_clause += ", e.name_embedding = $name_embedding"
            params["name_embedding"] = await embedding_provider.encode(resolved_name)
        await _execute_with_constraint_retry(
            driver,
            f"MERGE (e:Entity {{kg_id: $kg_id, name: $name}}) ON CREATE SET {entity_set_clause}",
            **params,
        )
        return resolved_name

    await _merge_chunk_mention(
        driver, kg_id, resolved_name, entity_type, surface_form,
        source_doc_id, source_svo_chunk_index, source_svo_chunk_file,
        embedding_provider=embedding_provider,
    )
    alias_counts = await _aggregate_alias_counts(driver, kg_id, resolved_name)

    final_name = resolved_name
    current_count = alias_counts.get(resolved_name, 0)
    candidate_count = alias_counts.get(surface_form, 0)
    if surface_form != resolved_name and should_promote_by_frequency(
        candidate_count, current_count, surface_form, resolved_name
    ):
        final_name = surface_form  # RECHECK/UPDATENAME：標準名隨語料持續擴增而更新

    # 2026-08-30 修正：改名（promote 到更常見的別名）理論上很安全——
    # `final_name` 通常是本來就沒有對應節點的新別名。但真實抽取發現一個
    # 殘留情境（見 `_fetch_entity_candidates()` docstring 的根因說明修正
    # 前）：`final_name` 可能已經是另一個既有節點的名稱，此時這條
    # `SET e.name = $final_name` 會撞上唯一約束。這不是可以重試解決的
    # 競態（是決定性的名稱衝突），改名的資訊本身也不是不可或缺——保留
    # 現有 `resolved_name` 不改名，仍是正確、不遺失資料的節點，只是這次
    # 沒有跟著提升成更常見的別名而已。因此遇到衝突時記錄但不讓整個 chunk
    # 抽取失敗。
    try:
        await driver.execute_query(
            "MATCH (e:Entity {kg_id: $kg_id, name: $resolved_name}) SET e.name = $final_name, e.aliases = $aliases",
            kg_id=str(kg_id),
            resolved_name=resolved_name,
            final_name=final_name,
            aliases=list(alias_counts.keys()),
        )
    except ConstraintError:
        return resolved_name
    return final_name


async def backfill_entity_name_embeddings(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    *,
    limit: int = 1000,
) -> int:
    """3.1.4 `DEDUP4` 節點向量化效能改造：補齊缺漏 `name_embedding` 的既有
    `Entity` 節點——把節點上已有的 `name` 文字算成 embedding 存回去，讓這些
    節點在 `resolve_entity_name()` 比對時能直接沿用持久化向量，不必再
    fallback 即時 `encode()`。**不做任何去重判斷**，純粹補向量，因此不需要
    `BACKFILL`（3.1.3 §a-1）那種 LLM 確認關卡——沒有判斷就沒有判斷錯誤的
    風險，跟該函式是不同層級的操作，比照同一套設計精神。

    涵蓋兩種成因（比照 `backfill_missing_verb_embeddings()` 同一套「歷史缺口
    ＋持續產生的新缺口」推理）：① 此改造上線前既有的歷史節點；② 任何一次
    `merge_entity()`／`_merge_chunk_mention()` 呼叫沒帶入 `embedding_provider`
    時持續產生的新缺口——成因 ② 會反覆發生，不是一次性事件。因此本函式
    設計為**冪等、可重複執行**，可排進治理 Worker 既有的定期巡視週期，不需
    另開一套維運流程。

    `limit`（預設 1000）批次大小比 `backfill_missing_verb_embeddings()`（100）
    大，因為單筆 `Entity.name` 通常遠短於 `RELATED_TO` 邊累積的完整
    `citations_json`，單次呼叫成本較低。回傳實際補上 `name_embedding` 的
    節點數。
    """
    result = await driver.execute_query(
        """
        MATCH (e:Entity {kg_id: $kg_id})
        WHERE e.name_embedding IS NULL AND e.name IS NOT NULL
        RETURN e.name AS name
        LIMIT $limit
        """,
        kg_id=str(kg_id),
        limit=limit,
    )

    kg_id_str = str(kg_id)
    count = 0
    for record in result.records:
        # 2026-08-04：embedding_provider.encode() 已改為真正的 async（見
        # core/providers/base.py EmbeddingProvider docstring），await 本身
        # 就會在底層 I/O／執行緒池等待期間正常讓出 event loop，不再需要
        # 額外插入 asyncio.sleep(0) 手動讓出（原本用於緩解同步阻塞呼叫佔滿
        # event loop 導致 extraction_worker 無法排程的問題，見 EXTRACTION_LOG.md）。
        name_embedding = await embedding_provider.encode(record["name"])
        await driver.execute_query(
            "MATCH (e:Entity {kg_id: $kg_id, name: $name}) SET e.name_embedding = $name_embedding",
            kg_id=kg_id_str,
            name=record["name"],
            name_embedding=name_embedding,
        )
        count += 1
    return count


def _new_citation(triple: SVOTriple) -> dict:
    """把一次抽取的來源追溯資訊，包成一筆可累積在邊上的引用紀錄。"""
    return {
        "source_doc_id": str(triple.source_doc_id) if triple.source_doc_id else None,
        # 2026-08-19：冗餘存下原始文件名稱字串，見 SVOTriple.source 欄位
        # docstring——即使查詢端手上只有這筆 citation、沒有另外查資料庫，
        # 也能直接回溯到 workspace/<kg_id>/<source>/ 找到原文。
        "source": triple.source,
        "source_svo_chunk_index": triple.source_svo_chunk_index,
        "source_svo_chunk_file": triple.source_svo_chunk_file,
        "source_sentence_start": triple.source_sentence_start,
        "source_sentence_end": triple.source_sentence_end,
        "verb": triple.verb,
        "confidence": triple.confidence,
        # 2026-08-24：見 SVOTriple.source_article_no docstring；一般文件恆為
        # None，供 backfill_fact_nodes() 回填時同樣能正確指向 LawArticle。
        "article_no": triple.source_article_no,
    }


def _verbalize_fact(subject: str, subject_type: str, verb: str, object_: str, object_type: str) -> str:
    """3.1.4 §a `VERBALIZE`：三元組文字化（linear verbalization），比照 KAPING
    （Baek et al., 2023）triple-to-text 模式——subject（＋型別）＋原始 verb＋
    object（＋型別）直接串接，不引入額外的 graph-to-text 轉換模型（KAPING
    Appendix B.5 消融實驗顯示簡單串接檢索表現優於訓練過的轉換模型，見
    docs/參考文獻/12_三元組事實層級向量化與檢索/README.md）。

    `subject`／`object` 使用 DEDUP4 解析後的**canonical Entity 名稱**（而非
    這次提及的原始字串），`verb` 則保留這筆 citation 的原始措辭——兩者取捨
    不同：canonical 名稱讓 `(Fact)-[:HAS_SUBJECT]->(Entity)` 連結與 `fact_text`
    描述的對象一致，`verb` 沒有對應的「解析後版本」（動詞只被歸類到
    `rel_type`，不像實體有 canonical 名稱可用），保留原始措辭才能反映這筆
    citation 的實際語意細節。`subject_type`／`object_type` 缺席時（型別選填）
    省略括號，不留空括號。
    """
    subj = f"{subject}（{subject_type}）" if subject_type else subject
    obj = f"{object_}（{object_type}）" if object_type else object_
    return f"{subj} {verb} {obj}"


def _kg_fact_label(kg_id: str) -> str:
    """每個 KG 各自一個 Fact 節點標籤（`Fact_<kg_id 底線化>`），供 per-KG
    向量索引使用——2026-08-19 真實資料庫實測確認（`docker exec` 對 5.26.27
    Enterprise 連續建立兩個同名 `(label, property)` 但不同索引名稱的向量索引，
    第二次 `IF NOT EXISTS` 靜默略過，`SHOW INDEXES` 確認實際只建立了一個），
    Neo4j 同一個 `(label, property)` 組合僅能有一個向量索引，無法只靠「不同
    索引名稱」切出多個獨立索引；要讓每個 KG 的 `Fact` 向量檢索範圍互相隔離，
    必須是不同的 label。節點仍同時保留通用 `:Fact` label（多重 label，
    `backfill_fact_nodes()` 的 `EXIST5` 存在性查詢等既有 `MATCH (f:Fact {...})`
    不需改動即可繼續運作）。`uuid.UUID()` 往返驗證輸入格式合法，避免非 UUID
    字串被直接字串插入 Cypher label（目前呼叫端皆為內部已驗證過的 kg_id，
    此為額外防禦層）。"""
    return f"Fact_{str(UUID(kg_id)).replace('-', '_')}"


def _fact_vector_index_name(kg_id: str) -> str:
    return f"fact_embedding_vector_{str(UUID(kg_id)).replace('-', '_')}"


async def _create_fact_node(
    driver: AsyncDriver,
    kg_id_str: str,
    *,
    subject: str,
    object_: str,
    rel_type: str,
    source_doc_id: str,
    chunk_index: int,
    fact_text: str,
    fact_embedding: list[float],
    verb: str,
    confidence: float,
    article_no: str | None = None,
) -> bool:
    """3.1.4 §a／§b 共用：建立一個 Fact 節點並連結 `HAS_SUBJECT`／`HAS_OBJECT`／
    `SUPPORTED_BY`。即時路徑（`merge_triples_to_graph`）與回填路徑
    （`backfill_fact_nodes`）共用同一段 Cypher，避免兩邊 schema 各自漂移。

    `subject`／`object`／`rel_type` 三個屬性同時存成 Fact 節點自身的扁平屬性
    （denormalized，而非只靠 `HAS_SUBJECT`／`HAS_OBJECT` 邊間接推得）——這是
    §b 回填批次任務能做到文件描述的冪等比對鍵（`source_doc_id`＋
    `source_svo_chunk_index`＋`subject`＋`rel_type`＋`object`）的前提，也讓
    `vector_search_facts()` 不必額外 traversal 就能回傳完整三元組（2026-08-18
    追加，原始即時路徑上線時漏了這三個屬性，只在 Cypher 查詢參數裡用來
    MATCH，未真正寫進節點）。

    `MATCH (s)/(o)/(c)` 任一方不存在時（例如 Chunk 尚未向量化，見既有誠實
    侷限段落）整條鏈不會建立任何節點；回傳值依 `RETURN f` 是否有記錄判斷
    這次呼叫是否真的建立了節點，供 `backfill_fact_nodes()` 準確計數。

    `article_no`（2026-08-24 新增，見 03 §3.5「實作範圍定案」下一步）：提供
    時（法規領域來源，見 `SVOTriple.source_article_no`），`SUPPORTED_BY`
    改連向 `(:LawArticle {kg_id, source_doc_id, article_no})` 而非
    `(:Chunk {...chunk_index})`——`LawArticle` 節點須已由
    `LawDocumentRepository.merge_law_articles()` 建立，否則同樣整條鏈不會
    建立任何節點（沿用既有 fail-closed 語意，不靜默退化成錯誤的來源連結）。
    `chunk_index` 此時仍照舊寫入 Fact 節點自身的扁平屬性（`source_svo_chunk_index`，
    對應 `ArticleAwareChunking` 一條對一塊，數值上仍有意義），只有
    `SUPPORTED_BY` 的連結目標改變；`None`（預設）維持既有 `Chunk` 行為
    完全不變。
    """
    if article_no:
        support_match = (
            "MATCH (c:LawArticle {kg_id: $kg_id, source_doc_id: $source_doc_id, article_no: $article_no})"
        )
    else:
        support_match = (
            "MATCH (c:Chunk {kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: $chunk_index})"
        )
    result = await driver.execute_query(
        f"""
        MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})
        MATCH (o:Entity {{kg_id: $kg_id, name: $object}})
        {support_match}
        CREATE (f:Fact:{_kg_fact_label(kg_id_str)} {{
            kg_id: $kg_id, fact_text: $fact_text, fact_embedding: $fact_embedding,
            verb: $verb, confidence: $confidence,
            source_doc_id: $source_doc_id, source_svo_chunk_index: $chunk_index,
            subject: $subject, object: $object, rel_type: $rel_type
        }})
        CREATE (f)-[:HAS_SUBJECT]->(s)
        CREATE (f)-[:HAS_OBJECT]->(o)
        CREATE (f)-[:SUPPORTED_BY]->(c)
        RETURN f
        """,
        kg_id=kg_id_str,
        subject=subject,
        object=object_,
        rel_type=rel_type,
        source_doc_id=source_doc_id,
        chunk_index=chunk_index,
        article_no=article_no,
        fact_text=fact_text,
        fact_embedding=fact_embedding,
        verb=verb,
        confidence=confidence,
    )
    return bool(result.records)


async def merge_triples_to_graph(
    driver: AsyncDriver,
    kg_id: UUID,
    triples: list[SVOTriple],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> None:
    """將 SVO triples 的主客實體解析對齊後，MERGE 進 Neo4j Entity Graph。

    `embedding_provider`／`llm_provider` 皆為可選——未提供時，實體解析僅做
    編輯距離比對（跳過 cosine 與 LLM 仲裁兩層），行為退化為較保守的去重，
    讓離線管線與單元測試可以安全呼叫，不強制要求外部服務。

    **事實層級去重（2026-07-22 使用者確認）**：關係邊的 MERGE 鍵只有
    `(kg_id, subject, rel_type, object)`，不再含來源 chunk／句子欄位——相同
    的 (subject, rel_type, object) 一律收斂成同一條邊，不會因為來自不同
    chunk（例如重疊切塊、或同一事實在文件中不同段落各自被抽到一次）就產生
    第二條邊。每次抽取的來源改記錄在邊上累積的 `citations_json`（JSON 字串
    陣列）：先 MERGE 並讀回既有清單，在應用層附加這次的來源後整份寫回。
    未走圖節點反正化（每個事實仍是一條直接邊，不像 HAS_ENTITY 是
    `Chunk`→`Entity`的獨立邊），是為了不動到 `bfs_query` 既有的單層關係
    走訪語意；把事實也節點化雖然模型上更一致，但牽動的是 BFS 走訪深度定義
    這種更大範圍的變更，留待有實際需求時再評估。

    **事實層級向量化（2026-08-03 實作，見 3.1.4 §a）**：`embedding_provider`
    提供時，每筆 citation 額外產生一個獨立的 `Fact` 節點＋`fact_embedding`
    （`_verbalize_fact()` 三元組文字化後呼叫 embedding provider），供查詢時
    語意檢索使用——**與上方事實層級去重的 MERGE 邊平行存在，不取代、不
    影響**（`Fact` 以每筆 citation 為粒度，MERGE 邊仍以 `(subject, rel_type,
    object)` 為粒度收斂）。僅在 `triple.source_doc_id`／
    `triple.source_svo_chunk_index` 皆存在時才建立（需要靠這兩者 MATCH 到
    `merge_entity()` 剛建立的 `Chunk` 節點才能連結 `SUPPORTED_BY`；兩者缺席
    時無法連結，直接跳過，不建立不完整的 `Fact` 節點）。實際建立交給
    `_create_fact_node()`（見該函式 docstring，2026-08-18 補上 `subject`／
    `object`／`rel_type` 扁平屬性，供 §b 回填批次任務比對鍵使用）。
    """
    kg_id_str = str(kg_id)
    for triple in triples:
        rel_type = _relationship_type(triple.rel_type)
        subject_name = await merge_entity(
            driver, kg_id, triple.subject, triple.subject_type, triple.subject,
            source_doc_id=triple.source_doc_id,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            embedding_provider=embedding_provider, llm_provider=llm_provider,
        )
        object_name = await merge_entity(
            driver, kg_id, triple.object, triple.object_type, triple.object,
            source_doc_id=triple.source_doc_id,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            embedding_provider=embedding_provider, llm_provider=llm_provider,
        )

        get_or_create = await driver.execute_query(
            f"""
            MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})
            MATCH (o:Entity {{kg_id: $kg_id, name: $object}})
            MERGE (s)-[r:{rel_type} {{kg_id: $kg_id}}]->(o)
            ON CREATE SET r.citations_json = '[]'
            RETURN r.citations_json AS citations_json
            """,
            kg_id=kg_id_str,
            subject=subject_name,
            object=object_name,
        )
        existing_json = get_or_create.records[0]["citations_json"] if get_or_create.records else "[]"
        citations = json.loads(existing_json or "[]")
        citations.append(_new_citation(triple))

        set_clause = "SET r.citations_json = $citations_json, r.confidence = $confidence"
        set_params = {
            "kg_id": kg_id_str,
            "subject": subject_name,
            "object": object_name,
            "citations_json": json.dumps(citations, ensure_ascii=False),
            "confidence": max(c["confidence"] for c in citations),
        }
        # 3.1.3 §a-1 BACKFILL：RELATED_TO 兜底的邊順便存 verb_embedding，
        # 供日後 EXPAND 核准新型別時的向量索引查詢使用（見 backfill_related_to_edges）。
        if triple.rel_type == "RELATED_TO" and triple.verb_embedding is not None:
            set_clause += ", r.verb_embedding = $verb_embedding"
            set_params["verb_embedding"] = triple.verb_embedding

        await driver.execute_query(
            f"""
            MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})-[r:{rel_type} {{kg_id: $kg_id}}]->
                  (o:Entity {{kg_id: $kg_id, name: $object}})
            {set_clause}
            """,
            **set_params,
        )

        # 3.1.4 §a：事實層級向量化——每筆 citation 各自產生一個 Fact 節點，
        # 永不相互覆蓋或平均（與上方的邊 MERGE／citations_json 累積是不同粒度）。
        if (
            embedding_provider is not None
            and triple.source_doc_id is not None
            and triple.source_svo_chunk_index is not None
        ):
            fact_text = _verbalize_fact(
                subject_name, triple.subject_type, triple.verb, object_name, triple.object_type
            )
            await _create_fact_node(
                driver, kg_id_str,
                subject=subject_name,
                object_=object_name,
                rel_type=triple.rel_type,
                source_doc_id=str(triple.source_doc_id),
                chunk_index=triple.source_svo_chunk_index,
                fact_text=fact_text,
                fact_embedding=await embedding_provider.encode(fact_text),
                verb=triple.verb,
                confidence=triple.confidence,
                article_no=triple.source_article_no,
            )


async def revoke_chunk_facts(
    driver: AsyncDriver,
    kg_id: UUID,
    source_doc_id: str,
    chunk_index: int,
) -> dict:
    """重新抽取某個 chunk 前的清理：撤銷這個 chunk 先前寫入的 Fact 節點與
    Entity 關係邊上的 citation（2026-08-28，見 `docs/論文/03_變更紀錄.md`
    「規則7/8/9 修正前抽取資料的重抽取」設計）。

    **背景**：`merge_triples_to_graph()` 對兩種節點的冪等性不同——Fact 節點
    是 `CREATE`（見 `_create_fact_node()`），完全沒有去重，同一 chunk 重跑
    兩次會直接產生兩倍的 Fact 節點；Entity 關係邊是 `MERGE`，鍵為
    `(kg_id, subject, rel_type, object)`，且**一條邊設計上會累積多個 chunk
    的 citations**（`citations_json`，見該函式 docstring「事實層級去重」）。
    若不先清理就重跑：(1) Fact 節點直接重複；(2) 若新版三元組的
    `object`／`rel_type` 跟舊版不同（例如本次規則7修正後「婚假→八日」
    vs. 舊版「婚假→''」），會多出一條新邊，舊的錯誤邊變成沒人清理的孤兒
    垃圾資料，新舊兩條邊同時存在。

    **不能整條邊直接刪除**——`citations_json` 可能同時累積了其他、未受
    影響的 chunk 的 citation，必須先只移除屬於這個 chunk 的那幾筆；移除後
    若清單變空才把整條邊一起刪除，否則保留邊、重算 `confidence`（沿用
    `merge_triples_to_graph()` 既有的 `confidence = max(citations)` 規則）。

    Entity 節點本身不刪除——`(kg_id, name)` 已有唯一約束防重複（見
    `create_entity_index()`），且同一個 Entity 通常被多個 chunk／文件共用，
    刪除是不安全的；只清理 Fact 節點與關係邊上「屬於這個 chunk」的部分。

    回傳統計字典（`facts_deleted`／`edges_updated`／`edges_deleted`）供呼叫端
    （重抽取批次腳本）記錄與驗證，不靜默執行。
    """
    kg_id_str = str(kg_id)

    fact_result = await driver.execute_query(
        """
        MATCH (f:Fact {kg_id: $kg_id, source_doc_id: $source_doc_id, source_svo_chunk_index: $chunk_index})
        DETACH DELETE f
        RETURN count(f) AS deleted
        """,
        kg_id=kg_id_str, source_doc_id=source_doc_id, chunk_index=chunk_index,
    )
    facts_deleted = fact_result.records[0]["deleted"] if fact_result.records else 0

    # 關係邊型別（rel_type）在寫入時可以是 SVO_REL_TYPES 裡任何一個，這裡
    # 不指定型別、只靠 `r.citations_json IS NOT NULL` 篩出真正的 SVO 事實邊
    # （`HAS_SUBJECT`／`HAS_OBJECT`／`SUPPORTED_BY`／`HAS_ENTITY` 等其他邊
    # 型別都沒有這個屬性，自然被排除）。
    edge_result = await driver.execute_query(
        """
        MATCH (s:Entity {kg_id: $kg_id})-[r]->(o:Entity {kg_id: $kg_id})
        WHERE r.citations_json IS NOT NULL
        RETURN elementId(r) AS rel_id, r.citations_json AS citations_json
        """,
        kg_id=kg_id_str,
    )

    edges_updated = 0
    edges_deleted = 0
    for record in edge_result.records:
        citations = json.loads(record["citations_json"] or "[]")
        remaining = [
            c for c in citations
            if not (
                c.get("source_doc_id") == source_doc_id
                and c.get("source_svo_chunk_index") == chunk_index
            )
        ]
        if len(remaining) == len(citations):
            continue  # 這條邊沒有屬於這個 chunk 的 citation，不動它

        if remaining:
            await driver.execute_query(
                """
                MATCH ()-[r]->() WHERE elementId(r) = $rel_id
                SET r.citations_json = $citations_json, r.confidence = $confidence
                """,
                rel_id=record["rel_id"],
                citations_json=json.dumps(remaining, ensure_ascii=False),
                confidence=max(c["confidence"] for c in remaining),
            )
            edges_updated += 1
        else:
            await driver.execute_query(
                "MATCH ()-[r]->() WHERE elementId(r) = $rel_id DELETE r",
                rel_id=record["rel_id"],
            )
            edges_deleted += 1

    return {"facts_deleted": facts_deleted, "edges_updated": edges_updated, "edges_deleted": edges_deleted}


async def create_fact_vector_index(
    driver: AsyncDriver | None = None, kg_id: UUID | None = None, dim: int = VECTOR_DIM
) -> None:
    """建立指定 KG 專屬的 `Fact` 向量索引，供 3.1.4 §a 事實層級語意檢索使用。

    **2026-08-19 改為每個 KG 各自一個獨立索引（原本是全 KG 共用單一
    `fact_embedding_vector` 索引，`vector_search_facts()` 查完再用
    `WHERE node.kg_id = $kg_id` 過濾，已知有 post-filter 限制）**：查證
    Neo4j 目前部署版本（5.26.27 Enterprise LTS）不支援 Cypher 25 的原生
    向量索引 pre-filter（該功能是 2026.01 preview／2026.02 GA 才推出的
    calendar-versioned continuous release 版本線，5.26 這條 LTS 線依官方
    版本政策只收安全性/bug 修補、不收新功能，無法透過小版本更新取得，
    需要整條版本線遷移，非本次範圍）。改採比照 Pinecone 官方建議的「每個
    租戶各自一個 namespace」精神（`docs.pinecone.io` 已查證原文；無對應
    學術文獻，這是向量資料庫多租戶隔離的常見工程模式，非本論文提出）——
    Neo4j 沒有 namespace 概念，但 2026-08-19 實測確認可用「每個 KG 各自
    一個 label」達到等效效果（見 `_kg_fact_label()`），索引範圍由 label
    在結構上保證，不再依賴查詢後才執行的應用層過濾。冪等（`IF NOT EXISTS`），
    呼叫端（`vector_search_facts()`）每次查詢前直接呼叫，不需要另外在寫入
    路徑或啟動流程預先建立——Neo4j 索引本來就會自動涵蓋建立之前已寫入的
    符合條件節點，不要求「先有索引才能寫資料」。"""
    if driver is None or kg_id is None:
        return
    kg_id_str = str(kg_id)
    await driver.execute_query(
        f"""
        CREATE VECTOR INDEX {_fact_vector_index_name(kg_id_str)} IF NOT EXISTS
        FOR (f:{_kg_fact_label(kg_id_str)}) ON f.fact_embedding
        OPTIONS {{ indexConfig: {{ `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' }} }}
        """,
        dim=dim,
    )


async def vector_search_facts(
    driver: AsyncDriver, kg_id: UUID, query_vector: list[float], top_k: int
) -> list[dict]:
    """3.1.4 §a `RETRIEVE`：per-KG `Fact` 向量索引 KNN 查詢，比照
    `ConceptRepository.vector_search_concept_ids()` 同一套模式，回傳最相近的
    `Fact` 候選（`fact_text`／`verb`／`confidence`／`subject`／`object`／
    `rel_type`／來源追溯欄位／`score`；2026-08-18 追加後三者——
    `_create_fact_node()` 補上這三個扁平屬性後，呼叫端不必再額外 traversal
    `HAS_SUBJECT`／`HAS_OBJECT` 邊就能取得完整三元組）。

    ✅ **KG 範圍過濾已從查詢後 post-filter 改為索引結構原生隔離
    （2026-08-19，見 `create_fact_vector_index()` 與 `_kg_fact_label()`
    docstring 完整查證脈絡）**：原本是全 KG 共用單一向量索引、查完再用
    `WHERE node.kg_id = $kg_id` 過濾，若前 `top_k` 名近似鄰居剛好大多來自
    其他 KG，篩選後回傳筆數可能少於 `top_k` 甚至為空。改為每個 KG 各自一個
    索引後，`db.index.vector.queryNodes()` 天生只能查到該索引涵蓋範圍
    （該 KG）的節點，範圍過濾由索引定義本身保證，不再是可能失效的應用層
    篩選步驟，此已知限制已解除。**扁平相似度檢索本身、未利用圖結構鄰接
    關係的侷限（G-Retriever 對照討論）不在此次範圍內，仍待後續評估。**

    ✅ **查詢後去重（2026-08-19，真實資料驗證發現並修復；與上方 KG 範圍
    過濾是兩個獨立問題，此處的候選池倍數不因上方修復而可以拿掉）**：同一件
    事實可能因多筆 citation（例如切塊重疊）各自產生獨立 `Fact` 節點——這是
    刻意設計（見 3.1.4 §a「解法」段落，避免代表性偏差與語意壓平），但代表
    `top_k` 名額可能被近乎重複的結果佔掉，與 KG 範圍無關、單一 KG 內就會
    發生。改為先取 `top_k × FACT_SEARCH_CANDIDATE_MULTIPLIER` 的候選池，
    再依 `(subject, rel_type, object)` 去重（`_dedupe_facts_by_key()`，
    同一鍵只保留分數最高的一筆），最後截斷回 `top_k`。不改動 Fact 節點的
    建立/儲存邏輯，只在查詢輸出層後處理，對外 `top_k` 契約不變。
    """
    await create_fact_vector_index(driver, kg_id, dim=len(query_vector))
    candidate_k = top_k * FACT_SEARCH_CANDIDATE_MULTIPLIER
    result = await driver.execute_query(
        f"""
        CALL db.index.vector.queryNodes('{_fact_vector_index_name(str(kg_id))}', $candidate_k, $vector)
        YIELD node, score
        RETURN node.fact_text AS fact_text, node.verb AS verb, node.confidence AS confidence,
               node.subject AS subject, node.object AS object, node.rel_type AS rel_type,
               node.source_doc_id AS source_doc_id,
               node.source_svo_chunk_index AS source_svo_chunk_index, score
        """,
        candidate_k=candidate_k,
        vector=query_vector,
    )
    records = [dict(r) for r in result.records]
    return _dedupe_facts_by_key(records)[:top_k]


async def vector_search_entities(
    driver: AsyncDriver, kg_id: UUID, query_vector: list[float], top_k: int
) -> list[str]:
    """語意種子實體比對：供 `_find_seed_entities()` 在字面比對找不到任何
    種子時的 fallback，回傳依相似度排序的 `Entity.name` 清單（2026-08-25
    新增，見 `docs/報告/17`／`docs/論文/03_變更紀錄.md` 第五十二次調整發現
    的字面比對失效問題）。

    ⚠️ **v1（ANN 全域共用索引 + post-filter）在真實測試中被證實無效，
    v2 改為 `WHERE kg_id` 先行過濾＋`vector.similarity.cosine()` 純量函式
    現算現排，不再用 Neo4j 原生向量索引**：`Entity` 目前仍是全 KG 共用
    單一 label（未比照 `Fact` 拆成每個 KG 各自的 label——`merge_entity()`／
    `_fetch_entity_candidates()`／DEDUP4 合併改名等邏輯已遍佈全專案多處，
    改動範圍與風險遠大於這次要解決的問題，非本次範圍）。v1 沿用
    `vector_search_facts()` 的「候選池 + post-filter」模式，實測發現候選池
    在開發用 Neo4j 累積多個 KG（3292 個 Entity／5 個 KG）時幾乎不可能包含
    到目標 KG 的實體，fallback 形同無效（BFS 仍是 0）。v2 改為 `MATCH
    (e:Entity {{kg_id}})` 先精確過濾到本 KG，再逐筆算 cosine 相似度排序——
    犧牲 ANN 索引的效能換取正確性，demo 規模（單 KG 數十至數百個 Entity）
    下 brute-force 完全可接受；`name_embedding` 缺席的 Entity（尚未跑過
    `backfill_entity_name_embeddings()` 的舊資料）會被排除。KG 規模顯著
    成長時應重新評估是否改用 per-KG label 的原生向量索引。
    """
    result = await driver.execute_query(
        """
        MATCH (e:Entity {kg_id: $kg_id})
        WHERE e.name_embedding IS NOT NULL AND e.name IS NOT NULL
        WITH e, vector.similarity.cosine(e.name_embedding, $vector) AS score
        RETURN e.name AS name, score
        ORDER BY score DESC
        LIMIT $top_k
        """,
        kg_id=str(kg_id),
        vector=query_vector,
        top_k=top_k,
    )
    return [r["name"] for r in result.records if r["name"]]


def _dedupe_facts_by_key(records: list[dict]) -> list[dict]:
    """`vector_search_facts()` 查詢輸出層去重：以 `(subject, rel_type,
    object)` 為鍵，同一鍵只保留分數最高的一筆，維持原始分數排序。任一欄位
    為 `None`（例如 2026-08-18 schema 修正前建立、尚未跑過 §b 回填批次的
    舊 Fact 節點）時視為無法安全去重，一律原樣保留——與
    `routers/agent.py::_merge_fact_lines()` 既有的同名情境處理原則一致。
    """
    best_by_key: dict[tuple, dict] = {}
    order: list[tuple | dict] = []

    for record in records:
        key = (record.get("subject"), record.get("rel_type"), record.get("object"))
        if not all(key):
            order.append(record)
            continue
        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = record
            order.append(key)
        elif record.get("score", 0) > existing.get("score", 0):
            best_by_key[key] = record

    deduped: list[dict] = []
    seen_keys: set[tuple] = set()
    for item in order:
        if isinstance(item, dict):
            deduped.append(item)
            continue
        if item in seen_keys:
            continue
        seen_keys.add(item)
        deduped.append(best_by_key[item])
    return deduped


async def backfill_fact_nodes(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    *,
    batch_size: int = 100,
) -> int:
    """3.1.4 §b 回填批次任務：掃描該 KG 內所有既有 `Entity--[REL_TYPE]-->Entity`
    邊累積的 `citations_json`，把尚未有對應 `Fact` 節點的歷史 citation 補建成
    `Fact` 節點——`Fact` 向量化功能是**抽取管線跑完之後**（2026-08-03）才上線
    的（見 3.1.4 §a 時機選擇段落），這之前完成的抽取只留下 `citations_json`，
    沒有對應 `Fact` 節點；本函式與即時路徑（`merge_triples_to_graph` →
    `_create_fact_node`）共用同一套 verbalize／embedding／建節點邏輯，不重複
    實作兩套。

    **人工觸發的一次性腳本，非常駐背景 Worker**（與 `backfill_related_to_edges`／
    `backfill_missing_verb_embeddings`／`backfill_entity_name_embeddings` 三個
    接線進治理 Worker 週期的函式不同類，見 03_系統設計與方法論.md § 3.1.4 §b
    `START5` 節點）——因此本函式在單次呼叫內部自行分頁掃完整個 KG（`skip`／
    `batch_size` 循環直到取不到下一批邊），不像那三個函式只吃外部傳入的單一
    `limit` 批次、依賴呼叫端反覆呼叫。

    **冪等性（EXIST5）**：每筆 citation 建立前，先用
    `(kg_id, source_doc_id, source_svo_chunk_index, subject, rel_type, object)`
    六個欄位查詢是否已有對應 `Fact` 節點——已存在就跳過，不重複呼叫
    `embedding_provider`、不產生重複節點。這個比對鍵之所以能查得到，是因為
    `_create_fact_node()` 已把 `subject`／`object`／`rel_type` 存成 Fact 節點
    自身的扁平屬性（2026-08-18 追加，見該函式 docstring）；若沒有這三個屬性，
    §b 無法做到文件描述的原生 Neo4j 比對，只能退化成不精確的 traversal 猜測。

    citation 缺少 `source_doc_id`／`source_svo_chunk_index` 時直接跳過（理論上
    `_new_citation()` 一律會填，此處防禦性處理；即使有值，`_create_fact_node()`
    底層的 `MATCH (c:Chunk ...)` 找不到對應節點時仍會整條鏈不建立任何東西，
    繼承 3.1.4 §a／SVO chunk 向量化既有記錄的 `Chunk` 雙鍵值缺口，非本函式
    新引入）。回傳實際新建立的 `Fact` 節點數。
    """
    kg_id_str = str(kg_id)
    created = 0
    skip = 0
    while True:
        result = await driver.execute_query(
            """
            MATCH (s:Entity {kg_id: $kg_id})-[r]->(o:Entity {kg_id: $kg_id})
            WHERE r.kg_id = $kg_id AND r.citations_json IS NOT NULL
            RETURN type(r) AS rel_type, s.name AS subject, o.name AS object,
                   s.type AS subject_type, o.type AS object_type,
                   r.citations_json AS citations_json
            SKIP $skip LIMIT $batch_size
            """,
            kg_id=kg_id_str,
            skip=skip,
            batch_size=batch_size,
        )
        edges = result.records
        if not edges:
            break

        for edge in edges:
            citations = json.loads(edge["citations_json"] or "[]")
            for citation in citations:
                source_doc_id = citation.get("source_doc_id")
                chunk_index = citation.get("source_svo_chunk_index")
                if source_doc_id is None or chunk_index is None:
                    continue

                exists = await driver.execute_query(
                    """
                    MATCH (f:Fact {
                        kg_id: $kg_id, source_doc_id: $source_doc_id,
                        source_svo_chunk_index: $chunk_index,
                        subject: $subject, rel_type: $rel_type, object: $object
                    })
                    RETURN count(f) AS cnt
                    """,
                    kg_id=kg_id_str,
                    source_doc_id=source_doc_id,
                    chunk_index=chunk_index,
                    subject=edge["subject"],
                    rel_type=edge["rel_type"],
                    object=edge["object"],
                )
                if exists.records and exists.records[0]["cnt"] > 0:
                    continue  # EXIST5：已有對應 Fact 節點，略過

                fact_text = _verbalize_fact(
                    edge["subject"], edge["subject_type"], citation.get("verb", ""),
                    edge["object"], edge["object_type"],
                )
                created_now = await _create_fact_node(
                    driver, kg_id_str,
                    subject=edge["subject"],
                    object_=edge["object"],
                    rel_type=edge["rel_type"],
                    source_doc_id=source_doc_id,
                    chunk_index=chunk_index,
                    fact_text=fact_text,
                    fact_embedding=await embedding_provider.encode(fact_text),
                    verb=citation.get("verb", ""),
                    confidence=citation.get("confidence", 1),
                    article_no=citation.get("article_no"),
                )
                if created_now:
                    created += 1

        if len(edges) < batch_size:
            break
        skip += batch_size

    return created


async def create_related_to_vector_index(driver: AsyncDriver | None = None, dim: int = VECTOR_DIM) -> None:
    """建立 `RELATED_TO` 邊的 `verb_embedding` 向量索引（app 啟動時呼叫一次），
    供 3.1.3 §a-1 `EXPAND` 核准新型別後的 `BACKFILL` 回溯重分類使用。"""
    if driver is None:
        return
    await driver.execute_query(
        """
        CREATE VECTOR INDEX related_to_verb_embedding IF NOT EXISTS
        FOR ()-[r:RELATED_TO]-() ON r.verb_embedding
        OPTIONS { indexConfig: { `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' } }
        """,
        dim=dim,
    )


async def _confirm_backfill_candidate(
    subject: str,
    verb: str,
    object_: str,
    new_rel_type: str,
    new_type_description: str,
    llm_provider: LLMProvider,
) -> bool:
    """BACKFILL 的 LLM 確認關卡（2026-07-27 新增，比照 `ESCALATE3` 精神，見
    docs/論文/03_系統設計與方法論.md § 3.1.3 §a-1）：cosine 分數達門檻只代表
    候選，`backfill` 只看得到孤立的 `verb` 字串（不像抽取當下能看到完整句子），
    風險比 `ESCALATE3` 更高，因此改寫前一律需要 LLM 用三元組本身做最後把關。
    """
    prompt = (
        f"三元組「{subject}」－「{verb}」－「{object_}」，"
        f"是否真的屬於關係型別「{new_rel_type}」（{new_type_description}）？"
        "只回答「是」或「否」，不要有其他文字。"
    )
    answer = (await llm_provider.generate(prompt)).strip()
    return answer.startswith("是")


async def backfill_related_to_edges(
    driver: AsyncDriver,
    kg_id: UUID,
    new_rel_type: str,
    new_type_description: str,
    embedding_provider: EmbeddingProvider,
    *,
    llm_provider: LLMProvider | None = None,
    top_k: int = 100,
) -> int:
    """3.1.3 §a-1 BACKFILL：`EXPAND` 核准新型別後，對該 KG 既有的 `RELATED_TO`
    邊做一次向量索引查詢，把 `verb_embedding` 與新型別描述句夠相似
    （≥ `COMPARE_COSINE_THRESHOLD`）、且經 `llm_provider` 二次確認的邊，從
    `RELATED_TO` 升級為新型別。

    Neo4j 的邊型別建立後不能原地改名，做法是刪除舊邊、把 `citations_json`／
    `confidence` 搬到新型別的邊上。回傳實際升級的邊數。

    ⚠️ 查無直接對應的學術文獻或開源專案精確處理「型別詞彙擴充後回溯重分類既有
    資料」這個問題（誠實聲明與查證過程見
    docs/論文/03_系統設計與方法論.md § 3.1.3 §a-1），本函式是自行設計的工程
    方案：預先計算並存於邊上的 `verb_embedding` 避免重複呼叫 embedding
    provider（比照 3.1.4 SVO chunk 向量化慣例），改用 Neo4j 原生 relationship
    向量索引做一次查詢取代逐條 Python 迴圈掃描。此功能上線前既有的 `RELATED_TO`
    邊沒有 `verb_embedding`，不會被向量索引收錄，backfill 對這些邊無效
    （已知限制，見設計文件）。

    **`llm_provider` 為必要的二次確認關卡（2026-07-27 新增）**：cosine 分數
    只是候選篩選，實際改寫前一律需要 `_confirm_backfill_candidate()` 用
    subject／verb／object 三元組本身向 LLM 確認——backfill 比對的是孤立的
    `verb` 字串，沒有原句上下文，比 `ESCALATE3` 風險更高，不能只憑單一
    embedding 訊號就直接動手改寫。**未提供 `llm_provider` 時，為安全起見一律
    不改寫任何邊（回傳 0）**，不會退回「純 cosine 分數即可改寫」的舊行為——
    這是刻意的保守預設，不是遺漏。
    """
    query_vector = await embedding_provider.encode(new_type_description)
    result = await driver.execute_query(
        """
        CALL db.index.vector.queryRelationships('related_to_verb_embedding', $top_k, $query_vector)
        YIELD relationship AS r, score
        WHERE score >= $threshold AND r.kg_id = $kg_id
        MATCH (s)-[r]->(o)
        RETURN s.name AS subject, o.name AS object,
               r.citations_json AS citations_json, r.confidence AS confidence
        """,
        kg_id=str(kg_id),
        top_k=top_k,
        query_vector=query_vector,
        threshold=COMPARE_COSINE_THRESHOLD,
    )

    if llm_provider is None:
        return 0

    new_type = _relationship_type(new_rel_type)
    kg_id_str = str(kg_id)
    count = 0
    for record in result.records:
        citations = json.loads(record["citations_json"] or "[]")
        verb = citations[-1]["verb"] if citations else ""
        confirmed = await _confirm_backfill_candidate(
            record["subject"], verb, record["object"],
            new_rel_type, new_type_description, llm_provider,
        )
        if not confirmed:
            continue

        await driver.execute_query(
            f"""
            MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})-[r:RELATED_TO {{kg_id: $kg_id}}]->
                  (o:Entity {{kg_id: $kg_id, name: $object}})
            DELETE r
            """,
            kg_id=kg_id_str,
            subject=record["subject"],
            object=record["object"],
        )
        await driver.execute_query(
            f"""
            MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})
            MATCH (o:Entity {{kg_id: $kg_id, name: $object}})
            CREATE (s)-[r:{new_type} {{kg_id: $kg_id, citations_json: $citations_json, confidence: $confidence}}]->(o)
            """,
            kg_id=kg_id_str,
            subject=record["subject"],
            object=record["object"],
            citations_json=record["citations_json"],
            confidence=record["confidence"],
        )
        count += 1
    return count


async def backfill_missing_verb_embeddings(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    *,
    limit: int = 100,
) -> int:
    """3.1.3 §a-1：補齊缺漏 `verb_embedding` 的既有 `RELATED_TO` 邊——**不做任何
    型別判斷**，純粹把邊上已有的 `verb` 文字（`citations_json` 最後一筆）算成
    embedding 存回去，讓這些邊能被 `related_to_verb_embedding` 向量索引收錄，
    未來 `backfill_related_to_edges()` 才找得到它們。與該函式是兩個不同層級
    的操作——本函式只補向量、不涉及任何判斷，因此不需要 LLM 確認關卡。

    涵蓋兩種成因（見 docs/論文/03_系統設計與方法論.md § 3.1.3 §a-1 誠實聲明）：
    ① 此功能上線前既有的歷史資料；② `embedding_provider` 選填，任何一次
    `extract_svo_triples()` 呼叫沒帶入時持續產生的新缺口——成因 ② 會反覆
    發生，不是一次性的。因此本函式設計為**冪等、可重複執行**，不是一次性
    遷移腳本——用意是排進治理 Worker 既有的定期巡視週期，跟 `POOLSIZE`
    檢查同一套排程機制，而非另外開一套維運流程。

    `citations_json` 為空或缺少 `verb` 欄位的邊會被跳過（沒有可供 embedding
    的原始文字，理論上不該發生，防禦性處理）。回傳實際補上 `verb_embedding`
    的邊數。
    """
    result = await driver.execute_query(
        """
        MATCH (s)-[r:RELATED_TO {kg_id: $kg_id}]->(o)
        WHERE r.verb_embedding IS NULL
        RETURN s.name AS subject, o.name AS object, r.citations_json AS citations_json
        LIMIT $limit
        """,
        kg_id=str(kg_id),
        limit=limit,
    )

    kg_id_str = str(kg_id)
    count = 0
    for record in result.records:
        citations = json.loads(record["citations_json"] or "[]")
        verb = citations[-1]["verb"] if citations else ""
        if not verb:
            continue
        verb_embedding = await embedding_provider.encode(verb)
        await driver.execute_query(
            """
            MATCH (s:Entity {kg_id: $kg_id, name: $subject})-[r:RELATED_TO {kg_id: $kg_id}]->
                  (o:Entity {kg_id: $kg_id, name: $object})
            SET r.verb_embedding = $verb_embedding
            """,
            kg_id=kg_id_str,
            subject=record["subject"],
            object=record["object"],
            verb_embedding=verb_embedding,
        )
        count += 1
    return count


async def embed_svo_chunks(
    driver: AsyncDriver,
    kg_id: UUID,
    source: str,
    chunks: list[SVOChunk],
    embedding_provider: EmbeddingProvider | None,
) -> None:
    """切塊當下把每個 SVO chunk 的向量算好存進 `Chunk` 節點的 `embedding`
    屬性（2026-07-22 使用者提出）。

    目的是供未來（不在本次範圍內）回答階段做來源篩選：把候選來源 chunk 的
    向量與問題向量做相似度比對，只挑分數最高的幾筆作為實際引用內容，而非
    直接吐出事實累積的全部來源原文。本函式只負責「切塊當下算好存起來」，
    比對／排序邏輯留給後續設計（沿用現有 `EmbeddingProvider`／
    `ConceptRepository.vector_search_concept_ids` 那套向量檢索模式，非學習式
    attention）。

    `embedding_provider` 未提供時安全跳過，比照 `merge_entity` 對可選
    provider 的既有慣例。

    ✅ **雙鍵值缺口已收斂（2026-08-18，見 § 3.1.4 §c）**：本函式原以
    `(kg_id, source, chunk_index)` 為 `Chunk` 節點識別鍵（`source` 為檔案系統
    路徑字串），`_merge_chunk_mention()`（`HAS_ENTITY` 邊）則以
    `(kg_id, source_doc_id: UUID, chunk_index)` 為鍵——`source_doc_id` 先前
    從未真正被賦值，導致兩者形成兩個彼此不相連的 `Chunk` 節點群。現改為
    `document_record_service.document_uuid(source)` 決定性推導出
    `source_doc_id`，與 `_merge_chunk_mention()` 共用同一個 MERGE 鍵——本函式
    在 CHUNKREADY 階段先建立節點並存 `embedding`，`_merge_chunk_mention()`
    在抽取階段接著 MERGE 到同一個節點補上 `HAS_ENTITY` 邊，`_create_fact_node()`
    的 `SUPPORTED_BY` 才真正連得到有向量的節點。`source` 字串仍保留為節點的
    一般屬性（除錯／回溯用），只是不再是識別鍵的一部分。**僅對此修正上線後
    新產生的資料生效**——既有資料（例如已用舊鍵值寫入的既有 KG）仍是兩群
    分離的 `Chunk` 節點，回填／補充抽取留待後續獨立討論，非本次範圍。
    """
    if embedding_provider is None or not chunks:
        return

    source_doc_id = document_record_service.document_uuid(source)
    vectors = await embedding_provider.encode_batch([chunk.text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors):
        await driver.execute_query(
            """
            MERGE (c:Chunk {kg_id: $kg_id, source_doc_id: $source_doc_id, chunk_index: $chunk_index})
            SET c.embedding = $embedding, c.chunk_file = $chunk_file, c.source = $source
            """,
            kg_id=str(kg_id),
            source_doc_id=str(source_doc_id),
            source=source,
            chunk_index=chunk.index,
            embedding=vector,
            chunk_file=chunk.filename,
        )


def _kg_sentence_label(kg_id: str) -> str:
    """每個 KG 各自一個標準化句子節點標籤，比照 `_kg_fact_label()` 同一套
    per-KG label＋per-KG 向量索引模式（見該函式 docstring 完整查證脈絡：
    Neo4j 同一個 `(label, property)` 組合僅能有一個向量索引，2026-08-19
    已用真實資料庫驗證確認）——供 § Phase 1 標準化 RAG 句子向量索引使用，
    見 `docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md` §5。"""
    return f"Sentence_{str(UUID(kg_id)).replace('-', '_')}"


def _sentence_vector_index_name(kg_id: str) -> str:
    return f"sentence_embedding_vector_{str(UUID(kg_id)).replace('-', '_')}"


async def create_sentence_vector_index(
    driver: AsyncDriver | None = None, kg_id: UUID | None = None, dim: int = VECTOR_DIM
) -> None:
    """建立指定 KG 專屬的標準化句子向量索引（§ Phase 1）。冪等
    （`IF NOT EXISTS`），呼叫端（`services/retrieval_service.py`）每次查詢前
    直接呼叫，不需要另外在寫入路徑或 app 啟動流程預先建立——與
    `create_fact_vector_index()` 同一套惰性建立設計，見該函式 docstring。"""
    if driver is None or kg_id is None:
        return
    kg_id_str = str(kg_id)
    await driver.execute_query(
        f"""
        CREATE VECTOR INDEX {_sentence_vector_index_name(kg_id_str)} IF NOT EXISTS
        FOR (s:{_kg_sentence_label(kg_id_str)}) ON s.sentence_embedding
        OPTIONS {{ indexConfig: {{ `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' }} }}
        """,
        dim=dim,
    )


async def embed_standardized_sentences(
    driver: AsyncDriver,
    kg_id: UUID,
    source: str,
    sentences: list[str],
    vectors: list[list[float]],
    chunks: list[SVOChunk],
) -> None:
    """把每句標準化句子（已消解代名詞）各自建立一個 `Sentence` 節點＋向量，
    供 § Phase 1／Phase 2 標準化 RAG 雙階檢索使用（`docs/報告/
    08_三軌混合檢索架構與標準化RAG設計報告.md` §3：單句精確命中 → 依
    `chunk_index` 拉出所屬語意 chunk 全文）。

    **句子→所屬 chunk 的對應規則**：`build_svo_chunks()` 產出的 chunk 之間
    刻意有重疊（見 3.1.2 節設計），同一句話可能同時落在多個相鄰 chunk 的
    範圍內——比照既有 MVP（`standardized_rag.py` 前身 `build_standardized_rag_index.py::
    _chunk_for_sentence()`）的既有規則，取**第一個**（依 `chunks` 既有順序，
    即 chunk_index 由小到大）涵蓋此句的 chunk，非任意規則。

    `sentences`／`vectors` 長度不一致，或任一為空，視為資料不一致，不寫入
    任何節點（比照 `build_standardized_rag_index.py` 既有的「資料不一致就
    略過，不假裝能對齊」原則）。不建立 Neo4j 向量索引本身（見
    `create_sentence_vector_index()`，惰性建立於查詢端）。
    """
    if not sentences or not vectors or len(sentences) != len(vectors):
        return

    source_doc_id = document_record_service.document_uuid(source)
    label = _kg_sentence_label(str(kg_id))

    for i, (sentence, vector) in enumerate(zip(sentences, vectors), start=1):
        chunk = next(
            (c for c in chunks if c.source_sentence_start <= i <= c.source_sentence_end), None
        )
        if chunk is None:
            continue
        await driver.execute_query(
            f"""
            MERGE (s:Sentence:{label} {{
                kg_id: $kg_id, source_doc_id: $source_doc_id, sentence_index: $sentence_index
            }})
            SET s.sentence_text = $sentence_text, s.sentence_embedding = $embedding,
                s.chunk_index = $chunk_index, s.source = $source
            """,
            kg_id=str(kg_id),
            source_doc_id=str(source_doc_id),
            sentence_index=i,
            sentence_text=sentence,
            embedding=vector,
            chunk_index=chunk.index,
            source=source,
        )


async def vector_search_sentences(
    driver: AsyncDriver, kg_id: UUID, query_vector: list[float], top_k: int
) -> list[dict]:
    """§ Phase 1 標準化 RAG（`docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md`
    §3 第一階「單句粗篩」）：per-KG `Sentence` 向量索引 KNN 查詢，比照
    `vector_search_facts()` 同一套模式，回傳原始候選（`sentence_text`／
    `source`／`chunk_index`／`source_doc_id`／`score`）。

    **刻意不在此處做 chunk 去重與上下文擴展**（同一 chunk 內相鄰句子很可能
    同時命中）——去重需要讀取 `svo_index.json`（檔案系統存取，非 Neo4j
    查詢），依本專案既有的分層慣例（router → service → repository），這是
    `services/retrieval_service.py::search_standardized_rag()`（§ Phase 2）
    的職責，本函式只負責「單純的向量索引查詢」這一層，與 `vector_search_facts()`
    的分工原則一致。"""
    await create_sentence_vector_index(driver, kg_id, dim=len(query_vector))
    result = await driver.execute_query(
        f"""
        CALL db.index.vector.queryNodes('{_sentence_vector_index_name(str(kg_id))}', $top_k, $vector)
        YIELD node, score
        RETURN node.sentence_text AS sentence_text, node.source AS source,
               node.chunk_index AS chunk_index, node.source_doc_id AS source_doc_id, score
        """,
        top_k=top_k,
        vector=query_vector,
    )
    return [dict(r) for r in result.records]


async def trigger_extraction(
    driver: AsyncDriver,
    doc_folder: Path,
    kg_id: UUID,
    *,
    articles: Sequence[Mapping[str, str]] | None = None,
) -> None:
    """文件搬進 KG 資料夾後立即觸發抽取任務（§ 3.1.2「立即觸發抽取任務，
    不需要使用者另外按『開始建圖』」）：`CHUNKREADY`（前處理＋逐句 embedding＋
    SVO 專用切塊）→ 切塊向量化（`embed_svo_chunks`）→ `ENQUEUE`（登記進
    `task_queue.db`）。同步直接呼叫（2026-07-21 使用者決策），而非背景排程
    或延後執行。

    原本是 `routers/staging.py` 的私有函式，遷移至此供
    `services/knowledge_graph_service.py::build_graph()` 共用同一套
    CHUNKREADY→EMBEDCHUNK→ENQUEUE 邏輯，避免 router 層與 service 層各自
    維護一份（見 `docs/報告/11_抽取管線完整實作任務書.md` P0-2）。`driver`
    改為明確參數（而非函式內自行呼叫 `get_driver()`），比照本模組其餘函式
    的依賴注入慣例，也讓測試不需要 monkeypatch 全域函式。

    ✅ **2026-08-20 接上指代消解 LLM（docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md
    §0 前提缺口）**：`prepare_svo_ready_chunks()` 現在帶入 `pronoun_llm_provider`，
    代名詞消解不再退化為原句直接通過——這不只補上一份額外的標準化句子索引，
    `build_svo_chunks()` 的 `chunk.text` 本身就是 `normalized_sentences` 組成，
    即現有 `LLM_SVO` 三元組抽取送出的原文，因此本次改動同時也是既有 SVO 抽取
    品質的修正（代名詞換成具體實體後，LLM 抽取應更準確），非僅服務標準化 RAG。
    **範圍聲明**：僅對此修正上線後**新觸發**的抽取生效；已完成抽取的既有 KG
    需要 `knowledge_graph_service.build_graph(force_rebuild=True)` 重新觸發
    才能拿到消解後版本，見上述報告 §0 的時機決策記錄。

    ✅ **2026-08-20 KG 專屬代名詞排除詞庫**：真實匯入法規全文資料集時發現，
    `DEFAULT_PRONOUN_LEXICON` 的「其」「該」在法律文本中幾乎都是自我完備的
    正式泛稱（如「及其家屬」「該法」），字面比對規則卻一律當成代名詞觸發 LLM
    消解——實測某份 390 句的法規全文 41% 的句子因此觸發，單筆文件耗時超過
    600 秒（見 `docs/報告/08_三軌混合檢索架構與標準化RAG設計報告.md`）。
    每次呼叫先查一次 `KnowledgeGraph.pronoun_lexicon_exclude`，扣除該 KG 指定
    排除的字後才傳入 `prepare_svo_ready_chunks()`；欄位預設為空，對其他既有／
    未來 KG 沒有行為變化，只有明確設定過此欄位的 KG（例如本次的「請假與排班
    法規遵循」）才會套用縮減後的詞庫。

    `articles`（2026-08-24 新增，見 § 3.5「實作範圍定案」）：提供時原樣轉交
    `prepare_svo_ready_chunks()`，改走 `ArticleAwareChunking` 路徑；`None`
    （預設）維持既有行為完全不變。

    ⚠️ 誠實侷限（仍未解決，非本次範圍）：`prepare_svo_ready_chunks()` 仍以
    `mentions=None` 呼叫，跳過 §a 別名登記表階段（具名提及抽取／NER 仍是未解決
    的上游依賴，見 `services/svo_preprocessing_service.py` docstring）——別名
    登記與代名詞消解是兩個獨立階段，本次只解決後者。`get_llm_provider()`／
    `get_embedding_provider()` 在尚未呼叫 `init_providers()` 的情境（例如測試）
    皆會拋出 `RuntimeError`，此時視為對應功能不可用，優雅跳過，不影響切塊與
    排隊本身——兩個 provider 各自獨立降級，任一缺席不影響另一個。
    """
    record = document_record_service.read_record(doc_folder)
    if record is None:
        return

    try:
        embedding_provider = get_embedding_provider()
    except RuntimeError:
        embedding_provider = None

    try:
        pronoun_llm_provider = get_llm_provider()
    except RuntimeError:
        pronoun_llm_provider = None

    kg = await KGRepository(driver).get(kg_id)
    pronoun_lexicon = DEFAULT_PRONOUN_LEXICON
    if kg is not None and kg.pronoun_lexicon_exclude:
        pronoun_lexicon = DEFAULT_PRONOUN_LEXICON - set(kg.pronoun_lexicon_exclude)

    kg_folder = doc_folder.parent
    _paths, chunks = await prepare_svo_ready_chunks(
        record.source, kg_folder, kg_folder,
        articles=articles,
        embedding_provider=embedding_provider, pronoun_llm_provider=pronoun_llm_provider,
        pronoun_lexicon=pronoun_lexicon,
    )
    if not chunks:
        return

    document_record_service.set_svo_chunk_total(doc_folder, len(chunks))

    if embedding_provider is not None:
        await embed_svo_chunks(driver, kg_id, record.source, chunks, embedding_provider)
        # § Phase 1 標準化 RAG（docs/報告/08_...md §5）：SENTEMBED 剛寫入的
        # sentence_embeddings.json 現在同時含句子文字（見 write_sentence_embeddings()
        # docstring），讀回後逐句建立 Sentence 節點＋向量，供 Phase 2 檢索服務使用。
        normalized_sentences = read_standardized_sentences(record.source, kg_folder)
        vectors_for_sentences = read_sentence_embeddings(record.source, kg_folder)
        if normalized_sentences is not None and vectors_for_sentences is not None:
            await embed_standardized_sentences(
                driver, kg_id, record.source, normalized_sentences, vectors_for_sentences, chunks,
            )

    task_queue_service.enqueue(
        task_queue_db_path(), str(kg_id), record.source, list(range(1, len(chunks) + 1)),
    )


async def bfs_query(driver: AsyncDriver, kg_id: UUID, seed_entities: list[str], hops: int = 2) -> list[SVOTriple]:
    """從 seed entity 做 bounded BFS，回傳路徑上的去重 SVO triples。

    每條邊可能累積多筆來源引用（見 `merge_triples_to_graph` 的事實層級
    去重說明）；`SVOTriple` 的 `source_*` 欄位是單筆值，這裡先取
    `citations_json` 清單中「最後一筆」（最近一次抽取到這個事實）作為代表
    值——挑選哪一筆／哪幾筆來源最適合呈現，是回答階段的向量篩選設計
    （不在本次範圍），這裡只是先確保欄位不會靜默變成 null。
    """
    seeds = [entity.strip() for entity in seed_entities if entity.strip()]
    if not seeds:
        return []
    if hops < 1 or hops > 5:
        raise ValueError("hops 必須介於 1 到 5")

    # 2026-08-19 修復：走訪必須限定在 SVO_REL_TYPES（Entity--[REL_TYPE]-->Entity
    # 知識層邊）——先前的 [*1..{hops}] 未限定關係型別，一旦圖譜內同時存在
    # § 3.1.4 §a 的 HAS_ENTITY／HAS_SUBJECT／HAS_OBJECT／SUPPORTED_BY 等結構性
    # 邊（連到 Chunk／Fact 節點），BFS 就可能行經這些邊、把 startNode/endNode
    # 解析成沒有 .name 屬性的 Chunk／Fact 節點，導致 SVOTriple(subject=None)
    # 驗證失敗直接拋例外。此問題先前從未在正式環境重現過，因為所有既有 KG
    # 的 source_doc_id 一律為 None（見 § 3.1.4 §c），HAS_ENTITY／Fact 從未
    # 真正建立過，圖上根本沒有這些結構性邊可供誤走——直到今天才第一次有
    # KG 同時具備知識層與結構層邊，暴露出這個潛藏 bug。
    rel_types = "|".join(sorted(SVO_REL_TYPES))
    result = await driver.execute_query(
        f"""
        MATCH (seed:Entity {{kg_id: $kg_id}})
        WHERE seed.name IN $seed_entities
        MATCH path = (seed)-[:{rel_types}*1..{hops}]-(neighbor:Entity {{kg_id: $kg_id}})
        UNWIND relationships(path) AS rel
        WITH DISTINCT startNode(rel) AS s, rel, endNode(rel) AS o
        RETURN
            s.name AS subject,
            coalesce(s.type, "概念") AS subject_type,
            type(rel) AS rel_type,
            coalesce(rel.confidence, 1) AS confidence,
            rel.citations_json AS citations_json,
            o.name AS object,
            coalesce(o.type, "概念") AS object_type
        """,
        kg_id=str(kg_id),
        seed_entities=seeds,
    )

    triples: list[SVOTriple] = []
    for record in result.records:
        payload = dict(record)
        citations_json = payload.pop("citations_json", None)
        citations = json.loads(citations_json) if citations_json else []
        latest = citations[-1] if citations else {}
        payload["verb"] = latest.get("verb", payload["rel_type"])
        payload["source_doc_id"] = UUID(latest["source_doc_id"]) if latest.get("source_doc_id") else None
        payload["source"] = latest.get("source")
        payload["source_svo_chunk_index"] = latest.get("source_svo_chunk_index")
        payload["source_svo_chunk_file"] = latest.get("source_svo_chunk_file")
        payload["source_sentence_start"] = latest.get("source_sentence_start")
        payload["source_sentence_end"] = latest.get("source_sentence_end")
        triples.append(SVOTriple(**payload))
    return triples
