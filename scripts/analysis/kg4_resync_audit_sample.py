"""重現報告254 的審核抽樣（純離線：只讀 `kg4_resync_audit_20261002.json`，不連線）。

抽樣規則：每類取「影響 Fact 數最多的前 n/3 組」＋「其餘隨機（seed=11）n−n/3 組」；
人工判讀標籤見 `data/analysis/kg4_resync_audit_labels_20261002.json`（索引對應本腳本輸出的序號）。
用法：python scripts/analysis/kg4_resync_audit_sample.py <category> <n>
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[2] / "data" / "analysis" / "kg4_resync_audit_20261002.json"


def sample_pairs(pairs: list[dict], category: str, n: int) -> list[dict]:
    ps = [p for p in pairs if p["category"] == category]
    if len(ps) <= n:
        return ps
    rng = random.Random(11)
    return ps[: n // 3] + rng.sample(ps[n // 3:], n - n // 3)


def main(argv: list[str]) -> int:
    pairs = json.loads(AUDIT.read_text(encoding="utf-8"))["pairs"]
    for i, p in enumerate(sample_pairs(pairs, argv[1], int(argv[2]))):
        print(f"{i:3d} [{p['side'][:1]}x{p['facts']}] {p['old']}  =>  {p['new']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
