"""Safely fix the two report 90 naturalization facts verified against law text.

The default mode is a read-only preflight.  ``--apply`` performs only the two
allowlisted ``SET r.natural_text`` operations, after re-reading each
relationship and checking the compare-and-set guard.  Structured relationship
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
WRITE_LOG = DRYRUN_DIR / "report90_manual_fix_write_log.json"
DATABASE = "neo4j"

KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"
TARGETS: dict[str, dict[str, str]] = {
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152927002165041341": {
        "rel_type": "RELATED_TO",
        "subject": "發生災害時之",
        "subject_type": "Action",
        "object": "左列高壓氣體製造安全有關事項",
        "object_type": "WORK_GUIDELINE",
        "expected_old": "發生災害時之 災害原因調查及檢討防災對策 左列高壓氣體製造安全有關事項",
        "new_text": "發生災害時之災害原因調查及檢討防災對策。",
    },
    "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:1152937997281292486": {
        "rel_type": "USED_FOR",
        "subject": "接受從事本法第四十六條規定工作之外國人委任",
        "subject_type": "ORGANIZATION",
        "object": "始得從事就業服務業務",
        "object_type": "Service",
        "expected_old": "接受從事本法第四十六條規定工作之外國人委任 代其辦理居留業務 始得從事就業服務業務",
        "new_text": "接受從事本法第四十六條規定工作之外國人委任，代其辦理居留業務。",
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

# This is deliberately the only write query in this tool.  It updates only
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
        "operation": "report90_manual_naturalization_fix",
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
        raise RuntimeError("existing report90 audit log target IDs do not match")
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
            print(f"preflight only: {len(TARGETS)} exact report90 edges; no SET executed")
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
    parser.add_argument("--apply", action="store_true", help="execute the two guarded SET operations")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
