"""從「請假與排班法規庫（精簡標準化版）」資料集匯入 469 筆篩選後的法規記錄，
建立獨立新 KG，並以 `Document`／`LawArticle` 節點保留原本會被匯入時丟棄的
JSON 結構化中繼資料（2026-08-24，對應 `docs/論文/03_系統設計與方法論.md`
§ 3.5「實作範圍定案」）。

**與 `import_labor_compliance_dataset.py` 的關係**：後者處理的是另一個更舊、
schema 不同的資料夾（`03_extraction_input/{source_key}/{record_type}/*.json`，
只有 `text` 欄位可直接餵給既有句子聚合管線）；本腳本處理的是
`filter_leave_scheduling_dataset.py` 篩出的單一 JSONL 檔案，schema 含
`payload.articles`（逐條 `ArticleNo`／`ArticleContent`）與
`payload.effective_date`／`effective_note`／`scope_temporal` 等結構化欄位，
需要不同的匯入邏輯，故另立腳本，不修改既有腳本。

**外部資料來源**（固定路徑，另一個獨立工具的輸出，本專案不擁有、不寫回）：
`D:\\Users\\666\\Desktop\\labor-compliance-collector\\projects\\20260821_請假與排班法規庫_精簡標準化版\\20260821_leave_and_scheduling_normalized.jsonl`

**篩選邏輯**：直接呼叫 `filter_leave_scheduling_dataset.py::classify_record()`，
只收 `decision == "kept"` 的記錄——與該腳本共用同一套規則，不重複實作、不會
與獨立跑 `filter_leave_scheduling_dataset.py --out ...` 得到的統計數字對不上。

**每筆記錄的匯入步驟**：
1. `LawDocumentRepository.merge_document()`——建立 `Document` 節點，保存
   `category`（併入 `title`／`record_type` 已有欄位之外，`category` 目前
   設計未列入 schema，見下方「已知侷限」）、`update_date`、`effective_date`
   （正規化 `""`／`"99991231"` 為 `null`）、`effective_note`、`source_url`。
2. `LawDocumentRepository.merge_law_articles()`——依 `payload.articles`
   原始順序，把每條實際條文對應到最近一個章節標題，濾除規則與
   `services.svo_chunking.build_article_aware_chunks()` 完全一致。
3. `services.ingestion_service.chunk_and_stage()` 用 `record["text"]`（完整
   法規全文純文字）建立可讀的 `original.md`／記錄檔。
4. `services.svo_service.trigger_extraction(..., articles=payload["articles"])`
   ——改走 `ArticleAwareChunking` 路徑，SVO 抽取仍走既有管線，`Fact`
   `SUPPORTED_BY` 暫維持指向 `Chunk`（見 § 3.5「實作範圍定案」，未改指向
   `LawArticle`）。

**已知侷限（誠實聲明）**：`payload.category`（如「行政＞勞動部＞勞動條件及
就業平等目」）與 `scope_temporal`／`scope_spatial`／`scope_industry` 目前
**不**寫入 `Document` 節點——`Document` schema 依 03 §3.5 定案的九個欄位
（`kg_id`／`source_doc_id`／`source`／`title`／`record_type`／
`content_hash`／`update_date`／`effective_date`／`effective_note`／
`source_url`）為準，這幾個欄位未列入設計提案，本次不擅自擴充 schema；若
之後第五章實驗需要依 `category` 做結構化條件過濾，需先回頭補上設計討論，
非本腳本自行決定。舊 KG（`0bd40837-...` 等）依既有決策不做 backfill，本
腳本一律建立新 KG。

用法：
    python import_leave_scheduling_dataset.py --dry-run
        只列出將匯入的清單與統計，不寫入 Neo4j、不建立 KG。

    python import_leave_scheduling_dataset.py --kg-name "請假與排班法規遵循（469筆）"
        建立新 KG 並匯入，執行結束會印出新 KG 的 id，供之後重跑時用 --kg-id 帶入。

    python import_leave_scheduling_dataset.py --kg-id <uuid>
        匯入既有 KG（重跑／增量更新用，只處理尚未匯入過的記錄）。
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from uuid import UUID

import httpx

from core.config import staging_folder
from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from filter_leave_scheduling_dataset import DEFAULT_DATASET_PATH, _iter_records, classify_record
from models.knowledge_graph import KnowledgeGraphCreate
from models.law_document import LawArticleCreate, LawDocumentCreate
from parser.chunk_writer import document_folder_path, read_sentences_index
from repositories.kg_repo import KGRepository
from repositories.law_document_repo import LawDocumentRepository
from services.classify_service import KGInfo, assign_document_to_kg
from services.document_record_service import document_uuid
from services.ingestion_service import chunk_and_stage
from services.svo_chunking import _is_deleted_article_placeholder
from services.svo_service import trigger_extraction

DEFAULT_KG_NAME = "請假與排班法規遵循（469筆，Document/LawArticle 節點版）"


def _record_source_string(rec: dict) -> str:
    """比照 `import_labor_compliance_dataset.py::_record_source_string()` 既有
    的 `{pcode}_{標題}` 命名慣例。"""
    payload = rec.get("payload", {})
    pcode = payload.get("pcode") or rec.get("identity_key", "unknown")
    title = rec.get("title") or "unknown"
    return f"{pcode}_{title}"


def _normalize_effective_date(value: str | None) -> str | None:
    """`""`（未填）與 `"99991231"`（代表「施行日期由行政院/另定」，見
    03 §3.5）皆正規化為 `None`；其餘視為 `YYYYMMDD` 字串原樣保存，不轉型為
    `date`（本專案對此欄位未做進一步日期解析，避免對缺乏逐條精確度的欄位
    假裝有更高的結構化程度）。"""
    if not value or value == "99991231":
        return None
    return value


def _derive_law_articles(kg_id: UUID, source_doc_id: UUID, articles: list[dict]) -> list[LawArticleCreate]:
    """依 `payload.articles` 原始順序，把每條實際條文對應到「往前追溯最近一個
    章節標題」（`ArticleNo` 為空字串的項目）；濾除規則與
    `services.svo_chunking.build_article_aware_chunks()` 完全一致（`ArticleNo`
    為空、內容為空、或內容等同「（刪除）」佔位標記皆濾除），確保這裡建立的
    `LawArticle` 節點與實際送進 SVO 抽取管線的 chunk 一一對應。"""
    current_chapter: str | None = None
    result: list[LawArticleCreate] = []
    for article in articles:
        article_no = (article.get("ArticleNo") or "").strip()
        content = (article.get("ArticleContent") or "").strip()
        if not article_no:
            if content:
                current_chapter = content
            continue
        if not content or _is_deleted_article_placeholder(content):
            continue
        result.append(LawArticleCreate(
            kg_id=kg_id, source_doc_id=source_doc_id,
            article_no=article_no, article_content=content,
            chapter_title=current_chapter,
        ))
    return result


def _iter_kept_records(dataset_path: Path, filter_keyword: str | None, limit: int | None):
    """依 `classify_record()` 篩選出 `decision == "kept"` 的記錄，`yield rec`。"""
    yielded = 0
    for rec in _iter_records(dataset_path):
        decision, _hits = classify_record(rec)
        if decision != "kept":
            continue
        source = _record_source_string(rec)
        if filter_keyword and filter_keyword not in source:
            continue
        yield rec
        yielded += 1
        if limit and yielded >= limit:
            return


async def _run(
    dataset_path: Path,
    kg_id: UUID | None,
    kg_name: str | None,
    filter_keyword: str | None,
    limit: int | None,
    dry_run: bool,
) -> None:
    if not dataset_path.is_file():
        raise SystemExit(f"指定的資料集檔案不存在：{dataset_path}")

    print(f"資料來源檔案：{dataset_path}")
    candidates = list(_iter_kept_records(dataset_path, filter_keyword, limit))
    print(f"符合篩選條件（decision == 'kept'）的記錄數：{len(candidates)}")

    if dry_run or not candidates:
        print("\n候選清單（前 10 筆）：")
        for i, rec in enumerate(candidates[:10], 1):
            source = _record_source_string(rec)
            n_articles = len(rec.get("payload", {}).get("articles", []))
            print(f"  {i}. {source}（{n_articles} 筆 payload.articles）")
        if len(candidates) > 10:
            print(f"  ... 還有 {len(candidates) - 10} 筆")
        print("\n--dry-run 模式完成：僅列出統計，未寫入 Neo4j、未建立 KG。")
        return

    await connect()
    embedding = init_providers()
    driver = get_driver()
    try:
        kg_repo = KGRepository(driver)
        law_doc_repo = LawDocumentRepository(driver)
        if kg_id is not None:
            kg = await kg_repo.get(kg_id)
            if kg is None:
                raise SystemExit(f"找不到 --kg-id 指定的 KG：{kg_id}")
        else:
            kg = await kg_repo.create(
                KnowledgeGraphCreate(
                    name=kg_name or DEFAULT_KG_NAME,
                    description=(
                        f"從 {dataset_path.name} 篩選出的 469 筆請假與排班法規匯入，"
                        "以 Document/LawArticle 節點保留 JSON 結構化中繼資料。"
                    ),
                    pronoun_lexicon_exclude=["其", "該"],
                )
            )
            print(f"已建立新 KG：id={kg.id} name={kg.name}")

        kg_info = KGInfo(kg_id=kg.id, kg_name=kg.name, folder_path=Path(kg.folder_path))

        imported, skipped, timed_out = 0, 0, 0
        for idx, rec in enumerate(candidates, start=1):
            source = _record_source_string(rec)
            source_doc_id = document_uuid(source)
            existing_folder = document_folder_path(source, kg_info.folder_path)
            if existing_folder.exists():
                skipped += 1
                continue

            payload = rec.get("payload", {})
            articles = payload.get("articles", [])

            await law_doc_repo.merge_document(LawDocumentCreate(
                kg_id=kg.id,
                source_doc_id=source_doc_id,
                source=source,
                title=rec.get("title") or "unknown",
                record_type=rec.get("record_type") or "unknown",
                content_hash=rec.get("content_hash") or "",
                update_date=payload.get("update_date") or None,
                effective_date=_normalize_effective_date(payload.get("effective_date")),
                effective_note=payload.get("effective_note") or None,
                source_url=rec.get("provenance", {}).get("source_url"),
            ))
            law_articles = _derive_law_articles(kg.id, source_doc_id, articles)
            await law_doc_repo.merge_law_articles(law_articles)

            text = rec.get("text", "").strip()
            if not text:
                skipped += 1
                print(f"⚠️ text 為空，略過此筆：{source}", flush=True)
                continue

            staging_doc_folder, _record = chunk_and_stage(text, source, staging_folder())
            dest = assign_document_to_kg(staging_doc_folder, kg_info, method="manual")
            t0 = time.monotonic()
            sentences = read_sentences_index(source, kg_info.folder_path) or []
            timeout_seconds = max(600, len(sentences) * 5)
            try:
                await asyncio.wait_for(
                    trigger_extraction(driver, dest, kg.id, articles=articles),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                timed_out += 1
                print(
                    f"⚠️ 逾時（>{timeout_seconds}s，{len(sentences)} 句），"
                    f"略過此筆，之後可手動重跑補上：{source}",
                    flush=True,
                )
                continue
            except httpx.HTTPError as exc:
                timed_out += 1
                print(
                    f"⚠️ LLM 呼叫失敗（{type(exc).__name__}: {exc}），"
                    f"略過此筆，之後可手動重跑補上：{source}",
                    flush=True,
                )
                continue
            imported += 1
            elapsed = time.monotonic() - t0
            print(
                f"[{idx}/{len(candidates)}] 已匯入並觸發抽取（{elapsed:.1f}s，"
                f"{len(law_articles)} 條法條）：{source}（source_doc_id={source_doc_id}）",
                flush=True,
            )

        print(f"\n完成：新匯入 {imported} 筆，略過 {skipped} 筆，逾時略過 {timed_out} 筆。")
    finally:
        await disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dataset-path",
        "-d",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="指定 labor-compliance-collector 正規化 JSONL 檔案路徑",
    )
    parser.add_argument("--limit", "-n", type=int, default=None, help="限制處理筆數（供測試用）")
    parser.add_argument("--filter", "-f", type=str, default=None, help="依關鍵字或 PCODE 篩選 source")
    parser.add_argument("--dry-run", action="store_true", help="只列出將匯入的清單與統計，不寫入")
    parser.add_argument("--kg-id", type=str, default=None, help="匯入既有 KG（重跑／增量更新用）")
    parser.add_argument("--kg-name", type=str, default=None, help="建立新 KG 時使用的名稱")
    args = parser.parse_args()

    kg_id = UUID(args.kg_id) if args.kg_id else None
    asyncio.run(
        _run(
            dataset_path=args.dataset_path,
            kg_id=kg_id,
            kg_name=args.kg_name,
            filter_keyword=args.filter,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
