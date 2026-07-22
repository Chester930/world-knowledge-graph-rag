"""切塊落地存檔：將句子感知分塊結果寫成獨立 .md 檔案，並以 YAML frontmatter
明確標示來源文件與分塊序號，確保下游（embedding、SVO 抽取、知識圖譜寫入）可以隨時
從單一切塊檔案追溯回原始文件與其在文件中的相對位置。

另提供 `write_original_text()`，將解析完成、切塊之前的原始純文字另存一份
（`original.md`）。動機：`chunk-NNN-of-MMM.md` 是為 RAG 向量檢索切的（500 字元、
50 字元重疊），SVO 抽取不應沿用同一份切塊（見 docs/論文/03_變更紀錄.md 對此的
討論）；SVO 需要對原文重新設計獨立的切塊/標準化流程，若沒有原文可用，只能對
原始上傳檔案重新跑一次解析（掃描 PDF 需重跑 OCR，成本高）。保留這份原文，
下游可以直接讀取，不需要重新解析。

另提供 `write_sentences_index()`，將 `parser.core.split_into_sentences()` 對原文
切分出的句子清單存成 `sentences.json`。動機：句子切分本身雖是純規則運算、可
隨時重算，但下游（3.4 §a 指代消解與別名前處理、未來的標準化進度斷點續傳、
SVO Chunk 與原句子的對應索引）都需要一份**穩定不變**的句子清單可供引用——
若每次都重新呼叫 `split_into_sentences()`，一旦切分規則日後調整，先前存的
「第 N 句」索引就可能對不上新算出來的句子邊界。存一份固定的 `sentences.json`
可避免這個問題。

每份來源文件對應一個獨立子資料夾（以其安全化檔名命名），資料夾內只放這份文件自己的
切塊檔案——這是暫存區分類與資料夾歸檔（見 docs/論文/03_系統設計與方法論.md § 3.1.1）
的前提：歸檔動作是把「這份文件的整個資料夾」實際搬移到目標知識圖譜的資料夾底下，而非
搬移單一檔案或改寫資料庫欄位。

刻意獨立於 core.py 之外：`DocumentParser.parse_file()` 與 `sentence_aware_chunking()`
本身維持無副作用的純函式設計（輸入檔案/URL，輸出字串），是否要把分塊結果落地存檔，
交由呼叫端透過本模組明確選擇性呼叫，而非內建在解析流程中自動發生。

本模組只負責文件資料夾內、與「解析輸出的文字內容」直接相關的檔案（切塊檔案、原文
備份）；文件資料夾內的「記錄檔」（歸屬歷史／抽取進度狀態機）是 knowledge-graph 領域
的概念，由 services/document_record_service.py 獨立管理，不在此模組的職責範圍內，
避免 parser 模組耦合到與解析無關的下游概念。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Union


def _safe_filename_stem(source: str, max_length: int = 80) -> str:
    """將來源字串（檔案路徑或 URL）轉換為安全可用於檔名/資料夾名的詞幹。"""
    if source.startswith(("http://", "https://")):
        stem = source
    else:
        stem = Path(source).stem or source

    # 移除/替換檔名中不允許或易產生歧義的字元
    safe = re.sub(r'[\\/:*?"<>|]', "_", stem)
    safe = re.sub(r"\s+", "_", safe).strip("_")
    if not safe:
        safe = "untitled"
    return safe[:max_length]


def document_folder_path(source: str, base_dir: Union[str, Path]) -> Path:
    """回傳某來源文件在 `base_dir` 底下對應的獨立資料夾路徑（不保證已存在）。

    供其他模組（如 document_record_service）在不重複解析檔名的前提下，
    定位到同一份文件的資料夾。
    """
    return Path(base_dir) / _safe_filename_stem(source)


def _yaml_frontmatter(fields: dict) -> str:
    """產生簡易 YAML frontmatter（字串值自動加雙引號並跳脫內部反斜線/雙引號），
    刻意不引入 PyYAML 依賴，維持模組輕量化定位。僅供輸出，不需支援回讀解析。"""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def write_chunks_as_markdown(
    chunks: List[str],
    source: str,
    output_dir: Union[str, Path],
) -> List[Path]:
    """將句子感知分塊結果（`sentence_aware_chunking` 的輸出）逐一寫成獨立的 .md 檔案，
    存放於 `output_dir` 底下一個以該文件命名的獨立子資料夾中。

    每個檔案內部的 YAML frontmatter 都明確標示來源（`source`）與序號
    （`chunk_index`/`total_chunks`，皆為 1-based），確保下游可以隨時從單一切塊
    檔案追溯回原始文件與其在文件中的相對位置。

    重複呼叫同一 `source`（例如文件內容更新後重新處理）時，會先清除該來源資料夾內
    舊有的分塊檔案再寫入新的一批，避免分塊數變少時殘留舊分塊數較多時的過期檔案；
    資料夾內若已存在其他檔案（例如 document_record_service 寫入的記錄檔），不受影響。

    參數：
        chunks: 分塊後的文字內容清單（依原文閱讀順序）。
        source: 原始來源識別字串，通常是檔案路徑或 URL。
        output_dir: 輸出根資料夾，不存在時會自動建立；實際寫入位置是
            `output_dir / <該文件安全化檔名>/`。

    回傳：
        依序寫入的檔案路徑清單，順序與 `chunks` 一致；`chunks` 為空時回傳空清單
        （此時也不會建立該文件的資料夾）。
    """
    doc_folder = document_folder_path(source, output_dir)

    total = len(chunks)
    if total == 0:
        return []

    doc_folder.mkdir(parents=True, exist_ok=True)

    # 清除資料夾內舊有的分塊檔案，避免重新處理後分塊數變少時殘留過期檔案
    for stale_file in doc_folder.glob("chunk-*-of-*.md"):
        try:
            stale_file.unlink()
        except OSError:
            continue

    digits = max(3, len(str(total)))

    written_paths = []
    for idx, chunk_text in enumerate(chunks, start=1):
        frontmatter = _yaml_frontmatter({
            "source": source,
            "chunk_index": idx,
            "total_chunks": total,
        })
        content = f"{frontmatter}\n\n{chunk_text}\n"

        filename = f"chunk-{idx:0{digits}d}-of-{total:0{digits}d}.md"
        file_path = doc_folder / filename
        file_path.write_text(content, encoding="utf-8")
        written_paths.append(file_path)

    return written_paths


ORIGINAL_TEXT_FILENAME = "original.md"


def write_original_text(
    text: str,
    source: str,
    output_dir: Union[str, Path],
) -> Path:
    """將解析完成、切塊之前的原始純文字另存一份至該文件資料夾（`original.md`）。

    與 `write_chunks_as_markdown()` 使用同一套資料夾定位規則（`document_folder_path()`），
    確保兩者落在同一個文件資料夾內。單一固定檔名，重複呼叫同一 `source`（文件內容
    更新後重新處理）時直接覆寫，不像分塊檔案需要清理數量變動後的殘留檔——因為
    這裡永遠只有一個檔案。

    參數：
        text: 解析完成、尚未切塊的原始純文字。
        source: 原始來源識別字串，通常是檔案路徑或 URL，需與
            `write_chunks_as_markdown()` 傳入的 `source` 相同才會落在同一資料夾。
        output_dir: 輸出根資料夾，不存在時會自動建立；實際寫入位置是
            `output_dir / <該文件安全化檔名>/original.md`。

    回傳：
        寫入的檔案路徑。`text` 為空字串時仍會寫入一個空內容的檔案（僅含
        frontmatter），交由呼叫端自行決定是否要在更上層擋掉空白文件
        （`chunk_and_stage()` 已在更上層擋掉，此函式本身不重複判斷）。
    """
    doc_folder = document_folder_path(source, output_dir)
    doc_folder.mkdir(parents=True, exist_ok=True)

    frontmatter = _yaml_frontmatter({"source": source})
    content = f"{frontmatter}\n\n{text}\n"

    file_path = doc_folder / ORIGINAL_TEXT_FILENAME
    file_path.write_text(content, encoding="utf-8")
    return file_path


_FRONTMATTER_PATTERN = re.compile(r"^---\n.*?\n---\n\n?", re.DOTALL)


def read_original_text(source: str, base_dir: Union[str, Path]) -> Optional[str]:
    """讀回 `write_original_text()` 寫入的原文（去除 YAML frontmatter），
    對應 docs/論文/03_系統設計與方法論.md § 3.1.2 `GETSENT` 三層判斷的第二層
    （`sentences.json` 缺席、但 `original.md` 存在時，重新對其呼叫
    `split_into_sentences()` 補回句子清單）。資料夾或檔案不存在時回傳 `None`。
    """
    doc_folder = document_folder_path(source, base_dir)
    path = doc_folder / ORIGINAL_TEXT_FILENAME
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8")
    body = _FRONTMATTER_PATTERN.sub("", raw, count=1)
    # write_original_text() 在正文結尾多加了一個 "\n"，此處還原成呼叫時傳入的原始字串
    return body[:-1] if body.endswith("\n") else body


SENTENCES_INDEX_FILENAME = "sentences.json"


def write_sentences_index(
    sentences: List[str],
    source: str,
    output_dir: Union[str, Path],
) -> Path:
    """將句子切分結果（`parser.core.split_into_sentences()` 的輸出）存成該文件
    資料夾內固定的 `sentences.json`，作為下游可重複引用、不會因重新計算而
    跑掉的穩定句子清單。

    與 `write_chunks_as_markdown()`／`write_original_text()` 使用同一套資料夾
    定位規則（`document_folder_path()`），確保三者落在同一個文件資料夾內。
    單一固定檔名，重複呼叫同一 `source` 時直接覆寫。

    參數：
        sentences: `split_into_sentences()` 的輸出（保留原始間距，未 strip）。
        source: 原始來源識別字串，需與其他寫入函式傳入的 `source` 相同才會
            落在同一資料夾。
        output_dir: 輸出根資料夾，不存在時會自動建立；實際寫入位置是
            `output_dir / <該文件安全化檔名>/sentences.json`。

    回傳：
        寫入的檔案路徑。
    """
    doc_folder = document_folder_path(source, output_dir)
    doc_folder.mkdir(parents=True, exist_ok=True)

    payload = {
        "source": source,
        "total_sentences": len(sentences),
        "sentences": sentences,
    }

    file_path = doc_folder / SENTENCES_INDEX_FILENAME
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return file_path


def read_sentences_index(source: str, base_dir: Union[str, Path]) -> Optional[List[str]]:
    """讀回 `write_sentences_index()` 寫入的句子清單，對應 § 3.1.2 `GETSENT`
    三層判斷的第一層（優先讀取，不重新切分）。資料夾或檔案不存在時回傳
    `None`，交由呼叫端（`services/ingestion_service.py::get_or_rebuild_sentences()`）
    決定下一層判斷。
    """
    doc_folder = document_folder_path(source, base_dir)
    path = doc_folder / SENTENCES_INDEX_FILENAME
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["sentences"]
