"""報告62 §14（T5）：評分器稽核彙整（唯讀）。

讀 `audit_scorer_disagreements.py` 產生的審讀名單與 `labels_by_claude.json`（模型標註，非人工真值），
輸出：各組的評分器對錯數、以及一條**候選確定性規則**在這批標註上的表現。

候選規則 R（用來補救偽陰性，只在評分器判 missing 時檢查）：
  bigram 重疊 ≥ T，且 gold 內所有數字／條款序號 token 都出現在答案，且答案窗口沒有否定用語
  （無法確認／未明確記載／並未）。目的是檢查『高重疊』單獨不足以區分，需要數字與否定守衛。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_scorer_disagreements import overlap  # noqa: E402

AUDIT = Path(__file__).resolve().parents[2] / "data" / "eval" / "scorer_audit_20260922"
NUM = re.compile(r"[0-9]+|[一二三四五六七八九十百千萬兩]+")
NEG = ("無法確認", "未明確記載", "並未", "未直接", "沒有記載")


def numbers(s: str) -> list[str]:
    return NUM.findall(re.sub(r"\s+", "", s))


def rule_r(x: dict, t: float) -> bool:
    if x["overlap"] < t:
        return False
    ans = re.sub(r"\s+", "", x["window"])
    if any(n in x["window"] for n in NEG):
        return False
    return all(n in ans for n in numbers(x["gold_span"]))


def main() -> None:
    sample = json.loads((AUDIT / "review_sample.json").read_text(encoding="utf-8"))
    lab = json.loads((AUDIT / "labels_by_claude.json").read_text(encoding="utf-8"))
    label_of = {}
    for name in ("scorer_wrong", "scorer_correct", "ambiguous"):
        for i in lab[name]:
            label_of[i] = name
    assert len(label_of) == len(sample) == 69, (len(label_of), len(sample))

    print("=== 各組（評分器判定 × 標註）")
    for g in ("fn_candidate", "fp_candidate", "agree_hit", "agree_miss"):
        xs = [x for x in sample if x["group"] == g]
        c = {k: sum(1 for x in xs if label_of[x["id"]] == k) for k in ("scorer_wrong", "scorer_correct", "ambiguous")}
        print(f"{g:13s} n={len(xs):2d} (組母體 {xs[0]['group_size']}): 評分器錯 {c['scorer_wrong']}、對 {c['scorer_correct']}、不確定 {c['ambiguous']}")

    print("\n=== 唯一 (題目, gold span) 數（同一答案在多次執行重複出現）")
    for g in ("fn_candidate", "fp_candidate"):
        xs = [x for x in sample if x["group"] == g]
        wrong = {(x["question_id"], x["gold_span"]) for x in xs if label_of[x["id"]] == "scorer_wrong"}
        allu = {(x["question_id"], x["gold_span"]) for x in xs}
        print(f"{g}: 唯一 span {len(allu)}，其中評分器判錯 {len(wrong)}；涉及題目 {sorted({q for q, _ in wrong})}")

    print("\n=== 錯誤成因（評分器判錯者）")
    for cause, ids in lab["wrong_cause"].items():
        print(f"  {cause}: {len(ids)}")

    print("\n=== 候選規則 R 在『評分器判 missing』的 37＋10 個標註案例上（wrong＝答案其實有支持）")
    missing = [x for x in sample if x["scorer"] == "missing"]
    for t in (0.7, 0.8, 0.9):
        fired = [x for x in missing if rule_r(x, t)]
        tp = sum(1 for x in fired if label_of[x["id"]] == "scorer_wrong")
        fp = sum(1 for x in fired if label_of[x["id"]] == "scorer_correct")
        amb = sum(1 for x in fired if label_of[x["id"]] == "ambiguous")
        total_wrong = sum(1 for x in missing if label_of[x["id"]] == "scorer_wrong")
        total_correct = sum(1 for x in missing if label_of[x["id"]] == "scorer_correct")
        print(f"  T={t}: 觸發 {len(fired)}；救回真偽陰性 {tp}/{total_wrong}；誤翻正確的 missing {fp}/{total_correct}；不確定 {amb}")
    print("  （只重疊、不加守衛時，相同 T 會誤翻多少：）")
    for t in (0.7, 0.9):
        fired = [x for x in missing if x["overlap"] >= t]
        fp = sum(1 for x in fired if label_of[x["id"]] == "scorer_correct")
        tp = sum(1 for x in fired if label_of[x["id"]] == "scorer_wrong")
        print(f"  T={t} 無守衛: 觸發 {len(fired)}；救回 {tp}；誤翻 {fp}")


if __name__ == "__main__":
    main()
