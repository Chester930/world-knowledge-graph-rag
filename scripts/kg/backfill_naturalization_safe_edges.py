"""T2 backfill for the explicitly approved naturalization edge allowlist.

The dry-run generated the proposed values; this tool does not call an LLM.
It re-reads each relationship immediately before writing, compares the current
natural_text and relationship inputs with the dry-run snapshot, and uses the
current citations_json as a compare-and-set guard in the SET transaction.

Default mode is a read-only preflight.  Pass --apply to perform only
``SET r.natural_text`` on the 27 hard-coded approved edge IDs.
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
DRYRUN_JSON = DRYRUN_DIR / "affected_edges.json"
WRITE_LOG = DRYRUN_DIR / "t2_write_log.json"
DATABASE = "neo4j"

KG_ID = "236903cf-055a-40a8-8923-b9d06601f3b7"
EDGE_PREFIX = "5:e98c5070-f9d3-4e84-808d-8c0e8fa6e8c4:"
SAFE_EDGE_SUFFIXES = frozenset(
    {
        "1152927002165019572",
        "1152927002165023767",
        "1152927002165023772",
        "1152927002165025297",
        "1152927002165028952",
        "1152927002165033107",
        "1152927002165035802",
        "1152927002165040978",
        "1152927002165041341",
        "1152936897769664027",
        "1152937997281292486",
        "1152947892885957676",
        "1155178801978699636",
        "1155178801978703559",
        "1155178801978722249",
        "1157430601792410752",
        "6917534525199251412",
        "6917534525199251414",
        "6917534525199259984",
        "6917534525199263903",
        "6917534525199264614",
        "6917534525199266133",
        "6917534525199266661",
        "6917534525199269094",
        "6917534525199269602",
        "6917534525199271940",
        "6917546619827179615",
    }
)

READ_QUERY = """
MATCH (s)-[r]->(o)
WHERE elementId(r) = $edge_id
RETURN elementId(r) AS edge_id,
       r.kg_id AS kg_id,
       type(r) AS rel_type,
       r.natural_text AS natural_text,
       r.citations_json AS citations_json,
       s.name AS subject,
       s.type AS subject_type,
       o.name AS object,
       o.type AS object_type
"""

# This is deliberately the only write query in this tool.  No CREATE/DELETE
# or node property update is permitted by the T2 scope.
WRITE_QUERY = """
MATCH (s)-[r]->(o)
WHERE elementId(r) = $edge_id
  AND r.kg_id = $kg_id
  AND r.natural_text = $expected_old
  AND s.name = $subject
  AND s.type = $subject_type
  AND o.name = $object
  AND o.type = $object_type
  AND ((r.citations_json = $expected_citations_json)
       OR (r.citations_json IS NULL AND $expected_citations_json IS NULL))
SET r.natural_text = $new_text
RETURN r.natural_text AS natural_text
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_targets() -> dict[str, dict[str, Any]]:
    rows = json.loads(DRYRUN_JSON.read_text(encoding="utf-8"))
    targets = {
        row["edge_id"]: row
        for row in rows
        if row.get("edge_id", "").rsplit(":", 1)[-1] in SAFE_EDGE_SUFFIXES
    }
    expected_ids = {EDGE_PREFIX + suffix for suffix in SAFE_EDGE_SUFFIXES}
    if set(targets) != expected_ids:
        missing = sorted(expected_ids - set(targets))
        extra = sorted(set(targets) - expected_ids)
        raise RuntimeError(f"safe allowlist mismatch; missing={missing}, extra={extra}")
    for edge_id, row in targets.items():
        if row.get("status") != "recomputed":
            raise RuntimeError(f"approved edge is not recomputed: {edge_id}")
        if row.get("kg_id") != KG_ID:
            raise RuntimeError(f"approved edge has unexpected kg_id: {edge_id}")
        if not isinstance(row.get("new_text"), str) or not row["new_text"]:
            raise RuntimeError(f"approved edge has no proposed new_text: {edge_id}")
    return targets


def latest_citation_verb(citations_json: str | None) -> str | None:
    if not citations_json:
        return None
    citations = json.loads(citations_json)
    if not isinstance(citations, list) or not citations:
        return None
    latest = citations[-1]
    return latest.get("verb") if isinstance(latest, dict) else None


