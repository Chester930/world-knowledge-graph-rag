import pytest

from services.entity_registry_service import (
    EntityRegistry,
    Mention,
    apply_registry,
    read_registry_snapshot,
    should_promote_by_frequency,
    should_promote_by_length,
    write_registry_snapshot,
)


class FakeLLM:
    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response

    async def stream(self, prompt: str):
        yield self.response

    async def generate_json(self, prompt: str) -> str:
        return self.response


# ── should_promote_by_length（§a 文件內範圍 PK 規則，2026-07-21 新增）──────

def test_should_promote_by_length_prefers_longer_regardless_of_frequency():
    """長度優先是主規則——即使候選出現次數遠低於現有 Key，較長者仍勝出。"""
    assert should_promote_by_length(
        candidate_count=1, current_count=1000, candidate="Interstate Highway 35", current="I-35"
    ) is True


def test_should_promote_by_length_rejects_shorter_even_if_more_frequent():
    assert should_promote_by_length(
        candidate_count=1000, current_count=1, candidate="I-35", current="Interstate Highway 35"
    ) is False


def test_should_promote_by_length_uses_frequency_as_tiebreak_when_length_equal():
    assert should_promote_by_length(
        candidate_count=3, current_count=1, candidate="Apple LLC.", current="Apple Inc."
    ) is True
    assert should_promote_by_length(
        candidate_count=1, current_count=3, candidate="Apple LLC.", current="Apple Inc."
    ) is False


def test_should_promote_by_length_keeps_current_on_full_tie():
    assert should_promote_by_length(
        candidate_count=1, current_count=1, candidate="Apple LLC.", current="Apple Inc."
    ) is False


# ── should_promote_by_frequency（§b 跨文件範圍 PK 規則，原 should_promote）──

def test_should_promote_by_frequency_prefers_higher_frequency():
    assert should_promote_by_frequency(
        candidate_count=5, current_count=1, candidate="I-35", current="Interstate Highway 35"
    ) is True


def test_should_promote_by_frequency_rejects_lower_frequency_even_if_longer():
    assert should_promote_by_frequency(
        candidate_count=2, current_count=50, candidate="泰國全名", current="泰國"
    ) is False


def test_should_promote_by_frequency_uses_length_as_tiebreak_when_frequency_equal():
    assert should_promote_by_frequency(
        candidate_count=3, current_count=3, candidate="Richard Stone", current="Stone"
    ) is True
    assert should_promote_by_frequency(
        candidate_count=3, current_count=3, candidate="Stone", current="Richard Stone"
    ) is False


def test_should_promote_by_frequency_keeps_current_on_full_tie():
    assert should_promote_by_frequency(
        candidate_count=1, current_count=1, candidate="Apple LLC.", current="Apple Inc."
    ) is False


# ── EntityRegistry.resolve_mention（規則式比對＋長度優先動態提升）──────────

@pytest.mark.asyncio
async def test_new_entity_becomes_initial_canonical_name():
    registry = EntityRegistry()
    canonical = await registry.resolve_mention(0, "Richard Stone", "PERSON")
    assert canonical == "Richard Stone"
    assert registry.entry("Richard Stone").alias_counts == {"Richard Stone": 1}


@pytest.mark.asyncio
async def test_substring_alias_matches_without_llm():
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Richard Stone", "PERSON")
    canonical = await registry.resolve_mention(1, "Stone", "PERSON")
    assert canonical == "Richard Stone"
    assert registry.entry("Richard Stone").alias_counts["Stone"] == 1


@pytest.mark.asyncio
async def test_shorter_alias_never_promoted_regardless_of_frequency():
    """長度優先為主規則（2026-07-21 修訂）：即使「Stone」累計出現次數遠超過
    「Richard Stone」，仍不會被提升為標準名，因為它比較短。"""
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Richard Stone", "PERSON")
    canonical = ""
    for idx in range(1, 20):
        canonical = await registry.resolve_mention(idx, "Stone", "PERSON")

    assert canonical == "Richard Stone"
    entry = registry.entry("Richard Stone")
    assert entry.alias_counts["Stone"] == 19
    assert registry.entry("Stone") is None


@pytest.mark.asyncio
async def test_longer_alias_promoted_even_with_single_occurrence():
    """長度優先為主規則：較長的別名只出現一次，也會立即取代出現多次的
    現有標準名——這是刻意的行為，因為「哪個名稱在整個語料庫中較常見」這類
    跨文件共識問題，改由 §b（跨文件範圍，見 services/svo_service.py）處理，
    不是本模組（§a，單一文件範圍）的責任；單一文件內偏好取用最完整的稱呼，
    避免下游代名詞消解的實體接力上下文變得不夠清楚。"""
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Stone", "PERSON")
    for idx in range(1, 20):
        await registry.resolve_mention(idx, "Stone", "PERSON")

    canonical = await registry.resolve_mention(20, "Richard Stone", "PERSON")

    assert canonical == "Richard Stone"
    assert registry.entry("Stone") is None
    assert registry.entry("Richard Stone").alias_counts["Stone"] == 20


