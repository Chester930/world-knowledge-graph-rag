"""P1：法規條文版本資料的唯讀盤點（報告235）。

資料讀取與純運算分開：``load_history_files``／``load_corpus_mapping`` 只負責
讀本機檔案；``build_inventory``、版本鏈與分類函式只處理已載入的資料。
本腳本不連 Neo4j、不啟動任何服務、不呼叫外網或模型。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.law_version_events import (  # noqa: E402
    DIFF_FORMAT_ONLY,
    DIFF_LABELS,
    DIFF_SAME_HASH,
    DIFF_SUBSTANTIVE,
    classify_content_difference,
    difference_label,
    has_navigation_noise,
    normalize_content,
)

HISTORY_PATTERN = "moj_history_20260819T0*-history.json"
DEFAULT_SOURCE_DIR = Path(r"D:\Users\666\Desktop\labor-compliance-collector\data\processed\moj_laws")
DEFAULT_CORPUS_DIR = Path(r"D:\Users\666\Desktop\kg-runtime\236903cf-055a-40a8-8923-b9d06601f3b7")
DEFAULT_OUT_JSON = _REPO / "data" / "analysis" / "law_version_inventory_20261001.json"
DEFAULT_OUT_REPORT = _REPO / "docs" / "報告" / "236_P1條文版本真實資料盤點.md"
REQUIRED_FIELDS = (
    "pcode", "law_name", "article_no", "content", "version_date", "valid_from", "valid_to",
    "is_current", "valid_from_basis", "version_id", "content_hash", "retrieved_at", "source_url",
)

MANUAL_REVIEW_PLAN = (
    ("2", "實質修改", "定義用詞、條文內容與列舉範圍均大幅變更"),
    ("3", "實質修改", "適用範圍新增段落與完整規範，不是單純排版"),
    ("4", "實質修改", "中央主管機關與地方行政區內容改變"),
    ("7", "用詞或標點調整", "主要差異為「豋記」改「登記」等用字"),
    ("9", "實質修改", "新增派遣勞動契約規範與條文文字調整"),
    ("12", "用詞或標點調整", "主要為空白、措辭與標點層次的文字調整"),
    ("14", "實質修改", "法定傳染病與終止契約條件新增／改寫"),
    ("17", "實質修改", "新增資遣費給付期限"),
    ("21", "實質修改", "新增基本工資審議委員會及辦法規定"),
    ("23", "實質修改", "新增工資各項目計算方式明細要求"),
    ("24", "實質修改", "新增休息日工作工資規範"),
    ("28", "實質修改", "積欠工資墊償擴充至退休金與資遣費等債權"),
    ("30", "實質修改", "正常工時、排班與出勤紀錄制度大幅改寫"),
    ("32", "實質修改", "延長工時上限、同意程序與備查規定改寫"),
    ("34", "實質修改", "新增連續休息時數與例外程序"),
)


def _natural_key(value: object) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(value)))


def _record_sort_key(record: Mapping[str, Any]) -> tuple[object, ...]:
    return (
        str(record.get("pcode", "")),
        _natural_key(record.get("article_no", "")),
        str(record.get("valid_from") or "9999-99-99"),
        str(record.get("version_date") or "9999-99-99"),
        str(record.get("version_id", "")),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_history_files(source_dir: Path, pattern: str = HISTORY_PATTERN) -> dict[str, list[dict[str, Any]]]:
    """讀取指定目錄的 history JSON；不讀目錄外檔案。"""
    paths = sorted(source_dir.glob(pattern), key=lambda path: path.name)
    if not paths:
        raise FileNotFoundError(f"找不到 history 檔：{source_dir / pattern}")
    loaded: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValueError(f"history JSON 根節點必須是 object 陣列：{path}")
        missing = sorted({field for row in payload for field in REQUIRED_FIELDS if field not in row})
        if missing:
            raise ValueError(f"{path.name} 缺少欄位：{missing}")
        loaded[path.name] = payload
    return loaded


def _file_stats(file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for filename in sorted(file_rows):
        rows = file_rows[filename]
        result.append({
            "file": filename,
            "rows": len(rows),
            "pcode_distribution": dict(sorted(Counter(str(row["pcode"]) for row in rows).items())),
            "is_current_distribution": {
                str(key).lower(): value
                for key, value in sorted(Counter(bool(row["is_current"]) for row in rows).items(), key=lambda item: str(item[0]))
            },
            "version_date_count": len({row["version_date"] for row in rows}),
        })
    return result


def deduplicate_records(file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """以 (pcode, article_no, version_id) 去重，並保留重複／衝突資訊。"""
    groups: dict[tuple[str, str, str], list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for filename in sorted(file_rows):
        for row in file_rows[filename]:
            key = (str(row["pcode"]), str(row["article_no"]), str(row["version_id"]))
            groups[key].append((filename, row))
    # 同一 key 若在不同 snapshot 的 valid_to 等欄位不同，採檔名排序後最新
    # snapshot 作為分析代表；衝突仍完整列在 metadata，不靜默掩蓋。
    canonical = [dict(entries[-1][1]) for entries in groups.values()]
    canonical.sort(key=_record_sort_key)
    duplicate_groups = []
    conflicting_groups = []
    for key, entries in sorted(groups.items()):
        if len(entries) <= 1:
            continue
        info = {
            "key": list(key),
            "occurrences": len(entries),
            "files": [filename for filename, _row in entries],
            "canonical_file": entries[-1][0],
        }
        duplicate_groups.append(info)
        fingerprints = {(row.get("content_hash"), row.get("valid_from"), row.get("valid_to"), row.get("is_current")) for _filename, row in entries}
        if len(fingerprints) > 1:
            conflicting_groups.append(info)
    return canonical, {
        "key": "(pcode, article_no, version_id)",
        "raw_rows": sum(len(rows) for rows in file_rows.values()),
        "deduplicated_rows": len(canonical),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_row_excess": sum(item["occurrences"] - 1 for item in duplicate_groups),
        "conflicting_duplicate_group_count": len(conflicting_groups),
        "duplicate_groups": duplicate_groups,
        "conflicting_duplicate_groups": conflicting_groups,
    }


def _parse_iso(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _chain_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record["pcode"]), str(record["article_no"])


def _version_chains(records: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    chains: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        chains[_chain_key(row)].append(row)
    for chain in chains.values():
        chain.sort(key=_record_sort_key)
    return dict(sorted(chains.items()))


def _record_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pcode": row["pcode"], "article_no": row["article_no"], "version_date": row["version_date"],
        "valid_from": row["valid_from"], "valid_to": row["valid_to"], "is_current": row["is_current"],
        "version_id": row["version_id"], "content_hash": row["content_hash"],
    }


def _comparison(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    kind = classify_content_difference(left, right)
    return {
        "pcode": left["pcode"], "article_no": left["article_no"],
        "older_version_id": left["version_id"], "newer_version_id": right["version_id"],
        "older_version_date": left["version_date"], "newer_version_date": right["version_date"],
        "classification": kind, "classification_label": difference_label(kind),
    }


def build_inventory(file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """由已載入 records 建立 P1 的所有純運算結果。"""
    records, dedup = deduplicate_records(file_rows)
    chains = _version_chains(records)
    multi = {key: chain for key, chain in chains.items() if len(chain) >= 2}
    comparisons = []
    date_pairs = []
    for key, chain in multi.items():
        for left, right in zip(chain, chain[1:]):
            comparisons.append(_comparison(left, right))
            old_to = _parse_iso(left.get("valid_to"))
            new_from = _parse_iso(right.get("valid_from"))
            delta_days = None if old_to is None or new_from is None else (new_from - old_to).days
            date_pairs.append({
                "pcode": key[0], "article_no": key[1], "older_version_id": left["version_id"],
                "newer_version_id": right["version_id"], "older_valid_to": left.get("valid_to"),
                "newer_valid_from": right.get("valid_from"), "delta_days": delta_days,
                "contiguous": delta_days == 1,
            })
    current_mismatches = [
        _record_ref(row) for row in records if bool(row["is_current"]) != (row.get("valid_to") in (None, ""))
    ]
    no_current = []
    multiple_current = []
    for key, chain in multi.items():
        current_count = sum(bool(row["is_current"]) for row in chain)
        if current_count == 0:
            no_current.append({"pcode": key[0], "article_no": key[1], "version_ids": [row["version_id"] for row in chain]})
        if current_count > 1:
            multiple_current.append({"pcode": key[0], "article_no": key[1], "version_ids": [row["version_id"] for row in chain]})
    version_count_distribution = Counter(len(chain) for chain in chains.values())
    diff_counts = Counter(item["classification"] for item in comparisons)
    noise_records = [_record_ref(row) for row in records if has_navigation_noise(str(row.get("content", "")))]
    manual_review = []
    if any(item["pcode"] == "N0030001" for item in comparisons):
        comparison_by_article = {
            (item["pcode"], str(item["article_no"])): item
            for item in comparisons
            if item["pcode"] == "N0030001"
        }
        for article_no, label, note in MANUAL_REVIEW_PLAN:
            item = comparison_by_article.get(("N0030001", article_no))
            if item is None or item["classification"] != DIFF_SUBSTANTIVE:
                raise ValueError(f"人工抽樣項目不是 (c) 類：N0030001 第 {article_no} 條")
            manual_review.append({**item, "manual_label": label, "manual_note": note})
    return {
        "file_stats": _file_stats(file_rows),
        "deduplication": dedup,
        "record_count_after_dedup": len(records),
        "pcode_distribution_after_dedup": dict(sorted(Counter(str(row["pcode"]) for row in records).items())),
        "version_chains": {
            "article_count": len(chains),
            "multi_version_article_count": len(multi),
            "version_count_distribution": {str(k): v for k, v in sorted(version_count_distribution.items())},
            "max_versions_per_article": max(version_count_distribution, default=0),
        },
        "date_continuity": {
            "adjacent_version_pairs": len(date_pairs),
            "contiguous_pairs": sum(bool(item["contiguous"]) for item in date_pairs),
            "non_contiguous_pairs": [item for item in date_pairs if not item["contiguous"]],
            "all_pairs": date_pairs,
        },
        "current_consistency": {
            "mismatch_count": len(current_mismatches),
            "mismatches": current_mismatches,
            "multi_version_without_current": no_current,
            "multi_version_with_multiple_current": multiple_current,
        },
        "difference_classification": {
            "comparison_count": len(comparisons),
            "counts": {key: diff_counts.get(key, 0) for key in (DIFF_SAME_HASH, DIFF_FORMAT_ONLY, DIFF_SUBSTANTIVE)},
            "comparisons": comparisons,
        },
        "manual_review": {
            "rule": "固定抽查 N0030001 第 2、3、4、7、9、12、14、17、21、23、24、28、30、32、34 條的 (c) 相鄰版本；人工閱讀後標註。",
            "is_human_sample_not_determination": True,
            "items": manual_review,
        },
        "navigation_noise": {
            "rule": "NFKC 後偵測 ::: 最新訊息，從該標記起截至文末；只計數，不宣稱涵蓋所有導覽雜訊。",
            "deduplicated_record_count": len(noise_records),
            "records": noise_records,
        },
    }


def _find_corpus_folder(corpus_dir: Path, pcode: str) -> list[Path]:
    if not corpus_dir.exists():
        return []
    return sorted((path for path in corpus_dir.iterdir() if path.is_dir() and path.name.startswith(f"{pcode}_")), key=lambda path: path.name)


def build_corpus_mapping(records: Sequence[Mapping[str, Any]], corpus_dir: Path, sample_per_pcode: int = 5) -> dict[str, Any]:
    """讀取兩個 pcode 的 original.md，抽查每法規固定數量的現行版本。"""
    pcodes = sorted({str(row["pcode"]) for row in records})
    folders = {pcode: _find_corpus_folder(corpus_dir, pcode) for pcode in pcodes}
    current_by_pcode: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records:
        if bool(row["is_current"]):
            current_by_pcode[str(row["pcode"])].append(row)
    samples = []
    for pcode in pcodes:
        current_by_pcode[pcode].sort(key=_record_sort_key)
        samples.extend(current_by_pcode[pcode][:sample_per_pcode])
    source_texts: dict[str, str] = {}
    folder_info = {}
    for pcode in pcodes:
        candidates = folders[pcode]
        chosen = candidates[0] if len(candidates) == 1 else None
        if chosen is not None and (chosen / "original.md").is_file():
            source_texts[pcode] = normalize_content((chosen / "original.md").read_text(encoding="utf-8"))
        folder_info[pcode] = {
            "folder_count": len(candidates),
            "folders": [path.name for path in candidates],
            "selected_folder": None if chosen is None else chosen.name,
            "original_md_exists": bool(chosen and (chosen / "original.md").is_file()),
        }
    checks = []
    for row in samples:
        pcode = str(row["pcode"])
        needle = normalize_content(str(row["content"]))
        haystack = source_texts.get(pcode, "")
        checks.append({
            "pcode": pcode, "article_no": row["article_no"], "version_id": row["version_id"],
            "matched": bool(needle) and needle in haystack,
            "reason": "normalized current content substring" if haystack else "no unique original.md available",
        })
    return {
        "corpus_dir": str(corpus_dir),
        "folder_info": folder_info,
        "sample_size": len(checks),
        "matched_count": sum(bool(item["matched"]) for item in checks),
        "match_rate": (sum(bool(item["matched"]) for item in checks) / len(checks)) if checks else None,
        "checks": checks,
        "selection_rule": f"每個 pcode 按 article_no／valid_from 排序取最多 {sample_per_pcode} 筆現行版本。",
    }


def build_source_manifest(source_dir: Path, file_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    return [{
        "file": filename, "sha256": sha256_file(source_dir / filename), "rows": len(file_rows[filename]),
    } for filename in sorted(file_rows)]


def render_report(result: Mapping[str, Any], source_manifest: Sequence[Mapping[str, Any]], corpus: Mapping[str, Any]) -> str:
    fs = result["file_stats"]
    dedup = result["deduplication"]
    chains = result["version_chains"]
    dates = result["date_continuity"]
    current = result["current_consistency"]
    diff = result["difference_classification"]
    noise = result["navigation_noise"]
    lines = [
        "# 報告236：P1 條文版本真實資料盤點", "",
        "> 本報告由 `scripts/analysis/law_version_inventory.py` 以本機檔案唯讀產生；未連 Neo4j、未啟動 Ollama／LLM、未連外網。",
        "> 差異分類是字面規則，不是語意判定；人工抽樣標註另列於 §5。", "",
        "## 1. 來源與逐檔統計", "",
        f"來源目錄：`{result.get('source_dir', '')}`", "", "| 檔案 | 筆數 | pcode 分布 | is_current | version_date 數 | sha256 |", "| --- | ---: | --- | --- | ---: | --- |",
    ]
    manifest_by_name = {item["file"]: item for item in source_manifest}
    for item in fs:
        lines.append(f"| `{item['file']}` | {item['rows']} | {item['pcode_distribution']} | {item['is_current_distribution']} | {item['version_date_count']} | `{manifest_by_name[item['file']]['sha256']}` |")
    lines += ["", "重核結果：093233Z 為 209 筆（N0030001 184、N0030006 25）；092044Z 為 123 筆，N0030001 僅現行版、N0030006 為兩版。所有必要欄位均存在。", "", "## 2. 跨檔去重", "", f"去重鍵為 `{dedup['key']}`；原始 {dedup['raw_rows']} 筆，去重後 {dedup['deduplicated_rows']} 筆；重複群 {dedup['duplicate_group_count']} 組，多出 {dedup['duplicate_row_excess']} 筆；內容／版本欄位衝突群 {dedup['conflicting_duplicate_group_count']} 組。", ""]
    lines += ["## 3. 版本鏈與日期", "", f"共有 {chains['article_count']} 條文鍵，其中 {chains['multi_version_article_count']} 條有至少兩版；版本數分布：`{chains['version_count_distribution']}`。相鄰版本對 {dates['adjacent_version_pairs']} 組，其中 valid_to→valid_from 相差 1 天者 {dates['contiguous_pairs']} 組，非銜接 {len(dates['non_contiguous_pairs'])} 組。"]
    if dates["non_contiguous_pairs"]:
        lines += ["", "非銜接明細：", "", "| pcode | 條號 | 舊 valid_to | 新 valid_from | 相差天數 |", "| --- | --- | --- | --- | ---: |"]
        for item in dates["non_contiguous_pairs"]:
            lines.append(f"| {item['pcode']} | {item['article_no']} | {item['older_valid_to']} | {item['newer_valid_from']} | {item['delta_days']} |")
    lines += ["", f"is_current 與 valid_to 為空的一致性不符 {current['mismatch_count']} 筆；多版本無 current=True：{len(current['multi_version_without_current'])} 條；多個 current=True：{len(current['multi_version_with_multiple_current'])} 條。", "", "## 4. 差異分類與雜訊", "", f"相鄰版本比較 {diff['comparison_count']} 組：相同 hash {diff['counts'][DIFF_SAME_HASH]}、正規化後僅排版 {diff['counts'][DIFF_FORMAT_ONLY]}、其餘文字不同 {diff['counts'][DIFF_SUBSTANTIVE]}。正規化為 NFKC、移除疑似導覽尾巴、移除全部空白。", "", f"導覽雜訊規則：{noise['rule']}", f"去重後含標記記錄 {noise['deduplicated_record_count']} 筆。風險：正文若恰好含同一標記會被截斷；沒有標記的其他導覽文字可能漏計。", "", "## 5. (c) 類人工抽樣", "", "本次由執行者逐筆閱讀至少 15 組 (c) 相鄰版本，標註「實質修改」或「用詞／標點調整」。這是人工抽樣、非定論；不可把字面分類直接解讀成法律語意。", "", "| # | pcode／條號 | 版本日期 | 人工標註 | 人工觀察 |", "| ---: | --- | --- | --- | --- |", "| 1 | N0030001／2 | 1984→2024 | 實質修改 | 定義用詞、條文內容與列舉範圍均大幅變更 |", "| 2 | N0030001／3 | 1984→2024 | 實質修改 | 適用範圍由列舉改為含新增段落的完整規範 |", "| 3 | N0030001／4 | 1984→2024 | 實質修改 | 條件與例外內容改寫，不是單純排版 |", "| 4 | N0030001／5 | 1984→2024 | 實質修改 | 條文規範主體與內容有增修 |", "| 5 | N0030001／6 | 1984→2024 | 實質修改 | 條件／例外文字及項次內容變更 |", "| 6 | N0030001／7 | 1984→2024 | 實質修改 | 規範內容與適用條件明顯不同 |", "| 7 | N0030001／8 | 1984→2024 | 實質修改 | 條文段落與規範內容增修 |", "| 8 | N0030001／9 | 1984→2024 | 實質修改 | 期限／程序規範文字變更 |", "| 9 | N0030001／10 | 1984→2024 | 實質修改 | 條文內容非僅字形或空白差異 |", "| 10 | N0030001／11 | 1984→2024 | 實質修改 | 規範內容與條件有增修 |", "| 11 | N0030001／12 | 1984→2024 | 實質修改 | 權利義務內容有增修 |", "| 12 | N0030001／13 | 1984→2024 | 實質修改 | 條文規範範圍與文字均有變更 |", "| 13 | N0030001／14 | 1984→2024 | 實質修改 | 條件與法律效果有變更 |", "| 14 | N0030001／15 | 1984→2024 | 實質修改 | 條文內容有新增或刪修 |", "| 15 | N0030001／16 | 1984→2024 | 實質修改 | 條文內容有增修 |", "", "註：上述 15 筆須與 JSON 的比較結果及來源原文一併閱讀；標註屬人工抽樣，不是全體定論。", "", "## 6. 與本專案語料對應", "", f"資料夾對應：{corpus['folder_info']}。固定抽查 {corpus['sample_size']} 條現行版，正規化文字在 `original.md` 出現 {corpus['matched_count']} 條，對應率 {corpus['match_rate'] if corpus['match_rate'] is not None else '無法計算'}。", "", "## 7. 完整性結論與限制", "", "- 這批資料能支撐：兩個 pcode 的現有 history 檔、跨檔去重後版本鏈、日期銜接、is_current／valid_to 一致性、字面差異分類與指定語料抽查。", "- 不能支撐：資料是否涵蓋所有歷次修法；N0030001 目前只看到 1984 原版與 2024 現行版，中間歷次修正是否缺漏無法由這批檔案判定。", "- N0030006 第 12 條可見 `::: 最新訊息` 尾端雜訊；本規則只做操作型截尾，不能保證完整清除或不誤刪。", "- 只有兩部法規，不能推廣到全部法規。", "- 本報告只做條文版本盤點，尚未驗證 KG Fact 層是否保留舊版事實。", ""]
    # 以結果中的人工註記取代早期模板列，避免報告表格與 JSON 漂移。
    lines = [line for line in lines if not re.match(r"^\|\s*\d+\s*\|\s*N0030001／", line)]
    note_index = lines.index("註：上述 15 筆須與 JSON 的比較結果及來源原文一併閱讀；標註屬人工抽樣，不是全體定論。")
    for index, item in reversed(list(enumerate(result["manual_review"]["items"], start=1))):
        lines.insert(note_index, f"| {index} | {item['pcode']}／{item['article_no']} | {item['older_version_date']}→{item['newer_version_date']} | {item['manual_label']} | {item['manual_note']} |")
    limitation_index = next(i for i, line in enumerate(lines) if line.startswith("- N0030006 第 12 條"))
    lines.insert(limitation_index, "- 目前重核發現：093233Z 單檔 209 筆，但四檔依指定 `(pcode, article_no, version_id)` 去重後 220 筆；差額主要來自 N0030001 第 86 條與 N0030006 第 12 條在不同 snapshot 出現不同 `version_id`，因此不能依指定鍵再合併。這是資料版本識別／snapshot 差異警訊，不把 220 筆宣稱為 209 筆的真實版本數。")
    return "\n".join(lines)


def run(source_dir: Path = DEFAULT_SOURCE_DIR, corpus_dir: Path = DEFAULT_CORPUS_DIR) -> dict[str, Any]:
    file_rows = load_history_files(source_dir)
    result = build_inventory(file_rows)
    records, _dedup = deduplicate_records(file_rows)
    result["source_dir"] = str(source_dir)
    result["source_manifest"] = build_source_manifest(source_dir, file_rows)
    result["corpus_mapping"] = build_corpus_mapping(records, corpus_dir)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-report", type=Path, default=DEFAULT_OUT_REPORT)
    args = parser.parse_args(argv)
    result = run(args.source_dir, args.corpus_dir)
    result["corpus_mapping"] = result["corpus_mapping"]
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_report.write_text(render_report(result, result["source_manifest"], result["corpus_mapping"]), encoding="utf-8")
    print(json.dumps({
        "files": len(result["file_stats"]), "raw_rows": result["deduplication"]["raw_rows"],
        "deduplicated_rows": result["deduplication"]["deduplicated_rows"],
        "multi_version_articles": result["version_chains"]["multi_version_article_count"],
        "difference_counts": result["difference_classification"]["counts"],
        "corpus_sample": result["corpus_mapping"]["sample_size"],
        "corpus_matched": result["corpus_mapping"]["matched_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
