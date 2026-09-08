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

**schema 版本（報告33 §5 R6 緩解 / §6 第 5b 步）**：domain pack 與 per-KG profile
可在頂層宣告 `"schema_version": <int>`。`ConfigLoader` 在合併**前**取出並檢查：
未宣告 → 視為相容（相容所有既有檔）；宣告值 > 本程式支援上限 → 拋
`ConfigSchemaVersionError`（設定檔比程式新，避免無聲吃掉未知語意）；宣告值 <
最低支援 → 同樣拋（設定檔太舊）。取出後不進入 `KGConfig`（不觸發 `extra=forbid`）。
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Sequence
from uuid import UUID

from core.kg_config.model import KGConfig
from core.kg_config.sources import ConfigSource

#: 本程式能理解的設定 schema 版本。破壞相容的結構調整（改鍵名、換巢狀、改語意）
#: 時 +1，並同步 `config/README.md` 的「schema 版本」段與遷移說明。
CONFIG_SCHEMA_VERSION = 1
#: 仍接受的最舊 schema 版本。丟棄舊版支援時才往上調。
MIN_CONFIG_SCHEMA_VERSION = 1

_SCHEMA_VERSION_KEY = "schema_version"


class ConfigSchemaVersionError(ValueError):
    """設定檔宣告的 `schema_version` 落在本程式支援範圍外（報告33 §5 R6）。"""


def _take_schema_version(mapping: Mapping[str, Any], origin: str) -> dict[str, Any]:
    """回傳 `mapping` 去掉 `schema_version` 後的淺拷貝，並順帶檢查版本相容。

    `origin` 只用於錯誤訊息（例如 `domain pack 'generic'`）。
    """
    out = dict(mapping)
    if _SCHEMA_VERSION_KEY not in out:
        return out
    raw = out.pop(_SCHEMA_VERSION_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ConfigSchemaVersionError(
            f"{origin} 的 {_SCHEMA_VERSION_KEY} 必須是整數，得到 {raw!r}"
        )
    if raw > CONFIG_SCHEMA_VERSION:
        raise ConfigSchemaVersionError(
            f"{origin} 需要設定 schema v{raw}，但此版程式只支援到 "
            f"v{CONFIG_SCHEMA_VERSION}；請升級程式，或把設定檔改回相容版本。"
        )
    if raw < MIN_CONFIG_SCHEMA_VERSION:
        raise ConfigSchemaVersionError(
            f"{origin} 的設定 schema v{raw} 已不再支援"
            f"（本程式最低接受 v{MIN_CONFIG_SCHEMA_VERSION}）。"
        )
    return out


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
                raw = src.get_domain_pack(domain_pack)
                deep_merge(merged, _take_schema_version(raw, f"domain pack {domain_pack!r}"))

        kg_key = None if kg_id is None else str(kg_id)
        for src in self._sources:
            raw = src.get_kg_overrides(kg_key)
            deep_merge(merged, _take_schema_version(raw, f"KG profile {kg_key!r}"))

        if request_overrides:
            deep_merge(merged, _take_schema_version(request_overrides, "request_overrides"))

        return KGConfig.model_validate(merged)
