import json
from uuid import uuid4

import pytest

from models.document import ChatRequest
from models.knowledge_graph import SVOTriple
from routers import agent


# ── _merge_fact_lines：BFS 三元組與語意檢索 Fact 合併去重（2026-08-18）──────

def _triple(subject="A", rel_type="CAUSES", object_="B", verb="導致", natural_text=None):
    return SVOTriple(subject=subject, subject_type="概念", rel_type=rel_type,
                      verb=verb, object=object_, object_type="概念", natural_text=natural_text)


def test_merge_fact_lines_includes_both_sources_when_distinct():
    triples = [_triple("台積電", "CAUSES", "晶片")]
    fact_results = [{"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
                      "rel_type": "CREATED_BY", "object": "SpaceX"}]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 2
    assert any("台積電" in line for line in lines)
    assert any("馬斯克 創立 SpaceX" in line for line in lines)


def test_merge_fact_lines_dedupes_same_triple_from_both_sources():
    """同一 (subject, rel_type, object) 從 BFS 與語意檢索都找到時，只保留
    先出現的 BFS 版本，不重複列出。"""
    triples = [_triple("台積電", "CAUSES", "晶片", verb="生產")]
    fact_results = [{"fact_text": "台積電（組織） 製造 晶片（產品）", "subject": "台積電",
                      "rel_type": "CAUSES", "object": "晶片"}]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 1
    assert "生產" in lines[0]  # 保留 BFS 版本的措辭，語意檢索版本被去重掉


def test_merge_fact_lines_keeps_fact_with_missing_key_fields():
    """Fact 節點缺 subject/rel_type/object（2026-08-18 schema 修正前建立、
    尚未跑過 §b 回填的舊資料）時，無法安全去重，一律原樣保留。"""
    triples = [_triple("A", "CAUSES", "B")]
    fact_results = [{"fact_text": "舊資料事實", "subject": None, "rel_type": None, "object": None}]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 2
    assert any("舊資料事實" in line for line in lines)


def test_merge_fact_lines_empty_when_no_sources():
    assert agent._merge_fact_lines([], []) == []


# ── _merge_fact_lines：殘缺過濾改看渲染文字（報告25 §4 發現6 追查，2026-09-02）─
# 舊版直接看結構化 object 欄位是否為空——會把 `X -[RELATED_TO]-> (懸空概念)`
# 這種 payload 在 verb 的合法事實（Q8 三筆答案事實正是此形狀）一起丟掉。
# 改為看渲染後的文字：只丟「空字串」或「只有 subject」的行。

def test_merge_fact_lines_keeps_object_empty_fact_when_verb_carries_content():
    """報告25 §4 發現6：`訓練時數 以三百小時為度`（object 為空、payload 在
    verb）是合法事實，不再被殘缺過濾丟掉。"""
    fact_results = [{"fact_text": "訓練時數 以三百小時為度", "subject": "訓練時數",
                      "rel_type": "RELATED_TO", "object": ""}]

    lines = agent._merge_fact_lines([], fact_results)

    assert lines == ["- 訓練時數 以三百小時為度"]


def test_merge_fact_lines_keeps_object_empty_bfs_triple_with_verb():
    triples = [_triple("訓練時數", "RELATED_TO", "", verb="以三百小時為度")]

    lines = agent._merge_fact_lines(triples, [])

    assert lines == ["- 訓練時數 以三百小時為度"]


def test_merge_fact_lines_skips_subject_only_line():
    """渲染後只剩 subject（verb／object 皆空，或型別標記清掉後什麼都不剩）
    才算殘缺、丟棄。"""
    triples = [_triple("殘缺", "RELATED_TO", "", verb="")]
    fact_results = [{"fact_text": "失業給付（概念）  （概念）", "subject": "失業給付",
                      "rel_type": "RELATED_TO", "object": ""}]

    assert agent._merge_fact_lines(triples, []) == []
    assert agent._merge_fact_lines([], fact_results) == []


def test_merge_fact_lines_skips_triple_with_empty_subject():
    triples = [_triple("", "RELATED_TO", "B")]

    lines = agent._merge_fact_lines(triples, [])

    assert lines == []


def test_merge_fact_lines_keeps_valid_and_skips_truly_blank_when_mixed():
    triples = [_triple("A", "CAUSES", "B"), _triple("殘缺", "RELATED_TO", "", verb="")]
    fact_results = [
        {"fact_text": "有效事實", "subject": "C", "rel_type": "CAUSES", "object": "D"},
        {"fact_text": "殘缺事實", "subject": "", "rel_type": "RELATED_TO", "object": "E"},
    ]

    lines = agent._merge_fact_lines(triples, fact_results)

    assert len(lines) == 2
    assert any("A" in line for line in lines)
    assert any("有效事實" in line for line in lines)


# ── _merge_fact_lines：自然語言化優先於樣板拼接（報告24 §5 階段3，2026-09-01）──

def test_merge_fact_lines_uses_natural_text_when_present():
    triples = [_triple("事假", "RELATED_TO", "小時為請假單位", verb="得以",
                        natural_text="事假可以用小時為單位申請。")]

    lines = agent._merge_fact_lines(triples, [])

    assert lines == ["- 事假可以用小時為單位申請。"]


def test_merge_fact_lines_falls_back_to_template_when_natural_text_missing():
    """natural_text 缺席時優雅降級回 `subject verb object` 直接串接（報告25
    §4 發現5：不再塞 `（型別）`，避免洩漏到 prompt／答案）。"""
    triples = [_triple("A", "CAUSES", "B", verb="導致", natural_text=None)]

    lines = agent._merge_fact_lines(triples, [])

    assert lines == ["- A 導致 B"]


def test_merge_fact_lines_strips_residual_type_markers_from_fact_text():
    """報告25 §4 發現5：尚未跑過 `backfill_fact_text_embeddings()` 的 KG 其
    `fact_text` 仍帶 `（概念）`／`（PLACE）`，輸出前做防禦性清除。"""
    fact_results = [{"fact_text": "訓練時數（概念） 以三百小時為度 （概念）",
                      "subject": "訓練時數", "rel_type": "RELATED_TO", "object": "以三百小時為度"}]

    lines = agent._merge_fact_lines([], fact_results)

    assert lines == ["- 訓練時數 以三百小時為度"]


def test_merge_fact_lines_leaves_normal_parentheses_untouched():
    """只清型別標記（`（概念）`／ASCII 型別），不誤刪正常中文括號內容。"""
    fact_results = [{"fact_text": "本標準 自 中華民國一百十年（2021年）施行",
                      "subject": "本標準", "rel_type": "RELATED_TO", "object": "施行"}]

    lines = agent._merge_fact_lines([], fact_results)

    assert lines == ["- 本標準 自 中華民國一百十年（2021年）施行"]


# ── 事實清單排列用的假 embedding provider（2026-09-01 新增，報告23）───────
# 用簡單的字元計數向量取代真正的語意模型：兩段文字共用的字元越多，向量
# 越接近、cosine 相似度越高——不追求語意精確度，只求「排序邏輯本身正確」
# 這件事在測試裡可預期、不依賴外部模型。

class _FakeSemanticEmbeddingProvider:
    def __init__(self):
        self.encoded_texts: list[str] = []
        self.batch_calls: list[list[str]] = []

    async def encode(self, text: str) -> list[float]:
        self.encoded_texts.append(text)
        return self._vector_for(text)

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls.append(list(texts))
        return [self._vector_for(t) for t in texts]

    @staticmethod
    def _vector_for(text: str) -> list[float]:
        vec = [0.0] * 64
        for ch in text:
            vec[hash(ch) % 64] += 1.0
        return vec


# ── _build_prompt：合併後的事實清單接進 prompt ─────────────────────────────

@pytest.mark.asyncio
async def test_build_prompt_includes_semantic_fact_when_no_bfs_triples():
    """BFS 完全沒找到種子（字面比對失效），但語意檢索找到相關事實時，仍應
    進入「有事實」的 prompt 分支，而非誤判為完全無資料。"""
    fact_results = [{"fact_text": "資遣 需 預告", "subject": "資遣", "rel_type": "REQUIRES", "object": "預告"}]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_prompt(
        "資遣要注意什麼？", [], fact_results, None, embedding_provider=embedding
    )

    assert "資遣 需 預告" in prompt
    assert "請優先根據上述事實回答問題" in prompt


@pytest.mark.asyncio
async def test_build_prompt_falls_back_to_general_knowledge_when_nothing_found():
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_prompt("隨便問點什麼", [], [], None, embedding_provider=embedding)

    assert "沒有檢索到與問題直接相關的事實" in prompt
    assert embedding.batch_calls == []  # 空事實清單不應觸發任何 embedding 呼叫


@pytest.mark.asyncio
async def test_build_prompt_instructs_checking_every_fact_line():
    """報告22題3追查後新增：生成端遺漏了確實存在於事實清單中的正確事實，
    低成本緩解之一是在prompt裡明確要求逐條核對。"""
    fact_results = [{"fact_text": "資遣 需 預告", "subject": "資遣", "rel_type": "REQUIRES", "object": "預告"}]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_prompt(
        "資遣要注意什麼？", [], fact_results, None, embedding_provider=embedding
    )

    assert "逐條檢視" in prompt