def field_diffs(expected: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    checks = (
        ("kg_id", expected.get("kg_id"), current.get("kg_id")),
        ("rel_type", expected.get("rel_type"), current.get("rel_type")),
        ("natural_text", expected.get("old_text"), current.get("natural_text")),
        ("subject", expected.get("subject"), current.get("subject")),
        ("subject_type", expected.get("subject_type"), current.get("subject_type")),
        ("verb", expected.get("verb"), current.get("latest_verb")),
        ("object", expected.get("object"), current.get("object")),
        ("object_type", expected.get("object_type"), current.get("object_type")),
    )
    return [
        {"field": field, "expected": old, "actual": new}
        for field, old, new in checks
        if old != new
    ]


def read_log() -> dict[str, Any]:
    if not WRITE_LOG.exists():
        return {
            "operation": "t2_naturalization_safe_allowlist",
            "dryrun": str(DRYRUN_JSON.relative_to(REPO_ROOT)).replace("\\", "/"),
            "database": DATABASE,
            "kg_id": KG_ID,
            "target_count": len(SAFE_EDGE_SUFFIXES),
            "approved_edge_ids": sorted(EDGE_PREFIX + suffix for suffix in SAFE_EDGE_SUFFIXES),
            "entries": [],
        }
    return json.loads(WRITE_LOG.read_text(encoding="utf-8"))


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
    current = dict(result.records[0])
    current["latest_verb"] = latest_citation_verb(current.get("citations_json"))
    return current


async def apply_one(driver: Any, expected: dict[str, Any], log: dict[str, Any]) -> str:
    edge_id = expected["edge_id"]
    current = await read_current(driver, edge_id)
    if current is None:
        record_entry(
            log,
            {
                "timestamp_utc": utc_now(),
                "edge_id": edge_id,
                "kg_id": KG_ID,
                "status": "skipped_not_found",
                "old_value": None,
                "new_value": expected["new_text"],
                "reason": "relationship not found",
            },
        )
        return "skipped"

    diffs = field_diffs(expected, current)
    if diffs:
        record_entry(
            log,
            {
                "timestamp_utc": utc_now(),
                "edge_id": edge_id,
                "kg_id": KG_ID,
                "status": "skipped_source_changed",
                "old_value": current.get("natural_text"),
                "new_value": expected["new_text"],
                "field_diffs": diffs,
            },
        )
        return "skipped"

    params = {
        "edge_id": edge_id,
        "kg_id": KG_ID,
        "expected_old": expected["old_text"],
        "subject": current["subject"],
        "subject_type": current["subject_type"],
        "object": current["object"],
        "object_type": current["object_type"],
        "expected_citations_json": current["citations_json"],
        "new_text": expected["new_text"],
    }
    write_result = await driver.execute_query(WRITE_QUERY, **params, database_=DATABASE)
    if not write_result.records:
        after = await read_current(driver, edge_id)
        record_entry(
            log,
            {
                "timestamp_utc": utc_now(),
                "edge_id": edge_id,
                "kg_id": KG_ID,
                "status": "skipped_write_guard_failed",
                "old_value": current.get("natural_text"),
                "new_value": expected["new_text"],
                "actual_after_value": after.get("natural_text") if after else None,
                "reason": "compare-and-set guard did not match",
            },
        )
        return "skipped"

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
    return "written" if status == "written_verified" else "failed"


async def run(apply: bool) -> int:
    from core.config import settings
    from core.database import connect, disconnect, get_driver

    targets = load_targets()
    log = read_log()
    if log.get("approved_edge_ids") != sorted(targets):
        raise RuntimeError("existing audit log allowlist does not match the approved 27 IDs")

    await connect()
    driver = get_driver()
    try:
        if not apply:
            print(f"preflight only: {len(targets)} exact approved edges; no SET executed")
            for edge_id in sorted(targets):
                current = await read_current(driver, edge_id)
                if current is None:
                    print(edge_id, "NOT_FOUND")
                    continue
                diffs = field_diffs(targets[edge_id], current)
                print(edge_id, "READY" if not diffs else f"SKIP {json.dumps(diffs, ensure_ascii=False)}")
            return 0

        log["started_at_utc"] = log.get("started_at_utc") or utc_now()
        log["apply_requested_at_utc"] = utc_now()
        log["apply_mode"] = True
        write_log(log)
        counts = {"written": 0, "skipped": 0, "failed": 0}
        for edge_id in sorted(targets):
            outcome = await apply_one(driver, targets[edge_id], log)
            counts[outcome] += 1
            print(edge_id, outcome, flush=True)
        log["result_counts"] = counts
        log["completed_at_utc"] = utc_now()
        write_log(log)
        print(json.dumps(counts, ensure_ascii=False))
        return 1 if counts["failed"] else 0
    finally:
        await disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute the allowlisted SET operations")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
