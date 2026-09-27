"""Safely fix the 20 report 71 residual naturalization facts verified against law text.

Report 71 (2026-09-23) split 49 recomputed `natural_text` edges into 27 safe
(already backfilled), 17 needing manual review, and 5 recommended for
exclusion. Report 92 (2026-09-27) had those 22 residual edges checked one by
one against the official law text database (law.moj.gov.tw) and found:

- 5 edges are safe to backfill with their already-computed ``new_text``
  as-is (the mechanical review flag was a false positive).
- 10 edges (originally "needs review") have real defects and get a verified
  replacement ``natural_text`` sourced from the official article text.
- 5 edges (originally "recommended exclude") have their exclusion confirmed,
  but the official article text yields a clean replacement anyway, so they
  are fixed rather than left with the stale, type-marker-laden text.
- 2 edges (``...1152927002165017400`` and ``...1152927002165023783``) are
  NOT included here: their structured ``subject``/``object`` fields
  themselves are wrong (paragraph misplacement / formula symbol confusion),
  which ``natural_text`` alone cannot fix without touching structured
  fields. They are left untouched, as documented in report 92 section 2.3.

The default mode is a read-only preflight. ``--apply`` performs only the 20
allowlisted ``SET r.natural_text`` operations, after re-reading each
relationship and checking the compare-and-set guard. Structured relationship
fields are never written by this tool.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

DRYRUN_DIR = REPO_ROOT / "data" / "eval" / "naturalization_backfill_dryrun_20260923"
WRITE_LOG = DRYRUN_DIR / "report92_residual_20_fix_write_log.json"
DATABASE = "neo4j"

KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"
TARGETS: dict[str, dict[str, str]] = {
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165029730": {
        "rel_type": "RELATED_TO",
        "subject": "標示於槽壁缺乏識別效果之地下儲槽",
        "subject_type": "PRODUCT",
        "object": "標示牌",
        "object_type": "DEVICE",
        "expected_old": "地下儲槽（PRODUCT）標示於槽壁缺乏識別效果者得設置標示牌（DEVICE）。",
        "new_text": "標示於槽壁缺乏識別效果之地下儲槽 得採設置 標示牌",
        "source": "safe_as_computed",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1155178801978703584": {
        "rel_type": "RELATED_TO",
        "subject": "定期向雇主報告及勞工健康服務之建議",
        "subject_type": "Service",
        "object": "前條所定勞工健康服務事項",
        "object_type": "Service",
        "expected_old": "Service屬於前條所定勞工健康服務事項。",
        "new_text": "定期向雇主報告及勞工健康服務之建議 屬於 前條所定勞工健康服務事項",
        "source": "safe_as_computed",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1155178801978703736": {
        "rel_type": "RELATED_TO",
        "subject": "推介就業情形回覆卡",
        "subject_type": "CREATIVE_WORK",
        "object": "公立就業服務機構",
        "object_type": "概念",
        "expected_old": "CREATIVE_WORK通知ORGANIZATION有關推介就業情形回覆卡事宜。",
        "new_text": "推介就業情形回覆卡 通知 公立就業服務機構",
        "source": "safe_as_computed",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1161934201419755035": {
        "rel_type": "RELATED_TO",
        "subject": "支出殯葬費之人",
        "subject_type": "PERSON",
        "object": "保險給付",
        "object_type": "Property",
        "expected_old": "PERSON以郵寄方式向保險人請領insurance給付。",
        "new_text": "支出殯葬費之人以郵寄方式向保險人請領保險給付。",
        "source": "safe_as_computed",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:6917558714455078035": {
        "rel_type": "MOTIVATED_BY_GOAL",
        "subject": "清艙作業或解體作業之實際負責人",
        "subject_type": "PERSON",
        "object": "安全負責人",
        "object_type": "Role",
        "expected_old": "PERSON為安全負責人。",
        "new_text": "清艙作業或解體作業之實際負責人 為 安全負責人",
        "source": "safe_as_computed",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165016788": {
        "rel_type": "RELATED_TO",
        "subject": "最高負責人",
        "subject_type": "POSITION",
        "object": "地方主管機關應依下列各款規定審認之",
        "object_type": "ORGANIZATION",
        "expected_old": "最高負責人 POSITION 確定地方主管機關應依下列各款規定審認之 ORGANIZATION。",
        "new_text": "地方主管機關應依下列各款規定，審認本法所定之最高負責人。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165025320": {
        "rel_type": "RELATED_TO",
        "subject": "出生年月日",
        "subject_type": "PERSON",
        "object": "資料變更申請書",
        "object_type": "CREATIVE_WORK",
        "expected_old": "PERSON有提出資料變更申請書。",
        "new_text": "出生年月日有變更或錯誤時，雇主應即填具資料變更申請書。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165025328": {
        "rel_type": "RELATED_TO",
        "subject": "居留證統一證號",
        "subject_type": "PERSON",
        "object": "資料變更申請書",
        "object_type": "CREATIVE_WORK",
        "expected_old": "居留證統一證號 PERSON 有變更或錯誤時，需提出資料變更申請書。",
        "new_text": "居留證統一證號有變更或錯誤時，雇主應即填具資料變更申請書。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165025941": {
        "rel_type": "RELATED_TO",
        "subject": "現任或曾任公私立學校教師及職員",
        "subject_type": "PERSON",
        "object": "資格",
        "object_type": "SYNONYM",
        "expected_old": "PERSON 具有 教師及職員資格。",
        "new_text": "現任或曾任公私立學校教師及職員，具有擔任監場人員之資格。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165037197": {
        "rel_type": "RELATED_TO",
        "subject": "受託業務及提供服務之收入",
        "subject_type": "Service",
        "object": "經費來源",
        "object_type": "FUND",
        "expected_old": "Service為FUND來源。",
        "new_text": "受託業務及提供服務之收入為經費來源之一。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152945693862695968": {
        "rel_type": "PART_OF",
        "subject": "t",
        "subject_type": "PRODUCT",
        "object": "單位：立方公尺",
        "object_type": "概念",
        "expected_old": "t（PRODUCT）的回轉活塞之氣體壓縮部分之厚度值單位為立方公尺。",
        "new_text": "t 為回轉活塞之氣體壓縮部分之厚度值，單位為公尺。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1155179901490326826": {
        "rel_type": "DEFINED_AS",
        "subject": "本辦法",
        "subject_type": "概念",
        "object": "定團體",
        "object_type": "ORGANIZATION",
        "expected_old": "本辦法所稱定團體是指ORGANIZATION。",
        "new_text": "本辦法所稱之團體，指依人民團體法或其他法令設立者。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:6917534525199257486": {
        "rel_type": "RELATED_TO",
        "subject": "持有",
        "subject_type": "LOCAL_BUSINESS",
        "object": "合格證明",
        "object_type": "CREATIVE_WORK",
        "expected_old": "持有ORGANIZATION民用航空醫務中心所發出的航空人員體格檢查合格證明，為合格證明CREATIVE_WORK。",
        "new_text": "持有民用航空醫務中心航空人員體格檢查合格證明。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:6917534525199270989": {
        "rel_type": "RELATED_TO",
        "subject": "安置對象",
        "subject_type": "ORGANIZATION",
        "object": "安置",
        "object_type": "DEFINED_AS",
        "expected_old": "安置對象 CREATIVE_WORK 屬於安置 DEFINED_AS。",
        "new_text": "安置對象、期間及程序，由中央主管機關所定。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:6917534525199273547": {
        "rel_type": "RELATED_TO",
        "subject": "請領各項保險給付之診斷書及證明書",
        "subject_type": "CREATIVE_WORK,LOCAL_BUSINESS,PERSON",
        "object": "醫院出具",
        "object_type": "LOCAL_BUSINESS",
        "expected_old": "除第五十六條及第五十七條另有規定者外，請領各項保險給付之診斷書及證明書應由醫院出具（LOCAL_BUSINESS）。",
        "new_text": "請領各項保險給付之診斷書及證明書，除第五十六條及第五十七條另有規定者外，應由醫院、診所或領有執業執照之醫師出具。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165023788": {
        "rel_type": "RELATED_TO",
        "subject": "C",
        "subject_type": "PRODUCT",
        "object": "無",
        "object_type": "概念",
        "expected_old": "C（PRODUCT）依冷媒氣體決定之中央主管機關之指定值進行檢測。",
        "new_text": "C為依冷媒氣體決定之中央主管機關之指定值。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165040151": {
        "rel_type": "RELATED_TO",
        "subject": "國家標準 CNS 16368, 國家標准 CNS 16653 系列, 國家標准 CNS 18893",
        "subject_type": "概念",
        "object": "國際標準 ISO16368, 國際標准 ISO16653系列, 國際標准 ISO18893 不一致時，以",
        "object_type": "STANDARD",
        "expected_old": "國家標準CNS 16368、CNS 16653系列及CNS 18893與國際標準ISO 16368、ISO 16653系列及ISO 18893不一致時，以STANDARD為準。",
        "new_text": "國家標準CNS 16368、CNS 16653系列及CNS 18893與國際標準ISO16368、ISO16653系列及ISO18893不一致時，以國際標準為準。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152951191420832698": {
        "rel_type": "MOTIVATED_BY_GOAL",
        "subject": "被申訴人",
        "subject_type": "PERSON",
        "object": "最高負責人",
        "object_type": "POSITION",
        "expected_old": "被申訴人 PERSON 的最高負責人為最高負責人。",
        "new_text": "被申訴人為最高負責人。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1155178801978722385": {
        "rel_type": "RELATED_TO",
        "subject": "閥之相關裝置操作場所",
        "subject_type": "PRODUCT",
        "object": "措施",
        "object_type": "概念",
        "expected_old": "閥之相關裝置 PRODUCT 應當加鎖、鉛封或採取其他同等有效的措施 CREATIVE_WORK。",
        "new_text": "操作對製造設備安全有重大影響且不常使用之閥之相關裝置，應予加鎖、鉛封或採取其他同等有效之措施。",
        "source": "verified_correct",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1155178801978723107": {
        "rel_type": "RELATED_TO",
        "subject": "從事前項規定作業之勞工",
        "subject_type": "PERSON",
        "object": "十一",
        "object_type": "概念",
        "expected_old": "從事前項規定作業之勞工 PERSON 必須供給穿著不浸透性防護衣、防護手套、防護長鞋及呼吸用防護具等個人防護具十一種。",
        "new_text": "從事該作業之勞工，雇主應供給其穿著不浸透性防護衣、防護手套、防護長鞋、呼吸用防護具等個人防護具。",
        "source": "verified_correct",
    },
}

READ_QUERY = """
MATCH (s)-[r]->(o)
WHERE elementId(r) = $edge_id
RETURN elementId(r) AS edge_id,
       r.kg_id AS kg_id,
       type(r) AS rel_type,
       r.natural_text AS natural_text,
       s.name AS subject,
       s.type AS subject_type,
       o.name AS object,
       o.type AS object_type
