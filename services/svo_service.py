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
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Collection, Mapping, Sequence
from uuid import UUID

from neo4j import AsyncDriver
from neo4j.exceptions import ConstraintError

from core.constants import (
    COMPARE_COSINE_THRESHOLD,
    ENTITY_CANDIDATE_CANOPY_K,
    ENTITY_TYPES,
    FACT_SEARCH_CANDIDATE_MULTIPLIER,
    QSIM_ASSIGN_THRESHOLD,
    QSIM_ESCALATE_LOW_THRESHOLD,
    SVO_REL_TYPE_DESCRIPTIONS,
    SVO_REL_TYPES,
    VECTOR_DIM,
)
from core.config import task_queue_db_path
from core.kg_config import KGConfig
from core.kg_config.model import _DEFAULT_SVO_FEWSHOTS
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

logger = logging.getLogger(__name__)


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


_ENTITY_NAME_VECTOR_INDEX = "entity_name_vector"
_ENTITY_NAME_FULLTEXT_INDEX = "entity_name_fulltext"


async def create_entity_name_vector_index(driver: AsyncDriver | None = None, dim: int = VECTOR_DIM) -> None:
    """建立 Entity 節點名稱向量索引（app 啟動時呼叫一次），供
    `_fetch_entity_candidates()` 的 cosine canopy 使用（見 3.1.4 `DEDUP4`／
    報告40 §6.1）。`Entity` 仍是全 KG 共用單一 label（未比照 `Fact` 拆 per-KG
    label），故用全域索引＋查詢時 `WHERE e.kg_id = $kg_id` 後過濾，不像
    `Fact` 被迫 per-KG——`_fetch_entity_candidates()` 本來就帶 `kg_id` 過濾。"""
    if driver is None:
        return
    await driver.execute_query(
        f"""
        CREATE VECTOR INDEX {_ENTITY_NAME_VECTOR_INDEX} IF NOT EXISTS
        FOR (e:Entity) ON e.name_embedding
        OPTIONS {{ indexConfig: {{ `vector.dimensions`: $dim, `vector.similarity_function`: 'cosine' }} }}
        """,
        dim=dim,
    )