@pytest.mark.asyncio
async def test_build_prompt_allows_interval_lookup_inference():
    """報告32 §9 G2：Q8 型「分段對照表 + 題目數值 → 查表取對應值」的組合推論，
    草稿 prompt 明確允許（其他推論仍不允許）。"""
    fact_results = [
        {"fact_text": "1 以上，未滿 10 的容許濃度 變量係數為 2", "subject": "1 以上，未滿 10 的容許濃度", "rel_type": "RELATED_TO", "object": "2"},
    ]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_prompt(
        "8 小時容許濃度為 5 ppm 時變量係數是多少？", [], fact_results, None, embedding_provider=embedding
    )

    assert "數值區間 → 對應值" in prompt
    assert "落在哪一個區間" in prompt


@pytest.mark.asyncio
async def test_build_constrained_prompt_allows_interval_lookup_inference():
    """報告32 §9 G2：限制性重生成 prompt 規則 1 對「分段查表」開窄例外，
    其他推論仍一律禁止。"""
    fact_results = [
        {"fact_text": "1 以上，未滿 10 的容許濃度 變量係數為 2", "subject": "1 以上，未滿 10 的容許濃度", "rel_type": "RELATED_TO", "object": "2"},
    ]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_constrained_prompt(
        "8 小時容許濃度為 5 ppm 時變量係數是多少？", [], fact_results, None, embedding_provider=embedding
    )

    assert "唯一例外" in prompt
    assert "分段查表" in prompt
    assert "不可以用推論" in prompt  # 一般禁令仍在


@pytest.mark.asyncio
async def test_build_prompt_carries_segmented_answer_hint():
    """報告32 §9 G3：Q3/Q6 型「分 N 段回答」——草稿 prompt 要提醒逐段對照、
    相似段別（未滿六歲 vs 未滿六個月）不可混用、問幾段答幾段。"""
    fact_results = [
        {"fact_text": "年齡未滿六歲者 每日不得超過 二小時", "subject": "年齡未滿六歲者", "rel_type": "RELATED_TO", "object": "二小時"},
    ]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_prompt(
        "未滿十五歲工作者每日工時如何依年齡分三段？", [], fact_results, None, embedding_provider=embedding
    )

    assert "分段回答" in prompt
    assert "未滿六個月" in prompt  # 相似段別的警示例子
    assert "問題列出幾段就要回答幾段" in prompt


@pytest.mark.asyncio
async def test_targeted_correction_prompt_carries_tier_rule():
    """報告32 §9 G3：定向修訂 prompt 規則 5——被標記的片段若是分段清單其中一段，
    要鎖定是哪一段、到事實清單找「正是這一段」的正確值，而非一律答未記載。"""
    triples = [_triple("年齡未滿六歲者", "RELATED_TO", "二小時", verb="每日不得超過")]
    embedding = _FakeSemanticEmbeddingProvider()
    llm = _FakeStreamLLM(answers=["修正1：年齡未滿六歲者每日不得超過二小時。"])

    fixes = await agent._targeted_correction(
        "未滿十五歲工作者每日工時如何依年齡分三段？",
        ["年齡未滿六歲者的每日工作時間上限為三十分鐘。"],
        triples, [],
        embedding_provider=embedding, question_vector=None, llm_provider=llm,
    )

    assert fixes == ["年齡未滿六歲者每日不得超過二小時。"]
    assert "分段清單／分級" in llm.prompts[0]
    assert "把「未滿六歲」的值寫成「未滿六個月」的值" in llm.prompts[0]


# ── 報告32 §9 G3 completeness guard：_detect_tier_families／_missing_tier_members ──

def _tier_triples():
    return [
        _triple("年齡未滿六歲者", "RELATED_TO", "二小時", verb="每日不得超過"),
        _triple("六歲以上未滿十二歲者", "RELATED_TO", "三小時", verb="每日不得超過"),
        _triple("十二歲以上未滿十五歲者", "RELATED_TO", "四小時", verb="每日不得超過"),
    ]


def test_detect_tier_families_groups_three_siblings():
    fams = agent._detect_tier_families(_tier_triples(), [])
    assert len(fams) == 1
    assert {m[2] for m in fams[0]} == {"二小時", "三小時", "四小時"}


def test_detect_tier_families_needs_at_least_three_members():
    assert agent._detect_tier_families(_tier_triples()[:2], []) == []


def test_detect_tier_families_rejects_duplicate_objects():
    trips = [
        _triple("甲", "RELATED_TO", "三十日", verb="期限為"),
        _triple("乙", "RELATED_TO", "三十日", verb="期限為"),
        _triple("丙", "RELATED_TO", "三十日", verb="期限為"),
    ]
    assert agent._detect_tier_families(trips, []) == []


def test_detect_tier_families_from_fact_results():
    facts = [
        {"fact_text": "血中鉛濃度低於五 μg/dl 者 屬於 第一級管理", "subject": "血中鉛濃度低於五 μg/dl 者", "rel_type": "RELATED_TO", "object": "第一級管理"},
        {"fact_text": "血中鉛濃度在五 μg/dl 以上未達十 μg/dl 屬於 第二級管理", "subject": "血中鉛濃度在五 μg/dl 以上未達十 μg/dl", "rel_type": "RELATED_TO", "object": "第二級管理"},
        {"fact_text": "血中鉛濃度在十 μg/dl 以上者 屬於 第三級管理", "subject": "血中鉛濃度在十 μg/dl 以上者", "rel_type": "RELATED_TO", "object": "第三級管理"},
    ]
    fams = agent._detect_tier_families([], facts)
    assert len(fams) == 1
    assert {m[2] for m in fams[0]} == {"第一級管理", "第二級管理", "第三級管理"}


def test_missing_tier_members_flags_absent_object():
    fams = agent._detect_tier_families(_tier_triples(), [])
    ans = "六歲以上未滿十二歲者每日不得超過三小時；十二歲以上未滿十五歲者每日不得超過四小時。"
    missing = agent._missing_tier_members(ans, fams)
    assert [m[2] for m in missing] == ["二小時"]


def test_missing_tier_members_empty_when_all_present():
    fams = agent._detect_tier_families(_tier_triples(), [])
    ans = "未滿六歲：二小時；六至十二歲：三小時；十二至十五歲：四小時。"
    assert agent._missing_tier_members(ans, fams) == []


def test_wants_full_enumeration_gate():
    # Q3 型：要全列
    assert agent._wants_full_enumeration("未滿十五歲工作者每日工時如何依年齡分三段規定？")
    assert agent._wants_full_enumeration("血中鉛管理分別依濃度怎麼分級？")
    # Q8 型：查表取一段，不要被 guard 逼著貼整張表
    assert not agent._wants_full_enumeration("八小時容許濃度為 5 ppm 時變量係數是多少？")
    assert not agent._wants_full_enumeration("血中鉛濃度達到多少以上屬於第三級管理？")


# ── _score_lines_by_embedding／_arrange_fact_lines：報告23（2026-09-01）───
# 取代舊版 _sort_lines_by_relevance()（bigram，報告22題3真實重跑證實訊號
# 太弱）。改用 embedding cosine similarity，並補上截斷／條件式zigzag重排。

@pytest.mark.asyncio
async def test_score_lines_by_embedding_puts_most_similar_line_first():
    embedding = _FakeSemanticEmbeddingProvider()
    question = "事假可以用小時請假嗎"
    lines = ["- 高溫作業勞工給予中度工作", "- 事假得以小時為請假單位"]

    scored = await agent._score_lines_by_embedding(question, lines, embedding_provider=embedding)

    assert scored[0] == "- 事假得以小時為請假單位"


@pytest.mark.asyncio
async def test_score_lines_by_embedding_reuses_precomputed_question_vector():
    embedding = _FakeSemanticEmbeddingProvider()
    question_vector = [1.0] * 64

    await agent._score_lines_by_embedding(
        "問題", ["- A"], embedding_provider=embedding, question_vector=question_vector
    )

    assert embedding.encoded_texts == []  # 傳入 question_vector 時不應再呼叫 encode()


@pytest.mark.asyncio
async def test_score_lines_by_embedding_handles_empty_lines():
    embedding = _FakeSemanticEmbeddingProvider()

    assert await agent._score_lines_by_embedding("問題", [], embedding_provider=embedding) == []
    assert embedding.batch_calls == []


