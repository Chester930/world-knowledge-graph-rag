"""文件內實體別名登記表（Registry）與動態標準名提升機制。

對應 docs/論文/03_系統設計與方法論.md § 3.4 §a（RQ4b）與
docs/報告/09_實體別名登記與動態標準名提升機制設計報告.md。

**範圍限定（重要）**：本模組只負責「單一文件範圍」內的暫定標準名決定——
單一文件內某個別名出現次數多，可能只反映這份文件/這位作者的行文習慣（範圍內
簡稱），不代表這是實體在整個語料庫中被廣泛認可的通用標準名。真正寫入知識圖譜
的 Entity.name 由 services/svo_service.py 的跨文件 surface_form 頻率聚合決定
（見 3.4 §b RECHECK/recompute_canonical_name），本模組的輸出只是「文件內
暫定標準名」，供這份文件自身的後續處理（代名詞消解、SVO 切塊分組）使用。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from core.providers.base import LLMProvider

_REGISTRY_FILENAME = "entity_registry.json"


@dataclass(frozen=True)
class Mention:
    """一次具名提及，由上游（NER/LLM 抽取，不在本模組職責範圍內）提供。"""

    sentence_idx: int
    text: str
    entity_type: str = "概念"


@dataclass
class RegistryEntry:
    entity_type: str
    alias_counts: dict[str, int] = field(default_factory=dict)
    first_seen_idx: int = 0
    occurrences: list[int] = field(default_factory=list)


def should_promote(candidate_count: int, current_count: int, candidate: str, current: str) -> bool:
    """PK 規則（09 報告 § 3.2，2026-07-21 修訂）：出現頻率優先；頻率相同才比
    字面長度；長度也相同則保留既有 Key（回傳 False）。"""
    if candidate_count > current_count:
        return True
    if candidate_count < current_count:
        return False
    return len(candidate) > len(current)


def _normalize(text: str) -> str:
    return text.strip()


def _is_rule_match(mention: str, canonical: str, aliases: dict[str, int]) -> bool:
    """ALIASCHECK 規則式比對：子字串/常見縮寫規則，免呼叫 LLM。

    命中條件（任一即可）：
    - 與標準名或既有別名完全相同
    - 與標準名或既有別名互為子字串（如「Stone」⊂「Richard Stone」）
    - 是標準名/別名各詞首字母組成的縮寫（如「IH」對應「Interstate Highway」）

    無法規則命中、但登記表非空的情況（如「I-35」對「Interstate Highway 35」，
    字面幾乎無重疊），留給呼叫端的 LLM 仲裁（ALIASLLM），不在此函式內判斷。
    """
    if not mention:
        return False
    if mention == canonical or mention in aliases:
        return True
    for candidate in (canonical, *aliases.keys()):
        if mention in candidate or candidate in mention:
            return True
        initials = "".join(word[0] for word in candidate.split() if word)
        if initials and mention.upper() == initials.upper():
            return True
    return False


class EntityRegistry:
    """文件內範圍的別名登記表：維護每個實體的暫定標準名與別名出現頻率。"""

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def canonical_names(self) -> list[str]:
        return list(self._entries.keys())

    def entry(self, canonical: str) -> RegistryEntry | None:
        return self._entries.get(canonical)

    def find_matching_key(self, mention: str) -> str | None:
        """ALIASCHECK：回傳規則式命中的既有標準名 Key，無命中回傳 None。"""
        mention = _normalize(mention)
        if not mention:
            return None
        for key, e in self._entries.items():
            if _is_rule_match(mention, key, e.alias_counts):
                return key
        return None

    async def resolve_mention(
        self,
        sentence_idx: int,
        mention: str,
        entity_type: str = "概念",
        llm_provider: LLMProvider | None = None,
    ) -> str:
        """處理一次具名提及，回傳目前應該替換成的文件內暫定標準名。

        對應 3.4 §a Behavior Tree：ALIASCHECK → (ALIASRULE|ALIASLLM|NEWENT)
        → PROMOTE（出現次數 +1 後與現有 Key 比較，頻率優先，長度次規則）→ REPLACE。
        """
        mention = _normalize(mention)
        if not mention:
            raise ValueError("mention 不可為空字串")

        key = self.find_matching_key(mention)
        if key is None and llm_provider is not None and self._entries:
            key = await self._ask_llm(mention, llm_provider)

        if key is None or key not in self._entries:
            # NEWENT：視為新實體，以此提及作為初始標準名加入登記表
            self._entries[mention] = RegistryEntry(
                entity_type=entity_type,
                alias_counts={mention: 1},
                first_seen_idx=sentence_idx,
                occurrences=[sentence_idx],
            )
            return mention

        entry = self._entries[key]
        entry.occurrences.append(sentence_idx)
        entry.alias_counts[mention] = entry.alias_counts.get(mention, 0) + 1

        if mention == key:
            return key

        candidate_count = entry.alias_counts[mention]
        current_count = entry.alias_counts.get(key, 0)
        if should_promote(candidate_count, current_count, mention, key):
            # PROMOTE：主 Key 升級為此別名，舊 Key 已在 alias_counts 內、自動降級收錄
            del self._entries[key]
            self._entries[mention] = entry
            return mention

        return key

    async def _ask_llm(self, mention: str, llm_provider: LLMProvider) -> str | None:
        """ALIASLLM：LLM 比對整份登記表，判斷提及對應哪個既有實體，或是新實體。"""
        keys = self.canonical_names()
        prompt = (
            "以下是目前文件內已登記的實體標準名清單：\n"
            + "\n".join(f"- {k}" for k in keys)
            + f"\n\n新提及「{mention}」是否對應清單中的某一個實體？"
              "若是，只回傳該標準名（與清單中的文字完全一致）；"
              "若是新實體或無法判斷，只回傳 NEW，不要有其他文字。"
        )
        response = (await llm_provider.generate(prompt)).strip()
        return response if response in self._entries else None

    def snapshot(self) -> dict:
        """匯出可 JSON 序列化的狀態，供斷點續傳持久化（見 write_registry_snapshot）。"""
        return {
            key: {
                "entity_type": e.entity_type,
                "alias_counts": dict(e.alias_counts),
                "first_seen_idx": e.first_seen_idx,
                "occurrences": list(e.occurrences),
            }
            for key, e in self._entries.items()
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> "EntityRegistry":
        registry = cls()
        for key, payload in data.items():
            registry._entries[key] = RegistryEntry(
                entity_type=payload["entity_type"],
                alias_counts=dict(payload.get("alias_counts", {})),
                first_seen_idx=payload.get("first_seen_idx", 0),
                occurrences=list(payload.get("occurrences", [])),
            )
        return registry


async def apply_registry(
    sentences: list[str],
    mentions: list[list[Mention]],
    llm_provider: LLMProvider | None = None,
    registry: EntityRegistry | None = None,
    start_idx: int = 0,
) -> tuple[list[str], EntityRegistry]:
    """對句子清單套用文件內別名登記表，回傳（替換後句子清單, 最終登記表）。

    `mentions` 由上游具名提及抽取（NER/LLM，不在本模組職責範圍內）提供，需與
    `sentences` 逐句對應（無提及的句子傳空列表）。支援斷點續傳：傳入既有
    `registry`（見 read_registry_snapshot）與 `start_idx`
    （見 document_record_service 的 normalization_progress）即可從中斷處
    繼續，不需重新處理已完成的句子。
    """
    if len(mentions) != len(sentences):
        raise ValueError("mentions 長度必須與 sentences 一致（逐句對應，可為空列表）")

    registry = registry or EntityRegistry()
    output = list(sentences)
    for idx in range(start_idx, len(sentences)):
        sentence = output[idx]
        for mention in mentions[idx]:
            canonical = await registry.resolve_mention(
                idx, mention.text, mention.entity_type, llm_provider
            )
            if canonical != mention.text:
                sentence = sentence.replace(mention.text, canonical)
        output[idx] = sentence
    return output, registry


# ── 斷點續傳持久化（文件資料夾內 entity_registry.json）─────────────────────────

def _registry_path(folder: Path) -> Path:
    return Path(folder) / _REGISTRY_FILENAME


def write_registry_snapshot(folder: Path, registry: EntityRegistry) -> None:
    """原子寫入登記表快照，供程式中斷後從 normalization_progress 對應的句子
    索引繼續處理，不需整份文件重跑（見 03_系統設計與方法論.md § 3.4 §a）。"""
    path = _registry_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{_REGISTRY_FILENAME}.", suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(registry.snapshot(), f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_registry_snapshot(folder: Path) -> EntityRegistry | None:
    """讀取登記表快照；不存在時回傳 None（代表尚未開始或已從頭處理）。"""
    path = _registry_path(folder)
    if not path.exists():
        return None
    return EntityRegistry.from_snapshot(json.loads(path.read_text(encoding="utf-8")))