@pytest.mark.asyncio
async def test_no_literal_overlap_without_llm_provider_becomes_new_entity():
    """字面完全不重疊時（如 I-35 對完全不同的別名體系），沒有 LLM provider
    只能落到 NEWENT 分支——這是刻意的降級行為，不是錯誤。"""
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Acme公司", "ORG")
    canonical = await registry.resolve_mention(1, "該集團", "ORG")
    assert canonical == "該集團"
    assert len(registry) == 2


@pytest.mark.asyncio
async def test_llm_arbitration_merges_non_overlapping_alias():
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Interstate Highway 35", "LOCATION")
    llm = FakeLLM("Interstate Highway 35")

    canonical = await registry.resolve_mention(1, "I-35", "LOCATION", llm_provider=llm)

    assert canonical == "Interstate Highway 35"  # 長度優先：I-35 較短，不會升級
    assert "以下是目前文件內已登記的實體標準名清單" in llm.prompts[0]


@pytest.mark.asyncio
async def test_llm_arbitration_new_entity_when_llm_says_new():
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Interstate Highway 35", "LOCATION")
    llm = FakeLLM("NEW")

    canonical = await registry.resolve_mention(1, "Some Other Thing", "LOCATION", llm_provider=llm)

    assert canonical == "Some Other Thing"
    assert len(registry) == 2


def test_resolve_mention_rejects_blank_mention():
    import asyncio

    async def run():
        registry = EntityRegistry()
        with pytest.raises(ValueError):
            await registry.resolve_mention(0, "   ", "概念")

    asyncio.run(run())


# ── apply_registry（整份句子清單套用）───────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_registry_replaces_mentions_in_sentence_text():
    sentences = ["Richard Stone 創立了該公司。", "Stone 隨後擔任執行長。"]
    mentions = [
        [Mention(sentence_idx=0, text="Richard Stone", entity_type="PERSON")],
        [Mention(sentence_idx=1, text="Stone", entity_type="PERSON")],
    ]

    output, registry = await apply_registry(sentences, mentions)

    assert output[0] == "Richard Stone 創立了該公司。"
    assert output[1] == "Richard Stone 隨後擔任執行長。"
    assert registry.entry("Richard Stone").alias_counts["Stone"] == 1


@pytest.mark.asyncio
async def test_apply_registry_resumes_from_checkpoint():
    sentences = ["Richard Stone 創立了該公司。", "Stone 隨後擔任執行長。", "Stone 退休了。"]
    mentions = [
        [Mention(sentence_idx=0, text="Richard Stone", entity_type="PERSON")],
        [Mention(sentence_idx=1, text="Stone", entity_type="PERSON")],
        [Mention(sentence_idx=2, text="Stone", entity_type="PERSON")],
    ]

    partial_output, partial_registry = await apply_registry(sentences[:2], mentions[:2])
    assert partial_output[1] == "Richard Stone 隨後擔任執行長。"

    resumed_output, resumed_registry = await apply_registry(
        sentences, mentions, registry=partial_registry, start_idx=2
    )

    assert resumed_output[0] == sentences[0]  # 已完成的句子未被重新處理
    assert resumed_output[1] == sentences[1]
    # 長度優先為主規則：即使「Stone」第三次出現、累計次數已超過「Richard
    # Stone」，仍不會被提升——與舊版頻率優先規則的行為不同，這是刻意修訂後
    # 的預期結果。
    assert resumed_output[2] == "Richard Stone 退休了。"
    assert resumed_registry.entry("Richard Stone").alias_counts["Stone"] == 2
    assert resumed_registry.entry("Stone") is None


@pytest.mark.asyncio
async def test_apply_registry_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        await apply_registry(["句子一"], [])


# ── 斷點續傳持久化 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_write_and_read_registry_snapshot_roundtrip(tmp_path):
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Richard Stone", "PERSON")
    await registry.resolve_mention(1, "Stone", "PERSON")

    write_registry_snapshot(tmp_path, registry)
    restored = read_registry_snapshot(tmp_path)

    assert restored is not None
    assert restored.entry("Richard Stone").alias_counts == {"Richard Stone": 1, "Stone": 1}


def test_read_registry_snapshot_returns_none_when_missing(tmp_path):
    assert read_registry_snapshot(tmp_path) is None
