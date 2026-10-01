"""計算 L1「概念」實體 P／C／U 草稿比例與 Wilson 95% 信賴區間。"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.empty_object_annotation_stats import wilson_interval

LABELS = ("P", "C", "U")


def summarize_counts(counts: dict[str, int] | Counter[str]) -> dict[str, Any]:
    normalized = {label: int(counts.get(label, 0)) for label in LABELS}
    total = sum(normalized.values())
    rows = {}
    for label in LABELS:
        lo, hi = wilson_interval(normalized[label], total)
        rows[label] = {
            "count": normalized[label],
            "share": normalized[label] / total if total else None,
            "wilson_95": [lo, hi] if lo is not None else None,
        }
    return {"total": total, "labels": rows}


def read_csv_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            label = (row.get("草稿標註") or row.get("label") or "").strip().upper()
            if label not in LABELS:
                raise ValueError(f"CSV 含無效標籤：{label!r}")
            counts[label] += 1
    return counts


def counts_from_records(records: Iterable[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        label = str(record.get("label", record.get("草稿標註", ""))).strip().upper()
        if label not in LABELS:
            raise ValueError(f"含無效標籤：{label!r}")
        counts[label] += 1
    return counts


def read_question_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for row in csv.DictReader(f) if (row.get("疑問") or "").strip() == "是")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    question_count = read_question_count(args.csv)
    result = {
        "status": "草稿，未經使用者確認",
        "sample_50": summarize_counts(read_csv_counts(args.csv)),
        "question_flags": {"count": question_count, "share": question_count / 50},
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
