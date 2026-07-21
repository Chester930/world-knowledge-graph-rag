import pytest

from services.entity_registry_service import (
    EntityRegistry,
    Mention,
    apply_registry,
    read_registry_snapshot,
    should_promote,
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


# ── should_promote（PK 規則）───────────────────────────────────────────────

def test_should_promote_prefers_higher_frequency():
    assert should_promote(candidate_count=5, current_count=1, candidate="I-35", current="Interstate Highway 35") is True


def test_should_promote_rejects_lower_frequency_even_if_longer():
    assert should_promote(candidate_count=2, current_count=50, candidate="泰國全名", current="泰國") is False


def test_should_promote_uses_length_as_tiebreak_when_frequency_equal():
    assert should_promote(candidate_count=3, current_count=3, candidate="Richard Stone", current="Stone") is True
    assert should_promote(candidate_count=3, current_count=3, candidate="Stone", current="Richard Stone") is False


def test_should_promote_keeps_current_on_full_tie():
    assert should_promote(candidate_count=1, current_count=1, candidate="Apple LLC.", current="Apple Inc.") is False


# ── EntityRegistry.resolve_mention（規則式比對＋動態提升）──────────────────

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
async def test_frequent_abbreviation_gets_promoted_to_canonical():
    """「Stone」與「Richard Stone」字面有子字串重疊，免 LLM 即可規則命中；
    當「Stone」累計出現次數超過「Richard Stone」時應觸發提升。"""
    registry = EntityRegistry()
    await registry.resolve_mention(0, "Richard Stone", "PERSON")
    canonical = ""
    for idx in range(1, 3):
        canonical = await registry.resolve_mention(idx, "Stone", "PERSON")
    # 第 2 次「Stone」出現後（累計 2 次）已超過「Richard Stone」的 1 次，觸發提升
    assert canonical == "Stone"
    entry = registry.entry("Stone")
    assert entry is not None
    assert entry.alias_counts["Stone"] == 2
    assert entry.alias_counts["Richard Stone"] == 1
    assert registry.entry("Richard Stone") is None  # 舊 Key 已降級，不再是獨立條目


@pytest.mark.asyncio
async def test_rare_long_form_does_not_outrank_frequent_short_form():
    """對應使用者提出的「泰國 vs. 罕用正式全名」情境。"""
    registry = EntityRegistry()
    await registry.resolve_mention(0, "泰國", "LOCATION")
    for idx in range(1, 50):
        await registry.resolve_mention(idx, "泰國", "LOCATION")
    canonical = await registry.resolve_mention(50, "泰國全名", "LOCATION")
    # 「泰國全名」與「泰國」需先被判定為別名（此處靠子字串規則：「泰國」⊂「泰國全名」）
    assert canonical == "泰國"
    assert registry.entry("泰國").alias_counts["泰國全名"] == 1


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

    assert canonical == "Interstate Highway 35"  # 併入後次數 1 vs 1 平手，比長度，I-35 較短不會升級
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
    # 第三次出現「Stone」後，其累計次數（2）已超過「Richard Stone」（1），
    # 依頻率優先規則觸發提升——這是設計本身的預期行為，不是巧合。
    assert resumed_output[2] == "Stone 退休了。"
    assert resumed_registry.entry("Stone").alias_counts["Stone"] == 2
    assert resumed_registry.entry("Richard Stone") is None


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
