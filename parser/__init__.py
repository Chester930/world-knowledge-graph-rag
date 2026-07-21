"""parser 套件：多格式文件/URL 解析、圖片處理管線、切塊落地存檔。

使用方式與 Behavior Tree 見 parser/README.md。本檔案只重新匯出對外公開介面，
內部實作細節（各 _parse_* 方法、_safe_filename_stem 等底線開頭的私有函式）
不在此匯出，需要時請直接從對應子模組匯入。

刻意改為一般套件（而非隱式命名空間套件）：避免未來 sys.path 上若出現同名的
`parser` 目錄時被 Python 靜默合併命名空間，讓匯入行為維持明確可預期。
"""
from .core import (
    DocumentParser,
    DocumentParserError,
    URLParser,
    sentence_aware_chunking,
    split_into_sentences,
)
from .chunk_writer import document_folder_path, write_chunks_as_markdown
from .image_pipeline import (
    ImagePipeline,
    ImagePipelineConfig,
    ImageProcessResult,
    emu_to_px,
    points_to_px,
)

__all__ = [
    "DocumentParser",
    "DocumentParserError",
    "URLParser",
    "sentence_aware_chunking",
    "split_into_sentences",
    "document_folder_path",
    "write_chunks_as_markdown",
    "ImagePipeline",
    "ImagePipelineConfig",
    "ImageProcessResult",
    "emu_to_px",
    "points_to_px",
]
