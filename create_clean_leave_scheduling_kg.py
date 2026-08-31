"""對已知的64份「勞動部法規遵循示範集」文件，建立一個全新、乾淨的KG，
套用2026-08-31當日全部管線修正（規則7擴充、抽取完整性自我核對、數值
忠實性核對、報告21的5項管線缺陷修正）重新抽取。

**與舊KG `76bc98ff-2cbd-447e-a087-7f2df6898655` 的關係**：舊KG凍結保留
（不恢復其抽取），當作修正前的快照供比對；本腳本建立獨立新KG，不影響
舊KG任何資料。64份文件清單直接從舊KG既有的Document節點查詢取得（見
docs/報告/22_乾淨重跑執行報告.md），確保新舊兩個KG是同一批文件，比對
才有意義。

不重寫 `import_leave_scheduling_dataset.py` 既有邏輯——直接複用其
`_iter_records`／`classify_record`／`_record_source_string`／
`_derive_law_articles`／`_normalize_effective_date` 等既有函式，只是把
候選過濾條件從該腳本原本的單一關鍵字子字串比對，換成本次的64筆明確
清單比對。

用法：
    python create_clean_leave_scheduling_kg.py --dry-run
        只列出將匯入的64筆清單，不寫入。

    python create_clean_leave_scheduling_kg.py --kg-name "勞動部法規遵循示範集（64筆，2026-08-31乾淨重跑版）"
        建立新KG並開始匯入+觸發抽取。
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import httpx

from core.config import staging_folder
from core.database import connect, disconnect, get_driver
from core.providers.factory import init_providers
from filter_leave_scheduling_dataset import DEFAULT_DATASET_PATH, _iter_records, classify_record
from import_leave_scheduling_dataset import (
    _derive_law_articles,
    _normalize_effective_date,
    _record_source_string,
)
from models.knowledge_graph import KnowledgeGraphCreate
from models.law_document import LawDocumentCreate
from parser.chunk_writer import document_folder_path, read_sentences_index
from repositories.kg_repo import KGRepository
from repositories.law_document_repo import LawDocumentRepository
from services.classify_service import KGInfo, assign_document_to_kg
from services.document_record_service import document_uuid
from services.ingestion_service import chunk_and_stage
from services.svo_service import trigger_extraction

DEFAULT_KG_NAME = "勞動部法規遵循示範集（64筆，2026-08-31乾淨重跑版）"

# 直接從舊 KG 76bc98ff-2cbd-447e-a087-7f2df6898655 的既有 Document 節點查詢
# 取得，確保新舊兩個KG是同一批文件，比對才有意義（見本檔案模組docstring）。
TARGET_SOURCES = {
    "D0080015_警察人員特別休假辦法",
    "F0040034_員工接受召集請假期間薪資費用加成減除辦法",
    "N0010025_勞動部處務規程",
    "N0010026_勞動部勞工保險局處務規程",
    "N0020001_工會法",
    "N0020006_團體協約法",
    "N0020007_勞資爭議處理法",
    "N0020008_勞資會議實施辦法",
    "N0030001_勞動基準法",
    "N0030002_勞動基準法施行細則",
    "N0030006_勞工請假規則",
    "N0030010_勞動契約法",
    "N0030011_事業單位僱用女性勞工夜間工作場所必要之安全衛生設施標準",
    "N0030014_性別平等工作法",
    "N0030015_性別平等工作法施行細則",
    "N0030018_育嬰留職停薪實施辦法",
    "N0030020_勞工退休金條例",
    "N0030022_勞工退休金條例年金保險實施辦法",
    "N0030025_勞動基準法第四十五條無礙身心健康認定基準及審查辦法",
    "N0050001_勞工保險條例",
    "N0050002_勞工保險條例施行細則",
    "N0050008_勞工職業災害保險職業傷病審查準則",
    "N0050011_被裁減資遣被保險人繼續參加勞工保險及保險給付辦法",
    "N0050021_就業保險法",
    "N0050022_就業保險法施行細則",
    "N0050025_就業保險促進就業實施辦法",
    "N0050030_災區受災勞工保險與勞工職業災害保險及就業保險被保險人保險費支應及傷病給付辦法",
    "N0050031_勞工職業災害保險及保護法",
    "N0050039_勞工職業災害保險及保護法施行細則",
    "N0060001_職業安全衛生法",
    "N0060002_職業安全衛生法施行細則",
    "N0060004_勞工作業場所容許暴露標準",
    "N0060007_高溫作業勞工作息時間標準",
    "N0060009_職業安全衛生設施規則",
    "N0060010_職業安全衛生教育訓練規則",
    "N0060012_精密作業勞工視機能保護設施標準",
    "N0060014_營造安全衛生設施標準",
    "N0060015_特定化學物質危害預防標準",
    "N0060016_重體力勞動作業勞工保護措施標準",
    "N0060022_勞工健康保護規則",
    "N0060027_職業安全衛生管理辦法",
    "N0060029_高架作業勞工保護措施標準",
    "N0060030_高壓氣體勞工安全規則",
    "N0060031_船舶清艙解體職業安全規則",
    "N0060041_職業災害勞工保護法",
    "N0060065_女性勞工母性健康保護實施辦法",
    "N0060079_直轄市及縣市政府辦理協助職業災害勞工重返職場補助辦法",
    "N0060088_工程安全設計及整體工程統合管理辦法",
    "N0070004_勞動檢查法施行細則",
    "N0070020_危險性機械及設備檢查費收費標準",
    "N0080013_事業單位優先僱用經其大量解僱失業勞工獎勵辦法",
    "N0080014_技術士技能檢定作業及試場規則",
    "N0080016_原住民待工期間職前訓練經費補助辦法",
    "N0080028_身心障礙者職業訓練機構設立管理及補助準則",
    "N0080044_技能競賽實施及獎勵辦法",
    "N0090001_就業服務法",
    "N0090002_私立就業服務機構許可及管理辦法",
    "N0090025_就業促進津貼實施辦法",
    "N0090027_雇主聘僱外國人許可及管理辦法",
    "N0090031_外國人從事就業服務法第四十六條第一項第一款至第六款工作資格及審查標準",
    "N0090051_受聘僱從事就業服務法第四十六條第一項第八款至第十款規定工作之外國人請假返國辦法",
    "N0090055_中高齡者及高齡者就業促進法",
    "N0090058_失業中高齡者及高齡者就業促進辦法",
    "N0090064_外國技術人力工作資格及許可管理辦法",
}


def _iter_target_records(dataset_path: Path):
    """依 `TARGET_SOURCES` 明確清單過濾記錄，`yield rec`；同時比對
    `classify_record()` 的篩選結果作為誠實性驗證（若某筆在目標清單裡卻不是
    `kept`，直接印警告，不靜默納入或排除）。"""
    remaining = set(TARGET_SOURCES)
    for rec in _iter_records(dataset_path):
        source = _record_source_string(rec)
        if source not in TARGET_SOURCES:
            continue
        decision, _hits = classify_record(rec)
        if decision != "kept":
            print(f"⚠️ {source} 在目標清單裡，但 classify_record() 判定非 kept（{decision}）——仍納入本次匯入。")
        remaining.discard(source)
        yield rec
    if remaining:
        print(f"⚠️ 目標清單裡有 {len(remaining)} 筆在資料集裡找不到對應記錄：{sorted(remaining)}")


async def _run(dataset_path: Path, kg_name: str | None, dry_run: bool) -> None:
    if not dataset_path.is_file():
        raise SystemExit(f"指定的資料集檔案不存在：{dataset_path}")

    print(f"資料來源檔案：{dataset_path}")
    candidates = list(_iter_target_records(dataset_path))
    print(f"目標64筆清單裡實際找到的記錄數：{len(candidates)}")

    if dry_run:
        for i, rec in enumerate(candidates, 1):
            source = _record_source_string(rec)
            n_articles = len(rec.get("payload", {}).get("articles", []))
            print(f"  {i}. {source}（{n_articles} 筆 payload.articles）")
        print("\n--dry-run 模式完成：僅列出統計，未寫入 Neo4j、未建立 KG。")
        return

    await connect()
    init_providers()
    driver = get_driver()
    try:
        kg_repo = KGRepository(driver)
        law_doc_repo = LawDocumentRepository(driver)
        kg = await kg_repo.create(
            KnowledgeGraphCreate(
                name=kg_name or DEFAULT_KG_NAME,
                description=(
                    "對舊KG 76bc98ff-2cbd-447e-a087-7f2df6898655 的同一批64份"
                    "勞動部法規遵循示範集文件，套用2026-08-31管線稽核修正（報告21）"
                    "＋規則7擴充＋抽取完整性自我核對（報告19）＋數值忠實性核對"
                    "（報告20）後的乾淨重跑版本。"
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
        print(f"KG id={kg.id}——切塊完成後實際的SVO抽取由背景 drain_queue.py Worker 處理。")
    finally:
        await disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-path", "-d", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--kg-name", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(_run(args.dataset_path, args.kg_name, args.dry_run))


if __name__ == "__main__":
    main()
