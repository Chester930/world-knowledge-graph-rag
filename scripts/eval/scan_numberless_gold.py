"""報告62 §14.7：掃描題庫中『gold_answer 含數字、但所有 gold span 都不含該數字』的題目（唯讀）。

這類題目的 gold span 只是不含關鍵數字的片段，答案只要引用片段、說「無法確認數字」也能通過
（`57-DIST1/2` 的成因）。用法：python scripts/eval/scan_numberless_gold.py [--eligible-only]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "eval"
_DIG = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUMTOK = re.compile(r"[0-9]+|[零〇一二兩三四五六七八九十百千]+")
# 數量：數字後接單位（排除「第N條／款」這類條號）
_QTY = re.compile(r"([0-9]+|[零〇一二兩三四五六七八九十百千]+)\s*(?=日|天|年|個月|月|週|周|小時|分鐘|人|元|%|％|倍|歲|次|期)")


def cn2int(tok: str) -> int | None:
    """中文（或阿拉伯）數字 → 整數；支援到千位（『三十』『一百五十』『十四』）。"""
    if tok.isdigit():
        return int(tok)
    total, cur = 0, 0
    for ch in tok:
        if ch in _DIG:
            cur = _DIG[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        elif ch == "千":
            total += (cur or 1) * 1000
            cur = 0
        else:
            return None
    return total + cur


def values(s: str) -> set[int]:
    """文字中所有數值（阿拉伯與中文數字統一為整數），略過 0 與過大的編號。"""
    out = set()
    for tok in _NUMTOK.findall(s or ""):
        v = cn2int(tok)
        if v is not None and 0 < v < 100000:
            out.add(v)
    return out


def quantities(s: str) -> set[int]:
    """只取『數字＋單位』的數量（gold_answer 用），條號不算。"""
    out = set()
    for tok in _QTY.findall(s or ""):
        v = cn2int(tok)
        if v is not None and 0 < v < 100000:
            out.add(v)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eligible-only", action="store_true")
    args = ap.parse_args()
    bank = json.loads((DATA / "test_cases.json").read_text(encoding="utf-8"))["questions"]
    eligible = set(json.loads((DATA / "baseline_runs/20260920_frozen/frozen_manifest.json").read_text(encoding="utf-8"))["eligible_ids"])
    hits = []
    for q in bank:
        if args.eligible_only and q["id"] not in eligible:
            continue
        if q["scenario_type"] == "Type-E":
            continue
        need = quantities(q.get("gold_answer") or "") - values(q["question"])
        have = values(" ".join(f["exact_span"] for f in q["atomic_gold_facts"]))
        missing = sorted(need - have)
        if missing:
            hits.append((q["id"], q["scenario_type"], missing, q["question"][:50]))
    print(f"gold_answer 含數值（題目未給）但所有 gold span 都不含的題目：{len(hits)}／{len(bank)}"
          + (f"（僅 42 題合格）" if args.eligible_only else ""))
    for h in hits:
        print(" ", h[0], h[1], "缺:", h[2], "|", h[3])


if __name__ == "__main__":
    main()
