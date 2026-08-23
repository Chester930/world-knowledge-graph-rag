"""從 labor-compliance-collector 的「請假與排班法規庫（精簡標準化版）」資料集篩出真正與
請假／排班相關的候選記錄，供之後匯入 KG 前使用（2026-08-23，示範用知識圖譜資料準備）。

**外部資料來源**（固定路徑，另一個獨立工具的輸出，本專案不擁有、不寫回）：
`D:\\Users\\666\\Desktop\\labor-compliance-collector\\projects\\20260821_請假與排班法規庫_精簡標準化版\\20260821_leave_and_scheduling_normalized.jsonl`

**為什麼需要這支腳本**：這批資料集雖然名為「請假與排班法規庫」，但實測 11,865 筆記錄裡標題
含請假／排班相關字樣的只有 20 筆——內容抽查後確認，這批資料實質上是幾乎完整的現行法規資料庫
（含大量與請假排班無關的法規，如建築物室內裝修管理辦法、電力調度轉供費用優惠辦法等），並非
真正篩過的子集。與 `import_labor_compliance_dataset.py` 匯入的舊資料集（`20260818_請假_排班_
法規測試`）不同，這批資料**沒有**附帶 `06_agent_summary/phase0_pruning_dry_run.json` 這類
collector 自己算好的保留／剔除判斷，因此需要在這一側自行補上篩選邏輯，而非重造一個判斷依據。

**篩選邏輯（依序套用）**：
1. 排除 `payload.category` 以「廢止法規」開頭的記錄（已廢止，非現行法規）。
2. 標題＋全文以關鍵字集合（請假／休假／排班／輪班／工時…等 28 詞）比對，找出所有出現位置。
3. 排除已知「同字不同義」子字串碰撞（如「請假**釋**」≠請假、「竣**工時**」「勞**工時**」≠工時）
   ——這三個碰撞案例是實測抽樣審查時發現的真實誤判，非假設性防禦。
4. 排除「僅命中機關辦事細則制式代理條款」的記錄（如「因故不能執行職務或請假時，應指定人員
   代理」——這句話出現在數十個不相關機關的辦事細則裡，是組織內規樣板文字，不是實質請假規範）。
5. 排除「只有單一關鍵字且只出現一次」的低確信度記錄（多半是附帶提及，如日期換算、計費單位裡
   偶然出現「工時」「例假」等字——非規則本身在規範請假／排班行為）。保留門檻：≥2 種不同關鍵字，
   或同一關鍵字出現 ≥2 次。**例外**：`payload.category` 含「勞動部」或「勞工」的記錄不套用此
   門檻——實測發現這條規則會誤刪 20 筆貨真價實的勞動部法規（如「職業安全衛生法施行細則」只命中
   一次「輪班」、「團體協約法」只命中一次「工時」），因為勞動部發布的規範本身高機率就是實質相關，
   單次提及不代表附帶，跟「跨部會、非勞動類別」文件裡的單次提及風險不同。

**驗證方式**：規則式篩選無法窮盡所有語意碰撞，每一輪都靠隨機抽樣 30 筆人工審查校準（過程記錄
於 `docs/論文/` 相關設計討論，非本檔案職責）。最終結果：11,865 → 排除 3,522 筆已廢止 → 排除
345 筆低確信度 → 排除 36 筆純樣板條款 → 保留 **449 筆**。抽樣顯示保留集合裡約 85-90% 為實質
相關規範，殘留噪音是規則式方法的合理上限，非本次範圍要追求完美精確度。

**與後續工作的關係**：本腳本只做篩選、不寫入 Neo4j、不建立 KG——是 §3.5「文件／法條層級的
時序錨定」節點設計定案前的資料準備步驟。要接上既有的 `import_labor_compliance_dataset.py`
匯入管線，需等 Document/LawArticle 節點設計拍板後再做（因為這批資料的 schema 含 `scope_temporal`
／`scope_spatial`／`scope_industry`／`payload.effective_date`／`effective_note` 等尚未有對應
匯入邏輯的欄位，直接套用舊匯入腳本只會跟舊資料集一樣，只取 `text` 而遺失這些結構化資訊）。

用法：
    python filter_leave_scheduling_dataset.py
        列出篩選統計與抽樣結果，不寫檔。

    python filter_leave_scheduling_dataset.py --out workspace/leave_scheduling_filter_decisions.json
        額外把每筆記錄的篩選結果（identity_key、決策、命中關鍵字）寫成 JSON，供後續腳本讀取。
        預設輸出目錄 `workspace/` 已在 .gitignore 中，不會被提交。

    python filter_leave_scheduling_dataset.py --sample 50
        抽樣審查用，調整抽樣筆數（預設 30）。
"""
from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

DEFAULT_DATASET_PATH = Path(
    r"D:\Users\666\Desktop\labor-compliance-collector\projects"
    r"\20260821_請假與排班法規庫_精簡標準化版\20260821_leave_and_scheduling_normalized.jsonl"
)

