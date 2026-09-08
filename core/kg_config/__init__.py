"""每知識圖譜設定（`KGConfig`）—— 報告33 §3.9 / 論文 03 §3.9、04 §4.10 落地第 1 步。

**現況（2026-09-08）**：純新增、無接線。管線程式碼仍讀 `core/constants.py`、
`routers/agent.py`、`services/svo_service.py` 的模組常數；本套件只提供資料結構與
載入機制，尚未被任何呼叫端使用（第 2 步才把查詢端 θ 家族改為讀 `KGConfig`）。

**行為零變化不變式**：`ConfigLoader().load()`（不給任何 `ConfigSource`）產出的
`KGConfig`，逐欄位等於重構前的模組常數值——由 `tests/core/test_kg_config.py` 的
golden test 機械化把關。

四層疊合（低→高）：shipped defaults（本套件 `Field` 預設）→ domain pack → per-KG
profile → per-request override。前三層由 `ConfigSource` 提供，`ConfigLoader`
deep-merge 後建構出**深度不可變**的 `KGConfig`（pydantic frozen model，巢狀亦
frozen）。
"""
from core.kg_config.loader import (
    CONFIG_SCHEMA_VERSION,
    MIN_CONFIG_SCHEMA_VERSION,
    ConfigLoader,
    ConfigSchemaVersionError,
    deep_merge,
)
from core.kg_config.model import (
    BfsConfig,
    DecomposeConfig,
    DedupConfig,
    DomainConfig,
    ExtractionConfig,
    FactListConfig,
    KGConfig,
    RelTypeConfig,
    RoutingConfig,
)
from core.kg_config.sources import ConfigSource, DictConfigSource, FileConfigSource
from core.kg_config.stages import (
    STAGE_REGISTRY,
    Blocker,
    Gate,
    Harness,
    Metric,
    Stage,
    sections_covered,
    stages_for_section,
    stages_without_harness,
    unblocked_stages,
)

__all__ = [
    "KGConfig",
    "BfsConfig",
    "FactListConfig",
    "DecomposeConfig",
    "DedupConfig",
    "RelTypeConfig",
    "ExtractionConfig",
    "RoutingConfig",
    "DomainConfig",
    "ConfigLoader",
    "ConfigSchemaVersionError",
    "CONFIG_SCHEMA_VERSION",
    "MIN_CONFIG_SCHEMA_VERSION",
    "deep_merge",
    "ConfigSource",
    "DictConfigSource",
    "FileConfigSource",
    "STAGE_REGISTRY",
    "Stage",
    "Metric",
    "Gate",
    "Blocker",
    "Harness",
    "sections_covered",
    "stages_for_section",
    "unblocked_stages",
    "stages_without_harness",
]