def test_litm_reorder_places_most_relevant_at_both_ends():
    """Jin et al. (2025) 式1：最相關的排在首尾，最不相關的擠到正中央。"""
    ranked = ["- rank1", "- rank2", "- rank3", "- rank4", "- rank5", "- rank6", "- rank7"]

    reordered = agent._litm_reorder(ranked)

    assert reordered[0] == "- rank1"
    assert reordered[-1] == "- rank2"
    assert reordered[len(reordered) // 2] == "- rank7"
    assert sorted(reordered) == sorted(ranked)  # 只重排，不遺漏也不新增


@pytest.mark.asyncio
async def test_arrange_fact_lines_keeps_short_list_no_zigzag():
    """總長度 ≤ K：全部保留、RRF 排序、不套 zigzag（Jin et al. 2025：小清單
    重排效果不明顯）。"""
    embedding = _FakeSemanticEmbeddingProvider()
    bfs = [f"- bfs{i}" for i in range(3)]
    fact = [f"- fact{i}" for i in range(2)]

    arranged = await agent._arrange_fact_lines("問題", bfs, fact, embedding_provider=embedding)

    assert len(arranged) == 5
    assert sorted(arranged) == sorted(bfs + fact)


@pytest.mark.asyncio
async def test_arrange_fact_lines_caps_bfs_lines():
    """BFS 鄰居剪枝（SAGE）：BFS 行超過 `_BFS_KEEP_MAX` 時只留前這麼多筆。"""
    embedding = _FakeSemanticEmbeddingProvider()
    bfs = [f"- bfs{i}" for i in range(40)]

    arranged = await agent._arrange_fact_lines("問題", bfs, [], embedding_provider=embedding)

    assert len(arranged) == agent._BFS_KEEP_MAX


@pytest.mark.asyncio
async def test_arrange_fact_lines_semantic_facts_survive_truncation():
    """報告25 §4 發現6：截斷時語意 Fact 依檢索順序優先佔位，不被大量無
    問題相關性排序的 BFS 三元組擠掉；BFS 至少保底 `_MIN_BFS_SLOTS` 席。"""
    embedding = _FakeSemanticEmbeddingProvider()
    bfs = [f"- bfs{i}" for i in range(30)]
    fact = [f"- fact{i}" for i in range(13)]

    arranged = await agent._arrange_fact_lines("問題", bfs, fact, embedding_provider=embedding)

    assert len(arranged) == agent._FACT_LINE_TRUNCATE_K
    for line in fact:  # 全部 13 筆語意 Fact 都在最終清單裡
        assert line in arranged
    assert sum(1 for line in arranged if line.startswith("- bfs")) == agent._MIN_BFS_SLOTS + 1


@pytest.mark.asyncio
async def test_arrange_fact_lines_bfs_floor_when_few_semantic_facts():
    """語意 Fact 少時餘額讓給 BFS——不會因為「語意優先」就浪費名額。"""
    embedding = _FakeSemanticEmbeddingProvider()
    bfs = [f"- bfs{i}" for i in range(30)]
    fact = ["- fact0", "- fact1"]

    arranged = await agent._arrange_fact_lines("問題", bfs, fact, embedding_provider=embedding)

    assert len(arranged) == agent._FACT_LINE_TRUNCATE_K
    assert "- fact0" in arranged and "- fact1" in arranged


@pytest.mark.asyncio
async def test_build_prompt_arranges_fact_lines_by_relevance():
    question = "事假可以用小時請假嗎"
    triples = [
        _triple("高溫作業勞工", "RELATED_TO", "中度工作", verb="給予"),
        _triple("事假", "RELATED_TO", "小時為請假單位", verb="得以"),
    ]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_prompt(question, triples, [], None, embedding_provider=embedding)

    # 較相關的「事假…小時為請假單位」應排在較不相關的「高溫作業勞工…」之前
    assert prompt.index("事假 得以 小時為請假單位") < prompt.index("高溫作業勞工")


@pytest.mark.asyncio
async def test_build_constrained_prompt_arranges_fact_lines_and_instructs_checking_every_line():
    question = "事假可以用小時請假嗎"
    triples = [
        _triple("高溫作業勞工", "RELATED_TO", "中度工作", verb="給予"),
        _triple("事假", "RELATED_TO", "小時為請假單位", verb="得以"),
    ]
    embedding = _FakeSemanticEmbeddingProvider()

    prompt = await agent._build_constrained_prompt(
        question, triples, [], None, embedding_provider=embedding
    )

    assert prompt.index("事假 得以 小時為請假單位") < prompt.index("高溫作業勞工")
    assert "逐條檢視" in prompt


# ── _split_into_subquestions／_generate_decomposed_answer：報告27 C#2 M1
# （2026-09-04，規則式問題分解，避免複合問題單次生成內跨子答案自我矛盾）──

def test_split_into_subquestions_splits_on_multiple_question_marks():
    q = "連續僱用滿多久才能申請獎勵金？獎勵金最多發給幾個月？應在幾日內申請？"
    parts = agent._split_into_subquestions(q)
    assert parts == [
        "連續僱用滿多久才能申請獎勵金？",
        "獎勵金最多發給幾個月？",
        "應在幾日內申請？",
    ]


def test_split_into_subquestions_single_question_mark_stays_whole():
    q = "婚假可以請幾天？"
    assert agent._split_into_subquestions(q) == [q]


def test_split_into_subquestions_no_question_mark_stays_whole():
    q = "請說明婚假天數"
    assert agent._split_into_subquestions(q) == [q]


def test_split_into_subquestions_caps_at_max_subquestions():
    q = "".join(f"第{i}問？" for i in range(10))
    parts = agent._split_into_subquestions(q)
    assert len(parts) == agent._MAX_SUBQUESTIONS


def test_split_into_subquestions_ascii_question_mark_also_splits():
    q = "第一問?第二問?"
    assert agent._split_into_subquestions(q) == ["第一問?", "第二問?"]


@pytest.mark.asyncio
async def test_generate_decomposed_answer_calls_llm_once_per_subquestion_and_numbers_output():
    sub_questions = ["連續僱用滿多久才能申請獎勵金？", "獎勵金最多發給幾個月？"]
    triples = [_triple("優先僱用", "RELATED_TO", "連續三個月", verb="須")]
    llm = _FakeStreamLLM(answers=["連續三個月。", "以三個月為限。"])
    embedding = _FakeSemanticEmbeddingProvider()

    answer = await agent._generate_decomposed_answer(
        sub_questions, triples, [],
        embedding_provider=embedding, question_vector=None, llm_provider=llm,
    )

    assert len(llm.prompts) == 2  # 每個子問題各一次生成呼叫
    assert "1. 連續僱用滿多久才能申請獎勵金？\n連續三個月。" in answer
    assert "2. 獎勵金最多發給幾個月？\n以三個月為限。" in answer
    # 每個子問題各自的 prompt 都要看得到完整事實清單（不重新檢索、只是各自
    # 獨立生成），且子問題彼此的 prompt 不互相夾帶對方的問句文字。
    assert "優先僱用 須 連續三個月" in llm.prompts[0]
    assert "優先僱用 須 連續三個月" in llm.prompts[1]
    assert "獎勵金最多發給幾個月" not in llm.prompts[0]


@pytest.mark.asyncio
async def test_decomposed_answer_rescopes_fact_ranking_per_subquestion():
    """報告32 §9 G4：即使 chat() 傳進整個複合問題的 question_vector，分解路徑
    也要對「每個子問題」重新編碼排序事實清單——否則對子問題高度相關、對整題
    相關性低的事實（Q6「相關文件及紀錄至少保存三年」）排不進前段、被生成端
    忽略。以 `encoded_texts` 出現每個子問句本身為證。"""
    sub_questions = ["母性健康保護期間到什麼時候為止？", "相關文件及紀錄至少要保存幾年？"]
    triples = [_triple("相關文件及紀錄", "RELATED_TO", "三年", verb="至少保存")]
    llm = _FakeStreamLLM(answers=["至分娩後一年。", "至少保存三年。"])
    embedding = _FakeSemanticEmbeddingProvider()

    await agent._generate_decomposed_answer(
        sub_questions, triples, [],
        embedding_provider=embedding, question_vector=[1.0] * 64,  # 模擬 chat() 傳整題向量
        llm_provider=llm,
    )

    # 傳進來的整題向量被忽略，改對每個子問句本身編碼
    assert "母性健康保護期間到什麼時候為止？" in embedding.encoded_texts
    assert "相關文件及紀錄至少要保存幾年？" in embedding.encoded_texts


@pytest.mark.asyncio
async def test_decomposed_constrained_answer_rescopes_fact_ranking_per_subquestion():
    """報告32 §9 G4：`_generate_decomposed_constrained_answer()`（重生成路徑）
    同樣要對每個子問題重新編碼排序。"""
    sub_questions = ["期間到什麼時候？", "紀錄保存幾年？"]
    triples = [_triple("相關文件及紀錄", "RELATED_TO", "三年", verb="至少保存")]
    llm = _FakeStreamLLM(answers=["一年。", "三年。"])
    embedding = _FakeSemanticEmbeddingProvider()

    await agent._generate_decomposed_constrained_answer(
        sub_questions, triples, [],
        embedding_provider=embedding, question_vector=[1.0] * 64,
        llm_provider=llm,
    )

    assert "期間到什麼時候？" in embedding.encoded_texts
    assert "紀錄保存幾年？" in embedding.encoded_texts


# ── chat()：驗證語意 Fact 檢索確實接線（2026-08-18）─────────────────────────

class _FakeEmbeddingProvider:
    def __init__(self, vector):
        self._vector = vector
        self.encoded_texts: list[str] = []

    async def encode(self, text: str):
        self.encoded_texts.append(text)
        return self._vector

    async def encode_batch(self, texts: list[str]):
        return [self._vector for _ in texts]


class _FakeStreamLLM:
    def __init__(
        self,
        grounding_payload: str = '{"claims":[]}',
        *,
        answers: list[str] | None = None,
        grounding_payloads: list[str] | None = None,
    ):
        self.prompt: str | None = None
        self.prompts: list[str] = []  # 2026-08-28：方案 B 可能呼叫 stream() 兩次（草稿＋修正）
        self.grounding_payload = grounding_payload
        self.grounding_prompts: list[str] = []
        # 2026-08-28：`answers`／`grounding_payloads` 依序供應每次呼叫的回應，
        # 用完最後一個之後重複沿用——讓測試能模擬「草稿未接地→限制性重新生成
        # →修正版已接地」這種依 prompt 內容遞增變化的情境，不需要真的解析
        # prompt 內容來決定回應。
        self._answers = list(answers) if answers is not None else None
        self._grounding_payloads = list(grounding_payloads) if grounding_payloads is not None else None

    async def stream(self, prompt: str):
        self.prompt = prompt
        self.prompts.append(prompt)
        if self._answers:
            text = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
        else:
            text = "ok"
        yield text

    async def generate_json(self, prompt: str) -> str:
        # 2026-08-24：verify_fact_grounding() 串流結束後呼叫；預設回傳空
        # claims，既有測試（聚焦串流/檢索接線本身）不需要另外準備核對回應。
        self.grounding_prompts.append(prompt)
        if self._grounding_payloads:
            return self._grounding_payloads.pop(0) if len(self._grounding_payloads) > 1 else self._grounding_payloads[0]
        return self.grounding_payload


async def _drain(response):
    return [chunk async for chunk in response.body_iterator]


# ── _find_seed_entities：字面比對 + 語意 fallback（2026-08-25，見 docs/報告/17）──

class _FakeEntityDriver:
    def __init__(self, names):
        self._names = names

    async def execute_query(self, query, **params):
        class _Result:
            def __init__(self, records):
                self.records = records

        return _Result([{"name": n} for n in self._names])


@pytest.mark.asyncio
async def test_find_seed_entities_prefers_literal_match_over_vector_fallback(monkeypatch):
    """字面比對命中時，不應呼叫語意 fallback（優先採用更精確的字面匹配，
    見函式 docstring）。"""
    driver = _FakeEntityDriver(["勞工", "雇主"])
    vector_calls = []

    async def fake_vector_search(driver_arg, kg_id_arg, vector, top_k):
        vector_calls.append(True)
        return []

    monkeypatch.setattr(agent, "vector_search_entities", fake_vector_search)
    embedding = _FakeEmbeddingProvider([0.1])

    seeds = await agent._find_seed_entities(
        driver, uuid4(), "勞工可以請幾天婚假？", embedding_provider=embedding,
    )

    assert seeds == ["勞工"]
    assert vector_calls == []


@pytest.mark.asyncio
async def test_find_seed_entities_falls_back_to_vector_search_when_no_literal_match(monkeypatch):
    """2026-08-25 新增：字面比對找不到任何種子、且提供 `embedding_provider`
    時，改用 `vector_search_entities()` 的語意相似度結果。"""
    driver = _FakeEntityDriver(["請婚假、喪假、公傷病假及公假"])  # 不含「婚假」字面子字串比對不到

    async def fake_vector_search(driver_arg, kg_id_arg, vector, top_k):
        assert vector == [0.1, 0.2]
        assert top_k == agent._SEED_ENTITY_LIMIT
        return ["婚假"]

    monkeypatch.setattr(agent, "vector_search_entities", fake_vector_search)
    embedding = _FakeEmbeddingProvider([0.1, 0.2])

    seeds = await agent._find_seed_entities(
        driver, uuid4(), "婚假可以請幾天？",
        embedding_provider=embedding, question_vector=[0.1, 0.2],
    )

    assert seeds == ["婚假"]


@pytest.mark.asyncio
async def test_find_seed_entities_without_embedding_provider_stays_empty_on_no_match():
    """`embedding_provider=None`（既有呼叫端未升級）時行為與新增語意
    fallback 之前完全一致——不嘗試向量比對，直接回傳空清單。"""
    driver = _FakeEntityDriver(["請婚假、喪假、公傷病假及公假"])

    seeds = await agent._find_seed_entities(driver, uuid4(), "婚假可以請幾天？")

    assert seeds == []


# ── _drop_hub_seeds：種子度數上限（報告27 L1）──

class _DegreeAwareDriver:
    """對「列 Entity 名稱」查詢回傳全部候選；對「算度數」查詢回傳 degree map。"""

    def __init__(self, names, degrees):
        self._names = names
        self._degrees = degrees  # {name: degree}
        self.queries = []

    async def execute_query(self, query, **params):
        self.queries.append(query)

        class _Result:
            def __init__(self, records):
                self.records = records

        if "count(r) AS degree" in query:
            wanted = params["names"]
            return _Result([{"name": n, "degree": self._degrees.get(n, 0)} for n in wanted])
        return _Result([{"name": n} for n in self._names])


@pytest.mark.asyncio
async def test_find_seed_entities_drops_hub_seed_when_non_hub_available(monkeypatch):
    """報告27 L1：度數 > `_SEED_MAX_DEGREE` 的樞紐種子在還有非樞紐種子時被剔除。"""
    driver = _DegreeAwareDriver(
        names=["雇主", "特別休假"],
        degrees={"雇主": agent._SEED_MAX_DEGREE + 500, "特別休假": 12},
    )
    seeds = await agent._find_seed_entities(driver, uuid4(), "雇主應給特別休假幾天？")
    assert seeds == ["特別休假"]


@pytest.mark.asyncio
async def test_find_seed_entities_keeps_hub_when_all_candidates_are_hubs(monkeypatch):
    """全部候選都是樞紐時原樣保留——BFS 需要至少一個起點。"""
    driver = _DegreeAwareDriver(
        names=["雇主", "勞工"],
        degrees={"雇主": 9999, "勞工": 8888},
    )
    seeds = await agent._find_seed_entities(driver, uuid4(), "雇主與勞工的關係？")
    assert set(seeds) == {"雇主", "勞工"}


@pytest.mark.asyncio
async def test_find_seed_entities_single_candidate_skips_degree_query():
    """候選 < 2 個時不多打一次度數查詢。"""
    driver = _DegreeAwareDriver(names=["特別休假"], degrees={"特別休假": 99999})
    seeds = await agent._find_seed_entities(driver, uuid4(), "特別休假幾天？")
    assert seeds == ["特別休假"]  # 即使度數超標，唯一候選仍保留
    assert not any("count(r) AS degree" in q for q in driver.queries)


@pytest.mark.asyncio
async def test_chat_runs_semantic_search_before_bfs_and_passes_scope(monkeypatch):
    """報告27 L1：`vector_search_facts` 先跑、推出的 `relevant_doc_ids` 當
    `bfs_query(scope_doc_ids=)` 前置約束傳入；`per_seed_limit` 一併帶上。"""
    kg_id = uuid4()
    doc_id = uuid4()
    call_order = []
    bfs_kwargs = {}

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        call_order.append("seeds")
        return ["特別休假"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        call_order.append("bfs")
        bfs_kwargs.update(kwargs)
        bfs_kwargs["hops"] = hops
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        call_order.append("facts")
        return [{"fact_text": "x", "subject": "特別休假", "rel_type": "CAUSES",
                 "object": "y", "source_doc_id": str(doc_id), "score": 0.9}]

    async def fake_resolve(question, embedding_provider, *, llm_provider):
        return None

    async def fake_fetch_document_map(driver, kg_id_arg, triples, fact_results):
        return {}

    embedding = _FakeEmbeddingProvider([0.1])
    llm = _FakeStreamLLM()
    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve)
    monkeypatch.setattr(agent, "_fetch_document_map", fake_fetch_document_map)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="特別休假幾天？", kg_id=kg_id)
    await _drain(await agent.chat(payload))

    assert call_order.index("facts") < call_order.index("bfs")
    assert bfs_kwargs["hops"] == 1  # 報告27 L0 預設
    assert bfs_kwargs["scope_doc_ids"] == {doc_id}
    assert bfs_kwargs["per_seed_limit"] == agent._BFS_PER_SEED_LIMIT


