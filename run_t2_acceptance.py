"""T2 驗收腳本：報告27 §6.2 / 報告30 §2 端到端真實問答驗收。
對象：KG#4 236903cf-055a-40a8-8923-b9d06601f3b7。
評測條件：A（新 KG 全量抽取後，use_svo=True）與 D（純 LLM 基準，use_svo=False）。
支援 checkpoint/resume，每題每輪即時寫入 JSON，中斷不重跑。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from uuid import UUID

from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.document import ChatRequest
from routers.agent import chat

DEFAULT_KG_ID = UUID("236903cf-055a-40a8-8923-b9d06601f3b7")
RESULTS_FILE = Path("t2_acceptance_results.json")

RUBRICS = [
    {
        "num": 1,
        "tag": "N0060029 高架作業§4｜列舉分段完整性",
        "doc": "N0060029",
        "question": "依高架作業勞工保護措施標準，勞工從事高架作業每連續作業二小時應給予休息，休息時間如何依作業高度分三段規定？",
        "expected": "2–5m→20分、5–20m→25分、20m以上→35分",
        "checker": lambda ans: (
            bool(re.search(r"(20|二十)\s*分", ans)) and
            bool(re.search(r"(25|二十五)\s*分", ans)) and
            bool(re.search(r"(35|三十五)\s*分", ans))
        ),
        "check_desc": "必須同時包含 20分/二十、25分/二十五、35分/三十五 三段休息規定",
    },
    {
        "num": 2,
        "tag": "N0060016 重體力勞動§2｜13款列舉精準命中",
        "doc": "N0060016",
        "question": "依重體力勞動作業勞工保護措施標準，以人力搬運或揹負重量在多少公斤以上的物體，屬於重體力勞動作業？另外，以多少公斤以上的鎚及動力手工具從事敲擊等作業，也屬於重體力勞動作業？",
        "expected": "四十公斤、四點五公斤",
        "checker": lambda ans: (
            bool(re.search(r"(四十|40)\s*公斤", ans)) and
            bool(re.search(r"(四點五|4\.5)\s*公斤", ans))
        ),
        "check_desc": "必須同時包含 四十公斤(40公斤) 與 四點五公斤(4.5公斤)",
    },
    {
        "num": 3,
        "tag": "N0080013 §2/§3/§4｜多個三個月/三十日不混淆",
        "doc": "N0080013",
        "question": "事業單位大量解僱勞工後優先僱用原被解僱勞工，要連續僱用滿多久才能申請僱用獎勵金？獎勵金最多發給幾個月？事業單位應在開始僱用之日起幾日內、以及連續僱用滿三個月之日起幾日內，分別完成報備與申請？",
        "expected": "連續三個月、發給三個月為限、三十日內報備、三十日內申請",
        "checker": lambda ans: (
            bool(re.search(r"(三|3)\s*個\s*月", ans)) and
            bool(re.search(r"(三十|30)\s*日", ans))
        ),
        "check_desc": "必須包含 三個月 與 三十日",
    },
    {
        "num": 4,
        "tag": "N0080013 §3｜數值密集+單位保真+台/臺",
        "doc": "N0080013",
        "question": "依事業單位優先僱用經其大量解僱失業勞工獎勵辦法，受僱勞工每週工作時數達多少小時以上，事業單位每人每月可領多少僱用獎勵金？",
        "expected": "三十二小時、新台幣五千元",
        "checker": lambda ans: (
            bool(re.search(r"(三十二|32)\s*小時", ans)) and
            bool(re.search(r"(五千|5000|5,000)\s*元", ans))
        ),
        "check_desc": "必須同時包含 三十二小時(32小時) 與 五千元(5000元)",
    },
    {
        "num": 5,
        "tag": "N0050030 §2/§3｜跨文件不混淆",
        "doc": "N0050030",
        "question": "災區受災勞工，符合規定者在災後多久的期間內，個人應負擔的保險費由中央政府支應？這個期間從哪一天開始起算？",
        "expected": "災後六個月、自災害發生當月一日起算",
        "checker": lambda ans: (
            bool(re.search(r"(六|6)\s*個\s*月", ans)) and
            bool(re.search(r"(當月\s*一\s*日|當月\s*1\s*日|災害發生\w*當月)", ans))
        ),
        "check_desc": "必須包含 六個月 與 當月一日起算",
    },
    {
        "num": 6,
        "tag": "N0050011 §3｜週邊/低連通度節點可及性",
        "doc": "N0050011",
        "question": "申請繼續加保者原則上應於離職退保當日辦理繼續加保手續；如果原投保單位沒有在當日辦理，被保險人最遲應在什麼時候之前辦理繼續加保手續？",
        "expected": "離職退保當日起二年內",
        "checker": lambda ans: bool(re.search(r"(二|兩|2)\s*年\s*內?", ans)),
        "check_desc": "必須包含 二年內(兩年內)",
    },
    {
        "num": 7,
        "tag": "N0060007 高溫作業｜誠實拒答 vs 幻覺",
        "doc": "N0060007",
        "question": "依高溫作業勞工作息時間標準，雇主應每幾年為高溫作業勞工安排一次特殊健康檢查？",
        "expected": "未明確記載 / 未作規定 / 查無",
        "checker": lambda ans: any(
            kw in ans for kw in ["未明確", "未規定", "沒有規定", "查無", "無法確認", "未記載", "未作規定", "並未規定", "無相關規定"]
        ),
        "check_desc": "必須展現誠實拒答（包含 未明確 / 未規定 / 沒有規定 / 查無 / 無法確認 等）",
    },
    {
        "num": 8,
        "tag": "N0060004 §3+變量係數表｜組合/多跳推理",
        "doc": "N0060004",
        "question": "依勞工作業場所容許暴露標準，某有害物的八小時日時量平均容許濃度為 5 ppm，計算其短時間時量平均容許濃度時，應乘以的變量係數是多少？",
        "expected": "變量係數為 2",
        "checker": lambda ans: bool(
            re.search(r"係數[為是\s]*(2|二)", ans) or
            re.search(r"乘以\s*(2|二)", ans) or
            re.search(r"變量係數\s*(2|二)", ans)
        ),
        "check_desc": "必須命中 變量係數為 2 (係數 2 / 乘以 2)",
    },
]


def load_results() -> dict:
    if RESULTS_FILE.exists():
        try:
            return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_results(data: dict) -> None:
    RESULTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_single_chat(question: str, *, use_svo: bool, kg_id: UUID) -> dict:
    req = ChatRequest(question=question, use_svo=use_svo, kg_id=kg_id)
    t0 = time.monotonic()
    resp = await chat(req)
    
    answer = ""
    regenerated = None
    ev = None
    n_facts = 0
    n_triples = 0
    grounding_list = []

    async for chunk in resp.body_iterator:
        text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
        for line in text.split("\n"):
            if line == "":
                ev = None
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
                continue
            if line.startswith("data:"):
                raw = line[5:].strip()
                if not raw:
                    continue
                try:
                    d = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                
                if ev == "sources":
                    n_facts = len(d.get("facts", []))
                    n_triples = len(d.get("triples", []))
                elif ev == "grounding":
                    if isinstance(d, list):
                        grounding_list = d
                elif ev == "status" and isinstance(d, dict) and d.get("phase") == "done":
                    regenerated = d.get("regenerated")
                elif ev is None and "token" in d:
                    answer = d["token"]

    elapsed = round(time.monotonic() - t0, 2)
    
    # 計算 grounding 支持度
    claims = [c for c in grounding_list if c.get("is_claim")]
    supported_claims = [c for c in claims if c.get("supported")]
    grounding_ratio = round(len(supported_claims) / len(claims), 3) if claims else None

    return {
        "answer": answer,
        "elapsed": elapsed,
        "n_facts": n_facts,
        "n_triples": n_triples,
        "regenerated": regenerated,
        "grounding_claims_count": len(claims),
        "grounding_supported_count": len(supported_claims),
        "grounding_ratio": grounding_ratio,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="T2 驗收測試腳本")
    parser.add_argument("--kg-id", type=str, default=str(DEFAULT_KG_ID), help="目標 KG ID")
    parser.add_argument("--runs", type=int, default=3, help="每題測試次數 (預設 3)")
    parser.add_argument("--conditions", type=str, default="A,D", help="評測條件，以逗號分隔 (A: 新KG, D: 純LLM)")
    parser.add_argument("--questions", type=str, default="1,2,3,4,5,6,7,8", help="題號，以逗號分隔")
    args = parser.parse_args()

    kg_id = UUID(args.kg_id)
    n_runs = args.runs
    conditions = [c.strip().upper() for c in args.conditions.split(",") if c.strip()]
    question_nums = [int(q.strip()) for q in args.questions.split(",") if q.strip()]

    print(f"=== T2 驗收測試啟動 ===")
    print(f"KG ID: {kg_id}")
    print(f"條件: {conditions}")
    print(f"每題跑次: {n_runs}")
    print(f"題號: {question_nums}")
    print("=" * 60)

    await connect()
    init_providers()
    get_driver()

    all_data = load_results()
    kg_key = str(kg_id)
    if kg_key not in all_data:
        all_data[kg_key] = {}

    try:
        for q_item in RUBRICS:
            q_num = q_item["num"]
            if q_num not in question_nums:
                continue

            q_key = str(q_num)
            if q_key not in all_data[kg_key]:
                all_data[kg_key][q_key] = {
                    "tag": q_item["tag"],
                    "question": q_item["question"],
                    "expected": q_item["expected"],
                    "check_desc": q_item["check_desc"],
                    "results": {}
                }

            print(f"\n{'='*75}\n[題 {q_num}] {q_item['tag']}\nQ: {q_item['question']}\n{'='*75}", flush=True)

            for cond in conditions:
                use_svo = (cond == "A")
                cond_label = f"[{cond}] {'新KG' if use_svo else '純LLM'}"
                
                if cond not in all_data[kg_key][q_key]["results"]:
                    all_data[kg_key][q_key]["results"][cond] = []
                
                runs_list = all_data[kg_key][q_key]["results"][cond]
                already_done = len(runs_list)

                for run_idx in range(already_done + 1, n_runs + 1):
                    print(f"\n--- {cond_label} - 執行第 {run_idx}/{n_runs} 次 ---", flush=True)
                    call_res = await run_single_chat(q_item["question"], use_svo=use_svo, kg_id=kg_id)
                    ans = call_res["answer"]
                    is_pass = bool(q_item["checker"](ans))
                    call_res["pass"] = is_pass
                    call_res["run_idx"] = run_idx
                    call_res["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")

                    runs_list.append(call_res)
                    save_results(all_data)

                    pass_icon = "✅ PASS" if is_pass else "❌ FAIL"
                    print(f"結果: {pass_icon} | 耗時: {call_res['elapsed']}s | Triples: {call_res['n_triples']} | "
                          f"Facts: {call_res['n_facts']} | Regen: {call_res['regenerated']} | "
                          f"Grounding: {call_res['grounding_ratio']}", flush=True)
                    print(f"答案摘錄: {ans[:150]}...", flush=True)
                    if not is_pass:
                        print(f"未通過原因: 未完全符合 [{q_item['check_desc']}]", flush=True)

    finally:
        await disconnect()

    # 輸出最終總結報告
    print("\n\n" + "=" * 80)
    print("=== T2 驗收測試總結彙整表 ===")
    print("=" * 80)
    header = f"{'題號':<4} | {'面向/標籤':<28} | {'條件A (新KG)':<18} | {'條件D (純LLM)':<18}"
    print(header)
    print("-" * 80)

    for q_item in RUBRICS:
        q_num = q_item["num"]
        if q_num not in question_nums:
            continue
        q_key = str(q_num)
        q_data = all_data.get(kg_key, {}).get(q_key, {}).get("results", {})
        
        a_runs = q_data.get("A", [])
        d_runs = q_data.get("D", [])

        a_passes = sum(1 for r in a_runs if r.get("pass"))
        a_avg_time = round(sum(r.get("elapsed", 0) for r in a_runs) / len(a_runs), 1) if a_runs else 0
        a_summary = f"{a_passes}/{len(a_runs)} 乾淨 ({a_avg_time}s)" if a_runs else "N/A"

        d_passes = sum(1 for r in d_runs if r.get("pass"))
        d_avg_time = round(sum(r.get("elapsed", 0) for r in d_runs) / len(d_runs), 1) if d_runs else 0
        d_summary = f"{d_passes}/{len(d_runs)} 乾淨 ({d_avg_time}s)" if d_runs else "N/A"

        tag_short = q_item['tag'][:26]
        print(f"Q{q_num:<3} | {tag_short:<28} | {a_summary:<18} | {d_summary:<18}")

    print("=" * 80)
    print(f"詳細紀錄已保存至: {RESULTS_FILE.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
