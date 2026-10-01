"""條文版本差異的純運算工具（報告235 P1／P2，共用、未接線）。

本模組目前只提供不含 I/O 的內容正規化與差異分類；P2 的版本鏈事件原型
也會放在此模組。所有函式都不連資料庫、不呼叫模型、不使用時鐘。
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from services import relation_lifecycle as rl


NAVIGATION_MARKER_RE = re.compile(r":::\s*最新訊息")

DIFF_SAME_HASH = "same_hash"
DIFF_FORMAT_ONLY = "format_only"
DIFF_SUBSTANTIVE = "substantive"
DIFF_LABELS = {
    DIFF_SAME_HASH: "相同",
    DIFF_FORMAT_ONLY: "僅排版",
    DIFF_SUBSTANTIVE: "文字不同",
}


def has_navigation_noise(content: str) -> bool:
    """回報是否包含目前盤點採用的法規網站導覽起始標記。"""
    return bool(NAVIGATION_MARKER_RE.search(unicodedata.normalize("NFKC", content)))


def strip_navigation_noise(content: str) -> str:
    """移除從 ``::: 最新訊息`` 起至文末的疑似網站導覽尾巴。

    這是保守的操作型規則，不宣稱能識別所有網頁雜訊；誤把正文中的同名
    標記截掉，或漏掉沒有標記的導覽文字，均由呼叫端揭露限制。
    """
    normalized = unicodedata.normalize("NFKC", content)
    match = NAVIGATION_MARKER_RE.search(normalized)
    return normalized[: match.start()] if match else normalized


def normalize_content(content: str, *, remove_navigation_noise: bool = True) -> str:
    """以 NFKC 統一全形／半形並移除空白，供字面比較使用。"""
    text = strip_navigation_noise(content) if remove_navigation_noise else unicodedata.normalize("NFKC", content)
    return re.sub(r"\s+", "", text)


def classify_content_difference(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    """依 P1 (a)(b)(c) 分類相鄰版本；這是字面規則，不是語意判定。"""
    left_hash = left.get("content_hash")
    right_hash = right.get("content_hash")
    if left_hash and right_hash and left_hash == right_hash:
        return DIFF_SAME_HASH
    if normalize_content(str(left.get("content", ""))) == normalize_content(str(right.get("content", ""))):
        return DIFF_FORMAT_ONLY
    return DIFF_SUBSTANTIVE


def difference_label(kind: str) -> str:
    """把機器分類轉為報告／事件 reason 使用的中文標籤。"""
    return DIFF_LABELS[kind]


VERSION_FIELDS = (
    "pcode", "article_no", "content", "content_hash", "valid_from", "valid_to",
    "is_current", "version_id",
)

# 快照收斂時不把 retrieved_at 當成版本衝突：它本來就是用來選代表列的
# 觀測時間；version_id 也刻意不列為欄位衝突，因為不同快照的 ID 正是本
# 修正要收斂的對象。其餘來源欄位不一致均只回報、不修正。
SNAPSHOT_CONFLICT_FIELDS = (
    "law_name", "category", "version_date", "source_url", "valid_to",
    "is_current", "valid_from_basis", "content_hash",
)


def _version_sort_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("valid_from") or "9999-99-99"),
        str(record.get("version_date") or "9999-99-99"),
        str(record.get("version_id", "")),
    )


def _parse_iso(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _validate_version_record(record: Mapping[str, Any]) -> None:
    missing = [field for field in VERSION_FIELDS if field not in record]
    if missing:
        raise ValueError(f"版本記錄缺少欄位：{missing}")


def _selection_key(item: tuple[int, Mapping[str, Any]]) -> tuple[int, str, int]:
    """代表快照選擇鍵：有 retrieved_at 時取最大；全缺席時取輸入順序最後。"""
    index, record = item
    retrieved_at = record.get("retrieved_at")
    if retrieved_at in (None, ""):
        return (0, "", index)
    return (1, str(retrieved_at), index)


def _snapshot_field_conflict(
    candidates: Sequence[tuple[int, Mapping[str, Any]]], representative: Mapping[str, Any]
) -> dict[str, Any] | None:
    conflicts: dict[str, list[dict[str, Any]]] = {}
    for field in SNAPSHOT_CONFLICT_FIELDS:
        values = [record.get(field) for _index, record in candidates]
        if all(value == values[0] for value in values[1:]):
            continue
        conflicts[field] = [
            {"version_id": record.get("version_id"), "value": record.get(field)}
            for _index, record in candidates
        ]
    if not conflicts:
        return None
    return {
        "pcode": representative["pcode"],
        "article_no": representative["article_no"],
        "valid_from": representative.get("valid_from"),
        "version_ids": [record.get("version_id") for _index, record in candidates],
        "representative_version_id": representative.get("version_id"),
        "fields": conflicts,
        "message": "同一版本快照欄位不一致；只回報、不修正",
    }


def _collapse_snapshot_records(
    records: Sequence[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """依 (pcode, article_no, valid_from, normalized_content) 收斂快照。

    回傳：收斂後記錄、收斂稽核、欄位衝突、同日期不同內容異常。
    內容正規化相同才可收斂；同一 valid_from 的不同正規化內容永遠保留。
    """
    article_groups: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, record in enumerate(records):
        _validate_version_record(record)
        copied = dict(record)
        article_groups[(str(copied["pcode"]), str(copied["article_no"]))].append((index, copied))

    collapsed: list[dict[str, Any]] = []
    snapshot_collapses: list[dict[str, Any]] = []
    snapshot_field_conflicts: list[dict[str, Any]] = []
    same_valid_from_different_content: list[dict[str, Any]] = []

    for article_key in sorted(article_groups):
        by_valid_from: dict[object, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        entries = article_groups[article_key]
        for item in entries:
            by_valid_from[item[1].get("valid_from")].append(item)
        for valid_from, same_start in sorted(by_valid_from.items(), key=lambda item: str(item[0])):
            by_content: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
            for item in same_start:
                by_content[normalize_content(str(item[1].get("content", "")))].append(item)
            if len(by_content) > 1:
                same_valid_from_different_content.append({
                    "kind": "same_valid_from_different_content",
                    "pcode": article_key[0],
                    "article_no": article_key[1],
                    "valid_from": valid_from,
                    "version_ids_by_content": [
                        [record.get("version_id") for _index, record in candidates]
                        for _normalized, candidates in sorted(by_content.items())
                    ],
                    "message": "同一 valid_from 的正規化內容不同；保留為不同版本",
                })
            for _normalized, candidates in sorted(by_content.items()):
                representative_index, representative = max(candidates, key=_selection_key)
                collapsed.append(representative)
                if len(candidates) <= 1:
                    continue
                has_retrieved_at = any(record.get("retrieved_at") not in (None, "") for _index, record in candidates)
                snapshot_collapses.append({
                    "pcode": article_key[0],
                    "article_no": article_key[1],
                    "valid_from": valid_from,
                    "before_count": len(candidates),
                    "after_count": 1,
                    "version_ids": [record.get("version_id") for _index, record in candidates],
                    "collapsed_version_ids": [
                        record.get("version_id") for index, record in candidates if index != representative_index
                    ],
                    "representative_version_id": representative.get("version_id"),
                    "representative_selection": "retrieved_at_max" if has_retrieved_at else "input_order_last",
                })
                conflict = _snapshot_field_conflict(candidates, representative)
                if conflict is not None:
                    snapshot_field_conflicts.append(conflict)

    return collapsed, snapshot_collapses, snapshot_field_conflicts, same_valid_from_different_content


def _event_dict(event: rl.LifecycleEvent) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "effective_date": event.effective_date,
        "reason": event.reason,
        "evidence_ref": event.evidence_ref,
        "trigger_kind": event.trigger_kind,
    }


def _record_events(record: Mapping[str, Any], successor: Mapping[str, Any] | None = None) -> tuple[rl.LifecycleEvent, ...]:
    """一個官方版本的抽取／驗證事件，非最新版本再追加新版取代。"""
    version_id = str(record["version_id"])
    valid_from = record.get("valid_from")
    common = {
        "effective_date": None if valid_from in (None, "") else str(valid_from),
        "evidence_ref": version_id,
        "reason": "官方來源版本",
        "trigger_kind": "事件",
    }
    events = [rl.LifecycleEvent(rl.EXTRACTED, **common), rl.LifecycleEvent(rl.VERIFIED, **common)]
    if successor is not None:
        kind = classify_content_difference(record, successor)
        successor_date = successor.get("valid_from")
        events.append(rl.LifecycleEvent(
            rl.REPLACED,
            effective_date=None if successor_date in (None, "") else str(successor_date),
            reason=f"官方來源新版取代；差異分類：{difference_label(kind)}",
            evidence_ref=str(successor["version_id"]),
            trigger_kind="事件",
        ))
    return tuple(events)


def _build_version_chains(records: Sequence[Mapping[str, Any]]) -> tuple[tuple[dict[str, Any], ...], ...]:
    """由已收斂記錄依 (pcode, article_no) 建立排序後的不可變版本鏈。"""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        _validate_version_record(record)
        groups[(str(record["pcode"]), str(record["article_no"]))].append(dict(record))
    chains = []
    for key in sorted(groups):
        chain = sorted(groups[key], key=_version_sort_key)
        chains.append(tuple(chain))
    return tuple(chains)


def build_version_chains(records: Sequence[Mapping[str, Any]]) -> tuple[tuple[dict[str, Any], ...], ...]:
    """收斂重複快照後，依 (pcode, article_no) 建立排序後版本鏈。"""
    collapsed, _audits, _conflicts, _same_date_differences = _collapse_snapshot_records(records)
    return _build_version_chains(collapsed)


def _version_result(record: Mapping[str, Any], events: tuple[rl.LifecycleEvent, ...], result: rl.ReplayResult) -> dict[str, Any]:
    return {
        "version_id": record["version_id"],
        "version_date": record.get("version_date"),
        "valid_from": record.get("valid_from"),
        "valid_to": record.get("valid_to"),
        "is_current": record.get("is_current"),
        "content_hash": record.get("content_hash"),
        "events": [_event_dict(event) for event in events],
        "final_state": result.final_state,
        "ok": result.ok,
        "first_illegal": None if result.first_illegal is None else {
            "step": result.first_illegal[0],
            "event": result.first_illegal[1].event.event_type,
            "reason": result.first_illegal[1].reason,
        },
        "explain": rl.explain(result),
    }


def build_version_event_prototype(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """把條文版本鏈投影為狀態機事件；異常只回報，不修正輸入。"""
    collapsed_records, snapshot_collapses, snapshot_field_conflicts, same_date_differences = _collapse_snapshot_records(records)
    chains = _build_version_chains(collapsed_records)
    output_chains = []
    all_violations = []
    total_versions = 0
    total_events = 0
    same_date_by_article: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for anomaly in same_date_differences:
        same_date_by_article[(anomaly["pcode"], anomaly["article_no"])].append(anomaly)
    before_multiple_current: list[dict[str, Any]] = []
    raw_article_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        raw_article_groups[(str(record["pcode"]), str(record["article_no"]))].append(record)
    for (pcode, article_no), article_records in sorted(raw_article_groups.items()):
        # 同一 version_id 可能在多個 history snapshot 重複出現；current
        # 品質摘要以版本 ID 計數，否則同一版本的觀測列會被誤報成多個版本。
        current_by_version_id: dict[object, Mapping[str, Any]] = {}
        for record in article_records:
            if bool(record.get("is_current")):
                current_by_version_id.setdefault(record.get("version_id"), record)
        current_records = list(current_by_version_id.values())
        if len(current_records) > 1:
            before_multiple_current.append({
                "pcode": pcode,
                "article_no": article_no,
                "count": len(current_records),
                "version_ids": [record.get("version_id") for record in current_records],
                "message": "收斂前同一條文有多筆 is_current=True；與狀態機互斥檢查分開回報",
            })
    after_zero_current: list[dict[str, Any]] = []
    after_multiple_current: list[dict[str, Any]] = []
    for chain in chains:
        pcode = str(chain[0]["pcode"])
        article_no = str(chain[0]["article_no"])
        versions = []
        instances = []
        anomalies: list[dict[str, Any]] = list(same_date_by_article.get((pcode, article_no), []))
        current_count = sum(bool(record.get("is_current")) for record in chain)
        if len(chain) > 1 and current_count != 1:
            anomalies.append({"kind": "current_count", "count": current_count, "message": "多版本應有且僅有一個 current=True；僅回報，不修正"})
        current_records = [record for record in chain if bool(record.get("is_current"))]
        if current_count == 0:
            after_zero_current.append({
                "pcode": pcode, "article_no": article_no, "count": 0,
                "version_ids": [record.get("version_id") for record in chain],
                "message": "收斂後同一條文沒有 is_current=True；與狀態機互斥檢查分開回報",
            })
        elif current_count > 1:
            after_multiple_current.append({
                "pcode": pcode, "article_no": article_no, "count": current_count,
                "version_ids": [record.get("version_id") for record in current_records],
                "message": "收斂後同一條文仍有多筆 is_current=True；與狀態機互斥檢查分開回報",
            })
        for record in chain:
            if bool(record.get("is_current")) != (record.get("valid_to") in (None, "")):
                anomalies.append({"kind": "is_current_valid_to_mismatch", "version_id": record["version_id"], "message": "is_current 與 valid_to 空值不一致；僅回報，不修正"})
        for index, record in enumerate(chain):
            successor = chain[index + 1] if index + 1 < len(chain) else None
            events = _record_events(record, successor)
            replay_result = rl.replay(events)
            versions.append(_version_result(record, events, replay_result))
            instances.append(rl.RelationInstance(
                instance_id=str(record["version_id"]),
                key=(pcode, article_no, "條文版本"),
                state=replay_result.final_state,
            ))
            total_events += len(events)
            if successor is not None:
                old_to = _parse_iso(record.get("valid_to"))
                new_from = _parse_iso(successor.get("valid_from"))
                delta_days = None if old_to is None or new_from is None else (new_from - old_to).days
                if delta_days != 1:
                    anomalies.append({
                        "kind": "date_not_contiguous", "older_version_id": record["version_id"],
                        "newer_version_id": successor["version_id"], "delta_days": delta_days,
                        "message": "valid_to→valid_from 非相差 1 天；僅回報，不修正",
                    })
        violations = rl.check_exclusivity(instances)
        violation_dicts = [{"key": list(v.key), "instance_ids": list(v.instance_ids)} for v in violations]
        all_violations.extend(violation_dicts)
        output_chains.append({
            "pcode": pcode,
            "article_no": article_no,
            "version_count": len(chain),
            "versions": versions,
            "anomalies": anomalies,
            "exclusivity_violations": violation_dicts,
        })
        total_versions += len(chain)
    return {
        "rule": "先以 (pcode, article_no, valid_from, normalized_content) 收斂重複快照，再以 (pcode, article_no) 建立版本鏈；非最新版本以後繼 valid_from 產生新版取代；差異分類共用 classify_content_difference。",
        "chains": output_chains,
        "exclusivity_violations": all_violations,
        "snapshot_collapses": snapshot_collapses,
        "snapshot_field_conflicts": snapshot_field_conflicts,
        "current_flag_anomalies": {
            "before_collapse_multiple_current": before_multiple_current,
            "after_collapse_zero_current": after_zero_current,
            "after_collapse_multiple_current": after_multiple_current,
            "note": "current_flag_anomalies 是來源旗標品質摘要；exclusivity_violations 只檢查事件重播後的有效狀態，兩者語意不同。",
        },
        "counts": {
            "chains": len(output_chains), "versions": total_versions, "events": total_events,
            "chains_with_anomalies": sum(bool(chain["anomalies"]) for chain in output_chains),
            "exclusivity_violation_count": len(all_violations),
        },
    }