"""

# This is deliberately the only write query in this tool. It updates only
# natural_text; all other fields are compare-and-set guards.
WRITE_QUERY = """
MATCH (s)-[r]->(o)
WHERE elementId(r) = $edge_id
  AND r.kg_id = $kg_id
  AND type(r) = $rel_type
  AND r.natural_text = $expected_old
  AND s.name = $subject
  AND s.type = $subject_type
  AND o.name = $object
  AND o.type = $object_type
SET r.natural_text = $new_text
RETURN r.natural_text AS natural_text
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def field_diffs(expected: dict[str, str], current: dict[str, Any]) -> list[dict[str, Any]]:
    checks = (
        ("kg_id", KG_ID, current.get("kg_id")),
        ("rel_type", expected["rel_type"], current.get("rel_type")),
        ("natural_text", expected["expected_old"], current.get("natural_text")),
        ("subject", expected["subject"], current.get("subject")),
        ("subject_type", expected["subject_type"], current.get("subject_type")),
        ("object", expected["object"], current.get("object")),
        ("object_type", expected["object_type"], current.get("object_type")),
    )
    return [
        {"field": field, "expected": expected_value, "actual": actual_value}
        for field, expected_value, actual_value in checks
        if expected_value != actual_value
    ]


def new_log() -> dict[str, Any]:
    return {
        "operation": "report92_residual_20_naturalization_fix",
        "database": DATABASE,
        "kg_id": KG_ID,
        "target_count": len(TARGETS),
        "target_edge_ids": sorted(TARGETS),
        "entries": [],
    }