def test_chat_request_default_svo_hops_is_1():
    """報告27 L0：`svo_hops` 預設由 2 改為 1（`bfs_query` 現把它當最大跳數，
    先跑 1-hop、不足才擴展）。"""
    assert ChatRequest(question="x").svo_hops == 1
    assert ChatRequest(question="x", svo_hops=3).svo_hops == 3


@pytest.mark.asyncio
async def test_chat_wires_vector_search_facts_with_question_embedding_and_top_k(monkeypatch):
    kg_id = uuid4()
    vector_search_calls = []

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        vector_search_calls.append((kg_id_arg, vector, top_k))
        return [{"fact_text": "台積電 生產 晶片", "subject": "台積電", "rel_type": "CAUSES", "object": "晶片"}]

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None  # 本測試聚焦 Fact 檢索接線，不驗證關係連結（見專屬測試）

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="台積電是做什麼的？", kg_id=kg_id, top_k=7)
    response = await agent.chat(payload)
    await _drain(response)

    assert embedding.encoded_texts == ["台積電是做什麼的？"]
    assert vector_search_calls == [(kg_id, [0.1, 0.2, 0.3], 7)]
    assert "台積電 生產 晶片" in llm.prompt


def test_chat_request_default_top_k_is_20():
    """報告25 §4 發現1：語意 Fact 檢索預設候選數需 ≥ 事實清單截斷值
    `_FACT_LINE_TRUNCATE_K`（18），否則排序／截斷／重排永遠拿不到足夠候選。
    先前預設 5，已提高到 20（對齊 LangChain `EmbeddingsFilter` k=20）。"""
    assert ChatRequest(question="x").top_k == 20
    assert ChatRequest(question="x", top_k=50).top_k == 50


