"""SVO 專用切塊與原句/標準化句索引。

這個模組承接指代消解/標準化前處理的輸出，但不負責呼叫 LLM 做標準化。
輸入必須維持「一個原句對一個標準化句」；若標準化步驟合併或拆分句子，
這裡會直接拒絕，避免後續三元組無法追溯回 original.md 的句子範圍。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

from parser.chunk_writer import document_folder_path
from parser.core import split_into_sentences

SVO_INDEX_FILENAME = "svo_index.json"
SVO_CHUNK_PREFIX = "svo-chunk"
# 只用句數控制切塊大小（2026-07-22 使用者決策：拿掉原本的 300 字元上限，
# 因為字元上限沒有直接文獻依據，只呼應 GraphRAG 附錄的方向性發現，改用
# 純句數＋重疊句數這組有明確幾何論證的參數）。
DEFAULT_SVO_CHUNK_MAX_SENTENCES = 5
# 起始點公差 3、每塊最多 5 句（重疊 2 句）：對任一句子，其所屬的（最多兩個）
# chunk 聯集必為包含前 2 句與後 2 句——句子在塊內偏移量 0/1/3/4（邊界位置）
# 時，靠相鄰塊補齊；偏移量 2（塊正中央）時單一塊本身就已滿足，不需要第二個
# 框（見 docs/論文/03_變更紀錄.md 2026-07-22 條目的逐位置驗算）。此重疊只解決
# 「事實跨塊邊界被切斷」的問題；重疊造成的重複抽取由 svo_service.py 的
# 事實層級去重（相同 subject/rel_type/object 收斂成一條邊、來源改用累積式
# 引用清單）吸收，不會再產生重複邊。
DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES = 2


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
    # 法條感知切塊（ArticleAwareChunking）填入來源條號，供 Fact 追溯回
    # 「哪一份法規的哪一條」（見 LawArticle 節點設計）；SVOGROUP（固定句數
    # 聚合）產生的 chunk 橫跨任意句子範圍、不對應單一條文，維持 None。
    article_no: str | None = None


def split_and_clean_sentences(text: str) -> list[str]:
    """共用分句器的 SVO 前處理包裝：strip 並過濾空句。"""
    return [sentence.strip() for sentence in split_into_sentences(text) if sentence.strip()]


def build_svo_chunks(
    original_sentences: Sequence[str],
    normalized_sentences: Sequence[str],
    *,
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> list[SVOChunk]:
    """依標準化句子聚合 SVO chunk，並保存對應原句範圍。

    每塊固定最多 `max_sentences` 句；相鄰塊重疊 `overlap_sentences` 句
    （起始點以 `max_sentences - overlap_sentences` 為公差遞增，預設值對應
    1-5、4-8、7-11 這組序列）。最後一塊觸底（涵蓋到最後一句）後即停止，
    不會再產生更短的尾端重複塊。
    """
    originals = [s.strip() for s in original_sentences if s.strip()]
    normalized = [s.strip() for s in normalized_sentences if s.strip()]

    if len(originals) != len(normalized):
        raise ValueError("原句與標準化句數量必須一致，才能建立句子層追溯索引")
    if max_sentences <= 0:
        raise ValueError("max_sentences 必須大於 0")
    if overlap_sentences < 0:
        raise ValueError("overlap_sentences 不可為負數")
    if overlap_sentences >= max_sentences:
        raise ValueError("overlap_sentences 必須小於 max_sentences")
    if not normalized:
        return []

    total_sentences = len(normalized)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_sentences:
        end = min(start + max_sentences, total_sentences)
        ranges.append((start, end))
        if end >= total_sentences:
            break
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
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> list[SVOChunk]:
    return build_svo_chunks(
        split_and_clean_sentences(original_text),
        split_and_clean_sentences(normalized_text),
        max_sentences=max_sentences,
        overlap_sentences=overlap_sentences,
    )


# 法規全文本身以「（刪除）」／「(刪除)」標記已刪除但保留編號的條文（見
# labor-compliance-collector 資料集實測案例：D0070148 建築物室內裝修管理辦法
# 第 21 條）——內容非空但無任何可供 SVO 抽取的實質語意，逐條切塊時會產生
# 一整個「對『（刪除）』抽取事實」的無意義 LLM 呼叫，故在切塊階段先行濾除，
# 不留給下游抽取管線處理。
_DELETED_ARTICLE_MARKERS = frozenset({"（刪除）", "(刪除)", "刪除"})


def _is_deleted_article_placeholder(content: str) -> bool:
    stripped = content.strip()
    return stripped in _DELETED_ARTICLE_MARKERS


def build_article_aware_chunks(
    articles: Sequence[Mapping[str, str]],
    *,
    article_no_key: str = "ArticleNo",
    article_content_key: str = "ArticleContent",
) -> list[SVOChunk]:
    """法規領域專屬切塊策略：按 `payload.articles` 既有的 `ArticleNo` 邊界切，
    一條對一塊，取代 `SVOGROUP` 的固定句數聚合＋重疊窗。

    對應 `docs/論文/03_系統設計與方法論.md` §3.1.2「法規領域專屬切塊策略與
    『結構化資料優先直接映射』原則」：法規全文本身已經是逐條切好的結構化
    資料，比通用句數聚合更適合作為 SVO 抽取單位，讓 `Fact` 能精確追溯回
    「哪一份法規的哪一條」（見 `article_no` 欄位），而非只能追溯到「第幾個
    5 句聚合塊」。

    與 `build_svo_chunks()`（`SVOGROUP`）的關鍵差異：
    - `source_sentence_start`／`source_sentence_end` 是**該條文內部**的區域
      句子索引（從 1 起算），不是整份文件的全域句子索引——法條之間本來就是
      離散的語意單位，全域句子計數對追溯回原文沒有意義，`article_no` 才是
      正確的追溯鍵。
    - 不套用固定句數上限與相鄰塊重疊窗：`SVOGROUP` 的重疊窗是為了避免通用
      散文的事實描述被切塊邊界攔腰截斷；條文本身就是法規定義好的自我完備
      語意單位，不需要靠相鄰句補前後文。

    ⚠️ **誠實侷限**：`original_sentences`／`normalized_sentences` 目前相同
    （尚未接上代名詞消解）——法規全文本身極少使用代名詞是既有觀察（本專案
    對應 KG 已設定 `pronoun_lexicon_exclude=["其","該"]`，見
    `import_labor_compliance_dataset.py`），先以條文原文直接作為兩者輸入；
    是否需要逐條套用 `pronoun_resolution_service`，留待接入
    `services/svo_preprocessing_service.py::prepare_svo_ready_chunks()` 時
    再決定，本函式本身不呼叫 LLM。

    `ArticleNo` 為空白、內容為空、或內容等同「（刪除）」佔位標記（見
    `_is_deleted_article_placeholder()`）的條目會被濾除，不產生對應 chunk；
    回傳的 `index`／`total_chunks`／`filename` 以濾除後的實際數量重新編號。

    ⚠️ **`ArticleNo` 為空白＝非條文邊界（實測發現）**：`payload.articles` 除了
    `ArticleType: "A"`（實際條文）外，也可能混入 `ArticleType: "C"`（章節標題，
    如「第一章　總則」）——`ArticleNo` 恆為空字串，`ArticleContent` 則是章節
    標題文字，不是可供 SVO 抽取的條文內容（實測案例：`N0030001` 勞動基準法，
    110 個 `payload.articles` 項目中含 12 個章節標題）。以 `ArticleNo` 是否為
    空白判斷比硬編碼 `ArticleType == "A"` 更貼近設計本身宣稱的依據（「按
    `ArticleNo` 邊界切」），且不需要額外假設 `ArticleType` 欄位一定存在。
    """
    kept: list[tuple[str, list[str]]] = []
    for article in articles:
        article_no = (article.get(article_no_key) or "").strip()
        content = (article.get(article_content_key) or "").strip()
        if not article_no or not content or _is_deleted_article_placeholder(content):
            continue
        sentences = split_and_clean_sentences(content)
        if not sentences:
            continue
        kept.append((article_no, sentences))

    total = len(kept)
    if total == 0:
        return []

    digits = max(3, len(str(total)))
    chunks: list[SVOChunk] = []
    for idx, (article_no, sentences) in enumerate(kept, start=1):
        filename = f"{SVO_CHUNK_PREFIX}-{idx:0{digits}d}-of-{total:0{digits}d}.md"
        chunks.append(SVOChunk(
            index=idx,
            total_chunks=total,
            source_sentence_start=1,
            source_sentence_end=len(sentences),
            text="\n".join(sentences),
            original_sentences=sentences,
            normalized_sentences=sentences,
            filename=filename,
            article_no=article_no or None,
        ))
    return chunks


class ChunkingStrategy(Protocol):
    """SVO 切塊策略介面（策略模式，比照 `pronoun_resolution_service.PosTagger`
    的 Protocol 注入模式）。不同實作在建構時各自持有所需輸入（扁平句子清單、
    或條文清單），`build_chunks()` 呼叫時不需額外參數，統一回傳
    `list[SVOChunk]`——下游 SVO 抽取／`Fact` 建立只認 `SVOChunk` 既有契約
    （`text`／`source_doc_id`／`chunk_index`），不需要知道切塊策略本身。"""

    def build_chunks(self) -> list[SVOChunk]:
        ...


@dataclass
class FixedSentenceGroupChunking:
    """`SVOGROUP`：現行固定句數聚合＋重疊窗策略（通用預設），包裝既有
    `build_svo_chunks()`，行為完全不變。"""

    original_sentences: Sequence[str]
    normalized_sentences: Sequence[str]
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES

    def build_chunks(self) -> list[SVOChunk]:
        return build_svo_chunks(
            self.original_sentences,
            self.normalized_sentences,
            max_sentences=self.max_sentences,
            overlap_sentences=self.overlap_sentences,
        )


@dataclass
class ArticleAwareChunking:
    """法條感知切塊：法規領域專屬替代實作，包裝 `build_article_aware_chunks()`。"""

    articles: Sequence[Mapping[str, str]]
    article_no_key: str = "ArticleNo"
    article_content_key: str = "ArticleContent"

    def build_chunks(self) -> list[SVOChunk]:
        return build_article_aware_chunks(
            self.articles,
            article_no_key=self.article_no_key,
            article_content_key=self.article_content_key,
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
        frontmatter_fields = {
            "source": source,
            "svo_chunk_index": chunk.index,
            "total_svo_chunks": chunk.total_chunks,
            "source_sentence_start": chunk.source_sentence_start,
            "source_sentence_end": chunk.source_sentence_end,
        }
        if chunk.article_no:
            frontmatter_fields["article_no"] = chunk.article_no
        frontmatter = _yaml_frontmatter(frontmatter_fields)
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
    max_sentences: int = DEFAULT_SVO_CHUNK_MAX_SENTENCES,
    overlap_sentences: int = DEFAULT_SVO_CHUNK_OVERLAP_SENTENCES,
) -> tuple[list[Path], list[SVOChunk]]:
    """從原文/標準化全文建立 SVO chunks 並落地。"""
    chunks = build_svo_chunks_from_text(
        original_text,
        normalized_text,
        max_sentences=max_sentences,
        overlap_sentences=overlap_sentences,
    )
    paths = write_svo_chunks(chunks, source, output_dir)
    return paths, chunks
