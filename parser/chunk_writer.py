"""切塊落地存檔：將句子感知分塊結果寫成獨立 .md 檔案，並以檔名與 YAML frontmatter
明確標示來源文件與分塊序號，確保下游（embedding、SVO 抽取、知識圖譜寫入）可以隨時
從單一切塊檔案追溯回原始文件與其在文件中的相對位置。

刻意獨立於 core.py 之外：`DocumentParser.parse_file()` 與 `sentence_aware_chunking()`
本身維持無副作用的純函式設計（輸入檔案/URL，輸出字串），是否要把分塊結果落地存檔，
交由呼叫端透過本模組明確選擇性呼叫，而非內建在解析流程中自動發生。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Union


def _safe_filename_stem(source: str, max_length: int = 80) -> str:
    """將來源字串（檔案路徑或 URL）轉換為安全可用於檔名的詞幹。"""
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
    """將句子感知分塊結果（`sentence_aware_chunking` 的輸出）逐一寫成獨立的 .md 檔案。

    每個檔案的檔名與內部 YAML frontmatter 都明確標示來源（`source`）與序號
    （`chunk_index`/`total_chunks`，皆為 1-based），確保下游可以隨時從單一切塊
    檔案追溯回原始文件與其在文件中的相對位置。

    重複呼叫同一 `source`（例如文件內容更新後重新處理）時，會先清除該來源舊有的
    分塊檔案再寫入新的一批，避免分塊數變少時殘留舊分塊數較多時的過期檔案。

    參數：
        chunks: 分塊後的文字內容清單（依原文閱讀順序）。
        source: 原始來源識別字串，通常是檔案路徑或 URL。
        output_dir: 輸出資料夾，不存在時會自動建立。

    回傳：
        依序寫入的檔案路徑清單，順序與 `chunks` 一致；`chunks` 為空時回傳空清單。
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stem = _safe_filename_stem(source)

    # 清除同一來源舊有的分塊檔案，避免重新處理後分塊數變少時殘留過期檔案
    for stale_file in output_path.glob(f"{stem}__chunk-*-of-*.md"):
        try:
            stale_file.unlink()
        except OSError:
            continue

    total = len(chunks)
    if total == 0:
        return []

    digits = max(3, len(str(total)))

    written_paths = []
    for idx, chunk_text in enumerate(chunks, start=1):
        frontmatter = _yaml_frontmatter({
            "source": source,
            "chunk_index": idx,
            "total_chunks": total,
        })
        content = f"{frontmatter}\n\n{chunk_text}\n"

        filename = f"{stem}__chunk-{idx:0{digits}d}-of-{total:0{digits}d}.md"
        file_path = output_path / filename
        file_path.write_text(content, encoding="utf-8")
        written_paths.append(file_path)

    return written_paths
