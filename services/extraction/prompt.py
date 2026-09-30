"""N4 的提示詞、實體／關係型別詞彙與 LLM 輸出解析（報告160 U1 自 ``services.svo_service`` 搬入，行為不變）。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from core.constants import ENTITY_TYPES, SVO_REL_TYPES, SVO_REL_TYPE_DESCRIPTIONS
from core.kg_config import KGConfig, RelTypeExtension
from core.kg_config.model import _DEFAULT_SVO_FEWSHOTS

def _strip_json_fence(raw: str) -> str:
    cleaned = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return fence.group(1).strip() if fence else cleaned


def _parse_triples_payload(raw: str) -> list[dict]:
    payload = json.loads(_strip_json_fence(raw))
    if isinstance(payload, dict):
        payload = payload.get("triples", [])
    if not isinstance(payload, list):
        raise ValueError("SVO 抽取結果必須是 JSON list 或含 triples 的 object")
    return [item for item in payload if isinstance(item, dict)]


# 實體型別參考清單——由 core.constants.ENTITY_TYPES（schema.org 實測最常見類型，
# 見該常數 docstring 的文獻依據）動態組出，避免與該常數重複維護兩份清單。僅供 LLM
# 判斷參考，不強制驗證——subject_type/object_type 選填、可多值（見 3.1.4），清單中
# 找不到合適選項時可自訂名稱，或留空字串代表無法判斷。
_ENTITY_TYPE_GUIDE = "、".join(f"{tag}（{desc}）" for tag, desc in ENTITY_TYPES.items())

# 實體型別擴充庫（schema.org 官方完整清單，939 類）的讀取/比對邏輯——核心庫
# （ENTITY_TYPES，52 類）優先比對，查不到才查這裡；兩者皆查無對應時保留 LLM
# 原始輸出，不拋出例外、不拒絕，對應 3.1.4「實體型別選填、不做強制驗證」定案。
def _locate_data_dir() -> Path:
    """以不依賴目錄深度的方式定位 ``data/``（報告160 U1：原寫法 ``parent.parent`` 在搬深一層後會靜默指向錯誤位置）。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "schema_org_entity_types.json").is_file():
            return parent / "data"
    return here.parents[2] / "data"


_EXTENDED_ENTITY_TYPES_PATH = _locate_data_dir() / "schema_org_entity_types.json"


def _normalize_type_key(value: str) -> str:
    """把型別字串正規化成不分大小寫、不分空白/底線/駝峰的比對 key，
    讓「Local Business」「local_business」「LOCAL_BUSINESS」都能對到同一個候選。"""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


_CORE_TYPE_LOOKUP: dict[str, str] = {_normalize_type_key(key): key for key in ENTITY_TYPES}


@lru_cache(maxsize=1)
def _load_extended_entity_type_lookup() -> dict[str, str]:
    """讀取 data/schema_org_entity_types.json，回傳 {正規化 key: schema.org 官方
    CamelCase id} 供核心庫查不到時查閱。讀取失敗（檔案缺失/格式錯誤）時回傳空
    dict，讓呼叫端安全退回保留原始字串，不影響抽取流程本身。"""
    try:
        with open(_EXTENDED_ENTITY_TYPES_PATH, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {_normalize_type_key(t["label"]): t["id"] for t in payload.get("types", [])}


def resolve_entity_type(raw_type: str) -> str:
    """正規化 LLM 抽取出的 subject_type／object_type：核心庫（52 類）優先比對，
    查不到才查擴充庫（939 類）；可多值（逗號分隔，見 3.1.3 § LLM_SVO 節點），
    逐一正規化後以逗號重組；兩者皆查無對應的 token 保留原始字串——選填、不強制
    驗證，任何一步查無結果都不拋出例外或拒絕整條三元組。"""
    if not raw_type or not raw_type.strip():
        return raw_type

    extended_lookup = _load_extended_entity_type_lookup()
    resolved_tokens = []
    for token in raw_type.split(","):
        token = token.strip()
        if not token:
            continue
        key = _normalize_type_key(token)
        if key in _CORE_TYPE_LOOKUP:
            resolved_tokens.append(_CORE_TYPE_LOOKUP[key])
        elif key in extended_lookup:
            resolved_tokens.append(extended_lookup[key])
        else:
            resolved_tokens.append(token)
    return ",".join(resolved_tokens)


def _effective_rel_types(cfg: KGConfig) -> frozenset[str]:
    return frozenset(SVO_REL_TYPES) | {
        extension.name for extension in cfg.domain.rel_type_extensions
    }


def _effective_rel_type_descriptions(cfg: KGConfig) -> dict[str, str]:
    descriptions = dict(SVO_REL_TYPE_DESCRIPTIONS)
    descriptions.update({
        extension.name: extension.description
        for extension in cfg.domain.rel_type_extensions
    })
    return descriptions


def _svo_prompt(
    text: str,
    *,
    fewshots: Sequence[str] | None = None,
    rel_type_extensions: Sequence[RelTypeExtension] | None = None,
) -> str:
    rel_types = set(SVO_REL_TYPES)
    if rel_type_extensions is not None:
        rel_types.update(extension.name for extension in rel_type_extensions)
    rel_types_text = ", ".join(sorted(rel_types))
    selected_fewshots = _DEFAULT_SVO_FEWSHOTS if fewshots is None else fewshots
    fewshot_items = [
        f"{6 + index}. {example}" for index, example in enumerate(selected_fewshots)
    ]
    # 規則 6 在 35f95ab 的既有 prompt 中直接接在規則 5 後，規則 7–10
    # 之間則保留空行；保留這個微小的分隔差異才能讓 shipped default 逐字相容。
    fewshot_block = "\n\n".join(fewshot_items[1:])
    if fewshot_items:
        if fewshot_block:
            first_separator = f"\n{fewshot_items[1]}"
            remaining = "".join(f"\n\n{item}" for item in fewshot_items[2:])
            fewshot_block = fewshot_items[0] + first_separator + remaining
        else:
            fewshot_block = fewshot_items[0]
    return f"""你是知識圖譜 SVO 抽取器。
請只輸出 JSON，不要輸出解釋。從文本抽取符合受控關係詞彙的三元組。

合法 rel_type：
{rel_types_text}

實體型別參考清單（非強制，僅供判斷參考）：
{_ENTITY_TYPE_GUIDE}

輸出格式：
{{"triples":[{{"subject":"", "subject_type":"", "rel_type":"RELATED_TO", "verb":"", "object":"", "object_type":"", "confidence":1}}]}}

規則：
1. rel_type 必須完全等於合法清單中的一個值。
2. verb 保留原文中的自然語言關係描述。
3. confidence 使用 1 到 5 的整數。
4. subject_type／object_type 優先從參考清單挑選最貼切的一個；同時符合多個時用逗號分隔（如「PERSON,PRODUCT」）；清單中無合適選項時可自訂名稱，或留空字串代表無法判斷；不強制驗證。
5. 沒有可判定三元組時輸出 {{"triples":[]}}。
{fewshot_block}

文本：
{text}
"""
