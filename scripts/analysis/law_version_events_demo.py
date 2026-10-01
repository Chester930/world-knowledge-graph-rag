"""P2：以小型真實條文版本材料示範版本→狀態機事件（報告235）。

本腳本只讀本專案 ``tests/fixtures``，不讀 collector、不連 Neo4j、不啟動服務。
原型本身在 ``services.law_version_events``，純運算且零接線。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.law_version_events import build_version_event_prototype

DEFAULT_FIXTURE = _REPO / "tests" / "fixtures" / "law_version_real_sample.json"
DEFAULT_OUT_JSON = _REPO / "data" / "analysis" / "law_version_events_demo_20261001.json"
DEFAULT_OUT_REPORT = _REPO / "docs" / "報告" / "237_P2條文版本轉狀態機事件原型與真實案例示範.md"


def build_demo(fixture_path: Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = build_version_event_prototype(payload["records"])
    return {
        "disclaimer": "這是條文層原型示範，不是 KG#4 寫入，也不是 Fact 層舊版資料驗證。",
        "fixture": {
            "path": str(fixture_path),
            "source_file": payload["source_file"],
            "source_sha256": payload["source_sha256"],
            "source_record_count": payload["source_record_count"],
            "fixture_record_count": len(payload["records"]),
            "scope": payload["fixture_scope"],
        },
        "prototype": result,
    }


def _chain(result: dict[str, Any], pcode: str, article_no: str) -> dict[str, Any]:
    return next(chain for chain in result["prototype"]["chains"] if chain["pcode"] == pcode and chain["article_no"] == article_no)


def render_report(demo: dict[str, Any]) -> str:
    counts = demo["prototype"]["counts"]
    lines = [
        "# 報告237：P2 條文版本→狀態機事件純運算原型與真實案例示範", "",
        "> 本報告只讀本專案 `tests/fixtures/law_version_real_sample.json`；未連 collector、Neo4j、Ollama、LLM 或外網。",
        "> 事件／狀態仍是 PROVISIONAL 原型，不是 schema，也未接進任何現有執行路徑。", "",
        "## 1. 材料與原型規則", "",
        f"來源檔：`{demo['fixture']['source_file']}`；來源 SHA-256：`{demo['fixture']['source_sha256']}`；來源筆數 {demo['fixture']['source_record_count']}；fixture 筆數 {demo['fixture']['fixture_record_count']}。",
        "以 `(pcode, article_no)` 排序成版本鏈。每個官方版本產生 `抽取完成`→`驗證通過`；非最新版本追加 `新版取代`，effective_date 使用後繼版本的 `valid_from`，差異分類重用 P1 的純函式。",
        "每個版本以獨立的條文版本關係實例輸入 `relation_lifecycle.replay`；同鍵的互斥檢查使用 `check_exclusivity`。異常只回報，不靜默修正。", "",
        "## 2. 執行結果", "",
        f"版本鏈 {counts['chains']} 條、版本 {counts['versions']} 個、事件 {counts['events']} 個；含異常鏈 {counts['chains_with_anomalies']} 條；互斥違規 {counts['exclusivity_violation_count']} 組。",
        "本批三個勞工請假規則修法案例的日期均為舊版 valid_to 後隔 1 天以上（2025-12-07→2025-12-09），原型如實標為日期不銜接；這不阻止事件重播。", "",
        "## 3. 真實案例示範", "",
        "| pcode／條號 | 版本鏈 | 舊版最終狀態 | 新版最終狀態 | 新版取代事件 |", "| --- | --- | --- | --- | --- |",
    ]
    for pcode, article in (("N0030006", "7"), ("N0030006", "9"), ("N0030006", "12"), ("N0030001", "2"), ("N0030001", "3"), ("N0030001", "8")):
        chain = _chain(demo, pcode, article)
        old, new = chain["versions"][0], chain["versions"][-1]
        replacement = old["events"][-1]
        lines.append(f"| {pcode}／第{article}條 | {old['version_date']}→{new['version_date']} | {old['final_state']} | {new['final_state']} | {replacement['effective_date']}；{replacement['reason']} |")
    lines += [
        "", "可讀說明（N0030006 第7條舊版）：", "", "```", _chain(demo, "N0030006", "7")["versions"][0]["explain"], "```", "",
        "## 4. 異常與限制", "",
        "- 這只驗證條文層的版本取代；KG 目前只有現行條文抽出的 Fact，沒有舊版 Fact，因此不能用這批資料驗證 Fact 層的取代。",
        "- 材料只有兩部法規；勞動基準法在 collector history 目前只看到原版／現行版，中間歷次修正是否缺漏不能由此判定。",
        "- 差異分類是 hash、NFKC／去空白／去導覽標記的字面規則，不是語意判定；P1 的人工抽樣也只是樣本。",
        "- N0030006 第12條 fixture 為必要正文與導覽標記片段，不代表完整網頁尾巴。",
        "- 未涵蓋 CORRECTION、更正事件、矛盾自動偵測、修法生效自動判定或時間軸互斥。",
        "- 本示範沒有寫入 KG#4、沒有新增儲存欄位、沒有改抽取／檢索／prompt。", "",
        "## 5. 狀態", "",
        "P2 純運算原型與真實材料示範完成，等待規劃對話獨立驗證；不宣稱本報告已由規劃對話驗證。", "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-report", type=Path, default=DEFAULT_OUT_REPORT)
    args = parser.parse_args(argv)
    demo = build_demo(args.fixture)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(demo, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_report.write_text(render_report(demo), encoding="utf-8")
    print(json.dumps(demo["prototype"]["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