KEYWORDS = [
    "請假", "休假", "排班", "輪班", "工時", "特別休假", "出勤", "加班", "值班",
    "例假", "產假", "病假", "事假", "公假", "喪假", "育嬰留職停薪", "留職停薪",
    "工作時間", "延長工時", "夜間工作", "責任制", "變形工時", "班表", "排休",
    "輪值", "值勤", "彈性工時", "差勤", "休息日",
]

# 關鍵字 -> 已知的「同字不同義」子字串碰撞正規表示式（實測抽樣審查時發現，非假設性防禦）。
FALSE_FRIEND_PATTERNS = {
    "請假": re.compile(r"請假釋"),
    "工時": re.compile(r"竣工時|勞工時"),
}

# 機關辦事細則常見的制式「因故不能執行職務或請假時，應指定人員代理」條款——組織內規樣板，
# 非實質請假規範。
BOILERPLATE_RE = re.compile(r"因故不能執行職務或請假時.{0,15}應(依規定)?指定(或委(請|託))?適當?人員代理")

MIN_DISTINCT_KEYWORDS = 2
MIN_SAME_KEYWORD_REPEATS = 2


def _find_hits(title: str, text: str) -> list[tuple[str, str, int]]:
    """回傳所有存活過同字不同義碰撞檢查的命中：(關鍵字, 欄位, 起始位置)。"""
    hits: list[tuple[str, str, int]] = []
    haystacks = [("title", title)] if title else []
    haystacks.append(("text", text))
    for kw in KEYWORDS:
        false_friend = FALSE_FRIEND_PATTERNS.get(kw)
        for field, s in haystacks:
            for m in re.finditer(re.escape(kw), s):
                if false_friend:
                    window = s[max(0, m.start() - 3): m.end() + 3]
                    if false_friend.search(window):
                        continue
                hits.append((kw, field, m.start()))
    return hits


def classify_record(rec: dict) -> tuple[str, list[tuple[str, str, int]]]:
    """判斷單筆正規化記錄的篩選結果。回傳 (決策, 命中清單)。

    決策值：`kept` / `no_match` / `excluded_abandoned` / `excluded_boilerplate_only`
    / `excluded_low_confidence`。詳細規則見模組 docstring「篩選邏輯」。
    """
    title = rec.get("title", "") or ""
    text = rec.get("text", "") or ""
    category = rec.get("payload", {}).get("category", "") or ""

    if category.startswith("廢止法規"):
        return "excluded_abandoned", []

    hits = _find_hits(title, text)
    if not hits:
        return "no_match", []

    non_boilerplate = []
    for kw, field, pos in hits:
        if field == "title":
            non_boilerplate.append((kw, field, pos))
            continue
        window = text[max(0, pos - 30): pos + 40]
        if BOILERPLATE_RE.search(window):
            continue
        non_boilerplate.append((kw, field, pos))

    if not non_boilerplate:
        return "excluded_boilerplate_only", hits

    kw_counts = Counter(h[0] for h in non_boilerplate)
    is_labor_ministry = "勞動部" in category or "勞工" in category
    if (
        not is_labor_ministry
        and len(kw_counts) < MIN_DISTINCT_KEYWORDS
        and max(kw_counts.values()) < MIN_SAME_KEYWORD_REPEATS
    ):
        return "excluded_low_confidence", non_boilerplate

    return "kept", non_boilerplate


def _iter_records(dataset_path: Path) -> Iterable[dict]:
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH, help="正規化 JSONL 資料集路徑")
    parser.add_argument("--out", type=Path, default=None, help="把篩選決策寫成 JSON 的輸出路徑（選填）")
    parser.add_argument("--sample", type=int, default=30, help="抽樣審查筆數（預設 30）")
    args = parser.parse_args()

    if not args.dataset.is_file():
        raise SystemExit(f"找不到資料集檔案：{args.dataset}")

    counts: Counter[str] = Counter()
    decisions: list[dict] = []
    kept_records: list[tuple[str, str, list[tuple[str, str, int]]]] = []

    for rec in _iter_records(args.dataset):
        status, hits = classify_record(rec)
        counts[status] += 1
        identity_key = rec.get("identity_key")
        title = rec.get("title")
        matched_keywords = sorted({h[0] for h in hits})
        decisions.append({
            "identity_key": identity_key,
            "title": title,
            "decision": status,
            "matched_keywords": matched_keywords,
        })
        if status == "kept":
            kept_records.append((title, identity_key, hits))

    total = sum(counts.values())
    print(f"資料集：{args.dataset}")
    print(f"總筆數：{total}")
    for status, count in counts.most_common():
        print(f"  {status}: {count}")

    if kept_records:
        random.seed(7)
        sample = random.sample(kept_records, min(args.sample, len(kept_records)))
        print(f"\n--- 保留記錄抽樣（{len(sample)} 筆）---")
        for title, ident, hits in sample:
            kw_list = sorted({h[0] for h in hits})
            print(f"- [{','.join(kw_list)}] {title} ({ident})")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已寫入篩選決策：{args.out}（共 {len(decisions)} 筆）")


if __name__ == "__main__":
    main()
