"""報告221 N1：檢索 trace 的 `semantic_marks` 影子欄位——伺服器端旗標的參數組裝與靜態型別表載入。

位置理由：`services/semantic_marks.py` 必須維持純運算（無 I/O），所以讀檔放在本模組；本模組屬 N10
上下文組裝的遙測周邊（與 `telemetry.py` 同層），只讀 repo 內靜態檔（`core.constants.ENTITY_TYPES`、
`data/schema_org_entity_types.json`），**不連 DB、不呼叫 LLM**。

旗標關閉時 `semantic_marks_trace_kwargs()` 回傳 `{}`，**不載入任何檔案**，呼叫端的
`build_retrieval_trace(...)` 與旗標新增前完全相同。
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.constants import ENTITY_TYPES
from services.semantic_marks import CONCEPT_SCHEMES, INDETERMINATE, normalize_type_key

logger = logging.getLogger(__name__)

_EXT_TYPES_PATH = Path(__file__).resolve().parents[2] / "data" / "schema_org_entity_types.json"


@lru_cache(maxsize=1)
def load_type_lookups() -> tuple[dict[str, str], dict[str, str]]:
    """`(core_lookup, ext_lookup)`，鍵為 `normalize_type_key()` 結果；程序內只載入一次。

    擴充表檔缺失或格式錯誤時降級為空 `ext_lookup` 並記 log（不崩潰）：此時擴充型別會被標為
    「尚未處理」而非「已解決」，是影子標示的保守偏差，不影響回答。
    """
    core = {normalize_type_key(k): k for k in ENTITY_TYPES}
    ext: dict[str, str] = {}
    try:
        payload = json.loads(_EXT_TYPES_PATH.read_text(encoding="utf-8"))
        ext = {normalize_type_key(t["label"]): t["id"] for t in payload.get("types", [])}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("[trace_marks] 無法載入 %s，擴充型別表降級為空：%s", _EXT_TYPES_PATH, exc)
    return core, ext


def semantic_marks_trace_kwargs(enabled: bool, concept_scheme: str) -> dict:
    """旗標關閉＝`{}`（不載檔）；開啟＝傳給 `build_retrieval_trace` 的額外關鍵字參數。

    無效 `concept_scheme` 立即 `ValueError`（只在旗標開啟時檢查，關閉時不影響任何路徑）。
    """
    if not enabled:
        return {}
    if concept_scheme not in CONCEPT_SCHEMES:
        raise ValueError(f"trace_semantic_marks_concept_scheme 必須是 {CONCEPT_SCHEMES} 之一，收到 {concept_scheme!r}")
    return {
        "include_semantic_marks": True,
        "concept_scheme": concept_scheme,
        "type_lookups": load_type_lookups(),
    }


def effective_marks_kwargs(
    enabled: bool, as_of: str, document_map: Mapping[str, Any] | None
) -> tuple[dict, dict]:
    """組裝文件層施行摘要的來源／trace 選用參數；關閉時完全不運算。"""
    if not enabled:
        return {}, {}
    from services.effective_note import summarize_document_effective

    effective_status = {}
    for doc_id, document in (document_map or {}).items():
        if document is not None:
            effective_status[doc_id] = summarize_document_effective(
                document.effective_note, as_of
            ).status
    return (
        {"effective_as_of": as_of},
        {"document_effective_status": effective_status},
    )


def article_effective_marks(
    *,
    as_of: str,
    document_notes: Mapping[str, str | None],
    document_status: Mapping[str, str],
    evidence_keys: Sequence[tuple[str | None, int | None]],
    article_nos: Mapping[tuple[str, int], str],
    known_articles: Mapping[str, Sequence[str]],
) -> dict[tuple[str, int], dict[str, Any]]:
    """以文件備註與條號對照表推導證據的條文層影子狀態。"""
    from services.effective_note import article_effective_status, parse_effective_note

    parsed_by_doc: dict[str, Mapping[str, Any]] = {}
    output: dict[tuple[str, int], dict[str, Any]] = {}

    def _indeterminate() -> dict[str, Any]:
        return {"status": INDETERMINATE, "effective_from": None, "locators": []}

    def _normalize_known_articles(values: Sequence[str]) -> list[str]:
        return ["".join(str(value).split()).replace("第", "").replace("條", "") for value in values]

    for raw_doc_id, raw_chunk in evidence_keys:
        if raw_doc_id is None or raw_chunk is None:
            continue
        doc_id = str(raw_doc_id)
        try:
            chunk = int(raw_chunk)
        except (TypeError, ValueError):
            continue
        key = (doc_id, chunk)
        status = document_status.get(doc_id)
        if status is None:
            output[key] = _indeterminate()
            continue
        if status != "has_pending":
            output[key] = {"status": status, "effective_from": None, "locators": []}
            continue
        article_no = article_nos.get(key)
        if not article_no:
            output[key] = _indeterminate()
            continue
        if doc_id not in parsed_by_doc:
            parsed_by_doc[doc_id] = parse_effective_note(
                document_notes.get(doc_id),
                known_articles=_normalize_known_articles(known_articles.get(doc_id, ())),
            )
        article_status = article_effective_status(parsed_by_doc[doc_id], str(article_no), as_of)
        output[key] = {
            "status": article_status.status,
            "effective_from": article_status.effective_from,
            "locators": list(article_status.locators),
        }
    return output
