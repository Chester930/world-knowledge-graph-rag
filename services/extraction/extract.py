"""N4 的 SVO 抽取與完整性核對（報告160 U1 自 ``services.svo_service`` 搬入，行為不變）。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from core.kg_config import KGConfig
from core.providers.base import EmbeddingProvider, LLMProvider
from models.knowledge_graph import SVOTriple
from services.classify_service import cosine_similarity
from services.extraction.guards import _filter_ungrounded_quantity_triples
from services.extraction.prompt import (
    _effective_rel_types,
    _parse_triples_payload,
    _svo_prompt,
    resolve_entity_type,
)
from services.extraction.reltype import (
    _reconcile_rel_type,
)

# 沿用舊 logger 名稱，確保搬移前後的 log 記錄（name／訊息）完全相同。
logger = logging.getLogger("services.svo_service")

async def extract_svo_triples(
    text: str,
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    *,
    cfg: KGConfig | None = None,
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

    _cfg = cfg or KGConfig()
    raw = await llm_provider.generate_json(
        _svo_prompt(
            text,
            fewshots=_cfg.domain.svo_fewshots,
            rel_type_extensions=_cfg.domain.rel_type_extensions,
        )
    )
    triples: list[SVOTriple] = []
    for item in _parse_triples_payload(raw):
        rel_type = str(item.get("rel_type", "RELATED_TO")).strip()
        # 3.1.3 REJECT：不在受控詞彙表內的 rel_type 退回 RELATED_TO 兜底，
        # 三元組本身保留（不可靜默丟棄整條事實），原始語意仍留在 verb 欄位。
        rel_type = rel_type if rel_type in _effective_rel_types(_cfg) else "RELATED_TO"
        verb = str(item.get("verb", "")).strip()
        if verb and embedding_provider is not None:
            rel_type = await _reconcile_rel_type(
                verb,
                rel_type,
                embedding_provider=embedding_provider,
                llm_provider=llm_provider,
                kg_id=kg_id,
                calibration_db_path=calibration_db_path,
                cfg=_cfg,
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


async def extract_svo_triples_with_completeness_check(
    text: str,
    original_sentences: Sequence[str],
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    *,
    cfg: KGConfig | None = None,
    kg_id: str | None = None,
    calibration_db_path: Path | None = None,
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
        text, llm_provider, embedding_provider,
        cfg=cfg, kg_id=kg_id, calibration_db_path=calibration_db_path,
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
        cfg=cfg, kg_id=kg_id, calibration_db_path=calibration_db_path,
    )

    seen = {(t.subject, t.verb, t.object) for t in triples}
    merged = list(triples)
    for t in supplement_triples:
        key = (t.subject, t.verb, t.object)
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return _filter_ungrounded_quantity_triples(merged, text, original_sentences)
