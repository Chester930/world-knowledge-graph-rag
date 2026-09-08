"""`ConfigLoader` —— 四層 deep-merge → 建構深度不可變的 `KGConfig`。

疊合順序（低→高）：
    shipped defaults（`KGConfig()` 的 Field 預設）
      → domain pack（每個 `ConfigSource.get_domain_pack(name)`）
      → per-KG profile（每個 `ConfigSource.get_kg_overrides(kg_id)`）
      → per-request override（`load(..., request_overrides=)`）

**合併語意（報告33 §3.9.3 要求釘死；論文 05 §5.3.6「合併語意 test」把關）**：
- 兩邊都是 mapping → 遞迴合併。
- 其餘型別（含 list）→ overlay 值**整個取代** base 值，不做位置式合併。
- overlay 內出現某鍵（即使值為 `None`）→ 視為明確覆蓋，寫入該值。
- overlay 內**沒有**某鍵 → 保留 base。
- 多個 `ConfigSource` 在同一層 → 依 `sources` 順序後者覆蓋前者。
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Sequence
from uuid import UUID

from core.kg_config.model import KGConfig
from core.kg_config.sources import ConfigSource


def deep_merge(base: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """把 `overlay` 就地合併進 `base`（見模組 docstring 的語意）。回傳 `base`。

    以 `_` 開頭的鍵視為註解（JSON 無原生註解），任何層級都略過——設定檔可用
    `"_note": "..."` 自我說明而不觸發 `KGConfig` 的 `extra="forbid"`。
    """
    for key, val in overlay.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        if (
            key in base
            and isinstance(base[key], MutableMapping)
            and isinstance(val, Mapping)
        ):
            deep_merge(base[key], val)
        else:
            base[key] = copy.deepcopy(val)
    return base


class ConfigLoader:
    """建構 `KGConfig`。無 `ConfigSource` 時，`load()` 直接回傳 shipped defaults。"""

    def __init__(self, sources: Sequence[ConfigSource] = ()) -> None:
        self._sources: tuple[ConfigSource, ...] = tuple(sources)

    def load(
        self,
        kg_id: str | UUID | None = None,
        *,
        domain_pack: str | None = None,
        request_overrides: Mapping[str, Any] | None = None,
    ) -> KGConfig:
        """`domain_pack=None`（預設）→ **不載入任何 domain pack**，直接用 shipped
        defaults（＝重構前的模組常數／prompt）。指定名稱才疊該 pack。此預設保證
        「不明確指定 → 行為零變化」，`generic` pack 只在明確載入時才把
        `system_context` 換成中性版（論文 §2.6.8）。"""
        merged: dict[str, Any] = KGConfig().model_dump()

        if domain_pack is not None:
            for src in self._sources:
                deep_merge(merged, src.get_domain_pack(domain_pack))

        kg_key = None if kg_id is None else str(kg_id)
        for src in self._sources:
            deep_merge(merged, src.get_kg_overrides(kg_key))

        if request_overrides:
            deep_merge(merged, request_overrides)

        return KGConfig.model_validate(merged)
