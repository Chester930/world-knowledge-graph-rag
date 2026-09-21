"""報告62 §14.6：彙整盲審交叉比對（唯讀）。

把各模型對「答案是否支持 gold 命題」的盲審判斷，與標註者（Claude）由標註推得的真值比較：

  真值：scorer_wrong → 與評分器判定相反；scorer_correct → 與評分器判定相同；ambiguous → 不計。

輸出：各模型對標註真值的一致率、模型間一致率、以及『需人工複核』清單＝所有有效模型都與標註者
不同意的案例（模型一致地反對標註者，較可能是標註者錯，或案例本身有歧義）。
小模型判斷力有限，一致率只當交叉檢查訊號，不是真值。
"""
from __future__ import annotations

import json
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[2] / "data" / "eval" / "scorer_audit_20260922"


def main() -> None:
    sample = {x["id"]: x for x in json.loads((AUDIT / "review_sample.json").read_text(encoding="utf-8"))}
    lab = json.loads((AUDIT / "labels_by_claude.json").read_text(encoding="utf-8"))
    label_of = {i: n for n in ("scorer_wrong", "scorer_correct", "ambiguous") for i in lab[n]}
    res = json.loads((AUDIT / "crosscheck_results.json").read_text(encoding="utf-8"))

    truth: dict[int, bool] = {}  # True＝答案確實支持該命題
    for i, x in sample.items():
        scorer_supported = x["scorer"] == "supported"
        if label_of[i] == "scorer_wrong":
            truth[i] = not scorer_supported
        elif label_of[i] == "scorer_correct":
            truth[i] = scorer_supported
    print(f"標註真值可用案例：{len(truth)}／{len(sample)}（ambiguous {len(sample) - len(truth)} 個不計）")
    print(f"標註者判『答案支持』{sum(truth.values())}、『不支持』{len(truth) - sum(truth.values())}")

    votes: dict[int, dict[str, bool | None]] = {i: {} for i in sample}
    for model, d in res.items():
        valid = {int(k): v.get("supported") for k, v in d.items() if isinstance(v.get("supported"), bool)}
        if len(d) < len(sample):
            print(f"\n{model}: 只完成 {len(d)}/{len(sample)}，略過")
            continue
        n_none = len(d) - len(valid)
        agree = [i for i in truth if i in valid and valid[i] == truth[i]]
        used = [i for i in truth if i in valid]
        p = sum(1 for i in used if valid[i] and truth[i])
        fp = sum(1 for i in used if valid[i] and not truth[i])
        fn = sum(1 for i in used if not valid[i] and truth[i])
        tn = sum(1 for i in used if not valid[i] and not truth[i])
        print(f"\n{model}: 有效判斷 {len(valid)}（無法解析 {n_none}）；與標註真值一致 {len(agree)}/{len(used)} = {len(agree) / max(len(used), 1):.1%}")
        print(f"   混淆（相對標註真值）：TP={p} FP={fp} FN={fn} TN={tn}")
        for i, v in valid.items():
            votes[i][model] = v

    models = [m for m in res if all(votes[i].get(m) is not None for i in truth if m in votes[i]) or True]
    full = [m for m in res if len(res[m]) >= len(sample)]
    if len(full) >= 2:
        both = [i for i in sample if all(isinstance(votes[i].get(m), bool) for m in full)]
        same = sum(1 for i in both if len({votes[i][m] for m in full}) == 1)
        print(f"\n模型間一致：{same}/{len(both)} = {same / max(len(both), 1):.1%}")
    contested = []
    for i in truth:
        vs = [votes[i][m] for m in full if isinstance(votes[i].get(m), bool)]
        if len(vs) == len(full) and full and all(v != truth[i] for v in vs):
            contested.append(i)
    print(f"\n所有有效模型都與標註者不同意的案例（建議人工複核）：{len(contested)}")
    for i in contested:
        x = sample[i]
        print(f"  #{i} {x['question_id']} [{x['arm']}] 評分器={x['scorer']}；標註真值={'支持' if truth[i] else '不支持'}；模型={[votes[i][m] for m in full]}")
        print(f"      GOLD: {x['gold_span'][:70]}")
        print(f"      ANS : {x['window'][:110]}")
    (AUDIT / "contested_for_human_review.json").write_text(
        json.dumps([{**sample[i], "claude_truth_supported": truth[i], "model_votes": {m: votes[i].get(m) for m in full}}
                    for i in contested], ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
