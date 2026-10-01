"""計算 K3 (a)/(b)/(c) 草稿標註比例與 Wilson 95% 信賴區間。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

LABELS = ("a", "b", "c")
Z95 = 1.959963984540054


def wilson_interval(successes: int, total: int, z: float = Z95) -> tuple[float | None, float | None]:
    """回傳比例尺度（0–1）的 Wilson 95% 區間。"""
    if total <= 0:
        return None, None
    p = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    centre = (p + z2 / (2 * total)) / denominator
    half = z * math.sqrt((p * (1 - p) / total) + (z2 / (4 * total * total))) / denominator
    lower = 0.0 if successes == 0 else max(0.0, centre - half)
    upper = 1.0 if successes == total else min(1.0, centre + half)
    return lower, upper


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
            label = (row.get("草稿標註") or row.get("label") or "").strip().lower()
            if label not in LABELS:
                raise ValueError(f"CSV 含無效標籤：{label!r}")
            counts[label] += 1
    return counts


def combined_counts(new_counts: dict[str, int] | Counter[str], existing_counts: dict[str, int] | None) -> dict[str, int]:
    out = {label: int(new_counts.get(label, 0)) for label in LABELS}
    if existing_counts:
        for label in LABELS:
            out[label] += int(existing_counts.get(label, 0))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--existing-counts", nargs=3, type=int, metavar=("A", "B", "C"), help="既有 30 筆的 a b c 數量，例如 11 14 5")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    new_counts = read_csv_counts(args.csv)
    result: dict[str, Any] = {
        "status": "草稿，未經使用者確認",
        "new_70": summarize_counts(new_counts),
    }
    if args.existing_counts:
        existing = dict(zip(LABELS, args.existing_counts))
        if sum(existing.values()) != 30:
            raise SystemExit("既有標註數量必須合計 30")
        result["existing_30_reference"] = {"status": "報告200 單人參考標註，未經本次使用者確認", **summarize_counts(existing)}
        result["combined_100_draft"] = summarize_counts(combined_counts(new_counts, existing))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
