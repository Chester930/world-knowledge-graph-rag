"""`ConfigSource` —— 抽象「設定參數從哪來」，管線只碰解析後的 `KGConfig`。

報告33 §3.9.3：使用者不被綁定於單一檔案或單一格式。身份類參數（domain pack 名）
可放一個來源、調校類放另一個，`ConfigLoader` 合併。

第 1 步提供 `DictConfigSource`（測試注入）與 `FileConfigSource`（副檔名分派：
`.json`／`.toml` 為 stdlib，`.yaml` 為選配依賴）。`Neo4jNodeConfigSource`／
`SqliteConfigSource`／`CompositeConfigSource` 於後續步驟按需新增——只要符合
`ConfigSource` 協定即可插入 `ConfigLoader`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

try:  # py3.11+
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover
    _tomllib = None


@runtime_checkable
class ConfigSource(Protocol):
    """一個設定來源。兩個方法都回傳**部分**覆蓋值（plain mapping，可為空）。"""

    def get_domain_pack(self, name: str) -> Mapping[str, Any]:
        """回傳名為 `name` 的 domain pack 覆蓋值；查無回傳 `{}`。"""
        ...

    def get_kg_overrides(self, kg_id: str | None) -> Mapping[str, Any]:
        """回傳 `kg_id` 的 per-KG profile 覆蓋值；`kg_id` 為 None 或查無回傳 `{}`。"""
        ...


class DictConfigSource:
    """記憶體來源——測試注入用，不碰檔案系統。

    `packs`：`{pack_name: overrides}`；`kg_overrides`：`{kg_id: overrides}`。
    """

    def __init__(
        self,
        *,
        packs: Mapping[str, Mapping[str, Any]] | None = None,
        kg_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._packs = dict(packs or {})
        self._kg = dict(kg_overrides or {})

    def get_domain_pack(self, name: str) -> Mapping[str, Any]:
        return dict(self._packs.get(name, {}))

    def get_kg_overrides(self, kg_id: str | None) -> Mapping[str, Any]:
        if kg_id is None:
            return {}
        return dict(self._kg.get(str(kg_id), {}))


_PARSERS: dict[str, Any] = {".json": json.loads}
if _tomllib is not None:
    _PARSERS[".toml"] = lambda text: _tomllib.loads(text)
try:  # 選配
    import yaml as _yaml  # type: ignore

    _PARSERS[".yaml"] = _yaml.safe_load
    _PARSERS[".yml"] = _yaml.safe_load
except ModuleNotFoundError:  # pragma: no cover
    pass


class FileConfigSource:
    """檔案來源。目錄佈局：

        <root>/domain_packs/<name>.<ext>
        <root>/kg/<kg_id>.<ext>

    `<ext>` 由 `_PARSERS` 分派（`.json` 一定有；`.toml` 見 Python 版本；`.yaml`
    需另裝 PyYAML）。同名多副檔名時取 `_PARSERS` 的登記順序第一個存在者。
    檔案不存在 → `{}`（相容尚未建立 profile 的知識圖譜）。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _read(self, base: Path) -> Mapping[str, Any]:
        for ext, parse in _PARSERS.items():
            path = base.with_suffix(ext)
            if path.is_file():
                data = parse(path.read_text(encoding="utf-8"))
                if data is None:
                    return {}
                if not isinstance(data, Mapping):
                    raise ValueError(f"{path} 頂層必須是 mapping，得到 {type(data).__name__}")
                return data
        return {}

    def get_domain_pack(self, name: str) -> Mapping[str, Any]:
        return self._read(self._root / "domain_packs" / name)

    def get_kg_overrides(self, kg_id: str | None) -> Mapping[str, Any]:
        if kg_id is None:
            return {}
        return self._read(self._root / "kg" / str(kg_id))