def read_log() -> dict[str, Any]:
    if not WRITE_LOG.exists():
        return new_log()
    log = json.loads(WRITE_LOG.read_text(encoding="utf-8"))
    if log.get("target_edge_ids") != sorted(TARGETS):
        raise RuntimeError("existing report92 audit log target IDs do not match")
    return log


def write_log(log: dict[str, Any]) -> None:
    WRITE_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_entry(log: dict[str, Any], entry: dict[str, Any]) -> None:
    log["entries"].append(entry)
    log["updated_at_utc"] = utc_now()
    write_log(log)


async def read_current(driver: Any, edge_id: str) -> dict[str, Any] | None:
    result = await driver.execute_query(READ_QUERY, edge_id=edge_id, database_=DATABASE)
    if not result.records:
        return None
    return dict(result.records[0])


async def apply_one(
    driver: Any, edge_id: str, expected: dict[str, str], log: dict[str, Any]
) -> str:
    current = await read_current(driver, edge_id)
    if current is None:
        status = "skipped_not_found"
        record_entry(
            log,
            {
                "timestamp_utc": utc_now(),
                "edge_id": edge_id,
                "kg_id": KG_ID,
                "status": status,
                "old_value": None,
                "new_value": expected["new_text"],
                "reason": "relationship not found",
            },
        )
        return status

    diffs = field_diffs(expected, current)
    if diffs:
        status = "skipped_source_changed"
        record_entry(
            log,
            {
                "timestamp_utc": utc_now(),
                "edge_id": edge_id,
                "kg_id": KG_ID,
                "status": status,
                "old_value": current.get("natural_text"),
                "new_value": expected["new_text"],
                "field_diffs": diffs,
            },
        )
        return status

    params = {
        "edge_id": edge_id,
        "kg_id": KG_ID,
        "rel_type": expected["rel_type"],
        "expected_old": expected["expected_old"],
        "subject": expected["subject"],
        "subject_type": expected["subject_type"],
        "object": expected["object"],
        "object_type": expected["object_type"],
        "new_text": expected["new_text"],
    }
    write_result = await driver.execute_query(WRITE_QUERY, **params, database_=DATABASE)
    if not write_result.records:
        after = await read_current(driver, edge_id)
        status = "skipped_write_guard_failed"
        record_entry(
            log,
            {
                "timestamp_utc": utc_now(),
                "edge_id": edge_id,
                "kg_id": KG_ID,
                "status": status,
                "old_value": current.get("natural_text"),
                "new_value": expected["new_text"],
                "actual_after_value": after.get("natural_text") if after else None,
                "reason": "compare-and-set guard did not match",
            },
        )
        return status

    after = await read_current(driver, edge_id)
    actual_after = after.get("natural_text") if after else None
    status = "written_verified" if actual_after == expected["new_text"] else "verification_failed"
    record_entry(
        log,
        {
            "timestamp_utc": utc_now(),
            "edge_id": edge_id,
            "kg_id": KG_ID,
            "status": status,
            "old_value": current.get("natural_text"),
            "new_value": expected["new_text"],
            "actual_before_value": current.get("natural_text"),
            "actual_after_value": actual_after,
        },
    )
    return status