@pytest.mark.asyncio
async def test_chat_skips_semantic_search_when_use_svo_is_false(monkeypatch):
    kg_id = uuid4()
    vector_search_calls = []
    embed_calls = []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        vector_search_calls.append((kg_id_arg, vector, top_k))
        return []

    def fake_get_embedding_provider():
        embed_calls.append(True)
        return _FakeEmbeddingProvider([0.0])

    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", fake_get_embedding_provider)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="任意問題", kg_id=kg_id, use_svo=False)
    response = await agent.chat(payload)
    await _drain(response)

    assert vector_search_calls == []
    assert embed_calls == []  # use_svo=False 時完全不呼叫 embedding provider
    assert "沒有檢索到與問題直接相關的事實" in llm.prompt


@pytest.mark.asyncio
async def test_chat_yields_error_event_when_kg_id_missing():
    payload = ChatRequest(question="沒有指定 KG", kg_id=None)

    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(chunks) == 1
    assert "event: error" in chunks[0]


# ── _filter_triples_by_relation_type：§ 3.2 §c QFILTER（2026-08-18）─────────

def test_filter_triples_by_relation_type_keeps_only_matching_type():
    triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    filtered = agent._filter_triples_by_relation_type(triples, "CAUSES")

    assert len(filtered) == 1
    assert filtered[0].subject == "A"


def test_filter_triples_by_relation_type_none_passes_through_unfiltered():
    """QNOMATCH（None）時原樣回傳，不篩選——優雅降級。"""
    triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    filtered = agent._filter_triples_by_relation_type(triples, None)

    assert filtered == triples


def test_filter_triples_by_relation_type_empty_input():
    assert agent._filter_triples_by_relation_type([], "CAUSES") == []


# ── _relevant_doc_ids_from_facts／_filter_triples_by_source_doc_ids：
# 借用語意 Fact 檢索結果當 BFS 前置篩選範圍（2026-08-27）─────────────────────

def test_relevant_doc_ids_from_facts_collects_unique_ids():
    doc_a, doc_b = uuid4(), uuid4()
    fact_results = [
        {"fact_text": "F1", "source_doc_id": str(doc_a)},
        {"fact_text": "F2", "source_doc_id": str(doc_a)},
        {"fact_text": "F3", "source_doc_id": str(doc_b)},
    ]

    ids = agent._relevant_doc_ids_from_facts(fact_results)

    assert ids == {doc_a, doc_b}


def test_relevant_doc_ids_from_facts_ignores_missing_or_invalid():
    doc_a = uuid4()
    fact_results = [
        {"fact_text": "F1", "source_doc_id": str(doc_a)},
        {"fact_text": "F2", "source_doc_id": None},
        {"fact_text": "F3"},
        {"fact_text": "F4", "source_doc_id": "not-a-uuid"},
    ]

    ids = agent._relevant_doc_ids_from_facts(fact_results)

    assert ids == {doc_a}


def test_relevant_doc_ids_from_facts_empty_when_no_facts():
    assert agent._relevant_doc_ids_from_facts([]) == set()


def test_filter_triples_by_source_doc_ids_keeps_matching_and_unknown():
    """排除篩選：只排除明確知道來源、且不在允許範圍內的三元組；
    source_doc_id 為 None（無法判定）一律保留。"""
    doc_a, doc_b = uuid4(), uuid4()
    triple_in_range = _triple("A", "CAUSES", "B")
    triple_in_range.source_doc_id = doc_a
    triple_out_of_range = _triple("C", "CAUSES", "D")
    triple_out_of_range.source_doc_id = doc_b
    triple_unknown = _triple("E", "CAUSES", "F")
    triple_unknown.source_doc_id = None

    filtered = agent._filter_triples_by_source_doc_ids(
        [triple_in_range, triple_out_of_range, triple_unknown], {doc_a}
    )

    assert filtered == [triple_in_range, triple_unknown]


def test_filter_triples_by_source_doc_ids_no_filter_when_allowed_set_empty():
    """語意檢索沒有找到任何範圍訊號（allowed_doc_ids 為空）時原樣回傳，
    不強加篩選——優雅降級，不因為沒有篩選依據就讓查詢端拿不到結果。"""
    triples = [_triple("A", "CAUSES", "B"), _triple("C", "CAUSES", "D")]

    filtered = agent._filter_triples_by_source_doc_ids(triples, set())

    assert filtered == triples


def test_filter_triples_by_source_doc_ids_zero_out_guard_keeps_original():
    """歸零守衛（報告25 §4 發現1）：套用篩選會把原本非空的 BFS 結果清成
    空集合時，代表語意範圍與圖遍歷完全不一致——放棄篩選、原樣回傳，不讓
    較小的語意 top-K 訊號零化圖遍歷結果。"""
    doc_a, doc_b = uuid4(), uuid4()
    triple_out_1 = _triple("A", "CAUSES", "B")
    triple_out_1.source_doc_id = doc_b
    triple_out_2 = _triple("C", "CAUSES", "D")
    triple_out_2.source_doc_id = doc_b

    filtered = agent._filter_triples_by_source_doc_ids([triple_out_1, triple_out_2], {doc_a})

    assert filtered == [triple_out_1, triple_out_2]


def test_filter_triples_by_source_doc_ids_partial_overlap_still_filters():
    """部分重疊命中（2026-08-27 情境）：篩選後仍有結果時照常排除範圍外的
    三元組，歸零守衛不介入。"""
    doc_a, doc_b = uuid4(), uuid4()
    triple_in = _triple("A", "CAUSES", "B")
    triple_in.source_doc_id = doc_a
    triple_out = _triple("C", "CAUSES", "D")
    triple_out.source_doc_id = doc_b

    filtered = agent._filter_triples_by_source_doc_ids([triple_in, triple_out], {doc_a})

    assert filtered == [triple_in]


def test_relevant_doc_ids_from_facts_top_n_only_considers_highest_scored():
    """報告25 §4 發現1：範圍只取分數最高的前 N 筆推導（fact_results 已依
    score 遞減），避免 top_k 提高後被低分的跨文件事實稀釋。"""
    doc_a, doc_b, doc_c = uuid4(), uuid4(), uuid4()
    fact_results = [
        {"fact_text": "F1", "source_doc_id": str(doc_a), "score": 0.88},
        {"fact_text": "F2", "source_doc_id": str(doc_a), "score": 0.86},
        {"fact_text": "F3", "source_doc_id": str(doc_b), "score": 0.81},
        {"fact_text": "F4", "source_doc_id": str(doc_c), "score": 0.80},
    ]

    assert agent._relevant_doc_ids_from_facts(fact_results, top_n=2) == {doc_a}
    assert agent._relevant_doc_ids_from_facts(fact_results) == {doc_a, doc_b, doc_c}


def test_filter_facts_by_source_doc_ids_keeps_in_scope_and_unknown():
    """語意 Fact 清單也套文件範圍過濾（報告25 §4 發現1）：範圍內＋來源不明
    （source_doc_id 缺席／None／非 UUID）一律保留，只排除明確跨文件的。"""
    doc_a, doc_b = uuid4(), uuid4()
    facts = [
        {"fact_text": "in", "source_doc_id": str(doc_a)},
        {"fact_text": "out", "source_doc_id": str(doc_b)},
        {"fact_text": "none", "source_doc_id": None},
        {"fact_text": "missing"},
        {"fact_text": "bad", "source_doc_id": "not-a-uuid"},
    ]

    kept = agent._filter_facts_by_source_doc_ids(facts, {doc_a})

    assert [f["fact_text"] for f in kept] == ["in", "none", "missing", "bad"]


def test_filter_facts_by_source_doc_ids_zero_out_guard_and_empty_scope():
    """歸零守衛：範圍完全不重疊時放棄篩選、原樣回傳；allowed 為空時不篩選。"""
    doc_a, doc_b = uuid4(), uuid4()
    all_out = [
        {"fact_text": "x", "source_doc_id": str(doc_b)},
        {"fact_text": "y", "source_doc_id": str(doc_b)},
    ]

    assert agent._filter_facts_by_source_doc_ids(all_out, {doc_a}) == all_out
    assert agent._filter_facts_by_source_doc_ids(all_out, set()) == all_out


