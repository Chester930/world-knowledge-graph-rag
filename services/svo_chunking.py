"""SVO 專用切塊與原句/標準化句索引。

這個模組承接指代消解/標準化前處理的輸出，但不負責呼叫 LLM 做標準化。
輸入必須維持「一個原句對一個標準化句」；若標準化步驟合併或拆分句子，
這裡會直接拒絕，避免後續三元組無法追溯回 original.md 的句子範圍。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from parser.chunk_writer import document_folder_path
from parser.core import split_into_sentences

SVO_INDEX_FILENAME = "svo_index.json"
SVO_CHUNK_PREFIX = "svo-chunk"
# 🟡 工程預設，非最終定案（見 docs/論文/03_系統設計與方法論.md § 3.4 §a
# `SVOGROUP` 節點）：依序聚合句子，最多 5 句或最多 300 字元，先到者為準。
# 300 字元沒有直接文獻依據，僅呼應 GraphRAG（Edge et al., 2024）附錄查證到的
# 方向性發現「切塊越小、抽取密度越高」；最終數值留給第五章消融實驗校準。
DEFAULT_SVO_CHUNK_SIZE = 300
DEFAULT_SVO_CHUNK_MAX_SENTENCES = 5
DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES = 0


@dataclass(frozen=True)
class SVOChunk:
    index: int
    total_chunks: int
    source_sentence_start: int
    source_sentence_end: int
    text: str
    original_sentences: list[str]
    normalized_sentences: list[str]
    filename: str


def split_and_clean_sentences(text: str) -> list[str]:
    """共用分句器的 SVO 前處理包裝：strip 並過濾空句。"""
    return [sentence.strip() for sentence in split_into_sentences(text) if sentence.strip()]


def build_svo_chunks(
    original_sentences: Sequence[str],
    normalized_sentences: Sequence[str],
    *,
    max_chars: int = DEFAULT_SVO_CHUNK_SIZE,
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> list[SVOChunk]:
    """依標準化句子聚合 SVO chunk，並保存對應原句範圍。

    依序聚合句子，`max_sentences` 句或 `max_chars` 字元（以標準化後文字計算），
    先到者為準。單句超過 `max_chars` 上限時仍獨立成一個 chunk，不硬切句子。
    預設不做重疊，避免同一事實被重複抽取；若研究實驗需要，可明確傳入
    `overlap_sentences`。
    """
    originals = [s.strip() for s in original_sentences if s.strip()]
    normalized = [s.strip() for s in normalized_sentences if s.strip()]

    if len(originals) != len(normalized):
        raise ValueError("原句與標準化句數量必須一致，才能建立句子層追溯索引")
    if max_chars <= 0:
        raise ValueError("max_chars 必須大於 0")
    if max_sentences <= 0:
        raise ValueError("max_sentences 必須大於 0")
    if overlap_sentences < 0:
        raise ValueError("overlap_sentences 不可為負數")
    if not normalized:
        return []

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(normalized):
        end = start
        current_len = 0

        while end < len(normalized):
            sentence_len = len(normalized[end])
            separator_len = 1 if end > start else 0
            would_exceed_chars = current_len + separator_len + sentence_len > max_chars
            would_exceed_sentences = (end - start) >= max_sentences
            if (would_exceed_chars or would_exceed_sentences) and end > start:
                break

            current_len += separator_len + sentence_len
            end += 1

            if sentence_len >= max_chars:
                break
            if (end - start) >= max_sentences:
                break

        ranges.append((start, end))
        next_start = end - overlap_sentences
        start = max(next_start, start + 1)

    digits = max(3, len(str(len(ranges))))
    chunks: list[SVOChunk] = []
    total = len(ranges)
    for idx, (start_idx, end_idx) in enumerate(ranges, start=1):
        filename = f"{SVO_CHUNK_PREFIX}-{idx:0{digits}d}-of-{total:0{digits}d}.md"
        normalized_slice = normalized[start_idx:end_idx]
        original_slice = originals[start_idx:end_idx]
        chunks.append(SVOChunk(
            index=idx,
            total_chunks=total,
            source_sentence_start=start_idx + 1,
            source_sentence_end=end_idx,
            text="\n".join(normalized_slice),
            original_sentences=original_slice,
            normalized_sentences=normalized_slice,
            filename=filename,
        ))
    return chunks


def build_svo_chunks_from_text(
    original_text: str,
    normalized_text: str,
    *,
    max_chars: int = DEFAULT_SVO_CHUNK_SIZE,
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> list[SVOChunk]:
    return build_svo_chunks(
        split_and_clean_sentences(original_text),
        split_and_clean_sentences(normalized_text),
        max_chars=max_chars,
        max_sentences=max_sentences,
        overlap_sentences=overlap_sentences,
    )


def _yaml_frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def write_svo_chunks(
    chunks: Sequence[SVOChunk],
    source: str,
    output_dir: str | Path,
) -> list[Path]:
    """將 SVO chunk 與 `svo_index.json` 寫入來源文件資料夾。"""
    if not chunks:
        return []

    doc_folder = document_folder_path(source, output_dir)
    doc_folder.mkdir(parents=True, exist_ok=True)

    for stale_file in doc_folder.glob(f"{SVO_CHUNK_PREFIX}-*-of-*.md"):
        try:
            stale_file.unlink()
        except OSError:
            continue

    paths: list[Path] = []
    for chunk in chunks:
        frontmatter = _yaml_frontmatter({
            "source": source,
            "svo_chunk_index": chunk.index,
            "total_svo_chunks": chunk.total_chunks,
            "source_sentence_start": chunk.source_sentence_start,
            "source_sentence_end": chunk.source_sentence_end,
        })
        path = doc_folder / chunk.filename
        path.write_text(f"{frontmatter}\n\n{chunk.text}\n", encoding="utf-8")
        paths.append(path)

    index = {
        "source": source,
        "total_svo_chunks": chunks[0].total_chunks,
        "chunks": [asdict(chunk) for chunk in chunks],
    }
    (doc_folder / SVO_INDEX_FILENAME).write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths


def read_svo_index(doc_folder: str | Path) -> dict | None:
    path = Path(doc_folder) / SVO_INDEX_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_svo_chunks(
    original_text: str,
    normalized_text: str,
    source: str,
    output_dir: str | Path,
    *,
    max_chars: int = DEFAULT_SVO_CHUNK_SIZE,
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> tuple[list[Path], list[SVOChunk]]:
    """從原文/標準化全文建立 SVO chunks 並落地。"""
    chunks = build_svo_chunks_from_text(
        original_text,
        normalized_text,
        max_chars=max_chars,
        max_sentences=max_sentences,
        overlap_sentences=overlap_sentences,
    )
    paths = write_svo_chunks(chunks, source, output_dir)
    return paths, chunks