async def run(apply: bool) -> int:
    from core.database import connect, disconnect, get_driver

    log = read_log()
    await connect()
    driver = get_driver()
    try:
        if not apply:
            print(f"preflight only: {len(TARGETS)} exact report92 edges; no SET executed")
            all_ready = True
            for edge_id in sorted(TARGETS):
                current = await read_current(driver, edge_id)
                if current is None:
                    print(edge_id, "NOT_FOUND")
                    all_ready = False
                    continue
                diffs = field_diffs(TARGETS[edge_id], current)
                if diffs:
                    print(edge_id, f"SKIP {json.dumps(diffs, ensure_ascii=False)}")
                    all_ready = False
                else:
                    print(edge_id, "READY")
            return 0 if all_ready else 1

        log["started_at_utc"] = log.get("started_at_utc") or utc_now()
        log["apply_requested_at_utc"] = utc_now()
        log["apply_mode"] = True
        write_log(log)
        result_counts: dict[str, int] = {}
        for edge_id in sorted(TARGETS):
            status = await apply_one(driver, edge_id, TARGETS[edge_id], log)
            result_counts[status] = result_counts.get(status, 0) + 1
            print(edge_id, status, flush=True)
        log["result_counts"] = result_counts
        log["completed_at_utc"] = utc_now()
        write_log(log)
        print(json.dumps(result_counts, ensure_ascii=False))
        return 0 if result_counts == {"written_verified": len(TARGETS)} else 1
    finally:
        await disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute the 20 guarded SET operations")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