# ── chat()：驗證查詢時關係連結（QSIM/QFILTER）確實接線（2026-08-18）─────────

@pytest.mark.asyncio
async def test_chat_filters_bfs_triples_by_resolved_relation_type(monkeypatch):
    kg_id = uuid4()
    resolve_calls = []
    all_triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["A", "C"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return all_triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        resolve_calls.append((question, embedding_provider, llm_provider))
        return "CAUSES"

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="是什麼導致 B 的？", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert len(resolve_calls) == 1
    assert resolve_calls[0][0] == "是什麼導致 B 的？"
    assert resolve_calls[0][2] is llm  # llm_provider 有正確傳入
    assert "A 導致 B" in llm.prompt
    assert "C 導致 D" not in llm.prompt  # PART_OF 三元組已被篩掉


@pytest.mark.asyncio
async def test_chat_keeps_all_triples_when_relation_type_unresolved(monkeypatch):
    """QNOMATCH：解析不到型別時，兩個來源的三元組都應該保留。"""
    kg_id = uuid4()
    all_triples = [_triple("A", "CAUSES", "B"), _triple("C", "PART_OF", "D")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["A", "C"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return all_triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="隨便問點什麼", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert "A 導致 B" in llm.prompt
    assert "C 導致 D" in llm.prompt


# ── _serialize_sources / sources SSE 事件：終端機 CLI 顯示來源用（2026-08-18）──

def test_serialize_sources_includes_triples_facts_and_resolved_rel_type():
    triples = [_triple("A", "CAUSES", "B")]
    fact_results = [{"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
                      "rel_type": "CREATED_BY", "object": "SpaceX", "score": 0.9}]

    serialized = agent._serialize_sources(triples, fact_results, "CAUSES")

    assert serialized["resolved_rel_type"] == "CAUSES"
    assert serialized["triples"] == [{
        "subject": "A", "subject_type": "概念", "verb": "導致", "object": "B",
        "object_type": "概念", "rel_type": "CAUSES", "source": None,
        "source_svo_chunk_file": None, "document": None,
    }]
    assert serialized["facts"] == [{
        "fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
        "object": "SpaceX", "rel_type": "CREATED_BY", "score": 0.9,
        "document": None,
    }]


def test_serialize_sources_empty_when_nothing_retrieved():
    assert agent._serialize_sources([], [], None) == {
        "resolved_rel_type": None, "triples": [], "facts": [],
    }


# ── _serialize_sources 引用豐富化：附加 Document 中繼資料（2026-08-25）───────

def test_serialize_sources_attaches_document_metadata_when_available():
    """`document_map` 有對應 `source_doc_id` 時，triples／facts 都附加
    `effective_date` 等法規層級中繼資料，供回答來源標註現行狀態。"""
    from models.law_document import LawDocument

    doc_id = uuid4()
    triple = SVOTriple(subject="A", subject_type="概念", rel_type="CAUSES",
                        verb="導致", object="B", object_type="概念", source_doc_id=doc_id)
    fact_results = [{"fact_text": "F", "subject": "A", "object": "B",
                      "rel_type": "CAUSES", "score": 0.9, "source_doc_id": str(doc_id)}]
    doc = LawDocument(kg_id=uuid4(), source_doc_id=doc_id, source="s", title="勞工請假規則",
                       record_type="law", content_hash="h", update_date="20251209",
                       effective_date=None, effective_note="施行日另定")
    document_map = {str(doc_id): doc}

    serialized = agent._serialize_sources([triple], fact_results, "CAUSES", document_map)

    expected_document = {
        "title": "勞工請假規則", "update_date": "20251209",
        "effective_date": None, "effective_note": "施行日另定",
    }
    assert serialized["triples"][0]["document"] == expected_document
    assert serialized["facts"][0]["document"] == expected_document


def test_serialize_sources_document_none_when_source_doc_id_missing_from_map():
    """`source_doc_id` 存在但 `document_map` 查無對應（一般文件，或尚未
    跑過 Document/LawArticle 匯入的舊 KG）時優雅退化為 `None`，不拋例外。"""
    triple = SVOTriple(subject="A", subject_type="概念", rel_type="CAUSES",
                        verb="導致", object="B", object_type="概念", source_doc_id=uuid4())

    serialized = agent._serialize_sources([triple], [], "CAUSES", document_map={})

    assert serialized["triples"][0]["document"] is None


@pytest.mark.asyncio
async def test_fetch_document_map_dedupes_and_skips_lookup_when_no_doc_ids(monkeypatch):
    """triples／facts 都沒有 `source_doc_id` 時完全不呼叫 repository（不需要
    真的能連線的 driver）；有重複的 `source_doc_id` 時只查一次。"""

    class _ExplodingRepo:
        def __init__(self, driver):
            raise AssertionError("doc_ids 為空時不應建立 repository")

    monkeypatch.setattr(agent, "LawDocumentRepository", _ExplodingRepo)

    result = await agent._fetch_document_map(
        "fake-driver", uuid4(), [_triple("A", "CAUSES", "B")], [{"fact_text": "F"}]
    )

    assert result == {}


@pytest.mark.asyncio
async def test_fetch_document_map_returns_map_keyed_by_source_doc_id_string(monkeypatch):
    from models.law_document import LawDocument

    doc_id = uuid4()
    doc = LawDocument(kg_id=uuid4(), source_doc_id=doc_id, source="s", title="T",
                       record_type="law", content_hash="h")
    calls: list = []

    class _FakeRepo:
        def __init__(self, driver):
            pass

        async def get_document(self, kg_id, source_doc_id):
            calls.append(source_doc_id)
            return doc if source_doc_id == doc_id else None

    monkeypatch.setattr(agent, "LawDocumentRepository", _FakeRepo)
    triple = SVOTriple(subject="A", subject_type="概念", rel_type="CAUSES",
                        verb="導致", object="B", object_type="概念", source_doc_id=doc_id)

    result = await agent._fetch_document_map("fake-driver", uuid4(), [triple], [])

    assert calls == [doc_id]
    assert result == {str(doc_id): doc}


@pytest.mark.asyncio
async def test_chat_yields_sources_event_after_answer_stream(monkeypatch):
    kg_id = uuid4()
    triples = [_triple("A", "CAUSES", "B")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["A"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return [{"fact_text": "馬斯克 創立 SpaceX", "subject": "馬斯克",
                  "rel_type": "CREATED_BY", "object": "SpaceX"}]

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return "CAUSES"

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="是什麼導致 B 的？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    # 2026-08-24：event: grounding 在 sources 之後才送出（見該測試），
    # sources 因此不再是最後一個 chunk，改用 event 類型定位。
    sources_chunk = next(c for c in chunks if c.startswith("event: sources\n"))
    sources_data = json.loads(sources_chunk.split("\n", 1)[1][len("data: "):])
    assert sources_data["resolved_rel_type"] == "CAUSES"
    assert sources_data["triples"][0]["subject"] == "A"
    assert sources_data["facts"][0]["fact_text"] == "馬斯克 創立 SpaceX"


@pytest.mark.asyncio
async def test_chat_yields_grounding_event_after_sources(monkeypatch):
    """2026-08-24：串流結束後應額外送出 event: grounding（見 § 3.6 設計提案
    ／`docs/報告/16_事實接地性核對機制設計報告.md`），且順序在 sources 之後。"""
    kg_id = uuid4()

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return [{"fact_text": "公務員每日辦公時數為八小時。", "subject": "公務員",
                  "rel_type": "HAS_PROPERTY", "object": "八小時"}]

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(grounding_payload=json.dumps({
        "claims": [{"statement": "ok", "supported": False, "reason": "查無此數字"}]
    }))

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="考試院公務員每日辦公時數是幾小時？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    # 2026-08-28：方案 B 升級後，grounding 判定未接地會觸發限制性重新生成，
    # event: grounding 之後還會多送一個 event: status（phase=done），不再是
    # 最後一個 chunk，改用 event 類型定位（比照 sources 定位方式）。
    grounding_chunk = next(c for c in chunks if c.startswith("event: grounding\n"))
    grounding_data = json.loads(grounding_chunk.split("\n", 1)[1][len("data: "):])
    assert grounding_data == [
        {"statement": "ok", "is_claim": True, "supported": False, "reason": "查無此數字"}
    ]
    # 待核對文字（串流累積的完整回答）與 fact_text 清單皆確實送進了核對呼叫
    assert "公務員每日辦公時數為八小時。" in llm.grounding_prompts[0]


@pytest.mark.asyncio
async def test_chat_converts_simplified_chinese_in_final_answer_to_traditional(monkeypatch):
    """報告26 §4 #5：生成端（`qwen2.5:7b`）偶爾在自己的答案文字裡混簡體，
    跟已修的抽取端發現4（SVO 三元組欄位，`traditionalize_triples()`）是不同
    呼叫點的同一類問題。`chat()` 最終送給使用者的 `final_answer` 應套用
    同一套字元級選擇性轉繁（`_to_traditional_selective()`）。測試用的
    `kg_id` 在 workspace 底下沒有對應資料夾，`_kg_source_charset()` 依既有
    「找不到來源檔→空白名單」的優雅降級規則回傳空集合，等同全轉——不需要
    另外準備真實 workspace 檔案即可驗證轉換有生效。"""
    kg_id = uuid4()

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(answers=["补助经费额度为八千元。"])

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="補助經費額度是多少？", kg_id=kg_id, use_svo=False)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    answer_chunk = next(c for c in chunks if c.startswith("data: ") and '"token"' in c)
    answer_data = json.loads(answer_chunk[len("data: "):].strip())
    assert answer_data["token"] == "補助經費額度為八千元。"


@pytest.mark.asyncio
async def test_chat_grounding_check_includes_bfs_triples_not_just_vector_facts(monkeypatch):
    """2026-08-24 真實測試發現的迴歸案例：核對範圍必須與 `_build_prompt()`
    實際餵給生成模型的 context 一致（`_merge_fact_lines()`），只用
    `fact_results` 會把 BFS 三元組來源的正確陳述誤判為未接地（假陽性）。"""
    kg_id = uuid4()
    triples = [_triple("公務員", "HAS_PROPERTY", "四十小時", verb="每週辦公總時數為")]

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["公務員"]

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return triples

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []  # 這筆事實只由 BFS 找到，語意檢索沒有對應結果

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="公務員每週辦公總時數多少？", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert len(llm.grounding_prompts) == 1
    assert "公務員" in llm.grounding_prompts[0] and "四十小時" in llm.grounding_prompts[0]


@pytest.mark.asyncio
async def test_chat_yields_empty_grounding_event_when_no_facts_retrieved(monkeypatch):
    """未檢索到任何 Fact 時，`verify_fact_grounding()` 不呼叫 LLM 但仍應送出
    `event: grounding`（見該函式 docstring：明確標記未接地，不可靜默省略整個
    事件）。"""
    kg_id = uuid4()

    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)

    payload = ChatRequest(question="隨便問點什麼", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    grounding_chunk = next(c for c in chunks if c.startswith("event: grounding\n"))
    grounding_data = json.loads(grounding_chunk.split("\n", 1)[1][len("data: "):])
    assert len(grounding_data) == 1
    assert grounding_data[0]["supported"] is False
    assert llm.grounding_prompts == []  # 沒有 Fact 可供比對，不呼叫 LLM（兩次核對皆短路）


# ── 方案 B：限制性重新生成（2026-08-28，見 docs/報告/16 § 3、6）──


def _chat_common_monkeypatch(monkeypatch, llm, embedding, *, triples=None, facts=None):
    async def fake_find_seeds(driver, kg_id_arg, question, **kwargs):
        return ["A"] if triples else []

    async def fake_bfs_query(driver, kg_id_arg, seeds, hops, **kwargs):
        return triples or []

    async def fake_vector_search_facts(driver, kg_id_arg, vector, top_k):
        return facts or []

    async def fake_resolve_query_relation_type(question, embedding_provider, *, llm_provider):
        return None

    monkeypatch.setattr(agent, "_find_seed_entities", fake_find_seeds)
    monkeypatch.setattr(agent, "bfs_query", fake_bfs_query)
    monkeypatch.setattr(agent, "vector_search_facts", fake_vector_search_facts)
    monkeypatch.setattr(agent, "resolve_query_relation_type", fake_resolve_query_relation_type)
    monkeypatch.setattr(agent, "get_driver", lambda: "fake-driver")
    monkeypatch.setattr(agent, "get_embedding_provider", lambda: embedding)
    monkeypatch.setattr(agent, "get_llm_provider", lambda: llm)


@pytest.mark.asyncio
async def test_chat_decomposes_compound_question_into_isolated_generation_calls(monkeypatch):
    """報告27 C#2 M1：複合問題（≥2 個句末問號）且有檢索到事實時，`chat()`
    應改用 `_generate_decomposed_answer()`——每個子問題各自一次生成呼叫，
    取代原本的單次生成。最終送給使用者的 `data:` token 是組裝後的完整文字。"""
    kg_id = uuid4()
    facts = [{"fact_text": "連續僱用滿三個月得申請獎勵金", "subject": "連續僱用",
              "rel_type": "RELATED_TO", "object": "三個月"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(answers=["連續三個月。", "以三個月為限。"])
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="連續僱用滿多久才能申請獎勵金？獎勵金最多發給幾個月？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(llm.prompts) == 2  # 兩個子問題各自獨立生成，非單次生成
    data_chunk = next(c for c in chunks if c.startswith("data: ") and "token" in c)
    token = json.loads(data_chunk[len("data: "):])["token"]
    assert "連續三個月。" in token
    assert "以三個月為限。" in token


@pytest.mark.asyncio
async def test_chat_single_question_mark_uses_single_generation_call(monkeypatch):
    """非複合問題（單一句末問號）行為與 M1 修改前完全一致——只呼叫一次生成，
    不觸發 `_generate_decomposed_answer()`。"""
    kg_id = uuid4()
    facts = [{"fact_text": "婚假為八日", "subject": "婚假", "rel_type": "HAS_PROPERTY", "object": "八日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(answers=["婚假為八日。"])
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="婚假幾天？", kg_id=kg_id)
    response = await agent.chat(payload)
    await _drain(response)

    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_chat_no_regeneration_when_fully_grounded(monkeypatch):
    """全部陳述句皆接地時，不應該多花一次 LLM 呼叫重新生成——這是方案 B
    刻意設計的成本控制（見 chat() docstring：只有真的抓到未接地內容才多付
    一次生成的延遲）。"""
    kg_id = uuid4()
    facts = [{"fact_text": "婚假為八日", "subject": "婚假", "rel_type": "HAS_PROPERTY", "object": "八日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["婚假為八日。"],
        grounding_payloads=[json.dumps({"claims": [{"statement": "婚假為八日。", "supported": True, "reason": ""}]})],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="婚假幾天？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(llm.prompts) == 1  # 沒有觸發第二次（限制性重新生成）呼叫
    data_chunk = next(c for c in chunks if c.startswith("data: "))
    assert json.loads(data_chunk[len("data: "):])["token"] == "婚假為八日。"
    done_chunk = next(
        c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c
    )
    assert json.loads(done_chunk.split("\n", 1)[1][len("data: "):])["regenerated"] is False


@pytest.mark.asyncio
async def test_chat_regenerates_with_constrained_prompt_when_ungrounded(monkeypatch):
    """草稿有未接地陳述時，應該用 `_build_constrained_prompt()` 重新生成一次，
    使用者最終收到的 `data:` 事件是修正版而非草稿（對應使用者要求「寧願說
    不知道，也禁止亂回答」）。"""
    kg_id = uuid4()
    facts = [{"fact_text": "婚假為八日", "subject": "婚假", "rel_type": "HAS_PROPERTY", "object": "八日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["婚假三日，我自己推測的。", "資料未明確記載，無法確認婚假天數。"],
        grounding_payloads=[
            json.dumps({"claims": [{"statement": "婚假三日", "supported": False, "reason": "查無此數字"}]}),
            json.dumps({"claims": [{"statement": "資料未明確記載，無法確認婚假天數。", "supported": True, "reason": ""}]}),
        ],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="婚假幾天？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(llm.prompts) == 2  # 草稿 + 限制性重新生成各一次
    constrained_prompt = llm.prompts[1]
    # 2026-08-28：讀完 Dhuliawala et al. (2023) CoVe 全文後修正——修正步驟的
    # prompt 刻意不放草稿或未接地陳述（避免文字錨定效應讓模型重複自己的
    # 錯誤），只放事實清單＋問題＋強約束指示。
    assert "婚假三日" not in constrained_prompt
    assert "資料未明確記載" in constrained_prompt  # 明確要求答不知道而非臆測

    data_chunk = next(c for c in chunks if c.startswith("data: "))
    assert json.loads(data_chunk[len("data: "):])["token"] == "資料未明確記載，無法確認婚假天數。"
    assert "婚假三日" not in data_chunk  # 使用者最終看到的不是未接地的草稿

    done_chunk = next(
        c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c
    )
    assert json.loads(done_chunk.split("\n", 1)[1][len("data: "):])["regenerated"] is True

    grounding_chunk = next(c for c in chunks if c.startswith("event: grounding\n"))
    grounding_data = json.loads(grounding_chunk.split("\n", 1)[1][len("data: "):])
    assert grounding_data[0]["supported"] is True  # 反映修正版，非草稿的核對結果


@pytest.mark.asyncio
async def test_chat_decomposed_regeneration_keeps_subquestion_structure_when_ungrounded(monkeypatch):
    """報告27 C#2 M1（2026-09-05 修正）：複合問題的草稿被判未接地時，限制性
    重新生成也要保留分解結構——逐子問題各自重生（各一次 `stream()` 呼叫），
    而非退回單次生成整個複合問題。這曾是真實測出的 bug：重生路徑漏接分解，
    見 `_generate_decomposed_constrained_answer()` docstring。"""
    kg_id = uuid4()
    facts = [{"fact_text": "連續僱用滿三個月得申請獎勵金", "subject": "連續僱用",
              "rel_type": "RELATED_TO", "object": "三個月"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["亂猜的答案一。", "亂猜的答案二。", "資料未明確記載，無法確認。", "以三個月為限。"],
        grounding_payloads=[
            json.dumps({"claims": [{"statement": "亂猜的答案一。", "supported": False, "reason": "查無依據"}]}),
            json.dumps({"claims": [{"statement": "以三個月為限。", "supported": True, "reason": ""}]}),
        ],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="連續僱用滿多久才能申請獎勵金？獎勵金最多發給幾個月？", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    # 草稿：每子問題各一次 stream() 呼叫（2）＋重生：每子問題各一次（2）＝4。
    assert len(llm.prompts) == 4
    data_chunk = next(c for c in chunks if c.startswith("data: ") and "token" in c)
    token = json.loads(data_chunk[len("data: "):])["token"]
    assert "資料未明確記載，無法確認。" in token
    assert "以三個月為限。" in token
    assert "亂猜的答案" not in token  # 使用者最終看到的是重生版，非未接地草稿


@pytest.mark.asyncio
async def test_chat_no_regeneration_when_only_non_claim_sentences_unsupported(monkeypatch):
    """報告25 §4 發現6→⑥：草稿的具體主張都接地，只有引言句／問題回貼這類
    非主張句被判「未接地」時，不觸發限制性重生成——否則會把正確草稿改壞。"""
    kg_id = uuid4()
    facts = [{"fact_text": "婚假為八日", "subject": "婚假", "rel_type": "HAS_PROPERTY", "object": "八日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["婚假幾天？根據提供的事實，婚假為八日。"],
        grounding_payloads=[json.dumps({"claims": [
            {"statement": "婚假幾天？", "is_claim": False, "supported": False, "reason": "問題被當標題回貼，非陳述"},
            {"statement": "根據提供的事實，婚假為八日。", "is_claim": True, "supported": True, "reason": "與事實一致"},
        ]})],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    payload = ChatRequest(question="婚假幾天？", kg_id=kg_id)
    chunks = await _drain(await agent.chat(payload))

    assert len(llm.prompts) == 1  # 沒有觸發限制性重生成
    done_chunk = next(c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c)
    assert json.loads(done_chunk.split("\n", 1)[1][len("data: "):])["regenerated"] is False
    data_chunk = next(c for c in chunks if c.startswith("data: "))
    assert "婚假為八日" in json.loads(data_chunk[len("data: "):])["token"]


@pytest.mark.asyncio
async def test_chat_targeted_correction_keeps_grounded_sentences_when_partly_ungrounded(monkeypatch):
    """報告32 §9 G1（2b 定向修訂）：草稿裡部分主張接地、部分未接地時，只重寫
    未接地的主張句（一次 LLM 呼叫），接地的句子原樣保留——不再整段重寫把已
    對的部分一併改壞（T1 的 ~75% 觸發率、正確草稿被改成「未記載」）。"""
    kg_id = uuid4()
    facts = [{"fact_text": "甲項為三十日", "subject": "甲項", "rel_type": "HAS_PROPERTY", "object": "三十日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["甲項為三十日。乙項為六個半月。", "修正1：（此部分）資料未明確記載，無法確認乙項期程。"],
        grounding_payloads=[
            json.dumps({"claims": [
                {"statement": "甲項為三十日。", "is_claim": True, "supported": True, "reason": "與事實一致"},
                {"statement": "乙項為六個半月。", "is_claim": True, "supported": False, "reason": "查無此數字"},
            ]}),
            json.dumps({"claims": [
                {"statement": "甲項為三十日。", "is_claim": True, "supported": True, "reason": ""},
                {"statement": "（此部分）資料未明確記載，無法確認乙項期程。", "is_claim": True, "supported": True, "reason": ""},
            ]}),
        ],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    chunks = await _drain(await agent.chat(ChatRequest(question="甲項乙項各多久？", kg_id=kg_id)))

    assert len(llm.prompts) == 2  # 草稿 + 定向修訂各一次（沒有整段重寫）
    targeted_prompt = llm.prompts[1]
    assert "下列片段來自一份草稿答案" in targeted_prompt  # 是定向修訂 prompt
    assert "乙項為六個半月。" in targeted_prompt          # 未接地片段有傳進去（joint 的一面）
    assert "不要沿用" in targeted_prompt                  # 但明確禁止沿用未查核數值

    token = json.loads(next(c for c in chunks if c.startswith("data: ") and "token" in c)[len("data: "):])["token"]
    assert "甲項為三十日。" in token          # 接地句原樣保留
    assert "六個半月" not in token            # 未接地句被換掉
    assert "資料未明確記載" in token

    done = next(c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c)
    assert json.loads(done.split("\n", 1)[1][len("data: "):])["regenerated"] is True


@pytest.mark.asyncio
async def test_chat_targeted_correction_parse_failure_falls_back_to_full_regen(monkeypatch):
    """定向修訂的 LLM 輸出行數對不上（解析失敗）→ 退回整份限制性重生成
    （`_build_constrained_prompt()`，factored、不給草稿）。"""
    kg_id = uuid4()
    facts = [{"fact_text": "甲項為三十日", "subject": "甲項", "rel_type": "HAS_PROPERTY", "object": "三十日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["甲項為三十日。乙項為六個半月。", "亂七八糟、沒有依格式輸出的回應", "資料未明確記載，無法確認。"],
        grounding_payloads=[
            json.dumps({"claims": [
                {"statement": "甲項為三十日。", "is_claim": True, "supported": True, "reason": ""},
                {"statement": "乙項為六個半月。", "is_claim": True, "supported": False, "reason": "查無"},
            ]}),
            json.dumps({"claims": [{"statement": "資料未明確記載，無法確認。", "is_claim": True, "supported": True, "reason": ""}]}),
        ],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    chunks = await _drain(await agent.chat(ChatRequest(question="甲項乙項各多久？", kg_id=kg_id)))

    assert len(llm.prompts) == 3  # 草稿 + 定向修訂(失敗) + 整份重生
    assert "下列片段來自一份草稿答案" not in llm.prompts[2]  # 整份重生 prompt 不含草稿片段
    assert "資料未明確記載" in llm.prompts[2]
    token = json.loads(next(c for c in chunks if c.startswith("data: ") and "token" in c)[len("data: "):])["token"]
    assert "六個半月" not in token


@pytest.mark.asyncio
async def test_chat_full_regen_when_no_grounded_claim_to_keep(monkeypatch):
    """草稿裡每一句主張都未接地（`grounded_claim_count == 0`）→ 沒有東西可保留，
    走既有的整份 factored 重生，不呼叫定向修訂。"""
    kg_id = uuid4()
    facts = [{"fact_text": "甲項為三十日", "subject": "甲項", "rel_type": "HAS_PROPERTY", "object": "三十日"}]
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM(
        answers=["甲項為十日。乙項為六個半月。", "資料未明確記載，無法確認。"],
        grounding_payloads=[
            json.dumps({"claims": [
                {"statement": "甲項為十日。", "is_claim": True, "supported": False, "reason": "查無"},
                {"statement": "乙項為六個半月。", "is_claim": True, "supported": False, "reason": "查無"},
            ]}),
            json.dumps({"claims": [{"statement": "資料未明確記載，無法確認。", "is_claim": True, "supported": True, "reason": ""}]}),
        ],
    )
    _chat_common_monkeypatch(monkeypatch, llm, embedding, facts=facts)

    chunks = await _drain(await agent.chat(ChatRequest(question="甲項乙項各多久？", kg_id=kg_id)))

    assert len(llm.prompts) == 2  # 草稿 + 整份重生（沒有定向修訂那次）
    assert "下列片段來自一份草稿答案" not in llm.prompts[1]
    done = next(c for c in chunks if c.startswith("event: status\n") and '"phase": "done"' in c)
    assert json.loads(done.split("\n", 1)[1][len("data: "):])["regenerated"] is True


@pytest.mark.asyncio
async def test_chat_emits_status_events_in_expected_order(monkeypatch):
    kg_id = uuid4()
    embedding = _FakeEmbeddingProvider([0.1, 0.2, 0.3])
    llm = _FakeStreamLLM()  # 預設空 claims，不觸發重新生成
    _chat_common_monkeypatch(monkeypatch, llm, embedding)

    payload = ChatRequest(question="任意問題", kg_id=kg_id)
    response = await agent.chat(payload)
    chunks = await _drain(response)

    status_phases = [
        json.loads(c.split("\n", 1)[1][len("data: "):])["phase"]
        for c in chunks
        if c.startswith("event: status\n")
    ]
    assert status_phases == ["generating", "verifying", "done"]


@pytest.mark.asyncio
async def test_chat_yields_empty_sources_event_when_kg_id_missing():
    """kg_id 缺失時提早 return error 事件，不應該再多送一個 sources 事件。"""
    payload = ChatRequest(question="沒有指定 KG", kg_id=None)

    response = await agent.chat(payload)
    chunks = await _drain(response)

    assert len(chunks) == 1
    assert "event: sources" not in chunks[0]
