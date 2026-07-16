"""切塊落地存檔：將句子感知分塊結果寫成獨立 .md 檔案，並以 YAML frontmatter
明確標示來源文件與分塊序號，確保下游（embedding、SVO 抽取、知識圖譜寫入）可以隨時
從單一切塊檔案追溯回原始文件與其在文件中的相對位置。

每份來源文件對應一個獨立子資料夾（以其安全化檔名命名），資料夾內只放這份文件自己的
切塊檔案——這是暫存區分類與資料夾歸檔（見 docs/論文/03_系統設計與方法論.md § 3.1.1）
的前提：歸檔動作是把「這份文件的整個資料夾」實際搬移到目標知識圖譜的資料夾底下，而非
搬移單一檔案或改寫資料庫欄位。

刻意獨立於 core.py 之外：`DocumentParser.parse_file()` 與 `sentence_aware_chunking()`
本身維持無副作用的純函式設計（輸入檔案/URL，輸出字串），是否要把分塊結果落地存檔，
交由呼叫端透過本模組明確選擇性呼叫，而非內建在解析流程中自動發生。

本模組只負責切塊檔案本身；文件資料夾內的「記錄檔」（歸屬歷史／抽取進度狀態機）是
knowledge-graph 領域的概念，由 services/document_record_service.py 獨立管理，不在此
模組的職責範圍內，避免 parser 模組耦合到與解析無關的下游概念。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Union


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
