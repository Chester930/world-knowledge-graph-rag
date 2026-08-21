"""從 labor-compliance-collector 的「請假/排班法規測試」資料集匯入文件，建立獨立
新 KG（2026-08-20，使用者確認會不定時更新這批資料，且明確要求建新 KG、不覆蓋
既有 KG）。

**外部資料來源**（固定路徑，另一個獨立工具的輸出，本專案不擁有、不寫回）：
`D:\\Users\\666\\Desktop\\labor-compliance-collector\\projects\\20260818_請假_排班_法規測試`

**範圍（第一階段）**：僅匯入三個長篇全文來源——`MOJ_FULL_CURRENT_LAWS_JSON`（法律
全文）、`MOJ_CURRENT_ORDERS_JSON`（命令全文）、`JUDICIAL_YUAN_OPEN_DATA_API`（司法院
判決）。三者在 `03_extraction_input/` 底下共用同一套 schema，`text` 欄位皆為可直接
餵給 `chunk_and_stage()` 的完整純文字，形態上與現有「指代消解→SVO切塊→LLM抽取」管線
匹配。

**刻意排除**（非本次範圍）：
- `MOL_DATASET_109896`（勞動部裁罰，51,612 筆）——短結構化記錄，跟長篇法規文字是
  不同的資料形狀，硬套現有管線等於對 5 萬多筆短記錄各自呼叫一輪 LLM，時間/成本
  可觀，且這些記錄根本不需要指代消解前處理，留待後續設計專門的輕量抽取路徑。
- `MOJ_LAW_HISTORY_HTML_API`（209 筆歷史條文版本）——`text` 欄位是空殼（只有類似
  「勞動基準法 EN」的標題行），實際內容在 `payload.content`，且是逐條逐版本粒度，
  跟本階段其餘來源的 schema 不一致，需要另外設計才能正確處理。
- `MOL_WORKING_HOURS_HANDBOOK_API`（75 筆工時手冊）——`text` 欄位只有公文字號
  （如「88.7.26勞動2字第0034087號函」），沒有實質內容可供抽取。

**篩選邏輯**：讀取 `06_agent_summary/phase0_pruning_dry_run.json` 的
`source_decisions`（逐筆記錄 decision/reason），只收 `decision == "keep"` 且
`reason` 不是以 `topic_keyword` 開頭的記錄——這重現了收集器自己在
`coverage_manifest.json` 裡區分「核心保留」（442 筆）vs.「跨域 review 候選」
（858 筆）的判斷依據，非本專案自創的門檻：已用程式驗證 `source_decisions` 裡
`decision=="keep"` 且 reason 非 `topic_keyword` 開頭的記錄數，剛好等於
`coverage_manifest.json` 的 keep 加總（76+366=442）；`topic_keyword` 開頭的記錄數
剛好等於 review 加總（101+757=858）。實測附帶效果：《福建省金門縣政府組織規程》
（縣長職務代理，非勞動請假）、已於 2023-06-30 當然廢止的《嚴重特殊傳染性肺炎防治
及紓困振興特別條例》，兩者的 reason 皆為 `topic_keyword` 開頭，因此自動被排除，
不需要另外寫「排除已廢止法規」的邏輯。`JUDICIAL_YUAN_OPEN_DATA_API` 不在
`source_decisions` 涵蓋範圍內（司法院判決源頭未經過 MOJ 關鍵字篩選這道關卡，是
專案手動維護的小量目標清單，會持續累積），一律納入。

**識別碼與冪等重跑**：`source` 字串採 `{pcode 或 judgment_id}_{標題}` 格式（比照
`01_moj_laws/` 資料夾既有命名慣例），對應 `document_uuid(source)` 的穩定雜湊；每次
執行前檢查目標 KG 資料夾底下是否已有同名子資料夾，已存在則略過——支援資料集「會
不定時更新」時重複執行本腳本，只匯入真正新增的記錄，不重複處理、不重複觸發 LLM。

用法：
    python import_labor_compliance_dataset.py --dry-run
        只列出將匯入的清單與統計，不寫入 Neo4j、不建立 KG。

    python import_labor_compliance_dataset.py --kg-name "請假與排班法規遵循（測試）"
        建立新 KG 並匯入，執行結束會印出新 KG 的 id，供之後重跑時用 --kg-id 帶入。

    python import_labor_compliance_dataset.py --kg-id <uuid>
        匯入既有 KG（重跑／增量更新用，只處理尚未匯入過的記錄）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from uuid import UUID

import httpx

from core.config import settings, staging_folder
from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from models.knowledge_graph import KnowledgeGraphCreate
from parser.chunk_writer import document_folder_path, read_sentences_index
from repositories.kg_repo import KGRepository
from services.classify_service import KGInfo, assign_document_to_kg
from services.document_record_service import document_uuid
from services.ingestion_service import chunk_and_stage
from services.svo_service import trigger_extraction

DEFAULT_COLLECTOR_PROJECT_DIRS = [
    Path(r"c:\Users\mycena\Desktop\labor-compliance-collector\projects\20260821_請假與排班法規庫"),
    Path(r"D:\Users\666\Desktop\labor-compliance-collector\projects\20260818_請假_排班_法規測試"),
]

# (source_key, record_type 子資料夾名稱) —— 第一階段範圍的三個長篇全文來源。
TARGET_SOURCES = [
    ("MOJ_FULL_CURRENT_LAWS_JSON", "law"),
    ("MOJ_CURRENT_ORDERS_JSON", "law"),
    ("JUDICIAL_YUAN_OPEN_DATA_API", "judgment"),
]


def _find_default_project_dir() -> Path:
    for p in DEFAULT_COLLECTOR_PROJECT_DIRS:
        if p.is_dir():
            return p
    return DEFAULT_COLLECTOR_PROJECT_DIRS[0]


def _load_source_decisions(project_dir: Path) -> dict[str, dict]:
    pruning_path = project_dir / "06_agent_summary" / "phase0_pruning_dry_run.json"
    if pruning_path.is_file():
        data = json.loads(pruning_path.read_text(encoding="utf-8"))
        return data.get("source_decisions", {})
    return {}


def _is_core_keep(source_key: str, filename: str, decisions: dict[str, dict]) -> bool:
    """判斷依據見模組 docstring「篩選邏輯」。若未提供 decisions 或不在 `source_decisions`
    涵蓋範圍內（如 `JUDICIAL_YUAN_OPEN_DATA_API` 或無修剪報告時），一律視為保留。"""
    if not decisions:
        return True
    key = f"{source_key}/{filename}"
    decision = decisions.get(key)
    if decision is None:
        return True
    return decision.get("decision") == "keep" and not decision.get("reason", "").startswith("topic_keyword")


def _record_source_string(source_key: str, record: dict) -> str:
    """建立這份記錄在我們系統裡的 `source`（文件識別碼的自然鍵），比照
    `01_moj_laws/` 資料夾既有的 `{pcode}_{標題}` 命名慣例。"""
    title = record.get("title") or record.get("item_id", "unknown")
    if source_key == "JUDICIAL_YUAN_OPEN_DATA_API":
        judgment_id = record.get("payload", {}).get("judgment_id", record.get("item_id", "judgment"))
        return f"{judgment_id.replace(',', '_')}_{title}"
    pcode = record.get("payload", {}).get("pcode", record.get("item_id", "pcode"))
    return f"{pcode}_{title}"


def _iter_candidate_records(
    project_dir: Path,
    decisions: dict[str, dict],
    filter_keyword: str | None = None,
    limit: int | None = None,
):
    """依序讀出範圍內、通過核心保留篩選的記錄。yield (source_key, source, text)。"""
    extraction_input_dir = project_dir / "03_extraction_input"
    yielded = 0
    for source_key, record_type in TARGET_SOURCES:
        record_dir = extraction_input_dir / source_key / record_type
        if not record_dir.is_dir():
            continue
        for entry in os.scandir(record_dir):
            if not entry.name.endswith(".json"):
                continue
            if not _is_core_keep(source_key, entry.name, decisions):
                continue
            try:
                with open(entry.path, "r", encoding="utf-8") as f:
                    record = json.load(f)
            except Exception:
                continue
            text = record.get("text", "").strip()
            if not text:
                continue
            source = _record_source_string(source_key, record)
            if filter_keyword and filter_keyword not in source:
                continue
            yield source_key, source, text
            yielded += 1
            if limit and yielded >= limit:
                return


async def _run(
    project_dir: Path,
    kg_id: UUID | None,
    kg_name: str | None,
    filter_keyword: str | None,
    limit: int | None,
    dry_run: bool,
) -> None:
    if not project_dir.is_dir():
        raise SystemExit(f"指定的資料集目錄不存在：{project_dir}")

    print(f"資料來源目錄：{project_dir}")
    decisions = _load_source_decisions(project_dir)
    if decisions:
        print(f"已載入修剪決策報告（共 {len(decisions)} 條決策）")
    else:
        print("未偵測到 phase0_pruning_dry_run.json，將直接讀取 03_extraction_input 下所有候選檔案")

    candidates = list(_iter_candidate_records(project_dir, decisions, filter_keyword=filter_keyword, limit=limit))

    counts: dict[str, int] = {}
    for source_key, _source, _text in candidates:
        counts[source_key] = counts.get(source_key, 0) + 1
    print("\n符合篩選條件的記錄數：")
    for source_key, count in counts.items():
        print(f"  {source_key}: {count}")
    print(f"  合計: {len(candidates)}")

    if dry_run or not candidates:
        print("\n候選清單（前 10 筆）：")
        for i, (sk, src, txt) in enumerate(candidates[:10], 1):
            print(f"  {i}. [{sk}] {src} ({len(txt)} 字元)")
        if len(candidates) > 10:
            print(f"  ... 還有 {len(candidates) - 10} 筆")
        print("\n--dry-run 模式完成：僅列出統計，未寫入 Neo4j、未建立 KG。")
        return

    await connect()
    embedding = init_providers()
    driver = get_driver()
    try:
        kg_repo = KGRepository(driver)
        if kg_id is not None:
            kg = await kg_repo.get(kg_id)
            if kg is None:
                raise SystemExit(f"找不到 --kg-id 指定的 KG：{kg_id}")
        else:
            kg = await kg_repo.create(
                KnowledgeGraphCreate(
                    name=kg_name or "請假與排班法規遵循（測試）",
                    description=(
                        f"從 {project_dir.name} 資料集匯入，第一階段範圍：法律/命令全文（核心保留）＋司法院判決。"
                    ),
                    pronoun_lexicon_exclude=["其", "該"],
                )
            )
            print(f"已建立新 KG：id={kg.id} name={kg.name}")

        kg_info = KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))

        imported, skipped, timed_out = 0, 0, 0
        for idx, (source_key, source, text) in enumerate(candidates, start=1):
            doc_uuid = document_uuid(source)
            existing_folder = document_folder_path(source, kg_info.folder_path)
            if existing_folder.exists():
                skipped += 1
                continue

            staging_doc_folder, _record = chunk_and_stage(text, source, staging_folder())
            dest = assign_document_to_kg(staging_doc_folder, kg_info, method="manual")
            t0 = time.monotonic()
            sentences = read_sentences_index(source, kg_info.folder_path) or []
            timeout_seconds = max(600, len(sentences) * 5)
            try:
                await asyncio.wait_for(trigger_extraction(driver, dest, kg.id), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                timed_out += 1
                print(
                    f"[{source_key}] ⚠️ 逾時（>{timeout_seconds}s，{len(sentences)} 句），"
                    f"略過此筆，之後可手動重跑補上：{source}",
                    flush=True,
                )
                continue
            except httpx.HTTPError as exc:
                timed_out += 1
                print(
                    f"[{source_key}] ⚠️ LLM 呼叫失敗（{type(exc).__name__}: {exc}），"
                    f"略過此筆，之後可手動重跑補上：{source}",
                    flush=True,
                )
                continue
            imported += 1
            elapsed = time.monotonic() - t0
            print(
                f"[{idx}/{len(candidates)}][{source_key}] 已匯入並觸發抽取"
                f"（{elapsed:.1f}s）：{source}（document_uuid={doc_uuid}）",
                flush=True,
            )

        print(f"\n完成：新匯入 {imported} 筆，略過（已存在）{skipped} 筆，逾時略過 {timed_out} 筆。")
    finally:
        await disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset-dir",
        "-d",
        type=Path,
        default=_find_default_project_dir(),
        help="指定 labor-compliance-collector 專案目錄",
    )
    parser.add_argument("--limit", "-n", type=int, default=None, help="限制處理筆數（供測試用）")
    parser.add_argument("--filter", "-f", type=str, default=None, help="依關鍵字或 PCODE 篩選檔名")
    parser.add_argument("--dry-run", action="store_true", help="只列出將匯入的清單與統計，不寫入")
    parser.add_argument("--kg-id", type=str, default=None, help="匯入既有 KG（重跑／增量更新用）")
    parser.add_argument("--kg-name", type=str, default=None, help="建立新 KG 時使用的名稱")
    args = parser.parse_args()

    kg_id = UUID(args.kg_id) if args.kg_id else None
    asyncio.run(
        _run(
            project_dir=args.dataset_dir,
            kg_id=kg_id,
            kg_name=args.kg_name,
            filter_keyword=args.filter,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()

