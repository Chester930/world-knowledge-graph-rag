"""N4 的關係型別 embedding 比對與仲裁（報告160 U1 自 ``services.svo_service`` 搬入，行為不變）。"""
from __future__ import annotations

from pathlib import Path

from core.constants import SVO_REL_TYPE_DESCRIPTIONS
from core.kg_config import KGConfig
from core.providers.base import EmbeddingProvider, LLMProvider
from services import expand_governance_service, sim_calibration_service
from services.classify_service import cosine_similarity
from services.extraction.prompt import _effective_rel_type_descriptions

# SIM 節點的型別描述句 embedding 快取——model 與完整描述集合共同組成 key，
# 避免不同 domain pack 的 KG 在同一個 provider/model 下互相汙染結果。
_TYPE_DESCRIPTION_EMBEDDING_CACHE: dict[
    tuple[str, tuple[tuple[str, str], ...]], dict[str, list[float]]
] = {}


async def _type_description_embeddings(
    embedding_provider: EmbeddingProvider,
    descriptions: dict[str, str] | None = None,
) -> dict[str, list[float]]:
    description_map = SVO_REL_TYPE_DESCRIPTIONS if descriptions is None else descriptions
    description_items = tuple(sorted(description_map.items()))
    cache_key = (embedding_provider.model_name, description_items)
    cache = _TYPE_DESCRIPTION_EMBEDDING_CACHE.get(cache_key)
    if cache is None:
        vectors = await embedding_provider.encode_batch([description for _, description in description_items])
        cache = dict(zip((name for name, _ in description_items), vectors))
        _TYPE_DESCRIPTION_EMBEDDING_CACHE[cache_key] = cache
    return cache


async def classify_relation_by_embedding(
    verb: str,
    embedding_provider: EmbeddingProvider,
    descriptions: dict[str, str] | None = None,
) -> tuple[str, float]:
    """SIM：`verb` embedding 與 35 個關係型別**描述句**（非識別碼字串本身，見
    `SVO_REL_TYPE_DESCRIPTIONS` docstring）embedding 算 cosine 相似度，取最相似者。
    回傳 (最相似的型別, 該型別的相似度分數)。"""
    type_vectors = await _type_description_embeddings(embedding_provider, descriptions)
    verb_vec = await embedding_provider.encode(verb)
    best_type = ""
    best_score = -1.0
    for rel_type, vec in type_vectors.items():
        score = cosine_similarity(verb_vec, vec)
        if score > best_score:
            best_score = score
            best_type = rel_type
    return best_type, best_score


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

    best_type, best_score = await classify_relation_by_embedding(
        verb,
        embedding_provider,
        descriptions=_effective_rel_type_descriptions(_cfg),
    )
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
