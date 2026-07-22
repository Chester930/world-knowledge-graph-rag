import pytest

from services import ingestion_service
from services.entity_registry_service import Mention
from services.svo_preprocessing_service import prepare_svo_ready_chunks


class FakeLLM:
    def __init__(self, responses=None, default: str = ""):
        self.responses = list(responses) if responses is not None else None
        self.default = default
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.responses is not None:
            return self.responses.pop(0)
        return self.default

    async def stream(self, prompt: str):
        yield self.default

    async def generate_json(self, prompt: str) -> str:
        return self.default


@pytest.mark.asyncio
async def test_pipeline_without_mentions_skips_registry_and_chunks_result(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    # 刻意避開英文專有名詞緊接句號的組合（parser.core.split_into_sentences
    # 既有的縮寫防誤判 lookbehind 會連帶擋下如「SpaceX。」這類邊界，屬既有、
    # 與本次工作無關的規則限制，不在此修正，測試改用不觸發此限制的文字）。
    text = "馬斯克創立了太空公司。他隨後研發了獵鷹火箭。"
    ingestion_service.chunk_and_stage(text, "report.txt", staging)

    llm = FakeLLM(responses=["馬斯克隨後研發了獵鷹火箭。"])

    paths, chunks = await prepare_svo_ready_chunks(
        "report.txt", staging, output, pronoun_llm_provider=llm,
    )

    assert len(paths) == 1
    assert len(chunks) == 1
    assert chunks[0].original_sentences == ["馬斯克創立了太空公司。", "他隨後研發了獵鷹火箭。"]
    assert chunks[0].normalized_sentences == ["馬斯克創立了太空公司。", "馬斯克隨後研發了獵鷹火箭。"]
    assert paths[0].exists()


@pytest.mark.asyncio
async def test_pipeline_with_mentions_applies_registry_before_pronoun_resolution(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    text = "理查·史東創立了太空公司。史東隨後研發了獵鷹火箭。它是一枚可回收火箭。"
    ingestion_service.chunk_and_stage(text, "report.txt", staging)

    mentions = [
        [Mention(sentence_idx=0, text="理查·史東", entity_type="PERSON")],
        [Mention(sentence_idx=1, text="史東", entity_type="PERSON")],
        [],
    ]
    pronoun_llm = FakeLLM(responses=["獵鷹火箭是一枚可回收火箭。"])
    # 代名詞消解只會被觸發在第 3 句（含「它」），前兩句別名登記後不含代名詞

    paths, chunks = await prepare_svo_ready_chunks(
        "report.txt", staging, output,
        mentions=mentions,
        pronoun_llm_provider=pronoun_llm,
    )

    assert len(chunks) == 1
    normalized = chunks[0].normalized_sentences
    assert normalized[0] == "理查·史東創立了太空公司。"
    # 「史東」透過登記表子字串規則併入「理查·史東」，就地替換為文件內暫定標準名
    assert normalized[1] == "理查·史東隨後研發了獵鷹火箭。"
    assert normalized[2] == "獵鷹火箭是一枚可回收火箭。"
    # 第三句含代名詞「它」，交由（唯一一次）LLM 呼叫消解
    assert len(pronoun_llm.prompts) == 1


@pytest.mark.asyncio
async def test_pipeline_persists_svo_index_to_disk(tmp_path):
    staging = tmp_path / "staging"
    output = tmp_path / "output"
    ingestion_service.chunk_and_stage("單句無代名詞。", "note.md", staging)

    paths, chunks = await prepare_svo_ready_chunks("note.md", staging, output)

    from services.svo_chunking import read_svo_index
    index = read_svo_index(output / "note")
    assert index is not None
    assert index["total_svo_chunks"] == len(chunks)
