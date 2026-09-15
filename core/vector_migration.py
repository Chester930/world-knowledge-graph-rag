"""BGE-M3 向量維度遷移與舊快取清理工具。

SDD-52 的破壞性變更集中在這裡：Neo4j 向量索引不會因為
``CREATE ... IF NOT EXISTS`` 自動更新 dimensions，因此建立前必須檢查既有
索引；本機 baseline/prototype 快取則只清理已知命名格式，避免誤刪一般使用者檔案。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable

import numpy as np

from core.constants import VECTOR_DIM

logger = logging.getLogger(__name__)

_VECTOR_DIMENSION_KEY = "vector.dimensions"
_BASELINE_NPY_PREFIX = "baseline_rag_index_"
_BASELINE_NPY_SUFFIX = ".npy"
_SAFE_INDEX_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _index_dimension(options: object) -> int | None:
    """從 Neo4j ``SHOW VECTOR INDEXES`` 的 options 形狀取 dimensions。"""
    if not isinstance(options, dict):
        return None
    config = options.get("indexConfig", options)
    if not isinstance(config, dict):
        return None
    value = config.get(_VECTOR_DIMENSION_KEY)
    return int(value) if isinstance(value, (int, float)) else None


async def ensure_vector_index(
    driver,
    *,
    index_name: str,
    create_query: str,
    dim: int = VECTOR_DIM,
    legacy_index_names: Iterable[str] = (),
) -> None:
    """確保向量索引使用指定維度，必要時刪除後重建。

    ``index_name`` 與 ``legacy_index_names`` 皆為程式內常數，不接受外部輸入，
    因此可安全嵌入 Neo4j 的 ``DROP INDEX`` 識別碼位置（Neo4j 不允許參數化
    index name）。若資料庫中仍有舊命名索引，也會一併清除。
    """
    if dim < 1:
        raise ValueError("向量維度必須為正整數")

    names = [index_name, *legacy_index_names]
    result = await driver.execute_query(
        "SHOW VECTOR INDEXES YIELD name, options "
        "WHERE name IN $index_names RETURN name, options",
        index_names=names,
    )
    existing = {
        record["name"]: record
        for record in result.records
        if record.get("name") in names
    }

    for legacy_name in legacy_index_names:
        if legacy_name in existing:
            await driver.execute_query(f"DROP INDEX {legacy_name} IF EXISTS")

    canonical = existing.get(index_name)
    canonical_dim = _index_dimension(canonical.get("options")) if canonical else None
    if canonical is not None and canonical_dim == dim:
        return

    if canonical is not None:
        await driver.execute_query(f"DROP INDEX {index_name} IF EXISTS")
    await driver.execute_query(create_query, dim=dim)


async def migrate_vector_indexes(
    driver,
    *,
    dim: int = VECTOR_DIM,
    obsolete_index_names: Iterable[str] = (),
) -> list[str]:
    """刪除所有維度不符的既有向量索引，回傳被刪除的索引名稱。

    建立函式各自使用 ``IF NOT EXISTS``，它不會修改既有索引的 dimensions；
    因此應在應用啟動、各索引建立前呼叫本函式。刪除後由原有的各索引建立
    函式以目前 provider 維度重建。``obsolete_index_names`` 用於清除已退役
    的舊命名（例如 SDD-52 的 ``concept_embedding_idx``）。
    """
    if dim < 1:
        raise ValueError("向量維度必須為正整數")
    obsolete = set(obsolete_index_names)
    result = await driver.execute_query(
        "SHOW VECTOR INDEXES YIELD name, options RETURN name, options"
    )
    removed: list[str] = []
    for record in result.records:
        name = record.get("name")
        if not isinstance(name, str) or not _SAFE_INDEX_NAME.fullmatch(name):
            logger.warning("略過格式不安全的 Neo4j 索引名稱：%r", name)
            continue
        current_dim = _index_dimension(record.get("options"))
        if name in obsolete or current_dim != dim:
            await driver.execute_query(f"DROP INDEX {name} IF EXISTS")
            removed.append(name)
    return removed


def _mark_removed(path: Path, removed: list[Path]) -> None:
    try:
        path.unlink()
        removed.append(path)
        logger.warning("移除維度不符的向量快取：%s", path)
    except FileNotFoundError:
        pass


def clear_stale_vector_caches(root: str | Path) -> list[Path]:
    """清理指定根目錄下已知的舊向量快取，回傳實際移除的檔案。

    - ``baseline_rag_index_*.npy``：第二維不是 ``VECTOR_DIM`` 即移除，並同步
      移除同 stem 的 JSON metadata。
    - ``_prototype_cache.json``：prototype 存在且維度不是 ``VECTOR_DIM`` 即移除；
      無 prototype 的空快取保留。

    損毀或無法讀取的已知快取也視為 stale。此函式不會遞迴刪除未知檔案。
    """
    base = Path(root)
    if not base.exists():
        return []

    removed: list[Path] = []
    for npy_path in base.rglob(f"{_BASELINE_NPY_PREFIX}*{_BASELINE_NPY_SUFFIX}"):
        stale = False
        try:
            # 不使用 mmap：Windows 會在 mmap 物件仍存活時鎖住檔案，
            # 使後續 unlink 失敗。清理流程只檢查 shape，直接載入後即可釋放。
            matrix = np.load(npy_path, allow_pickle=False)
            stale = matrix.ndim != 2 or matrix.shape[1] != VECTOR_DIM
        except (OSError, ValueError):
            stale = True
        if stale:
            _mark_removed(npy_path, removed)
            _mark_removed(npy_path.with_suffix(".json"), removed)

    for cache_path in base.rglob("_prototype_cache.json"):
        stale = False
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            prototype = data.get("prototype") if isinstance(data, dict) else None
            stale = prototype is not None and len(prototype) != VECTOR_DIM
        except (OSError, ValueError, TypeError):
            stale = True
        if stale:
            _mark_removed(cache_path, removed)

    return removed
