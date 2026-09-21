"""報告62 §14.6：用不同模型家族盲審交叉比對稽核標註（唯讀，只呼叫本機 Ollama）。

盲審：模型只看到『題目、gold 命題、完整答案』，看不到評分器判定或標註者的意見。
輸出每個案例各模型的 supported 判斷，並與標註者（Claude）由標註推得的「真值」比較：

  標註真值：scorer_wrong → 與評分器判定相反；scorer_correct → 與評分器判定相同；ambiguous → 不計。

只用來提高標註可信度、找出『需人工複核』的少數案例；小模型的判斷力有限，一致不代表正確。
用法：python scripts/eval/scorer_audit_crosscheck.py --model granite4.2:8b --model qwen3.5:9b
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_scorer_disagreements import BASE_STAGES, CAND_STAGES, load  # noqa: E402

AUDIT = Path(__file__).resolve().parents[2] / "data" / "eval" / "scorer_audit_20260922"
OLLAMA = "http://127.0.0.1:11434"

PROMPT = """你是嚴謹的法規問答審查員。判斷「答案」是否明確斷言了下列「標準命題」。

判斷標準：
- 答案以相同的條件、數字、條號與主體陳述了該命題，就算「支持」；允許改寫、換詞序、換標點。
- 若答案對該命題說「無法確認」「未明確記載」，或只陳述部分內容、數字或條號不同、主體或新舊法寫反，就是「不支持」。
- 只看答案是否斷言了該命題，不要判斷命題本身是否正確，也不要用你自己的知識補充。

題目：{question}

標準命題：{span}

答案：
{answer}

只輸出 JSON：{{"supported": true 或 false, "reason": "不超過30字"}}"""


def compact_answer(answer: str, limit: int = 4000) -> str:
    """去除完全重複的行（部分候選答案會重複貼上上百行相同事實）並限制長度，避免超出 context。"""
    seen, out = set(), []
    for line in answer.splitlines():
        key = line.strip()
        if key and key in seen:
            continue
        seen.add(key)
        out.append(line)
    return "\n".join(out)[:limit]


def ask(model: str, prompt: str) -> dict:
    body = {
        "model": model, "stream": False, "format": "json", "keep_alive": "2m",
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "seed": 0, "num_ctx": 8192, "num_predict": 80},
    }
    # Granite 4.2、Qwen3／3.5 預設都會先『思考』（推理寫進 message.thinking、耗盡 token 而 content 為空），
    # 一律關閉；實測 think=false 對這幾個模型都有效。
    body["think"] = False
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            text = json.loads(resp.read().decode())["message"]["content"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Ollama HTTP {e.code}: {e.read().decode()[:400]}") from e
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {"supported": None, "reason": text[:60]}
    except json.JSONDecodeError:
        return {"supported": None, "reason": text[:60]}


def unload(model: str) -> None:
    body = {"model": model, "keep_alive": 0, "messages": []}
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", required=True)
    args = ap.parse_args()

    sample = json.loads((AUDIT / "review_sample.json").read_text(encoding="utf-8"))
    lab = json.loads((AUDIT / "labels_by_claude.json").read_text(encoding="utf-8"))
    label_of = {i: n for n in ("scorer_wrong", "scorer_correct", "ambiguous") for i in lab[n]}
    records = {}
    for r in load("baseline_runs/20260920_frozen", BASE_STAGES) + load("candidate_runs", CAND_STAGES):
        records.setdefault((r["question_id"], r["_arm"], r["_stage"]), r)

    results = json.loads((AUDIT / "crosscheck_results.json").read_text(encoding="utf-8")) \
        if (AUDIT / "crosscheck_results.json").exists() else {}
    for model in args.model:
        done = results.setdefault(model, {})
        for x in sample:
            if str(x["id"]) in done:
                continue
            rec = records[(x["question_id"], x["arm"], x["stage"])]
            done[str(x["id"])] = ask(model, PROMPT.format(question=x["question"], span=x["gold_span"], answer=compact_answer(rec["answer"])))
            print(f"{model} #{x['id']:2d} -> {done[str(x['id'])].get('supported')}", flush=True)
            (AUDIT / "crosscheck_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        unload(model)
    print("saved", AUDIT / "crosscheck_results.json")


if __name__ == "__main__":
    main()