async def create_entity_name_fulltext_index(driver: AsyncDriver | None = None) -> None:
    """建立 Entity 節點名稱 fulltext 索引（CJK bigram analyzer，app 啟動時
    呼叫一次），供 `_fetch_entity_candidates()` 的字串 canopy 使用（報告40
    §3.3）。純附加、冪等；部署的 Neo4j 版本若不支援 `cjk` analyzer，
    `_fetch_entity_candidates()` 會在查詢時偵測失敗並退回 `CONTAINS`
    （見該函式 docstring），此處不需要回傳成敗旗標。"""
    if driver is None:
        return
    await driver.execute_query(
        f"""
        CREATE FULLTEXT INDEX {_ENTITY_NAME_FULLTEXT_INDEX} IF NOT EXISTS
        FOR (e:Entity) ON EACH [e.name]
        OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}
        """,
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


def _svo_prompt(text: str, *, fewshots: Sequence[str] | None = None) -> str:
    rel_types = ", ".join(sorted(SVO_REL_TYPES))
    selected_fewshots = _DEFAULT_SVO_FEWSHOTS if fewshots is None else fewshots
    fewshot_items = [
        f"{6 + index}. {example}" for index, example in enumerate(selected_fewshots)
    ]
    # 規則 6 在 35f95ab 的既有 prompt 中直接接在規則 5 後，規則 7–10
    # 之間則保留空行；保留這個微小的分隔差異才能讓 shipped default 逐字相容。
    fewshot_block = "\n\n".join(fewshot_items[1:])
    if fewshot_items:
        if fewshot_block:
            first_separator = f"\n{fewshot_items[1]}"
            remaining = "".join(f"\n\n{item}" for item in fewshot_items[2:])
            fewshot_block = fewshot_items[0] + first_separator + remaining
        else:
            fewshot_block = fewshot_items[0]
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
{fewshot_block}

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
    cfg: KGConfig | None = None,
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

    `cfg` 未傳（`None`）時 → `KGConfig()` 預設，`qsim_assign_threshold` /
    `qsim_escalate_low_threshold` == `QSIM_ASSIGN_THRESHOLD` /
    `QSIM_ESCALATE_LOW_THRESHOLD`，行為零變化（報告33 §6 第 4 步查詢端半）。
    """
    _cfg = cfg or KGConfig()
    best_type, best_score = await classify_relation_by_embedding(verb_phrase, embedding_provider)

    if best_score >= _cfg.reltype.qsim_assign_threshold:
        return best_type

    if best_score < _cfg.reltype.qsim_escalate_low_threshold or llm_provider is None:
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
    cfg: KGConfig | None = None,
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
    _cfg = cfg or KGConfig()
    if embedding_provider is None:
        return llm_rel_type

    best_type, best_score = await classify_relation_by_embedding(verb, embedding_provider)
    if best_type == llm_rel_type and best_score >= _cfg.reltype.compare_cosine_threshold:
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
    cfg: KGConfig | None = None,
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

    _cfg = cfg or KGConfig()
    raw = await llm_provider.generate_json(
        _svo_prompt(text, fewshots=_cfg.domain.svo_fewshots)
    )
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
                cfg=cfg,
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
            # 2026-08-31（見 docs/報告/21_抽取管線稽核與修正報告.md）：先前
            # 靜默 continue、完全沒有記錄——LLM 對規則8/9輸出非預期型別
            # （如 subject 給成陣列）時，這筆三元組被丟掉卻沒有任何線索，
            # 事後無法從log得知重跑到底漏了什麼。不拋例外中斷整批抽取
            # （單筆格式錯誤不該讓其他正確三元組也遺失），但至少留下記錄。
            # ⚠️ 2026-09-05 修正：`item` 可能帶上方剛加的 `verb_embedding`
            # （高維浮點陣列），原樣 `%r` 會把整條向量印進 log、灌爆日誌
            # 檔案（真實跑批次重抽時發現）。記錄前換成長度摘要。
            loggable = {k: (f"<embedding len={len(v)}>" if k == "verb_embedding" else v)
                        for k, v in item.items()}
            logger.warning("[extract_svo_triples] 三元組格式不合法，已捨棄：%r", loggable)
            continue
    return triples


UNCOVERED_SENTENCE_THRESHOLD = 0.6
"""涵蓋比對門檻——沿用 ProMem（Yang et al. 2026，arXiv:2601.04463）§Memory
Completion 的 τmatch 設定，尚未針對本專案中文法規語料與 bge-m3 embedding
模型重新校正，是先訂佔位數字、留待第五章消融實驗校準的既有慣例（比照
`EXPAND_POOL_MIN_SIZE`／`COMPARE_COSINE_THRESHOLD` 等既有門檻常數的處理
方式，見 `docs/報告/19_SVO抽取完整性自我核對機制設計報告.md` §3 誠實侷限）。
"""


async def _find_uncovered_sentences(
    original_sentences: Sequence[str],
    triples: list[SVOTriple],
    embedding_provider: EmbeddingProvider,
    *,
    threshold: float | None = None,
    cfg: KGConfig | None = None,
) -> list[str]:
    """比照 ProMem《Beyond Static Summarization》(arXiv:2601.04463) §Memory
    Completion 的語意涵蓋比對：對每一句原文，計算它與「已抽出三元組」的最高
    相似度，低於門檻視為未涵蓋——供 `extract_svo_triples_with_completeness_check()`
    判斷是否需要對這些句子額外做一次針對性補抽（`docs/報告/19` §3 設計）。

    這一步刻意不用LLM——先用便宜的embedding比對局部定位可能遺漏的片段，
    只有真的有未涵蓋句子才觸發後續的LLM補抽（見報告19 §5 成本分析：與
    VeriFact 的 word-mapping 演算法同屬「先用非LLM/輕量機制定位、才針對性
    觸發LLM」這個架構原則，本專案選用embedding是為了與既有抽取管線的向量
    基礎設施一致，而非word-mapping這種字串比對）。

    `triples` 為空（第一階段完全沒抽到任何三元組）時，全部句子視為未涵蓋；
    `original_sentences` 為空時直接回傳空清單，不做無意義的比對。

    門檻依序採用明確的 `threshold`、`cfg.extraction.uncovered_sentence_threshold`，
    最後才是 `KGConfig()` 的預設值（與既有常數相同）。
    """
    _cfg = cfg or KGConfig()
    threshold = threshold if threshold is not None else _cfg.extraction.uncovered_sentence_threshold
    if not original_sentences:
        return []
    if not triples:
        return list(original_sentences)

    sentence_vectors = await embedding_provider.encode_batch(list(original_sentences))
    triple_texts = [f"{t.subject}{t.verb}{t.object}" for t in triples]
    triple_vectors = await embedding_provider.encode_batch(triple_texts)

    uncovered: list[str] = []
    for sentence, s_vec in zip(original_sentences, sentence_vectors):
        best_score = max(cosine_similarity(s_vec, t_vec) for t_vec in triple_vectors)
        if best_score < threshold:
            uncovered.append(sentence)
    return uncovered


# 中文數字（含全形／半形阿拉伯數字混用）＋常見單位的量詞片語粗略偵測，
# 不要求完全精確（寧可多檢查幾個非量詞片語，也不要漏掉真正的量詞片語）。
_QUANTITY_PATTERN = re.compile(
    r"[〇零一二三四五六七八九十百千萬0-9]+"
    r"(?:至[〇零一二三四五六七八九十百千萬0-9]+)?"
    # 「等級」（2026-09-16，任務C第3組候選真實案例）：N0060041 §8「第一等級
    # 至第七等級」被抽成「第一等級至第十等級」——「十等級」逐字取自同文件
    # 完全不同的第34條，屬跨條文數字挪用，跟「三至七日」錯抽「一至三日」
    # （報告19§10）同一種根因，但原本的單位清單沒收「等級」，這個片語從未
    # 被 `_QUANTITY_PATTERN` 掃描到，數值忠實性核對因此對這筆三元組完全失效。
    r"(?:日|月|年|次|小時|分鐘|百分之|％|%|元|倍|等級)"
)

# 比 `_QUANTITY_PATTERN` 更寬的「分段量詞」偵測——多收「歲／人／名／週／度／
# 種／類／條／款／項／點」等法規列舉分段常用的單位。原設計**只給
# `resolve_entity_name()` 的模糊合併守衛用**（報告25 §4 發現C／診斷 Q3），
# 2026-09-05（報告26 §4 #6）新增第二個用途：`_naturalization_dropped_
# quantity()` 借用同一組樣式核對自然語言化輸出是否遺漏量詞/日期片語，
# 兩個用途共用同一份「量詞/日期片語」定義，不必另建一份重複清單：
# `年齡未滿六歲者`／`年齡六歲以上未滿十二歲者`／`年齡十二歲以上未滿十五歲者`
# 這種「字面高度相似、分段值不同」的主詞，被 `_edit_ratio` 0.80／cosine 0.88
# 誤併成一個節點，三段工時上限（二／三／四小時）全接到同一個節點、
# `natural_text` 還被寫錯段。`_QUANTITY_PATTERN` 刻意不動（發現3 的
# `_quantity_mis_bound_to_clause`／報告20 的 `_contains_ungrounded_quantity`
# 對「數量忠實性」的語意較窄，混進「歲／人／條」會擴大它們的誤判面）。
_MEASURE_PATTERN = re.compile(
    r"[〇零一二三四五六七八九十百千萬0-9]+"
    r"(?:至[〇零一二三四五六七八九十百千萬0-9]+)?"
    # `個月／個年／個星期`（報告32 §9.3 E3，2026-09-07）：`X個月` 的「個」卡在數字
    # 與「月」之間，舊樣式抓不到——導致 `三個月為限`／`六個月為限` 這類期程分段
    # 主詞在 `resolve_entity_name` 沒被守衛擋（全庫掃描實際命中），且 `六個月`
    # 期程不受 `_naturalization_dropped_quantity()` 的逐字核對。放在 `_MEASURE_PATTERN`
    # 而不動 `_QUANTITY_PATTERN`（發現3／報告20 語意較窄，比照發現C）。
    r"(?:個月|個年|個星期|日|月|年|次|小時|分鐘|百分之|％|%|元|倍|等級|歲|人|名|週|度|種|類|條|款|項|點)"
)

# 數字＋（選配單位）＋「以上／以下／以內／未滿／超過」的比較句式偵測
# （報告29 §2.4／§4.3，2026-09-05，報告26 §4 #3 Q8 真實根因診斷）。法規門檻／
# 級距表（變量係數表、罰鍰級距等）常見寫法如「1 以上，未滿 10」「100 以上，
# 未滿 1000」——數字後面接的是比較詞而非 `_MEASURE_PATTERN` 認得的單位，
# 結構上抓不到，導致整段級距表在 `resolve_entity_name()` 被模糊合併壞（真實
# 案例：N0060004 容許暴露標準變量係數表 5 段被併成 2 個節點，其中一個同時
# 掛 3 個互相矛盾的係數值，Q8 需要的「1以上未滿10→2」完全從圖中消失）。
# 跟 `_MEASURE_PATTERN` 同樣只給 `resolve_entity_name()` 的模糊合併守衛用、
# 同樣是早退機制（見該函式 §4.3 設計說明：量詞類實體只准精確比對，不同數值
# range 之間沒有「同類可合併」的中間地帶，跟 `_SCOPE_MODIFIER_PATTERN` 的
# 雙向過濾機制不同）。
#
# v2（報告32 §9.3 F2，2026-09-07）：v1 的 `[數字]\s*(以上|以下|以內)` 要求數字
# 與比較詞相鄰（只允許空白），中間夾一個單位就失效——真實案例 `血中鉛濃度在
# 十 μg/dl 以上者` 被誤併進 `五 μg/dl 以上未達十 μg/dl`（第一級），「≥10→第三級」
# 事實從圖中消失（報告32 Q6）。改為在數字與比較詞之間允許至多 12 個非標點字元
# （非貪婪），涵蓋 `十 μg/dl 以上`、`二十公尺 以上`、`五百平方公尺 以上`；
# 既有「1 以上，未滿 10」等案例無迴歸（`\s*` 是新字元類的子集）。
_RANGE_COMPARATOR_PATTERN = re.compile(
    r"[〇零一二三四五六七八九十百千萬0-9]+[^，,。；;、（）()]{0,12}?(?:以上|以下|以內)"
    r"|(?:未滿|超過)[^，,。；;、（）()]{0,12}?[〇零一二三四五六七八九十百千萬0-9]+"
)

# 序數／分數／小數／附表列舉守衛（報告32 §9.3 F3b，2026-09-07）——`_MEASURE_PATTERN`
# （要單位）與 `_RANGE_COMPARATOR_PATTERN`（要比較詞）都抓不到的列舉主詞：
# `第三級管理`（`級` 不在 `_MEASURE_PATTERN`，vs `第一級管理`）、`二分之一`／`五分之一`、
# WBGT 溫度 `30.6℃`／`32.6℃`、變量係數 `1.25`／`1.5`、`附表一`／`附表二`、
# `精密作業之一`／`精密作業之三`。同 `_RANGE_COMPARATOR_PATTERN` 走早退（這類名稱
# 本身即精確列舉標記，不該跟任何東西模糊合併）。F3a「補 `_MEASURE_PATTERN` 單位表」
# 刻意不做：`_MEASURE_PATTERN` 已被 `_naturalization_dropped_quantity()`（報告26 §4 #6）
# 共用，擴大它會連帶讓自然語言化核對更嚴——`級` 走這裡、`公尺／μg/dl` 走 v2 的單位間隔。
# 2026-09-18（任務C第9組真實重抽）：`具顯著／中度／低度風險者` 是封閉列舉值，彼此只差一字；
# 曾把原文正確抽出的「具低度風險者」模糊合併成「具中度風險者」，造成第三類事業的 Fact 錯接。
# 三種風險值加入同一精確比對守衛，防止列舉成員跨值合併。
_ENUM_GUARD_PATTERN = re.compile(
    r"第[〇零一二三四五六七八九十百千0-9]+級"
    r"|[〇零一二三四五六七八九十百千0-9]+分之[〇零一二三四五六七八九十百千0-9]+"
    r"|[0-9]+\.[0-9]+"
    r"|附表[〇零一二三四五六七八九十0-9]+"
    r"|之[〇零一二三四五六七八九十]+$"
    r"|(?:顯著|中度|低度)風險"
)

# 範圍修飾詞守衛（報告29 §4.1／報告32 §9.3，2026-09-07）——「基礎量 vs 遞增量」：
# `每一型式` vs `每增加一種型式`（`_edit_ratio`＝0.727、不含任何量詞，`_MEASURE_PATTERN`／
# `_RANGE_COMPARATOR_PATTERN` 都不命中）。「增加／額外／追加／新增／逾／超出」這個修飾詞把
# 「基礎量」改成「遞增量」，語意相反、表面極相似。與 `_MEASURE_PATTERN`／§4.3 的早退不同：
# 此處做**雙向過濾**——比對迴圈前依「是否含範圍修飾詞」把候選清單與 `name` 分同異兩類、
# 只保留同類候選再比對（含修飾詞的彼此仍可正常合併，不含的彼此也是）。
_SCOPE_MODIFIER_PATTERN = re.compile(r"增加|增列|額外|追加|新增|另計|加計|超出")


def _has_scope_modifier(name: str) -> bool:
    return _SCOPE_MODIFIER_PATTERN.search(name) is not None


def _contains_ungrounded_quantity(text: str, source_text: str) -> bool:
    """`docs/報告/20_抽取數值忠實性核對機制設計報告.md` §3：偵測 `text`
    （三元組 subject 或 object）裡是否含有數量／期限用字，且該片段未逐字
    出現在 `source_text`（chunk 原文）裡——真的偵測到才回傳 True。

    根因（報告20 §2）：同一份輸入文字，不同次真實LLM呼叫可能產生不同
    結果（temperature=0 不保證LLM推論決定性輸出，Horace He 2025），真實
    案例是把「三至七日」錯抽成同文件另一條文的「一至三日」。純字串比對
    刻意不用embedding——數量用字需要精確比對，語意相似度比對反而會讓
    結構相似但數值不同的片語被誤判為語意相近而放行。
    """
    for match in _QUANTITY_PATTERN.finditer(text):
        if match.group() not in source_text:
            return True
    return False


# 假別（請假類型）詞彙家族（2026-09-16，任務C第2組候選真實案例）——
# N0030006 §7「事假期間不給工資」／§8「公假…工資照給」被抽成「產假期間
# 不給工資」／「產假期間照給工資」，但整份文件完全沒有「產假」的實質
# 規定，「產假」一詞只出現在完全不同的條文（§9 流產請假參照句）。跟
# `_QUANTITY_PATTERN` 抓的數字挪用同一種根因（同文件跨條文借用），差別
# 只在挪用的是類別名詞而非數字——重跑同一 chunk 3 次結果完全不變，是
# 決定性 bug 不是隨機雜訊，單純重試無法修正，需要字面比對守衛。
# 詞彙互斥（同一子句只會屬於其中一種假別），比照 `_rival_quantity()`
# 的手法，純字串比對，不需 embedding。
_LEAVE_TYPE_FAMILY: tuple[str, ...] = (
    "事假", "病假", "公假", "婚假", "喪假", "產假", "陪產假",
    "育嬰留職停薪", "特別休假", "公傷病假", "普通傷病假",
)

# 目前只驗證過假別這一組家族；未來若發現其他「同文件跨條文借用類別
# 名詞」的真實案例（例如職災等級／給付類別），比照這裡加一份新家族
# tuple 再併進本清單即可，不需改動比對邏輯本身。
_ENTITY_FAMILIES: tuple[tuple[str, ...], ...] = (_LEAVE_TYPE_FAMILY,)


def _rival_family_term(term: str, family: Sequence[str], source_text: str) -> str | None:
    """`family`（互斥類別詞彙表）裡除了 `term` 以外，是否有其他成員逐字
    出現在 `source_text`——有的話回傳第一個，代表三元組本該用這個詞彙。"""
    for other in family:
        if other != term and other in source_text:
            return other
    return None


def _contains_ungrounded_family_term(text: str, source_text: str) -> bool:
    """比照 `_contains_ungrounded_quantity()`：`text`（三元組 subject 或
    object）裡若含有 `_ENTITY_FAMILIES` 任一互斥類別詞彙表裡的詞，但該詞
    未逐字出現在 `source_text`（chunk 原文）、且家族裡「另一個」成員卻
    出現在原文——判定為跨條文借用，回傳 True。

    只在「另一個成員確實存在於原文」時才觸發，避免對『這份文件根本沒提到
    任何家族詞彙』的正常三元組誤殺（比照報告20/25 的降級哲學：寧可漏抓，
    不可誤殺）。
    """
    for family in _ENTITY_FAMILIES:
        for term in family:
            if term in text and term not in source_text:
                if _rival_family_term(term, family, source_text) is not None:
                    return True
    return False


# 條號／列舉項目的起始標記（「一、」「（一）」「1.」等）與句末標點，切子句
# 時一併當分隔點——讓「一、三十日以上：於十日前提出。二、未滿三十日：於
# 五日前提出。」被切成兩個獨立子句，而非黏成一句、使子句層級綁定核對失效。
_CLAUSE_SPLIT_PATTERN = re.compile(
    r"[。；\n]+"
    r"|(?=[一二三四五六七八九十]+、)"
    r"|(?=（[一二三四五六七八九十]+）)"
    r"|(?=\d+[.、)])"
)

_BINDING_NORMALIZE_PATTERN = re.compile(r"[\s、，。：:；「」（）()【】]")

# 子句層級綁定核對只對「夠有辨識度」的 subject 觸發：正規化後長度未達此值
# 的 subject（多為「受僱者」「雇主」「勞工」這類角色詞，且常在具體子句中被
# 省略）不做綁定判斷，避免誤殺——見 docs/報告/25 §4 發現3。
_MIN_BINDING_SUBJECT_LEN = 4


def _split_into_clauses(text: str) -> list[str]:
    """把一段原文切成子句（依句末標點與列舉項目起始標記）。"""
    return [seg.strip() for seg in _CLAUSE_SPLIT_PATTERN.split(text) if seg and seg.strip()]


def _normalize_for_binding(text: str) -> str:
    """比對子句綁定時的輕度正規化：去空白與常見標點、並統一轉繁體，讓
    subject 與子句用字的細微標點差異、以及抽取 LLM 偶發的簡繁混用
    （`qwen2.5:7b` 對繁體輸入有時輸出簡體字，見報告25 §4 發現4）不影響
    substring 判斷——否則簡體 subject 在繁體原文裡永遠找不到歸屬子句，
    子句層級綁定核對會被這個守衛條件靜默略過（報告25 §4 發現3 收尾發現）。"""
    return _BINDING_NORMALIZE_PATTERN.sub("", _to_traditional(text))


_BINDING_UNITS = ("百分之", "小時", "分鐘", "日", "月", "年", "次", "％", "%", "元", "倍")


def _quantity_unit(phrase: str) -> str:
    """取數量片語結尾的單位（「十日前」的 phrase 是 `_QUANTITY_PATTERN` 抓到的
    「十日」，回傳「日」）。取不到回傳空字串。"""
    for unit in _BINDING_UNITS:
        if phrase.endswith(unit):
            return unit
    return ""


def _rival_quantity(phrase: str, clause_texts: Sequence[str]) -> str | None:
    """`clause_texts` 裡是否有「與 `phrase` 同單位、但不同值」的競爭數量片語。
    有的話回傳第一個，代表三元組本該用這個值。"""
    unit = _quantity_unit(phrase)
    if not unit:
        return None
    for text in clause_texts:
        for other in _QUANTITY_PATTERN.findall(text):
            if other != phrase and _quantity_unit(other) == unit:
                return other
    return None


def _quantity_mis_bound_to_clause(
    triple: SVOTriple, source_text: str, original_sentences: Sequence[str] | None,
) -> bool:
    """`docs/報告/25_擴大版新舊KG問答品質比對報告.md` §4 發現3：把報告20 的
    數值忠實性核對從「字詞層級」擴充到「子句層級綁定」。

    報告20 的 `_contains_ungrounded_quantity()` 只檢查數量/期限用字有沒有
    逐字出現在 chunk 原文裡——但真實失效案例（報告25 Q7「每增加一種型式
    加收八千元」實為四千元、Q2「三十日以上於五日前提出」實為十日前）中，
    錯誤數字**確實逐字出現在同一 chunk 的另一個列舉子句**，字詞層級核對
    因此放行。

    子句層級綁定核對：對三元組 verb＋object 裡的每個數量片語 Q，找出原文中
    逐字包含 Q 的子句（Q 的「歸屬子句」）。若同時滿足——
      (1) subject 夠有辨識度（正規化後長度 ≥ `_MIN_BINDING_SUBJECT_LEN`）、
          在原文裡確實有自己的歸屬子句；
      (2) subject 的歸屬子句與 Q 的歸屬子句**完全不相交**；
      (3) subject 的歸屬子句裡帶著一個「同單位、不同值」的競爭數字
          （三元組本該用它）；
    ——才判定 Q 是從別的列舉子句挪過來錯接，回傳 True（應丟棄）。

    條件 (3) 是關鍵的誤殺防線：像「給予三至七日之特別休假：一、<條件>」
    這種「數字在共用句幹、條件在列舉項目」的正常法條，條件子句本身沒有
    競爭數字，不會被誤判。

    保守設計（寧可漏抓、不可誤殺，比照報告19/20 的降級哲學）：任一條件
    不成立就回傳 False。子句切分優先用 `original_sentences`（再各自切子句），
    沒有時退回切 `source_text`。純字串比對，不需額外 LLM／embedding 呼叫。
    """
    subj_norm = _normalize_for_binding(triple.subject)
    if len(subj_norm) < _MIN_BINDING_SUBJECT_LEN:
        return False

    units = list(original_sentences) if original_sentences else [source_text]
    clauses: list[str] = []
    for unit in units:
        clauses.extend(_split_into_clauses(unit))
    if not clauses:
        return False

    clauses_norm = [(_normalize_for_binding(c), c) for c in clauses]
    subject_clauses = [(cn, orig) for cn, orig in clauses_norm if subj_norm in cn]
    if not subject_clauses:
        # subject 在原文裡找不到對應子句（多為 coref 正規化後的標準名）：
        # 無從判斷綁定對錯，不丟。
        return False
    subject_clause_keys = {cn for cn, _ in subject_clauses}
    subject_clause_texts = [orig for _, orig in subject_clauses]

    for phrase in _QUANTITY_PATTERN.findall(f"{triple.verb}{triple.object}"):
        home_keys = {cn for cn, orig in clauses_norm if phrase in orig}
        if not home_keys or not subject_clause_keys.isdisjoint(home_keys):
            continue
        if _rival_quantity(phrase, subject_clause_texts) is not None:
            return True
    return False


_RISK_LEVEL_BY_BUSINESS_CATEGORY = {
    "第一類事業": "顯著風險",
    "第二類事業": "中度風險",
    "第三類事業": "低度風險",
}


def _risk_category_misbound_to_clause(
    triple: SVOTriple, source_text: str, original_sentences: Sequence[str] | None,
) -> bool:
    """攔截事業類別與風險等級從相鄰列舉項目錯接的三元組。

    只在三元組明確提到單一類別和單一風險等級、原文同一類別子句含有
    另一個等級，且抽出的等級實際屬於其他類別子句時才丟棄。這個窄條件
    避免影響同時比較多個類別的三元組，或來源沒有明確對應關係的內容。
    """
    triple_text = _normalize_for_binding(f"{triple.subject} {triple.verb} {triple.object}")
    categories = [
        (category, level)
        for category, level in _RISK_LEVEL_BY_BUSINESS_CATEGORY.items()
        if _normalize_for_binding(category) in triple_text
    ]
    levels = [
        level for level in _RISK_LEVEL_BY_BUSINESS_CATEGORY.values()
        if _normalize_for_binding(level) in triple_text
    ]
    if len(categories) != 1 or len(levels) != 1:
        return False

    category, expected_level = categories[0]
    observed_level = levels[0]
    if observed_level == expected_level:
        return False

    units = list(original_sentences) if original_sentences else [source_text]
    clauses = [
        _normalize_for_binding(clause)
        for unit in units
        for clause in _split_into_clauses(unit)
    ]
    category_norm = _normalize_for_binding(category)
    expected_norm = _normalize_for_binding(expected_level)
    observed_norm = _normalize_for_binding(observed_level)
    category_clauses = [clause for clause in clauses if category_norm in clause]
    if not any(expected_norm in clause for clause in category_clauses):
        return False

    observed_belongs_to_sibling = any(
        observed_norm in clause
        and any(
            _normalize_for_binding(other_category) in clause
            for other_category in _RISK_LEVEL_BY_BUSINESS_CATEGORY
            if other_category != category
        )
        for clause in clauses
    )
    return observed_belongs_to_sibling


def _filter_ungrounded_quantity_triples(
    triples: list[SVOTriple], source_text: str,
    original_sentences: Sequence[str] | None = None,
) -> list[SVOTriple]:
    """丟棄含未忠實數量/期限用字、跨條文借用類別詞彙、或列舉值錯接的三元組。

    四層核對：

    1. **字詞層級**（報告20）：subject／object 的數量用字未逐字出現於原文
       → 丟（跨條文數字挪用，如「三至七日」錯抽成「一至三日」）。
    2. **子句層級綁定**（報告25 §4 發現3）：數量用字逐字出現在原文、但
       出現它的子句與三元組 subject 的歸屬子句不相交 → 丟（數字錯接到
       別的列舉項目，如 Q7「每增加一種型式加收八千元」實為四千元）。
    3. **類別詞彙家族**（2026-09-16，任務C第2組候選）：subject／object 含
       `_ENTITY_FAMILIES` 裡的詞、該詞未逐字出現於原文、但家族裡另一個
       詞卻出現於原文 → 丟（假別跨條文借用，如「事假」被抽成「產假」）。
    4. **列舉子句類別值綁定**（2026-09-18，任務C第9組候選）：三元組將
       正確出現在同一 chunk 的風險等級接到錯誤事業類別，且來源子句明確
       顯示該值屬於相鄰類別 → 丟（「第三類事業」被配成「具中度風險者」）。

    寧可漏抓一筆有疑慮的三元組，也不留下錯誤數字污染圖譜（比照 3.1.3
    REJECT 不阻斷整體、report16/19 既有的降級哲學）。

    2026-08-31（見 docs/報告/21_抽取管線稽核與修正報告.md）：丟棄的三元組
    會記錄一筆 warning——上線首日完全沒有留下任何線索，無法統計這次修正
    實際攔了幾筆、也無法區分「這個chunk本來就沒有數量用字」跟「有數量
    用字但被攔下來了」，稽核時發現這是本機制自己需要補的缺口。
    """
    kept: list[SVOTriple] = []
    for t in triples:
        if _contains_ungrounded_quantity(t.subject, source_text) or _contains_ungrounded_quantity(
            t.object, source_text
        ):
            logger.warning(
                "[數值忠實性核對] 丟棄疑似跨段落挪用數字的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        if _contains_ungrounded_family_term(t.subject, source_text) or _contains_ungrounded_family_term(
            t.object, source_text
        ):
            logger.warning(
                "[類別詞彙忠實性核對] 丟棄疑似跨條文借用類別詞彙的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        if _quantity_mis_bound_to_clause(t, source_text, original_sentences):
            logger.warning(
                "[數值忠實性核對] 丟棄數字錯接到別的列舉子句的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        if _risk_category_misbound_to_clause(t, source_text, original_sentences):
            logger.warning(
                "[列舉類別值忠實性核對] 丟棄類別與值錯接的三元組：'%s' -[%s]-> '%s'",
                t.subject, t.verb, t.object,
            )
            continue
        kept.append(t)
    return kept


async def extract_svo_triples_with_completeness_check(
    text: str,
    original_sentences: Sequence[str],
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    *,
    kg_id: str | None = None,
    calibration_db_path: Path | None = None,
    cfg: KGConfig | None = None,
) -> list[SVOTriple]:
    """`extract_svo_triples()` 的完整性自我核對版本（`docs/報告/19_SVO抽取
    完整性自我核對機制設計報告.md` §3／§3.1，2026-08-31 設計，同日實作）。

    背景：規則7-9（`_svo_prompt()` few-shot 反例/正例）能提升第一階段的
    初始召回率，但只能讓 LLM 泛化到「跟範例夠像」的情況，遇到範例沒示範過
    的附加規定類別仍會漏抓（真實案例：以小時為請假單位，見報告18 §3.6）。
    本函式不取代規則7-9、也不要求精簡它們——兩者並存：規則7-9 降低第一階段
    的遺漏量、間接減少本函式第二階段需要補抽的量（成本考量）；本函式的
    涵蓋比對＋針對性補抽才是**真正保證召回率**的通用機制，不依賴事先窮舉
    附加規定類別（使用者 2026-08-31 決策：「先以涵蓋為主，補充為輔」）。

    流程：① 第一階段沿用現有 `extract_svo_triples()`；② 用
    `_find_uncovered_sentences()`（非LLM，embedding比對）定位未涵蓋句子；
    ③ 僅未涵蓋句子非空時才觸發第二次 `extract_svo_triples()` 呼叫，只對
    這些句子重新抽取；④ 合併去重。

    成本模型對稱於報告16接地核對機制：只有真的偵測到問題（此處是「有句子
    未涵蓋」）才多花一次 LLM 呼叫，多數已抽得夠完整的 chunk 不會觸發第二次
    呼叫（見報告19 §5，非無條件翻倍）。

    `original_sentences` 為空、或 `embedding_provider` 為 `None` 時，涵蓋
    比對無法執行，直接回傳第一階段結果，不強行報錯——優雅降級，行為等同
    直接呼叫 `extract_svo_triples()`。

    ✅ **數值忠實性核對（2026-08-31，報告20；2026-09-03 擴充子句層級綁定，
    報告25 §4 發現3）**：不管走哪個分支，回傳前一律套用
    `_filter_ungrounded_quantity_triples()`——除了丟棄 subject／object 含
    「數量/期限用字未逐字出現於 `text`」的三元組（報告20），再多一層子句
    層級綁定核對：數量用字雖逐字出現、但落在與三元組 subject 不相干的
    列舉子句 → 也丟（報告25 Q7/Q2 真實案例）。子句切分用 `original_sentences`，
    沒有時退回切 `text`。純字串比對，不需額外 LLM／embedding 呼叫。
    """
    triples = await extract_svo_triples(
        text, llm_provider, embedding_provider, kg_id=kg_id, calibration_db_path=calibration_db_path,
        cfg=cfg,
    )

    if not original_sentences or embedding_provider is None:
        return _filter_ungrounded_quantity_triples(triples, text, original_sentences or None)

    uncovered = await _find_uncovered_sentences(
        original_sentences, triples, embedding_provider, cfg=cfg,
    )
    if not uncovered:
        return _filter_ungrounded_quantity_triples(triples, text, original_sentences)

    supplement_text = "\n".join(uncovered)
    supplement_triples = await extract_svo_triples(
        supplement_text, llm_provider, embedding_provider,
        kg_id=kg_id, calibration_db_path=calibration_db_path,
        cfg=cfg,
    )

    seen = {(t.subject, t.verb, t.object) for t in triples}
    merged = list(triples)
    for t in supplement_triples:
        key = (t.subject, t.verb, t.object)
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return _filter_ungrounded_quantity_triples(merged, text, original_sentences)


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


async def _fetch_entity_candidates_canopy(
    driver: AsyncDriver,
    kg_id: UUID,
    name: str,
    *,
    embedding_provider: EmbeddingProvider | None,
    canopy_k: int,
) -> list[dict]:
    """報告40 §3 的三 canopy 聯集：exact（唯一約束）＋ cosine（向量索引
    top-`canopy_k`，需 `embedding_provider` 才能對 `name` 編碼）＋ 字串
    （fulltext CJK bigram，索引不存在/不支援時當場退回 `CONTAINS`）。
    只在 `_fetch_entity_candidates()` 有 `name` 可供 canopy 比對時呼叫。"""
    kg_id_str = str(kg_id)
    by_name: dict[str, dict] = {}

    exact = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id, name: $name}) "
        "RETURN e.name AS name, e.type AS type, e.name_embedding AS name_embedding",
        kg_id=kg_id_str, name=name,
    )
    for r in exact.records:
        by_name[r["name"]] = {"name": r["name"], "type": r.get("type"), "name_embedding": r.get("name_embedding")}

    if not name.strip():
        # Ollama 對空字串回傳 0 維 embedding，Neo4j vector index 不接受；空字串
        # 的 CONTAINS canopy 也會匹配過多節點，因此只保留精確名稱結果。
        return list(by_name.values())

    if embedding_provider is not None:
        name_vec = await embedding_provider.encode(name)
        cosine_result = await driver.execute_query(
            f"""
            CALL db.index.vector.queryNodes('{_ENTITY_NAME_VECTOR_INDEX}', $k, $vec)
            YIELD node AS e, score
            WHERE e.kg_id = $kg_id
            RETURN e.name AS name, e.type AS type, e.name_embedding AS name_embedding
            """,
            k=canopy_k, vec=name_vec, kg_id=kg_id_str,
        )
        for r in cosine_result.records:
            by_name.setdefault(
                r["name"], {"name": r["name"], "type": r.get("type"), "name_embedding": r.get("name_embedding")}
            )

    try:
        ft = await driver.execute_query(
            f"""
            CALL db.index.fulltext.queryNodes('{_ENTITY_NAME_FULLTEXT_INDEX}', $q)
            YIELD node AS e
            WHERE e.kg_id = $kg_id
            RETURN e.name AS name, e.type AS type, e.name_embedding AS name_embedding
            """,
            q=name, kg_id=kg_id_str,
        )
        string_records = ft.records
    except Exception:  # noqa: BLE001 -- fulltext 索引缺席/analyzer 不支援，優雅退回 CONTAINS（報告40 §3.3）
        contains = await driver.execute_query(
            "MATCH (e:Entity {kg_id: $kg_id}) WHERE e.name CONTAINS $name OR $name CONTAINS e.name "
            "RETURN e.name AS name, e.type AS type, e.name_embedding AS name_embedding",
            kg_id=kg_id_str, name=name,
        )
        string_records = contains.records
    for r in string_records:
        by_name.setdefault(
            r["name"], {"name": r["name"], "type": r.get("type"), "name_embedding": r.get("name_embedding")}
        )

    return list(by_name.values())


async def _fetch_entity_candidates(
    driver: AsyncDriver,
    kg_id: UUID,
    entity_type: str,
    name: str | None = None,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    canopy_k: int = ENTITY_CANDIDATE_CANOPY_K,
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

    **2026-09-14 效能改造（見 3.1.4 `DEDUP4` 節點向量化效能改造／報告40，
    Pass 2 L6 R2）**：`name` 有提供時（正式路徑 `merge_entity()` 恆提供），
    改用 `_fetch_entity_candidates_canopy()` 的三 canopy 聯集（exact／cosine
    向量索引 top-`canopy_k`／字串 fulltext-or-CONTAINS），取代全 KG 掃描——
    候選集從 O(n) 縮到 O(canopy_k)，`resolve_entity_name()` 的判準與門檻
    完全不變，只是換了候選來源。300-mention 抽樣驗證新舊候選集 100% 一致
    （`compare_entity_candidate_recall_result.json`）。`name` 缺席（僅供內部
    直接呼叫型別篩選邏輯的呼叫端）或未提供 `embedding_provider` 時，退回
    全 KG 掃描／略過 cosine canopy——**行為保守，寧可多掃不可漏候選**。
    """
    if name is None:
        result = await driver.execute_query(
            "MATCH (e:Entity {kg_id: $kg_id}) RETURN e.name AS name, e.type AS type, e.name_embedding AS name_embedding",
            kg_id=str(kg_id),
        )
        records = [
            {"name": r["name"], "type": r.get("type"), "name_embedding": r.get("name_embedding")}
            for r in result.records
        ]
    else:
        records = await _fetch_entity_candidates_canopy(
            driver, kg_id, name, embedding_provider=embedding_provider, canopy_k=canopy_k
        )

    query_types = _type_set(entity_type)
    if not query_types:
        return [{"name": r["name"], "name_embedding": r.get("name_embedding")} for r in records]
    return [
        {"name": r["name"], "name_embedding": r.get("name_embedding")}
        for r in records
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
    cfg: KGConfig | None = None,
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
    _cfg = cfg or KGConfig()
    if not candidates:
        return name

    # 2026-09-03（`docs/報告/25_擴大版新舊KG問答品質比對報告.md` §4 發現3 收尾
    # 真實重抽發現）：數量／金額實體只准精確比對，不做編輯距離／cosine 模糊
    # 合併。真實案例——正確抽出的三元組 `每增加一種型式 → 新臺幣四千元`，在
    # merge 階段 `新臺幣四千元` 與既有的 `新臺幣八千元` 只差一字（`_edit_ratio`
    # ＝0.833 ≥ `ENTITY_DEDUP_EDIT_RATIO_THRESHOLD` 0.70），被誤併成同一實體，
    # 邊接到 `八千元`，把 Q7 的答案數字改錯。`四千/八千`、`五日/十日`、
    # `三十日以上/未滿三十日` 這類「字面高度相似、數值完全不同」的量詞實體，
    # 模糊合併必然出錯——直接回傳原名，交由下游 `MERGE (e:Entity {kg_id, name})`
    # 做精確去重即可（發現3 的子句層級核對在 merge 前跑、攔不到這個 merge 期
    # 的錯併，兩者互補）。
    #
    # 2026-09-03 擴大（發現C／診斷 Q3）：守衛從 `_QUANTITY_PATTERN` 換成更寬的
    # `_MEASURE_PATTERN`——多收「歲／人／條／款」等法規列舉分段常用單位。真實
    # 案例：`年齡未滿六歲者`／`年齡六歲以上未滿十二歲者`／`年齡十二歲以上未滿
    # 十五歲者` 被 `_edit_ratio` 0.80／cosine 0.88 誤併成一個節點，三段每日
    # 工時上限（二／三／四小時）全接到同一個節點、`natural_text` 寫錯段。
    # 2026-09-05（報告29 §2.4／§4.3，報告26 §4 #3 Q8 真實根因診斷）：裸數字＋
    # 「以上／以下／以內／未滿／超過」比較句式，`_MEASURE_PATTERN` 抓不到
    # （數字後面接的是比較詞不是單位），法規門檻/級距表常見，同樣只准精確
    # 比對、不做模糊合併——理由見 `_RANGE_COMPARATOR_PATTERN` 定義處註解。
    # 2026-09-07（報告32 §9.3 F3b）：序數／分數／小數／附表列舉主詞（`第三級管理`／
    # `二分之一`／`30.6℃`／`附表一`／`精密作業之一`），前兩個守衛都抓不到，加進同一處早退。
    # 2026-09-18（任務C第9組）：事業風險等級（`具顯著／中度／低度風險者`）也是封閉列舉值；
    # 不得把正確抽出的第三類「低度」模糊合併成既有第二類「中度」實體。
    if (
        _MEASURE_PATTERN.search(name)
        or _RANGE_COMPARATOR_PATTERN.search(name)
        or _ENUM_GUARD_PATTERN.search(name)
    ):
        return name

    # 2026-09-07（報告29 §4.1／報告32 §9.3 §4.1）：範圍修飾詞雙向過濾。「基礎量 vs
    # 遞增量」——`每一型式`（無修飾詞）不該跟 `每增加一種型式`（有「增加」）模糊合併
    # （`_edit_ratio`＝0.727、無量詞、上面的早退守衛都不命中）。與早退不同，這裡只是
    # **縮小候選集**：把 `name` 與各候選依「是否含範圍修飾詞」分同異兩類，下方的模糊
    # 比對（編輯距離／cosine）只在同類候選內進行；exact 相符不受影響（仍先全量檢查）。
    _name_has_scope_mod = _has_scope_modifier(name)
    fuzzy_candidates = [
        c for c in candidates if _has_scope_modifier(c["name"]) == _name_has_scope_mod
    ]

    # 2026-08-19（真實審查發現並修復）：`_fetch_entity_candidates()` 的 Cypher
    # 查詢沒有 ORDER BY，Neo4j 回傳順序非決定性——若多個候選同時超過編輯距離
    # 門檻，原本「回傳第一個超過門檻的候選」在不同次執行間可能選到不同名稱，
    # 導致同一批資料的實體合併結果不可重現，與下方 cosine 相似度區塊、以及
    # 本專案其他地方（如 UMAP 固定 random_state=42）一貫的可重現性要求不一致。
    # 改為與 cosine 區塊同樣的寫法：走訪所有候選，取分數最高者，同分時保留
    # 先遇到的（Python min/max 對等值採穩定的「保留第一個」語意，但候選順序
    # 本身仍非決定性——此修復只保證「選到分數最高者」，不保證同分平局時的
    # 決定性，該情況本身即代表兩個候選對這次提及同樣合適，不影響合併正確性）。
    for c in candidates:
        if c["name"] == name:
            return name

    best_edit_name: str | None = None
    best_edit_ratio = 0.0
    for c in fuzzy_candidates:
        ratio = _edit_ratio(name, c["name"])
        if ratio >= _cfg.dedup.edit_ratio_threshold and ratio > best_edit_ratio:
            best_edit_ratio = ratio
            best_edit_name = c["name"]
    if best_edit_name is not None:
        return best_edit_name

    if embedding_provider is None:
        return name

    name_vec = await embedding_provider.encode(name)
    best_name: str | None = None
    best_score = 0.0
    for c in fuzzy_candidates:
        candidate_vec = c.get("name_embedding") or (await embedding_provider.encode(c["name"]))
        score = cosine_similarity(name_vec, candidate_vec)
        if score > best_score:
            best_score = score
            best_name = c["name"]

    if best_name is None:
        return name
    if best_score >= _cfg.dedup.cosine_threshold:
        return best_name

    if llm_provider is not None and best_score >= _cfg.dedup.escalate_low_threshold:
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
    cfg: KGConfig | None = None,
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
    candidates = await _fetch_entity_candidates(driver, kg_id, entity_type, name, embedding_provider=embedding_provider)
    resolved_name = await resolve_entity_name(
        name, candidates, embedding_provider=embedding_provider, llm_provider=llm_provider, cfg=cfg,
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
    （Baek et al., 2023）triple-to-text 模式——subject＋原始 verb＋object 直接
    串接，不引入額外的 graph-to-text 轉換模型（KAPING Appendix B.5 消融實驗
    顯示簡單串接檢索表現優於訓練過的轉換模型，見
    docs/參考文獻/12_三元組事實層級向量化與檢索/README.md）。

    `subject`／`object` 使用 DEDUP4 解析後的**canonical Entity 名稱**（而非
    這次提及的原始字串），`verb` 則保留這筆 citation 的原始措辭——兩者取捨
    不同：canonical 名稱讓 `(Fact)-[:HAS_SUBJECT]->(Entity)` 連結與 `fact_text`
    描述的對象一致，`verb` 沒有對應的「解析後版本」（動詞只被歸類到
    `rel_type`，不像實體有 canonical 名稱可用），保留原始措辭才能反映這筆
    citation 的實際語意細節。

    ⚠️ **型別括號已移除（2026-09-02，報告25 § 4 發現5）**：原本會在 subject／
    object 後綴 `（型別）`（如 `訓練時數（概念） 以三百小時為度 （概念）`）。
    真實查證（`vector_search_facts()` 對 bge-m3 的實測 cosine）發現：當型別
    是通用兜底值「概念」時，兩個 `（概念）` token 佔短事實字串近四成、且是
    純雜訊，明顯稀釋 `fact_embedding` 的語意——去掉後正確事實對問題的
    cosine 上升 +0.03～+0.10（跨文件雜訊事實幾乎不動，precision 也一併
    改善）。KAPING 引用的「簡單串接」本就是 `subject relation object`、
    不含型別標註，`（型別）` 是本專案先前額外加的、不在該引用涵蓋範圍。
    型別仍以 `subject_type`／`object_type` 存為 `Fact` 節點扁平屬性，需要的
    呼叫端（如 `_serialize_sources()`）照樣取得。
    """
    return f"{subject} {verb} {object_}".strip()


def _fact_code_prefix(source: str | None) -> str:
    """報告43（Fact-RAG 語意排名健壯性）選項B：從 `SVOTriple.source`／
    citation `source`（工作目錄名稱，法規類文件慣例格式 `<代碼>_<全名>`，
    見 `SVOTriple.source` 欄位 docstring）取出簡短的文件代碼，供
    `_fact_text_for_embedding()` 在嵌入前標記文件身分。

    報告41 §9 診斷：多部法規描述同一類概念（如「X 自 Y 起算」）時，
    `fact_text` 只有裸的 SVO 串接、完全沒有能區分「這是哪部法規」的訊號，
    語意相近但答非所問的跨文件事實會在全域 cosine 排名裡把正解擠開
    （26-Q5 案例：正解排名第41，被34條其他法規的近義事實擠出
    `top_k=20`）。Reuter et al. (2025) 命名同一類失效為 Document-Level
    Retrieval Mismatch，解法核心原則是「在被嵌入的文字本身注入能區分
    來源文件身分的上下文」（見 `docs/參考文獻/31_Fact-RAG語意排名健壯性/`）。

    只取底線前的代碼片段（非取整段檔名）——避免法規全名（可能十幾字）
    稀釋短事實字串裡 SVO 語意的權重比例（報告43 §3 選項B 風險項2）。
    非「代碼_全名」慣例命名的文件（無底線、或底線前非英數字）回傳空字串，
    呼叫端不加任何前綴——維持對非法規語料零風險。
    """
    if not source:
        return ""
    code, sep, _ = source.partition("_")
    if not sep or not code or not code.isalnum():
        return ""
    return code


def _fact_text_for_embedding(fact_text: str, source: str | None) -> str:
    """報告43 選項B：`fact_embedding` 實際嵌入的文字，跟儲存／顯示用的
    `fact_text` 刻意分開——只有這裡回傳的字串會被送進 embedding provider，
    `fact_text` 本身（存進 `Fact` 節點、供 `_arrange_fact_lines()` 顯示給
    LLM、`verify_fact_grounding()` 接地核對比對的原文）完全不受影響，
    避免這個檢索端最佳化意外波及生成端既有行為。
    """
    prefix = _fact_code_prefix(source)
    return f"（{prefix}）{fact_text}" if prefix else fact_text


@lru_cache(maxsize=1)
def _opencc_s2tw():
    """OpenCC 簡→繁（臺灣標準字）轉換器，惰性初始化。用 `s2tw`（字元級）而非
    `s2twp`（含詞彙轉換）——法規語料要的是字形正規化（台→臺、内→內、
    经→經），不希望詞彙層被改（如「软件」→「軟體」可能動到法律用語）。"""
    from opencc import OpenCC

    return OpenCC("s2tw")


def _to_traditional(text: str) -> str:
    """把字串正規化成臺灣標準繁體字。已是繁體時 OpenCC 近乎 identity。
    報告25 § 4 發現4：`qwen2.5:7b` 的自然語言化改寫偶爾漏簡體
    （`补助经费额度`／`训练`／`经费`），在既有 prompt「繁體中文」指示之外
    再加一道字元級保險。

    ⚠️ **會過度轉換**：OpenCC 把 `雇→僱`、`托→託`、`里→裡` 也當簡→繁字元
    映射，但這些字在臺灣法規原文有其正當用法（勞基法用「雇主」不用「僱主」、
    育嬰留停辦法原文是「停托」不是「停託」）。用於**內部比對**（如
    `_normalize_for_binding()` 兩邊都轉、過度轉換相互抵銷）沒問題；用於
    **寫回資料**（Entity 名稱／`fact_text`）時應改用
    `_to_traditional_selective()`，以來源語料實際用字為白名單。"""
    return _opencc_s2tw().convert(text)


def _to_traditional_selective(text: str, source_charset: frozenset[str] | None) -> str:
    """逐字選擇性簡→繁（報告25 §4 發現4，使用者 2026-09-03 選定「來源語料
    當白名單」）：只轉「OpenCC 會改、且該字不出現在這個 KG 的繁體來源文件
    裡」的字。`職`／`經`／`嬰`（來源 0 次）會轉；`雇`／`托`（來源實際在用）
    保留原字。`source_charset` 為 `None` 時退回 `_to_traditional()`（全轉，
    無來源可對照——優雅降級，行為等同舊版）。"""
    if source_charset is None:
        return _to_traditional(text)
    out = []
    for ch in text:
        tw = _opencc_s2tw().convert(ch)
        out.append(tw if (tw != ch and ch not in source_charset) else ch)
    return "".join(out)


@lru_cache(maxsize=8)
def _kg_source_charset(kg_folder: str) -> frozenset[str]:
    """蒐集這個 KG 所有繁體來源文件（`workspace/<kg>/<doc>/original.md`）出現
    過的字元集合，供 `_to_traditional_selective()` 當「這些字是合法繁體用字，
    不要動」的白名單。找不到任何來源檔時回傳空集合（等於全轉）。"""
    from pathlib import Path

    chars: set[str] = set()
    root = Path(kg_folder)
    if not root.exists():
        return frozenset()
    for src in root.glob("*/original.md"):
        try:
            chars.update(src.read_text(encoding="utf-8"))
        except OSError:
            continue
    return frozenset(chars)


#: 報告65 §6/§7 定向重抽驗證發現（2026-09-22）：`_to_traditional_selective()`
#: 是逐字比對白名單，遇到「單字本身是這個KG來源語料裡合法的繁體字、但用在
#: 特定詞組裡卻是簡體殘留」時會結構性失效——例如「准」在「核准」／「批准」
#: 是合法繁體用字，白名單因此保留它，但「准用」本應是「準用」，逐字比對
#: 抓不出「同一個字在這個詞組裡用錯」。這不是白名單邏輯寫錯，是逐字比對
#: 這個方法本身的粒度侷限，需要逐詞比對已知易錯詞組來補救。清單只收錄
#: 真實觀察到、且已核對過另一支語料的案例，不可臆測新增。
_KNOWN_SIMPLIFIED_COMPOUNDS: dict[str, str] = {
    # 報告65定向重抽驗證，57-AGGR19（N0050031 c85）真實案例。
    "准用": "準用",
    "基准法": "基準法",
}


def _fix_known_simplified_compounds(text: str) -> str:
    """逐字白名單處理不了的已知簡體殘留詞組，做逐詞取代補救（見上方常數
    docstring）。在 `_to_traditional_selective()` 之後呼叫，不取代它。"""
    for bad, good in _KNOWN_SIMPLIFIED_COMPOUNDS.items():
        text = text.replace(bad, good)
    return text


def traditionalize_triples(
    triples: list[SVOTriple], source_charset: frozenset[str] | None,
) -> list[SVOTriple]:
    """對一批三元組的 subject／verb／object 就地套用 `_to_traditional_selective()`
    ——抽取端修正 `qwen2.5:7b` 偶發輸出簡體字的失效（報告25 §4 發現4）。
    在 `extraction_worker._process_one()` merge 前呼叫；`source_charset` 由
    `_kg_source_charset(kg_folder)` 提供。逐字轉換後再補一次
    `_fix_known_simplified_compounds()`（報告65 §6/§7），涵蓋逐字白名單
    抓不到的已知易錯詞組。"""
    for t in triples:
        t.subject = _fix_known_simplified_compounds(_to_traditional_selective(t.subject, source_charset))
        t.verb = _fix_known_simplified_compounds(_to_traditional_selective(t.verb, source_charset))
        t.object = _fix_known_simplified_compounds(_to_traditional_selective(t.object, source_charset))
    return triples


_NATURALIZE_PROMPT_TEMPLATE = """把下列結構化事實改寫成一句通順的繁體中文自然語句，只輸出改寫後的句子本身，不要加引號、不要加任何說明或前綴。

主詞：{subject}
動作：{verb}
受詞：{object}

改寫時務必忠實於原意，不可以增加原文沒有的具體數字、期限或條件，也不可以省略主詞或受詞裡的關鍵資訊。若動作與受詞開頭字詞剛好重複（例如動作是「得以」、受詞開頭又是「以」），改寫時避免疊字重複，選用通順的講法而非逐字硬接。"""


def _naturalization_dropped_quantity(natural_text: str, subject: str, verb: str, object_: str) -> bool:
    """報告26 §4 #6／報告29-鄰近設計（`docs/參考文獻/25_三元組自然語言化
    遺漏偵測/README.md`）：`_naturalize_triple()` 的 LLM 改寫偶爾遺漏
    subject／verb／object 裡的量詞或日期片語（真實案例：`災害發生之當月
    一日起` 被改寫成「從災害發生之當月起…」，「一日」消失）——跟報告20
    「量詞接地核對」（`_contains_ungrounded_quantity`，核對輸出是否**新增**
    未依據內容）方向相反，是同一個「比對輸出與輸入」架構家族的鏡像版本：
    核對輸出是否**遺漏**了輸入裡的量詞/日期片語。

    沿用既有 `_MEASURE_PATTERN`（無需另外設計新樣式）從三個欄位抓出所有
    量詞/日期片語，逐一核對是否逐字留在 `natural_text` 裡；任一片語消失
    即回傳 `True`，由呼叫端決定是否退回樣板拼接（見 `_naturalize_triple()`）。
    """
    for field in (subject, verb, object_):
        for match in _MEASURE_PATTERN.finditer(field):
            if match.group(0) not in natural_text:
                return True
    return False


async def _naturalize_triple(
    subject: str,
    subject_type: str,
    verb: str,
    object_: str,
    object_type: str,
    llm_provider: LLMProvider,
) -> str:
    """把三元組改寫成自然語句（見 `docs/報告/24_事實清單自然語言化機制設計
    報告.md` § 4、§5 階段1）——取代 `routers/agent.py::_merge_fact_lines()`
    目前「主詞（型別）動詞受詞（型別）」的樣板拼接，解決報告23 §6.4對照
    實驗確認的根因：這種生硬格式會顯著降低 LLM 在生成階段引用該事實的
    機率，即使事實已經正確檢索、位置也排得夠前面。

    **與 `_verbalize_fact()`（§3.1.4 §a，供 Fact 節點 embedding 檢索用）的
    關係已在報告24 §2 釐清、不衝突**：KAPING（Baek et al., 2023）Appendix
    B.5 的「簡單串接優於訓練式轉換模型」結論測的是**檢索表現**，`_verbalize_
    fact()` 這個用途因此維持樣板拼接不變；本函式解決的是**生成階段**LLM
    能否引用已檢索事實，是不同問題面向，KAPING 未測試過這個面向。

    **忠實性風險提示（借鏡 KAPING 的觀察）**：KAPING 也觀察到訓練式轉換
    模型「有時生成語意偏離原三元組的文字」——prompt 因此明確要求「不可以
    增加原文沒有的具體數字、期限或條件」，降低幻覺風險；報告24 §5 階段4
    依當時實測幻覺率判斷不需要正式核對機制（只對殘缺三元組退回樣板拼接）。

    ✅ **遺漏偵測（2026-09-05，報告26 §4 #6 真實案例後新增）**：報告24 的
    忠實性防護只擋「編造內容」方向，報告26 §4 #6 發現真實案例走的是
    **相反方向**——`災害發生之當月一日起` 被改寫成「從災害發生之當月起…」，
    遺漏「一日」。新增 `_naturalization_dropped_quantity()` 核對，命中即
    捨棄 LLM 改寫、退回 `_verbalize_fact()` 樣板拼接（見下方回傳邏輯），
    與報告24 §5 階段4「殘缺三元組不呼叫LLM、直接退回樣板」同一取捨原則。
    文獻定位見 `docs/參考文獻/25_三元組自然語言化遺漏偵測/README.md`。

    `subject_type`／`object_type` 缺席時直接省略（比照 `_verbalize_fact()`
    同樣的「型別選填」處理），不強塞空字串進 prompt。失敗時（LLM 呼叫
    拋例外）由呼叫端決定如何處理，本函式不吞例外、不靜默降級。

    ✅ **疊字修正（2026-09-01，報告24 §8.4 真實回填品質觀察後新增）**：
    全KG真實回填發現偶有「得以以」這類疊字瑕疵（動作結尾字詞與受詞開頭
    字詞剛好相同，逐字硬接產生的冗贅）——語意忠實無誤，但不夠通順。
    prompt 加一句明確指示避免疊字，低成本 prompt 微調，非架構變更。
    """
    subject_part = f"{subject}（{subject_type}）" if subject_type else subject
    object_part = f"{object_}（{object_type}）" if object_type else object_
    prompt = _NATURALIZE_PROMPT_TEMPLATE.format(subject=subject_part, verb=verb, object=object_part)
    result = await llm_provider.generate(prompt)
    # 報告25 § 4 發現4：改寫輸出過一道 OpenCC 簡→繁（臺灣標準字）正規化，
    # 補救小模型偶爾漏簡體的情況（prompt 已要求繁體，這是保險不是取代）。
    result = _to_traditional(result.strip().strip("「」\"'"))
    if _naturalization_dropped_quantity(result, subject, verb, object_):
        return _verbalize_fact(subject, subject_type, verb, object_, object_type)
    return result


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


def _fact_fulltext_index_name(kg_id: str) -> str:
    return f"fact_text_fulltext_{str(UUID(kg_id)).replace('-', '_')}"


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
    cfg: KGConfig | None = None,
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

    **事實清單自然語言化（2026-09-01 實作，見報告24 § 5 階段1）**：
    `llm_provider` 提供時，把這筆citation的三元組改寫成自然語句存進
    `r.natural_text`（`_naturalize_triple()`），供 `routers/agent.py::
    _merge_fact_lines()` 生成 prompt 時優先使用，解決報告23 §6.4對照
    實驗確認的根因——樣板拼接文字太生硬會顯著降低LLM引用該事實的機率。
    每次有新citation合併時都重新生成、覆蓋舊值（與現行「`verb` 取最新
    一筆citation」慣例一致）；`llm_provider=None` 時完全不呼叫、不寫入
    `natural_text`，消費端 fallback 回現行樣板拼接，優雅降級。
    """
    kg_id_str = str(kg_id)
    for triple in triples:
        rel_type = _relationship_type(triple.rel_type)
        subject_name = await merge_entity(
            driver, kg_id, triple.subject, triple.subject_type, triple.subject,
            source_doc_id=triple.source_doc_id,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            embedding_provider=embedding_provider, llm_provider=llm_provider, cfg=cfg,
        )
        object_name = await merge_entity(
            driver, kg_id, triple.object, triple.object_type, triple.object,
            source_doc_id=triple.source_doc_id,
            source_svo_chunk_index=triple.source_svo_chunk_index,
            source_svo_chunk_file=triple.source_svo_chunk_file,
            embedding_provider=embedding_provider, llm_provider=llm_provider, cfg=cfg,
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

        # 3.6 事實清單自然語言化（報告24 §5 階段1，2026-09-01 新增）：
        # llm_provider 提供時，把這筆citation的三元組改寫成自然語句存在
        # r.natural_text，供 routers/agent.py::_merge_fact_lines() 生成
        # prompt 時優先使用（缺席時 fallback 回樣板拼接，見該函式）。每次
        # 有新citation合併時都重新生成、覆蓋舊值——與現行「verb 取最新一筆
        # citation」的既有慣例（見 bfs_query() docstring）一致，natural_text
        # 因此也反映最新一次抽取的措辭，不是累積歷史多個版本。
        #
        # ⚠️ **忠實性防護（2026-09-01，真實小規模回填抽查發現並修正，見
        # 報告24 §5 階段4）**：subject／object 任一為空字串的殘缺三元組
        # （見 `_merge_fact_lines()` 的既有殘缺過濾說明），若仍呼叫LLM改寫，
        # 真實觀察到LLM會自行編造內容補完空白受詞（例如 object 為空時，
        # 生成「本標準自發布日起施行」這種原文完全沒有依據的句子）——這正是
        # `_naturalize_triple()` docstring 借鏡 KAPING 提出的偏離風險，在
        # 真實資料上重現。殘缺三元組本來就會被 `_merge_fact_lines()` 的既有
        # 過濾（`if not t.subject or not t.object: continue`）擋下、不會被
        # LLM看到，因此不影響使用者體驗，但仍應在源頭跳過，避免浪費LLM呼叫、
        # 避免資料庫累積不會被使用且內容有疑慮的欄位。
        if llm_provider is not None and subject_name and object_name:
            set_clause += ", r.natural_text = $natural_text"
            set_params["natural_text"] = await _naturalize_triple(
                subject_name, triple.subject_type, triple.verb, object_name, triple.object_type,
                llm_provider,
            )

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
                fact_embedding=await embedding_provider.encode(
                    _fact_text_for_embedding(fact_text, triple.source)
                ),
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


async def create_fact_fulltext_index(driver: AsyncDriver | None = None, kg_id: UUID | None = None) -> None:
    """建立指定 KG 專屬的 `Fact.fact_text` fulltext 索引（CJK bigram
    analyzer），供 `vector_search_facts(..., hybrid=True)` 的 BM25 式候選
    使用（報告43 選項A）。命名與 label 範圍比照 `create_fact_vector_index()`
    ——每個 KG 各自一個索引，同一租戶隔離理由不重複贅述，見該函式
    docstring。冪等（`IF NOT EXISTS`），`vector_search_facts()` 只在
    `hybrid=True` 時才惰性呼叫，非 hybrid 呼叫路徑完全不受影響。"""
    if driver is None or kg_id is None:
        return
    kg_id_str = str(kg_id)
    await driver.execute_query(
        f"""
        CREATE FULLTEXT INDEX {_fact_fulltext_index_name(kg_id_str)} IF NOT EXISTS
        FOR (f:{_kg_fact_label(kg_id_str)}) ON EACH [f.fact_text]
        OPTIONS {{ indexConfig: {{ `fulltext.analyzer`: 'cjk' }} }}
        """,
    )


def _rrf_fuse_fact_ids(id_rankings: list[list[str]], *, k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion（Cormack, Clarke & Büttcher, 2009, SIGIR）——
    與 `baseline_rag_service.rrf_fuse()`／`routers.agent._rrf_order()` 同一
    演算法，這裡另寫一份操作 `elementId` 字串（而非 list index）的版本。
    三處各自保留一份小型複製、不互相 import，是本專案既有的分層慣例
    （見 `baseline_rag_service.rrf_fuse()` docstring：避免 services 反向
    import routers／跨 service 模組耦合），非本次新引入的重複。
    """
    scores: dict[str, float] = {}
    for ranking in id_rankings:
        for rank, fid in enumerate(ranking):
            scores[fid] = scores.get(fid, 0.0) + 1.0 / (k + rank)
    order_hint = {fid: pos for pos, fid in enumerate(id_rankings[0])} if id_rankings else {}
    return sorted(scores, key=lambda fid: (-scores[fid], order_hint.get(fid, math.inf)))


def _filter_fact_candidates_by_source_scope(
    records: list[dict], allowed_source_doc_ids: Collection[UUID] | None,
) -> list[dict]:
    """先在 over-fetch 候選中套用來源範圍，再做去重與 top-k 截斷。

    候選全都明確不在範圍內時保留原清單，以延續 agent 的 zero-out fail-open
    保護；缺少來源 ID 的舊 Fact 也保留，因為無法證明它在範圍外。
    """
    if not allowed_source_doc_ids:
        return records
    allowed = {str(doc_id) for doc_id in allowed_source_doc_ids}
    scoped = [
        record for record in records
        if record.get("source_doc_id") is None
        or str(record["source_doc_id"]) in allowed
    ]
    return scoped or records


async def vector_search_facts(
    driver: AsyncDriver,
    kg_id: UUID,
    query_vector: list[float],
    top_k: int,
    *,
    question: str | None = None,
    hybrid: bool = False,
    source_doc_cap: int | None = None,
    allowed_source_doc_ids: Collection[UUID] | None = None,
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

    🧪 **`hybrid=True`（報告43 選項A，prototype，預設關）**：`question` 與
    `hybrid=True` 齊備時，額外對 `Fact.fact_text` 跑一趟 fulltext（CJK
    analyzer，Lucene 內建排名，近似 BM25）查詢，與上面的 dense cosine 候選
    池以 `_rrf_fuse_fact_ids()`（Cormack et al. 2009 RRF）融合後再去重/
    截斷。動機：report41 §9／report43 §1 診斷的 26-Q5 案例——dense
    cosine 把「起算」這類樣板措辭的跨文件近義事實排得比正解還高，正解被
    擠出候選池；fulltext 的 IDF 機制對這種「共享虛詞、缺乏內容詞重疊」的
    情境理論上更有鑑別力（高頻虛詞如「起算」IDF 低、貢獻小，稀有內容詞如
    「災害發生」IDF 高、貢獻大）。**尚未對真實 KG 驗證**（report43 §3
    選項A風險項1：短事實文字上 BM25/fulltext 的實際鑑別力待實測），本參數
    預設 `False`，呼叫端不主動傳入 `hybrid=True` 前對既有行為零影響。
    `question` 缺席、或 fulltext 索引不支援（`cjk` analyzer 缺席等）時，
    直接跳過 fulltext 分支退回純 dense——不像 `_fetch_entity_candidates_
    canopy()` 那樣退回 `CONTAINS`：`fact_text` 是完整句子而非短名稱，對
    整句問題做 `CONTAINS` 子字串比對幾乎不可能命中，退回沒有意義。

    🧪 **`source_doc_cap`（報告57 §7.4，prototype，預設 `None`＝關閉）**：
    限制同一 `source_doc_id` 在最終 `top_k` 名額裡最多占幾筆，解決「單一
    來源文件內主題相近但答非所問的 Fact 集體擠占名額、稀釋掉跨文件關鍵
    事實」的問題（`57-AGGR2` 真實案例：N0060015 342 個 Fact 佔滿 20 個
    名額）。動機文獻見 `docs/參考文獻/35_同來源Fact冗餘去噪與多樣性檢索/`
    （MMR, Goldstein & Carbonell 1998；DF-RAG 固定 λ baseline, Khan et al.
    2026）——本實作是規則式簡化版（依 `source_doc_id` 計數上限），不算
    embedding centroid 距離，零額外 embedding／LLM 呼叫。`None` 時行為
    與先前完全一致（純 `[:top_k]` 截斷）。**尚未對真實 KG 端到端驗證**
    （檢索端已用獨立腳本確認`hybrid=True`能撈回目標事實，本參數的實際
    效果待驗證），預設 `None`，呼叫端不主動傳入前對既有行為零影響。

    **`allowed_source_doc_ids`**：呼叫端已有明確／種子錨定的文件範圍時，
    在 over-fetch 候選（預設 top-k 的 4 倍）上先過濾來源，再做 Fact 去重與
    top-k 截斷，避免其他來源的高分結果先佔滿名額。若候選全都在範圍外，
    保留原清單以維持既有 zero-out fail-open 行為；未提供範圍時結果不變。
    """
    await create_fact_vector_index(driver, kg_id, dim=len(query_vector))
    candidate_k = top_k * FACT_SEARCH_CANDIDATE_MULTIPLIER
    result = await driver.execute_query(
        f"""
        CALL db.index.vector.queryNodes('{_fact_vector_index_name(str(kg_id))}', $candidate_k, $vector)
        YIELD node, score
        RETURN elementId(node) AS fact_id,
               node.fact_text AS fact_text, node.verb AS verb, node.confidence AS confidence,
               node.subject AS subject, node.object AS object, node.rel_type AS rel_type,
               node.source_doc_id AS source_doc_id,
               node.source_svo_chunk_index AS source_svo_chunk_index, score
        """,
        candidate_k=candidate_k,
        vector=query_vector,
    )
    dense_records = [dict(r) for r in result.records]

    if not (hybrid and question):
        records = [{k: v for k, v in r.items() if k != "fact_id"} for r in dense_records]
        records = _filter_fact_candidates_by_source_scope(records, allowed_source_doc_ids)
        return _apply_source_doc_cap(_dedupe_facts_by_key(records), top_k, source_doc_cap)

    by_id = {r["fact_id"]: r for r in dense_records}
    dense_order = [r["fact_id"] for r in dense_records]
    fulltext_order: list[str] = []
    try:
        await create_fact_fulltext_index(driver, kg_id)
        ft_result = await driver.execute_query(
            f"""
            CALL db.index.fulltext.queryNodes('{_fact_fulltext_index_name(str(kg_id))}', $q)
            YIELD node, score
            RETURN elementId(node) AS fact_id,
                   node.fact_text AS fact_text, node.verb AS verb, node.confidence AS confidence,
                   node.subject AS subject, node.object AS object, node.rel_type AS rel_type,
                   node.source_doc_id AS source_doc_id,
                   node.source_svo_chunk_index AS source_svo_chunk_index, score
            LIMIT $candidate_k
            """,
            q=question,
            candidate_k=candidate_k,
        )
        for r in ft_result.records:
            rec = dict(r)
            by_id.setdefault(rec["fact_id"], rec)
            fulltext_order.append(rec["fact_id"])
    except Exception:  # noqa: BLE001 -- fulltext 索引缺席/analyzer 不支援，優雅退回純 dense（同 _fetch_entity_candidates_canopy 慣例）
        logger.warning("vector_search_facts: fulltext 候選查詢失敗，退回純 dense（kg_id=%s）", kg_id)
        fulltext_order = []

    fused_order = _rrf_fuse_fact_ids([dense_order, fulltext_order]) if fulltext_order else dense_order
    records = [{k: v for k, v in by_id[fid].items() if k != "fact_id"} for fid in fused_order]
    records = _filter_fact_candidates_by_source_scope(records, allowed_source_doc_ids)
    return _apply_source_doc_cap(_dedupe_facts_by_key(records), top_k, source_doc_cap)


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


def _apply_source_doc_cap(
    records: list[dict], top_k: int, source_doc_cap: int | None
) -> list[dict]:
    """`vector_search_facts()` 最終截斷層——`source_doc_cap` 為 `None` 時
    行為與先前完全一致（純 `records[:top_k]`）。非 `None` 時依既有分數
    排序貪婪走訪：同一 `source_doc_id` 累計達上限即跳過該筆、留給名額給
    其他來源；`source_doc_id` 缺席的記錄視為各自獨立來源，不受上限限制
    （比照 `_dedupe_facts_by_key()` 對缺欄位記錄的處理原則，缺 provenance
    的舊資料不強行歸併）。若依上限選完仍不足 `top_k`（候選池裡本來就
    沒有足夠的來源多樣性），第二輪按原順序把被跳過的記錄依序補滿——
    與 `routers/agent.py::_arrange_fact_lines()` 既有的「任一側不足時
    把餘額讓給另一側」同一設計精神，不因為湊不滿多樣性名額而讓清單
    比 `top_k` 短。文獻依據見 `docs/參考文獻/35_同來源Fact冗餘去噪與
    多樣性檢索/`（MMR／DF-RAG 固定 λ baseline 精神的規則式簡化版）。
    """
    if source_doc_cap is None:
        return records[:top_k]

    kept: list[dict] = []
    overflow: list[dict] = []
    doc_counts: dict[str, int] = {}
    for record in records:
        doc_id = record.get("source_doc_id")
        if doc_id is not None and doc_counts.get(doc_id, 0) >= source_doc_cap:
            overflow.append(record)
            continue
        kept.append(record)
        if doc_id is not None:
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
        if len(kept) >= top_k:
            return kept[:top_k]

    for record in overflow:
        if len(kept) >= top_k:
            break
        kept.append(record)
    return kept[:top_k]


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
                    fact_embedding=await embedding_provider.encode(
                        _fact_text_for_embedding(fact_text, citation.get("source"))
                    ),
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


async def backfill_natural_text(
    driver: AsyncDriver,
    kg_id: UUID,
    llm_provider: LLMProvider,
    *,
    batch_size: int = 100,
) -> int:
    """報告24 § 5 階段2 回填批次任務：掃描該 KG 內所有既有邊，把尚未有
    `r.natural_text` 的邊補上自然語句版本——`_naturalize_triple()` 是本次
    才實作（見 `merge_triples_to_graph()`），這之前完成的抽取只留下
    `citations_json`，沒有對應的 `natural_text`；本函式與即時路徑共用
    同一套 `_naturalize_triple()` 邏輯，不重複實作兩套。

    比照 `backfill_fact_nodes()` 定位為**人工觸發的一次性腳本**，理由相同：
    即時路徑已覆蓋所有新寫入，缺口是純歷史性的，不會持續產生新缺口
    （見 `docs/報告/24_事實清單自然語言化機制設計報告.md` § 5 階段2）。

    **分頁設計與 `backfill_fact_nodes()` 的差異（誠實記錄）**：`backfill_
    fact_nodes()` 的 WHERE 條件（`citations_json IS NOT NULL`）不會因為
    處理過程而改變，可以安全用 `SKIP`／`LIMIT` 累加分頁。本函式的 WHERE
    條件是 `r.natural_text IS NULL`——**每處理完一批，符合條件的邊集合
    就會縮小**，若沿用 `SKIP` 累加分頁，在 Neo4j 未保證穩定排序的情況下
    可能跳過尚未處理的邊。改為每次都重新查詢 `SKIP 0`（不累加），讓已
    處理過的邊自然從下一輪的篩選結果中消失，確保不遺漏、也不重複處理。
    為避免任何無法生成 `natural_text` 的邊造成無窮迴圈，**每一筆嘗試過的
    邊都保證會被寫入某個非 NULL 值**（`verb` 缺席時 fallback 回
    `_verbalize_fact()` 的樣板拼接，而非留白重試）——保證每輪迭代都讓
    符合條件的邊集合確實縮小。

    回傳實際更新的邊數。
    """
    kg_id_str = str(kg_id)
    updated = 0
    while True:
        result = await driver.execute_query(
            """
            MATCH (s:Entity {kg_id: $kg_id})-[r]->(o:Entity {kg_id: $kg_id})
            WHERE r.kg_id = $kg_id AND r.natural_text IS NULL
            RETURN type(r) AS rel_type, s.name AS subject, o.name AS object,
                   s.type AS subject_type, o.type AS object_type,
                   r.citations_json AS citations_json
            LIMIT $batch_size
            """,
            kg_id=kg_id_str,
            batch_size=batch_size,
        )
        edges = result.records
        if not edges:
            break

        for edge in edges:
            citations = json.loads(edge["citations_json"] or "[]")
            verb = citations[-1].get("verb", "") if citations else ""
            # 忠實性防護（2026-09-01，真實小規模回填抽查發現並修正，見報告24
            # §5 階段4）：subject／object 任一為空字串的殘缺三元組（見
            # `_merge_fact_lines()` 既有殘缺過濾說明）若仍呼叫LLM改寫，真實
            # 觀察到LLM會自行編造內容補完空白受詞——不呼叫LLM，直接退回樣板
            # 拼接（雖然殘缺三元組本來就會被 `_merge_fact_lines()` 擋下不會
            # 被使用，源頭跳過可省下LLM呼叫、避免資料庫累積有疑慮的內容）。
            if verb and edge["subject"] and edge["object"]:
                natural_text = await _naturalize_triple(
                    edge["subject"], edge["subject_type"], verb,
                    edge["object"], edge["object_type"], llm_provider,
                )
            else:
                # 防禦性 fallback：沒有 verb，或 subject／object 殘缺，無法
                # 生成有意義／忠實的自然語句，退回樣板拼接，保證這筆邊仍會
                # 被寫入非 NULL 值、下一輪不再被撈到。
                natural_text = _verbalize_fact(
                    edge["subject"], edge["subject_type"], verb, edge["object"], edge["object_type"],
                )
            await driver.execute_query(
                f"""
                MATCH (s:Entity {{kg_id: $kg_id, name: $subject}})-[r:{edge["rel_type"]} {{kg_id: $kg_id}}]->
                      (o:Entity {{kg_id: $kg_id, name: $object}})
                SET r.natural_text = $natural_text
                """,
                kg_id=kg_id_str,
                subject=edge["subject"],
                object=edge["object"],
                natural_text=natural_text,
            )
            updated += 1

        if len(edges) < batch_size:
            break

    return updated


async def backfill_fact_text_embeddings(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    *,
    batch_size: int = 200,
    source_charset: frozenset[str] | None = None,
) -> int:
    """報告25 § 4 發現5 回填批次任務：對該 KG 內既有 `Fact` 節點，用**新版**
    `_verbalize_fact()`（已移除 `（型別）` 括號）重算 `fact_text`，並在文字
    實際有變時重新 `encode()` 出 `fact_embedding`。

    起點：`_verbalize_fact()` 舊版會後綴 `（型別）`（如 `訓練時數（概念）
    以三百小時為度 （概念）`），真實查證（`vector_search_facts()` 對 bge-m3
    的 cosine）發現通用兜底型別「概念」的兩個 token 對短事實是純雜訊、
    明顯稀釋 `fact_embedding`——去掉後正確事實對問題 cosine 上升
    +0.03～+0.10。既有 `Fact` 節點的 `fact_embedding` 是舊字串算出來的，
    需回填重算才能受益。

    順帶做一次簡→繁正規化（報告25 § 4 發現4），把歷史抽取殘留的簡體字
    （`补助经费额度` 等）一併收掉——`fact_text` 是 `fact_embedding` 的來源
    字串，字形不一致同樣影響檢索。傳入 `source_charset`（`_kg_source_charset()`）
    時走 `_to_traditional_selective()`（`雇`／`托` 保留），未傳時退回全轉
    （向後相容）。

    比照 `backfill_fact_nodes()`／`backfill_natural_text()` 定位為**人工觸發的
    一次性腳本**：即時路徑（`merge_triples_to_graph` → `_create_fact_node`）
    已改用新版 `_verbalize_fact()`，缺口是純歷史性的。

    **冪等性**：重算後與現值相同就跳過、不呼叫 `embedding_provider`（已跑過
    一次的 KG 第二次執行回傳 0）。`fact_text` 由 `f.subject`／`f.verb`／
    `f.object` 三個扁平屬性重建（新版 `_verbalize_fact()` 不再需要型別），
    不依賴回頭 join Entity 節點。

    **分頁**：`ORDER BY elementId(f) SKIP $skip LIMIT`、`skip` 依「本批實際
    看過的列數」累加——本函式會改 `fact_text` 但**不會**把節點移出結果集
    （不像 `backfill_natural_text()` 的 `IS NULL` 條件），所以必須用 SKIP
    掃過每一列（不論有無變更），不能靠條件收斂。

    回傳實際更新（`fact_embedding` 有重算）的 `Fact` 節點數。
    """
    kg_id_str = str(kg_id)
    updated = 0
    skip = 0
    while True:
        result = await driver.execute_query(
            """
            MATCH (f:Fact {kg_id: $kg_id})
            RETURN elementId(f) AS eid, f.subject AS subject, f.verb AS verb,
                   f.object AS object, f.fact_text AS fact_text
            ORDER BY elementId(f)
            SKIP $skip LIMIT $batch_size
            """,
            kg_id=kg_id_str,
            skip=skip,
            batch_size=batch_size,
        )
        rows = result.records
        if not rows:
            break

        for row in rows:
            new_text = _to_traditional_selective(
                _verbalize_fact(row["subject"] or "", "", row["verb"] or "", row["object"] or "", ""),
                source_charset,
            )
            if new_text == row["fact_text"]:
                continue
            await driver.execute_query(
                """
                MATCH (f:Fact {kg_id: $kg_id}) WHERE elementId(f) = $eid
                SET f.fact_text = $fact_text, f.fact_embedding = $fact_embedding
                """,
                kg_id=kg_id_str,
                eid=row["eid"],
                fact_text=new_text,
                fact_embedding=await embedding_provider.encode(new_text),
            )
            updated += 1

        if len(rows) < batch_size:
            break
        skip += len(rows)

    return updated


async def backfill_fact_embeddings_with_doc_prefix(
    driver: AsyncDriver,
    kg_id: UUID,
    embedding_provider: EmbeddingProvider,
    *,
    batch_size: int = 200,
) -> int:
    """報告43（Fact-RAG 語意排名健壯性）選項B 回填批次任務：對該 KG 內
    既有 `Fact` 節點，用 `_fact_text_for_embedding()`（`fact_text` 前加
    文件代碼前綴）重新 `encode()` 出 `fact_embedding`——**不改動
    `fact_text` 本身**，只改嵌入的目標字串，修報告41 §9 診斷的問題
    （多部法規近義樣板條文在向量空間裡難以區分，見
    `docs/參考文獻/31_Fact-RAG語意排名健壯性/`）。

    跟 `backfill_fact_text_embeddings()`（報告25 發現5）是兩個獨立、
    互不影響的遷移：那個改的是 `fact_text` 本身的組字方式（移除型別
    括號＋簡繁正規化），這個完全不動 `fact_text`，只在計算
    `fact_embedding` 這一步額外注入文件身分前綴。因為 `fact_text` 不變，
    沒有「跟現值比較就跳過」的冪等判準可用（無法從已存的浮點向量反推
    是否已含前綴）——**比照人工觸發的一次性遷移腳本定位，每次執行都
    會重新 encode 全部 `Fact` 節點**，重複執行結果一致但浪費呼叫，不建議
    重複跑；即時路徑（`merge_triples_to_graph`）已在寫入當下套用前綴，
    只有既有（本次上線前建立）的 `Fact` 節點需要這個回填。

    先一次查出該 KG 內所有 `Document` 的 `(source_doc_id -> source)`
    對照表（文件數遠小於 `Fact` 數，避免逐筆 `Fact` 各自查一次 N+1）；
    `source_doc_id` 缺失或查無對應 `Document`（極舊資料、非本流程建立）
    時 `_fact_text_for_embedding()` 收到 `None`，回傳原樣 `fact_text`
    （零前綴，等同未受影響，非阻塞錯誤）。

    回傳實際更新的 `Fact` 節點數（分母＝ KG 內全部 `Fact`，因為每筆都會
    被重新 `encode()`）。
    """
    kg_id_str = str(kg_id)
    doc_result = await driver.execute_query(
        "MATCH (d:Document {kg_id: $kg_id}) RETURN d.source_doc_id AS doc_id, d.source AS source",
        kg_id=kg_id_str,
    )
    doc_sources = {str(r["doc_id"]): r["source"] for r in doc_result.records if r["doc_id"]}

    updated = 0
    skip = 0
    while True:
        result = await driver.execute_query(
            """
            MATCH (f:Fact {kg_id: $kg_id})
            RETURN elementId(f) AS eid, f.fact_text AS fact_text, f.source_doc_id AS source_doc_id
            ORDER BY elementId(f)
            SKIP $skip LIMIT $batch_size
            """,
            kg_id=kg_id_str,
            skip=skip,
            batch_size=batch_size,
        )
        rows = result.records
        if not rows:
            break

        for row in rows:
            source = doc_sources.get(str(row["source_doc_id"])) if row["source_doc_id"] else None
            embedding_text = _fact_text_for_embedding(row["fact_text"] or "", source)
            await driver.execute_query(
                """
                MATCH (f:Fact {kg_id: $kg_id}) WHERE elementId(f) = $eid
                SET f.fact_embedding = $fact_embedding
                """,
                kg_id=kg_id_str,
                eid=row["eid"],
                fact_embedding=await embedding_provider.encode(embedding_text),
            )
            updated += 1

        if len(rows) < batch_size:
            break
        skip += len(rows)

    return updated


async def backfill_natural_text_traditionalize(
    driver: AsyncDriver,
    kg_id: UUID,
    *,
    batch_size: int = 500,
) -> int:
    """報告25 § 4 發現4 回填批次任務：對該 KG 內既有 `r.natural_text` 套一次
    OpenCC 簡→繁（臺灣標準字）正規化，收掉報告24 全KG回填時 `qwen2.5:7b`
    漏轉的簡體字（`补助经费额度`／`训练`／`经费`）。

    純字串轉換、**不呼叫 LLM**、冪等（已是繁體時 OpenCC 近乎 identity，
    重算後 `converted == r.natural_text` 就跳過，第二次執行回傳 0）。分頁用
    `ORDER BY elementId(r) SKIP`、`skip` 依本批列數累加——本函式會改
    `natural_text` 但不會把邊移出結果集，須掃過每一列。

    即時路徑（`_naturalize_triple()`）已在輸出端加了同一道 `_to_traditional()`，
    缺口是純歷史性的。回傳實際更新的邊數。
    """
    kg_id_str = str(kg_id)
    updated = 0
    skip = 0
    while True:
        result = await driver.execute_query(
            """
            MATCH (:Entity {kg_id: $kg_id})-[r]->(:Entity {kg_id: $kg_id})
            WHERE r.kg_id = $kg_id AND r.natural_text IS NOT NULL
            RETURN elementId(r) AS eid, r.natural_text AS natural_text
            ORDER BY elementId(r)
            SKIP $skip LIMIT $batch_size
            """,
            kg_id=kg_id_str,
            skip=skip,
            batch_size=batch_size,
        )
        rows = result.records
        if not rows:
            break

        for row in rows:
            converted = _to_traditional(row["natural_text"])
            if converted == row["natural_text"]:
                continue
            await driver.execute_query(
                """
                MATCH (:Entity {kg_id: $kg_id})-[r]->(:Entity {kg_id: $kg_id})
                WHERE elementId(r) = $eid
                SET r.natural_text = $natural_text
                """,
                kg_id=kg_id_str,
                eid=row["eid"],
                natural_text=converted,
            )
            updated += 1

        if len(rows) < batch_size:
            break
        skip += len(rows)

    return updated


def _union_citations(a_json: str | None, b_json: str | None) -> tuple[str, float]:
    """把兩條 SVO 事實邊的 `citations_json` 合併去重（依整筆 citation 的
    JSON 字面），回傳 `(合併後 json, max confidence)`——比照
    `merge_triples_to_graph()` 的事實層級去重與 `confidence = max(citations)`
    規則。任一為空時視為空清單。"""
    seen: set[str] = set()
    merged: list[dict] = []
    for raw in (a_json, b_json):
        for c in json.loads(raw or "[]"):
            key = json.dumps(c, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                merged.append(c)
    conf = max((c.get("confidence", 1) for c in merged), default=1)
    return json.dumps(merged, ensure_ascii=False), conf


async def backfill_traditionalize_entity_names(
    driver: AsyncDriver,
    kg_id: UUID,
    kg_folder: str,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    batch_size: int = 300,
) -> dict:
    """報告25 §4 發現4 回填批次任務：把 KG 內 Entity 節點名稱裡 `qwen2.5:7b`
    遺漏的簡體字**選擇性**轉繁（`_to_traditional_selective()`，以這個 KG 的
    繁體來源文件實際用字為白名單——`雇`／`托` 保留，`職`／`經`／`嬰` 轉）。

    - **純改名**（繁體版節點不存在）：`SET e.name = 新名`，有 `embedding_provider`
      時一併重算 `name_embedding`。
    - **撞名**（繁體版節點已存在，如 `事业单位`↔`事業單位`）：把簡體節點的每
      一條邊搬到繁體節點——同型別、同另一端點的 SVO 事實邊 `union` 其
      `citations_json`＋重算 `confidence`，其餘同型別同端點的邊直接丟（繁體
      版已有等價邊），沒有對應的邊則在繁體節點上以相同屬性重建；最後
      `DETACH DELETE` 簡體節點。Entity 節點有 `(kg_id, name)` 唯一約束，直接
      `SET name` 撞名會拋例外，故撞名一律走搬邊＋刪節點。

    冪等（選擇性轉繁後 == 原名就跳過，第二次執行回傳全 0）。純字串轉換
    ＋圖結構搬移，改名分支不呼叫 LLM；`embedding_provider` 未提供時改名節點
    的 `name_embedding` 留待 `backfill_entity_name_embeddings()` 補。

    回傳 `{renamed, merged, edges_moved, edges_unioned, edges_dropped}`。
    """
    kg_id_str = str(kg_id)
    charset = _kg_source_charset(kg_folder)
    stats = {"renamed": 0, "merged": 0, "edges_moved": 0, "edges_unioned": 0, "edges_dropped": 0}

    result = await driver.execute_query(
        "MATCH (e:Entity {kg_id: $kg_id}) RETURN e.name AS name ORDER BY e.name",
        kg_id=kg_id_str,
    )
    names = [r["name"] for r in result.records]
    existing = set(names)

    for old_name in names:
        new_name = _to_traditional_selective(old_name, charset)
        if new_name == old_name:
            continue

        if new_name not in existing:
            # 純改名
            set_clause = "SET e.name = $new_name"
            params = {"kg_id": kg_id_str, "old_name": old_name, "new_name": new_name}
            if embedding_provider is not None:
                params["emb"] = await embedding_provider.encode(new_name)
                set_clause += ", e.name_embedding = $emb"
            await driver.execute_query(
                f"MATCH (e:Entity {{kg_id: $kg_id, name: $old_name}}) {set_clause}",
                **params,
            )
            existing.discard(old_name)
            existing.add(new_name)
            stats["renamed"] += 1
            continue

        # 撞名——搬邊到繁體節點後刪簡體節點
        for direction in ("out", "in"):
            pattern = (
                "MATCH (s:Entity {kg_id: $kg_id, name: $old})-[r]->(x)"
                if direction == "out"
                else "MATCH (x)-[r]->(s:Entity {kg_id: $kg_id, name: $old})"
            )
            edges = await driver.execute_query(
                f"{pattern} RETURN elementId(r) AS rid, type(r) AS t, "
                "properties(r) AS props, elementId(x) AS xid",
                kg_id=kg_id_str, old=old_name,
            )
            for e in edges.records:
                rel_type = _relationship_type(e["t"])  # 注入防線（大寫/底線）
                props = dict(e["props"])
                twin_pattern = (
                    f"MATCH (t:Entity {{kg_id: $kg_id, name: $new}})-[r2:{rel_type}]->(x) "
                    "WHERE elementId(x) = $xid"
                    if direction == "out"
                    else f"MATCH (x)-[r2:{rel_type}]->(t:Entity {{kg_id: $kg_id, name: $new}}) "
                    "WHERE elementId(x) = $xid"
                )
                twin = await driver.execute_query(
                    f"{twin_pattern} RETURN elementId(r2) AS r2id, r2.citations_json AS cj",
                    kg_id=kg_id_str, new=new_name, xid=e["xid"],
                )
                if twin.records:
                    r2 = twin.records[0]
                    if props.get("citations_json") is not None and r2["cj"] is not None:
                        union_json, conf = _union_citations(props["citations_json"], r2["cj"])
                        await driver.execute_query(
                            "MATCH ()-[r2]->() WHERE elementId(r2) = $r2id "
                            "SET r2.citations_json = $cj, r2.confidence = $conf",
                            r2id=r2["r2id"], cj=union_json, conf=conf,
                        )
                        stats["edges_unioned"] += 1
                    else:
                        stats["edges_dropped"] += 1
                    # 不論 union 或 drop，簡體節點這條邊都刪掉
                    await driver.execute_query(
                        "MATCH ()-[r]->() WHERE elementId(r) = $rid DELETE r",
                        rid=e["rid"],
                    )
                else:
                    create_pattern = (
                        f"MATCH (t:Entity {{kg_id: $kg_id, name: $new}}), (x) "
                        f"WHERE elementId(x) = $xid CREATE (t)-[nr:{rel_type}]->(x) SET nr = $props"
                        if direction == "out"
                        else f"MATCH (t:Entity {{kg_id: $kg_id, name: $new}}), (x) "
                        f"WHERE elementId(x) = $xid CREATE (x)-[nr:{rel_type}]->(t) SET nr = $props"
                    )
                    await driver.execute_query(
                        create_pattern, kg_id=kg_id_str, new=new_name, xid=e["xid"], props=props,
                    )
                    await driver.execute_query(
                        "MATCH ()-[r]->() WHERE elementId(r) = $rid DELETE r",
                        rid=e["rid"],
                    )
                    stats["edges_moved"] += 1

        await driver.execute_query(
            "MATCH (s:Entity {kg_id: $kg_id, name: $old}) DETACH DELETE s",
            kg_id=kg_id_str, old=old_name,
        )
        existing.discard(old_name)
        stats["merged"] += 1

    return stats


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
    cfg: KGConfig | None = None,
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
    _cfg = cfg or KGConfig()
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
        threshold=_cfg.reltype.compare_cosine_threshold,
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
    cfg: KGConfig | None = None,
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

    `cfg`（2026-09-14 新增，報告47 任務B）：`cfg.chunking` 原樣轉交
    `prepare_svo_ready_chunks(chunking_config=...)`；比照本模組其餘函式既有的
    `cfg: KGConfig | None = None` DI 慣例（見 `resolve_query_relation_type()`／
    `bfs_query()`），**呼叫端不傳就是 `KGConfig()` shipped defaults，行為
    零變化**。目前 `routers/staging.py`／`knowledge_graph_service.py::
    build_graph()` 皆尚未傳入真實 `cfg`（即尚未接上 `ConfigLoader` 依 KG
    的 domain pack 解析出的設定）——先開放本函式接受注入，讓「呼叫端何時
    真正接上」可以獨立於本函式的正確性驗證分開決定。`articles is not None`
    時 `cfg.chunking` 不生效（見上方 `articles` 說明的架構侷限）。

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
        chunking_config=(cfg or KGConfig()).chunking,
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


# 報告27 L0：`bfs_query` 的懶惰擴展門檻——1-hop 結果去重後少於這麼多筆，
# 才擴展到 2-hop（僅在呼叫端允許 `hops >= 2` 時）。共用高頻實體（雇主／
# 被保險人）當種子時，1-hop 通常已足夠且遠快於 2-hop 的組合爆炸（報告26
# §4 #4：Q5/6/7 各 330–440 秒）。初值 8，待報告27 §6 敏感度測試校準。
# 2026-09-08：`= KGConfig().bfs.expand_when_below`；本常數現為 golden test
# 錨點（`tests/core/test_kg_config.py`），`bfs_query()` 已改讀 `cfg`。
_BFS_EXPAND_WHEN_BELOW = 8

# 報告27 L2（向量引導 prize 剪枝，2026-09-08 prototype）：懶惰擴展觸發時，
# 不再對 1-hop frontier 做無差別 2-hop 走訪，改對每條候選 2-hop 邊算
# `cosine(問題向量, 邊 natural_text 向量)`，只保留分數 top-k 條。G-Retriever
# prize 機制（He et al. 2024）的扁平化簡化——無 Steiner tree 最佳化、無 GNN。
# 預設關（`bfs_query(prize_top_k=None)`）＝零行為變化；需三個參數齊備才啟用。
# 初值 10，待報告27 §6 敏感度測試校準（k ∈ {5, 10, 20}）。
_BFS_PRIZE_TOP_K = 10


def _bfs_pass_cypher(rel_types: str, min_hop: int, max_hop: int, *, scoped: bool, per_seed_limit: bool) -> str:
    """組一趟 BFS 走訪的 Cypher（報告27 L1）。

    - `scoped=True`：鄰居必須經 `(:Chunk)-[:HAS_ENTITY]->` 連到 `source_doc_id`
      在 `$scope_doc_ids` 內的文件——把 `routers/agent.py` 語意 Fact 推導出的
      文件範圍下推到走訪階段，遍歷不出離題文件。⚠️ `HAS_ENTITY` 只出現在
      這個 `EXISTS {}` 範圍子查詢裡，**不在** `*min..max` 變長走訪型別清單中
      （2026-08-19 迴歸：走訪本身行經 HAS_ENTITY 會把端點解析成 Chunk 節點）。
    - `per_seed_limit=True`：每個 seed 的展開路徑數上限 `$per_seed_limit`
      （CALL 子查詢內 LIMIT），限制樞紐種子的扇出。
    """
    scope_clause = (
        "\n            WHERE EXISTS {\n"
        "                MATCH (c:Chunk {kg_id: $kg_id})-[:HAS_ENTITY]->(neighbor)\n"
        "                WHERE c.source_doc_id IN $scope_doc_ids\n"
        "            }"
        if scoped else ""
    )
    limit_clause = "\n            RETURN path LIMIT $per_seed_limit" if per_seed_limit else "\n            RETURN path"
    return f"""
        MATCH (seed:Entity {{kg_id: $kg_id}})
        WHERE seed.name IN $seed_entities
        CALL (seed) {{
            MATCH path = (seed)-[:{rel_types}*{min_hop}..{max_hop}]-(neighbor:Entity {{kg_id: $kg_id}}){scope_clause}{limit_clause}
        }}
        UNWIND relationships(path) AS rel
        WITH DISTINCT startNode(rel) AS s, rel, endNode(rel) AS o
        RETURN
            s.name AS subject,
            coalesce(s.type, "概念") AS subject_type,
            type(rel) AS rel_type,
            coalesce(rel.confidence, 1) AS confidence,
            rel.citations_json AS citations_json,
            rel.natural_text AS natural_text,
            o.name AS object,
            coalesce(o.type, "概念") AS object_type
    """


def _bfs_records_to_triples(records) -> list[SVOTriple]:
    triples: list[SVOTriple] = []
    for record in records:
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


async def bfs_query(
    driver: AsyncDriver,
    kg_id: UUID,
    seed_entities: list[str],
    hops: int = 1,
    *,
    scope_doc_ids: Collection[UUID] | None = None,
    per_seed_limit: int | None = None,
    expand_when_below: int | None = None,
    prize_top_k: int | None = None,
    question_vector: list[float] | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    cfg: KGConfig | None = None,
) -> list[SVOTriple]:
    """從 seed entity 做 bounded BFS，回傳路徑上的去重 SVO triples。

    每條邊可能累積多筆來源引用（見 `merge_triples_to_graph` 的事實層級
    去重說明）；`SVOTriple` 的 `source_*` 欄位是單筆值，這裡先取
    `citations_json` 清單中「最後一筆」（最近一次抽取到這個事實）作為代表
    值——挑選哪一筆／哪幾筆來源最適合呈現，是回答階段的向量篩選設計
    （不在本次範圍），這裡只是先確保欄位不會靜默變成 null。

    ✅ **`natural_text` 原樣帶出（2026-09-01，報告24 §5 階段3）**：邊上的
    `r.natural_text`（若有，見 `merge_triples_to_graph()`／
    `backfill_natural_text()`）原樣填進回傳的 `SVOTriple.natural_text`，
    供 `routers/agent.py::_merge_fact_lines()` 優先使用；缺席時為 `None`，
    消費端 fallback 回樣板拼接。

    ✅ **報告27（2026-09-04）：遍歷剪枝**——`hops` 由「固定走訪深度」改為
    「最大允許跳數」，預設 1：

    - **L0 懶惰擴展**：一律先跑 1-hop；去重後三元組數 < `expand_when_below`
      且 `hops >= 2` 時，才補跑一趟 `2..hops` 擴展並合併（依
      `(subject, rel_type, object)` 去重）。避免樞紐種子 2-hop 的組合爆炸。
    - **L1 文件範圍下推**：`scope_doc_ids` 非空時，走訪只保留經
      `(:Chunk)-[:HAS_ENTITY]->` 連到範圍內文件的鄰居。**空結果 fallback**：
      scoped 首趟 1-hop 撈不到任何列時，自動改跑無範圍版（相容尚未建立
      `HAS_ENTITY` 結構邊的舊 KG，或範圍推導失準的情況）。
    - **L1 扇出上限**：`per_seed_limit` 非 None 時，每個 seed 的展開路徑數
      上限（CALL 子查詢內 LIMIT）。

    ✅ **報告27 L2（向量引導 prize 剪枝，2026-09-08 prototype）**：當懶惰
    擴展觸發（`hops >= 2` 且 1-hop 三元組 < `expand_when_below`）且
    `prize_top_k` / `question_vector` / `embedding_provider` 三者齊備時，
    **不跑無差別 `2..hops` 走訪**，改為：以 1-hop frontier 實體為新 seed 再
    走一趟 1-hop（＝候選 2-hop 邊），對每條候選邊算
    `cosine(question_vector, encode(邊 natural_text))`，只把分數 top-k 條
    併入結果。邊無 `natural_text` 時退回 `subject verb object` 拼接字串
    打分。三參數缺任一 → 走原無差別 `2..hops`（零行為變化）。目前只處理
    2-hop 擴展；`hops > 2` 時 prize 選完 2-hop 後不再深入（初期 `svo_hops`
    實際只到 2）。k 初值 `_BFS_PRIZE_TOP_K`，待報告27 §6 敏感度測試校準。

    ⚠️ `scope_doc_ids` 的 Cypher 下推需對真實 Neo4j（kg2-neo4j）驗證，
    見 `docs/報告/27_...md` §6；空結果 fallback 讓上線本身安全。
    L2 需邊 `natural_text` 齊備（新 KG 每條邊即時 `_naturalize_triple`），
    舊 KG 邊多無 `natural_text` → 退回拼接字串打分，品質下降但不失效。

    ✅ **報告33 §3.9 / 論文 04 §4.10（設定分層，2026-09-08 第 2 步）**：
    `expand_when_below` 未明確傳入（`None`）時，改讀 `(cfg or KGConfig()).bfs.
    expand_when_below`。`cfg=None` → `KGConfig()` 預設 == `_BFS_EXPAND_WHEN_BELOW`，
    行為零變化。呼叫端（`chat()`）傳入 `cfg` 後即由 domain pack / per-KG profile
    控制。
    """
    _cfg = cfg or KGConfig()
    if expand_when_below is None:
        expand_when_below = _cfg.bfs.expand_when_below
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
    # 驗證失敗直接拋例外。走訪型別清單一律只含 SVO_REL_TYPES；報告27 的
    # 文件範圍約束用獨立的 EXISTS {} 子查詢、不進走訪路徑。
    rel_types = "|".join(sorted(SVO_REL_TYPES))
    scoped = bool(scope_doc_ids)
    scope_ids = [str(d) for d in scope_doc_ids] if scoped else None
    want_limit = per_seed_limit is not None

    params: dict = {"kg_id": str(kg_id), "seed_entities": seeds}
    if scoped:
        params["scope_doc_ids"] = scope_ids
    if want_limit:
        params["per_seed_limit"] = per_seed_limit

    # L0：先跑 1-hop
    result = await driver.execute_query(
        _bfs_pass_cypher(rel_types, 1, 1, scoped=scoped, per_seed_limit=want_limit),
        **params,
    )
    triples = _bfs_records_to_triples(result.records)

    # L1 空結果 fallback：scoped 首趟撈不到 → 改跑無範圍版
    if scoped and not triples:
        result = await driver.execute_query(
            _bfs_pass_cypher(rel_types, 1, 1, scoped=False, per_seed_limit=want_limit),
            **{k: v for k, v in params.items() if k != "scope_doc_ids"},
        )
        triples = _bfs_records_to_triples(result.records)
        scoped = False  # 擴展趟也不再套範圍，維持一致

    # L0 懶惰擴展：1-hop 不足才補 2..hops
    if hops >= 2 and len(triples) < expand_when_below:
        seen = {(t.subject, t.rel_type, t.object) for t in triples}
        l2_active = (
            prize_top_k is not None
            and question_vector is not None
            and embedding_provider is not None
        )

        if l2_active:
            # L2：以 1-hop frontier 為新 seed 再走一趟 1-hop（＝候選 2-hop 邊），
            # 對每條候選邊算 cosine(問題向量, 邊 natural_text 向量)，只留 top-k。
            seed_set = set(seeds)
            frontier = sorted(
                {t.object for t in triples if t.object and t.object not in seed_set}
                | {t.subject for t in triples if t.subject and t.subject not in seed_set}
            )
            if frontier:
                fp = {"kg_id": str(kg_id), "seed_entities": frontier}
                if scoped:
                    fp["scope_doc_ids"] = scope_ids
                if want_limit:
                    fp["per_seed_limit"] = per_seed_limit
                fres = await driver.execute_query(
                    _bfs_pass_cypher(rel_types, 1, 1, scoped=scoped, per_seed_limit=want_limit),
                    **fp,
                )
                candidates = [
                    t for t in _bfs_records_to_triples(fres.records)
                    if (t.subject, t.rel_type, t.object) not in seen
                ]
                if candidates:
                    prize_texts = [
                        t.natural_text or f"{t.subject} {t.verb} {t.object}"
                        for t in candidates
                    ]
                    prize_vecs = await embedding_provider.encode_batch(prize_texts)
                    ranked = sorted(
                        zip(candidates, prize_vecs),
                        key=lambda cv: cosine_similarity(question_vector, cv[1]),
                        reverse=True,
                    )
                    for t, _vec in ranked[:prize_top_k]:
                        key = (t.subject, t.rel_type, t.object)
                        if key not in seen:
                            seen.add(key)
                            triples.append(t)
        else:
            exp_params = {"kg_id": str(kg_id), "seed_entities": seeds}
            if scoped:
                exp_params["scope_doc_ids"] = scope_ids
            if want_limit:
                exp_params["per_seed_limit"] = per_seed_limit
            exp = await driver.execute_query(
                _bfs_pass_cypher(rel_types, 2, hops, scoped=scoped, per_seed_limit=want_limit),
                **exp_params,
            )
            for t in _bfs_records_to_triples(exp.records):
                key = (t.subject, t.rel_type, t.object)
                if key not in seen:
                    seen.add(key)
                    triples.append(t)

    return triples
