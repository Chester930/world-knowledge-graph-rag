"""報告231 S2：關係狀態機「玩具圖譜」示範（**全部為虛構資料，不代表任何真實法規或 KG#4**）。

只用本檔內寫死的虛構關係與事件；不連 Neo4j、不讀任何真實資料檔、不啟動 Ollama／LLM。
輸出：中文示範報告（Markdown）＋JSON。狀態與事件為 PROVISIONAL 提案（`services/relation_lifecycle.py`）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services import relation_lifecycle as rl  # noqa: E402
from services.relation_lifecycle import LifecycleEvent as Ev  # noqa: E402

DISCLAIMER = "**本檔全部為虛構玩具資料，用來示範狀態機規則本身；不代表任何真實法規，也與 KG#4 或任何真實資料無關。**"
OUT_JSON = _REPO / "data" / "analysis" / "relation_lifecycle_demo_20261001.json"
OUT_MD = _REPO / "docs" / "報告" / "231_關係狀態機玩具圖譜示範輸出.md"

# 虛構擴充：關係型別「虛構-暫停適用」多一個「暫停」狀態（暫停≠終止，借 Round 3 AC-009 的觀念）
PAUSE_SPEC = rl.LifecycleSpec(
    relation_type="虛構-暫停適用",
    extra_states=frozenset({"暫停"}),
    extra_events=frozenset({"暫停適用", "恢復適用"}),
    extra_transitions={(rl.VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): rl.VALID, ("暫停", rl.TERMINATE): rl.TERMINATED},
)
# 虛構的破壞性擴充（示範被拒）：想讓「已被取代」可以轉出、並想改寫核心轉換
BAD_SPECS = {
    "終點狀態加轉出": rl.LifecycleSpec(
        relation_type="虛構-壞擴充A", extra_events=frozenset({"復活"}), extra_transitions={(rl.SUPERSEDED, "復活"): rl.VALID}),
    "改道核心轉換": rl.LifecycleSpec(
        relation_type="虛構-壞擴充B", extra_transitions={(rl.VALID, rl.TERMINATE): rl.REJECTED}),
    "刪除核心轉換": rl.LifecycleSpec(
        relation_type="虛構-壞擴充C", removed_core_transitions=frozenset({(rl.VALID, rl.TERMINATE)})),
}

# 每個情境：(編號, 標題, 說明, [(實例識別字, 鍵〔主詞,關係型別,受詞〕, 關係型別, 事件清單)])
# 事件寫法：(事件, 日期或 None[, 備註])
SCENARIOS: list[dict[str, Any]] = [
    {"no": 1, "title": "正常生命週期", "note": "候選 → 有效",
     "instances": [("S1-a", ("甲公司", "應給", "乙福利"), None,
                    [(rl.EXTRACTED, "2020-01-01"), (rl.VERIFIED, "2020-02-01", "人工確認")])]},
    {"no": 2, "title": "修法取代，新版自己走候選→有效", "note": "舊版有效 → 已被取代；新版是另一個實例（同鍵），自己走候選→有效；互斥檢查通過",
     "instances": [
         ("S2-v1", ("丙公司", "應給", "丁津貼"), None,
          [(rl.EXTRACTED, "2018-01-01"), (rl.VERIFIED, "2018-02-01"), (rl.REPLACED, "2022-07-01", "第二版生效")]),
         ("S2-v2", ("丙公司", "應給", "丁津貼"), None,
          [(rl.EXTRACTED, "2022-06-01"), (rl.VERIFIED, "2022-07-01")])]},
    {"no": 3, "title": "終止後重新生效（結束後重新開始）", "note": "同一個實例走過兩段有效期；舊的「同鍵併成一條」做法無法表示這件事",
     "instances": [("S3-a", ("戊機構", "適用", "己計畫"), None,
                    [(rl.EXTRACTED, "2015-01-01"), (rl.VERIFIED, "2015-02-01"), (rl.TERMINATE, "2019-01-01", "計畫停止適用"),
                     (rl.REACTIVATE, "2023-01-01", "計畫恢復")])]},
    {"no": 4, "title": "爭議：裁決保留本條", "note": "有效 → 爭議 → 有效",
     "instances": [("S4-a", ("庚部門", "規定", "辛上限"), None,
                    [(rl.EXTRACTED, None), (rl.VERIFIED, None), (rl.CONTRADICTION, None, "與另一來源矛盾"),
                     (rl.RULED_KEEP, None, "確認本條正確")])]},
    {"no": 5, "title": "爭議：裁決以他條為準", "note": "有效 → 爭議 → 已被取代",
     "instances": [("S5-a", ("壬部門", "規定", "癸期限"), None,
                    [(rl.EXTRACTED, None), (rl.VERIFIED, None), (rl.CONTRADICTION, None), (rl.RULED_OTHER, None, "以另一條為準")])]},
    {"no": 6, "title": "候選被駁回", "note": "候選 → 已駁回（終點）",
     "instances": [("S6-a", ("子單位", "允許", "丑行為"), None, [(rl.EXTRACTED, None), (rl.VERIFY_FAILED, None, "來源查無此規定")])]},
    {"no": 7, "title": "非法轉換被拒", "note": "已被取代→有效、已駁回→有效、尚未建立就驗證，皆被拒；狀態維持，重播繼續",
     "instances": [
         ("S7-a", ("寅單位", "需要", "卯文件"), None,
          [(rl.EXTRACTED, None), (rl.VERIFIED, None), (rl.REPLACED, None), (rl.REACTIVATE, None, "企圖讓已被取代者復活"), (rl.VERIFIED, None)]),
         ("S7-b", ("辰單位", "需要", "巳文件"), None, [(rl.EXTRACTED, None), (rl.VERIFY_FAILED, None), (rl.VERIFIED, None, "企圖讓已駁回者通過")]),
         ("S7-c", ("午單位", "需要", "未文件"), None, [(rl.VERIFIED, None, "尚未建立就驗證")])]},
    {"no": 8, "title": "互斥違規被偵測", "note": "同一鍵同時兩個「有效」實例",
     "instances": [
         ("S8-a", ("申公司", "應給", "酉獎金"), None, [(rl.EXTRACTED, None), (rl.VERIFIED, None)]),
         ("S8-b", ("申公司", "應給", "酉獎金"), None, [(rl.EXTRACTED, None), (rl.VERIFIED, None)])]},
    {"no": 9, "title": "無日期與有日期事件並存", "note": "同一事件序列，有日期與無日期版本的狀態轉換完全相同（時間不影響合法性）",
     "instances": [
         ("S9-dated", ("戌公司", "應給", "亥補貼"), None,
          [(rl.EXTRACTED, "2020-01-01"), (rl.VERIFIED, "2020-02-01"), (rl.CONTRADICTION, "2021-03-01"), (rl.RULED_KEEP, "2021-04-01")]),
         ("S9-undated", ("戌公司", "應給", "亥補貼二"), None,
          [(rl.EXTRACTED, None), (rl.VERIFIED, None), (rl.CONTRADICTION, None), (rl.RULED_KEEP, None)]),
         ("S9-mixed", ("戌公司", "應給", "亥補貼三"), None,
          [(rl.EXTRACTED, "2020-01-01"), (rl.VERIFIED, None), (rl.CONTRADICTION, "2021-03-01"), (rl.RULED_KEEP, None)])]},
    {"no": 10, "title": "擴充範例：虛構關係型別追加「暫停」狀態", "note": "暫停適用／恢復適用不是終止／重新生效；擴充不影響核心",
     "instances": [("S10-a", ("虛構子公司", "虛構-暫停適用", "虛構方案"), "虛構-暫停適用",
                    [(rl.EXTRACTED, None), (rl.VERIFIED, None), ("暫停適用", "2021-01-01"), ("恢復適用", "2021-06-01"),
                     ("暫停適用", "2022-01-01"), (rl.TERMINATE, "2022-03-01")])]},
]


def _event(spec: tuple) -> Ev:
    name, date = spec[0], spec[1]
    reason = spec[2] if len(spec) > 2 else None
    return Ev(name, effective_date=date, reason=reason)


def _lifecycles() -> dict[str, rl.Lifecycle]:
    return {PAUSE_SPEC.relation_type: rl.resolve_spec(PAUSE_SPEC)}


def run_instance(inst: tuple, lifecycles: dict[str, rl.Lifecycle]) -> dict[str, Any]:
    inst_id, key, rel_type, events = inst
    lc = rl.lifecycle_for(rel_type or key[1], lifecycles)
    evs = [_event(e) for e in events]
    result = rl.replay(evs, lifecycle=lc)
    again = [rl.replay(evs, lifecycle=lc) for _ in range(3)]
    return {
        "instance_id": inst_id, "key": list(key), "lifecycle": lc.name,
        "final_state": result.final_state, "ok": result.ok,
        "first_illegal": None if result.first_illegal is None else {
            "step": result.first_illegal[0] + 1, "event": result.first_illegal[1].event.event_type,
            "reason": result.first_illegal[1].reason},
        "steps": [{"ok": s.ok, "from": s.from_state, "event": s.event.event_type, "to": s.to_state,
                   "date": s.event.effective_date, "reason": s.reason} for s in result.steps],
        "explain": rl.explain(result), "deterministic": all(a == result for a in again),
    }


def build_demo() -> dict[str, Any]:
    lifecycles = _lifecycles()
    scenarios = []
    all_instances: list[rl.RelationInstance] = []
    for sc in SCENARIOS:
        runs = [run_instance(i, lifecycles) for i in sc["instances"]]
        insts = [rl.RelationInstance(r["instance_id"], tuple(r["key"]), r["final_state"]) for r in runs]
        all_instances += insts
        viol = rl.check_exclusivity(insts)
        scenarios.append({"no": sc["no"], "title": sc["title"], "note": sc["note"], "instances": runs,
                          "exclusivity_violations": [{"key": list(v.key), "instance_ids": list(v.instance_ids)} for v in viol]})
    s9 = next(s for s in scenarios if s["no"] == 9)
    s9_same = len({tuple((st["from"], st["to"], st["ok"]) for st in r["steps"]) for r in s9["instances"]}) == 1
    bad = {name: {"ok": (v := rl.validate_spec(spec)).ok, "errors": list(v.errors)} for name, spec in BAD_SPECS.items()}
    good = rl.validate_spec(PAUSE_SPEC)
    whole = rl.check_exclusivity(all_instances)
    return {
        "disclaimer": "全部為虛構玩具資料，不代表任何真實法規或 KG#4；狀態／事件／轉換為 PROVISIONAL 提案。",
        "scenarios": scenarios,
        "dated_vs_undated_identical_transitions": s9_same,
        "all_deterministic": all(r["deterministic"] for s in scenarios for r in s["instances"]),
        "extension": {"relation_type": PAUSE_SPEC.relation_type, "valid": good.ok, "errors": list(good.errors)},
        "bad_extensions": bad,
        "exclusivity_whole_toy_graph": [{"key": list(v.key), "instance_ids": list(v.instance_ids)} for v in whole],
        "counts": {"scenarios": len(scenarios), "instances": len(all_instances),
                   "illegal_events": sum(1 for s in scenarios for r in s["instances"] for st in r["steps"] if not st["ok"])},
    }


def render_markdown(demo: dict[str, Any]) -> str:
    c = demo["counts"]
    L = ["# 關係狀態機玩具圖譜示範輸出（報告231 S2）", "", f"> {DISCLAIMER}", "",
         "> 規則來源：報告229 §3（提案）；實作：`services/relation_lifecycle.py`（純運算、未接線）；腳本：`scripts/analysis/relation_lifecycle_demo.py`。",
         f"> 本次示範：{c['scenarios']} 個情境、{c['instances']} 條虛構關係實例、{c['illegal_events']} 個被拒的非法事件；重播決定性：{'全部通過' if demo['all_deterministic'] else '有不一致'}。", ""]
    for s in demo["scenarios"]:
        L += [f"## 情境 {s['no']}：{s['title']}", "", f"{s['note']}。", ""]
        for r in s["instances"]:
            L += [f"**實例 {r['instance_id']}**　鍵：（{'／'.join(r['key'])}）　生命週期：{r['lifecycle']}　最終狀態：**{r['final_state'] or '（尚未建立）'}**", "", "```"]
            L += r["explain"].split("\n") + ["```", ""]
        if s["no"] == 8 or s["exclusivity_violations"]:
            if s["exclusivity_violations"]:
                for v in s["exclusivity_violations"]:
                    L.append(f"⚠️ 互斥違規：鍵（{'／'.join(v['key'])}）同時有 {len(v['instance_ids'])} 個「有效」：{'、'.join(v['instance_ids'])}。\n")
        elif s["no"] == 2:
            L.append("✅ 互斥檢查：同鍵兩個實例中只有新版為「有效」，無違規。\n")
        if s["no"] == 9:
            L.append(f"✅ 有日期／無日期／混合三個實例的逐步轉換{'完全相同' if demo['dated_vs_undated_identical_transitions'] else '不同'}（時間只是事件的選用屬性）。\n")
    ext = demo["extension"]
    L += ["## 擴充檢查（Q1：通用核心＋可個別擴充）", "", f"- 虛構擴充「{ext['relation_type']}」：{'通過驗證' if ext['valid'] else '未通過：' + '；'.join(ext['errors'])}。", ""]
    for name, v in demo["bad_extensions"].items():
        L.append(f"- 破壞核心的擴充「{name}」：{'**竟然通過（異常）**' if v['ok'] else '被拒——' + '；'.join(v['errors'])}")
    L += ["", "## 全玩具圖譜互斥檢查", ""]
    if demo["exclusivity_whole_toy_graph"]:
        for v in demo["exclusivity_whole_toy_graph"]:
            L.append(f"- 違規：鍵（{'／'.join(v['key'])}）→ {'、'.join(v['instance_ids'])}（即情境 8 刻意製造的違規，其餘情境皆無）")
    else:
        L.append("- 無違規。")
    L += ["", "---", f"{DISCLAIMER}"]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-json", type=Path, default=OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=OUT_MD)
    args = ap.parse_args(argv)
    demo = build_demo()
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(render_markdown(demo), encoding="utf-8")
    print(json.dumps(demo["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
