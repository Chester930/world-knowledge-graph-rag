"""單元測試：全鏈路血統追蹤器（Lineage Tracker）。

驗證：
1. 階段一檢索召回與缺失判定。
2. 階段二上下文組裝保留與丟棄判定。
3. 階段三生成輸出與平滑化/幻覺因果歸因診斷。
4. 全流程順利保全之成功判定。
5. 檔案輸出與 JSON 序列化。
"""
import json
import pytest
from pathlib import Path
from models.eval_schema import (
    AtomicGoldFact,
    FullQueryLineage,
    RetrievalStageLineage,
    RetrievedEvidence,
)
from services.lineage_tracker import LineageTracker


class _FakeJudge:
    def __init__(self, response: str):
        self._response = response
        self.calls = 0

    async def generate_json(self, prompt: str) -> str:
        self.calls += 1
        return self._response


def test_lineage_tracker_stage1_failure():
    tracker = LineageTracker(
        query_id="26-Q5",
        arm="M1",
        question="災區受災勞工保費補助期間與起算日？",
    )
    gold_spans = ["自災害發生之當月一日起計算六個月", "由中央政府支應"]

    # 檢索只召回了無關內容
    retrieved = ["勞動基準法第38條特別休假規定..."]
    lineage1 = tracker.record_retrieval(retrieved, gold_spans, latency_ms=120.5)

    assert lineage1.recall_rate == 0.0
    assert len(lineage1.missed_exact_spans) == 2

    # 歸因診斷
    diag = tracker.diagnose_failure(gold_spans)
    assert "Stage 1 Retrieval Failure" in diag


def test_lineage_tracker_stage2_failure():
    tracker = LineageTracker(
        query_id="26-Q5",
        arm="M4",
        question="災區受災勞工保費補助期間與起算日？",
    )
    gold_spans = ["自災害發生之當月一日起計算六個月", "由中央政府支應"]

    # 檢索有召回
    retrieved = [
        "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。",
        "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。",
    ]
    tracker.record_retrieval(retrieved, gold_spans, latency_ms=85.0)

    # 經過截斷，漏掉了「自災害發生之當月一日起計算六個月」
    truncated_context = "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
    tracker.record_context_assembly(truncated_context, gold_spans, total_tokens=150)

    diag = tracker.diagnose_failure(gold_spans)
    assert "Stage 2 Assembly Failure" in diag
    assert "dropped in context assembly" in diag


def test_lineage_tracker_stage3_smoothing_failure():
    tracker = LineageTracker(
        query_id="26-Q5",
        arm="M4",
        question="災區受災勞工保費補助期間與起算日？",
    )
    gold_spans = ["自災害發生之當月一日起計算六個月", "由中央政府支應"]

    # 階段一與階段二都完整包含
    full_text = (
        "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。"
        "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
    )
    tracker.record_retrieval([full_text], gold_spans, latency_ms=90.0)
    tracker.record_context_assembly(full_text, gold_spans, total_tokens=200)

    # 階段三：生成模型擅自平滑化為「自災害發生當日起計算」
    smoothed_answer = (
        "災後六個月期間由中央政府支應，其期間自災害發生當日起計算六個月。"
    )
    tracker.record_generation(
        raw_draft=smoothed_answer,
        final_output=smoothed_answer,
        grounding_passed=True,
        latency_ms=1500.0,
    )

    diag = tracker.diagnose_failure(gold_spans)
    assert "Stage 3 Generation Failure" in diag
    assert "Intrinsic Hallucination / Smoothing" in diag


def test_lineage_tracker_success_and_export(tmp_path: Path):
    tracker = LineageTracker(
        query_id="26-Q5",
        arm="M4",
        question="災區受災勞工保費補助期間與起算日？",
    )
    gold_spans = ["自災害發生之當月一日起計算六個月", "由中央政府支應"]

    full_text = (
        "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。"
        "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
    )
    tracker.record_retrieval([full_text], gold_spans, latency_ms=90.0)
    tracker.record_context_assembly(full_text, gold_spans, total_tokens=200)

    exact_answer = (
        "受災勞工保險費由中央政府支應六個月；其期間自災害發生之當月一日起計算六個月。"
    )
    tracker.record_generation(
        raw_draft=exact_answer,
        final_output=exact_answer,
        grounding_passed=True,
        latency_ms=1200.0,
    )

    diag = tracker.diagnose_failure(gold_spans)
    assert "Success" in diag

    export_file = tmp_path / "lineage_26-Q5.json"
    tracker.export_to_file(gold_spans, export_file)
    assert export_file.exists()

    with open(export_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["query_id"] == "26-Q5"
    assert data["stage1_retrieval"]["recall_rate"] == 1.0
    assert "Success" in data["failure_attribution"]


@pytest.mark.asyncio
async def test_record_retrieval_async_no_judge_matches_sync():
    """報告52後續修正：judge_llm_provider=None 時，async 版與 sync 版逐位元相同"""
    gold_spans = ["自災害發生之當月一日起計算六個月", "由中央政府支應"]
    retrieved = ["勞動基準法第38條特別休假規定..."]

    sync_tracker = LineageTracker("26-Q5", "M1", "起算日？")
    sync_lineage = sync_tracker.record_retrieval(retrieved, gold_spans, latency_ms=120.5)

    async_tracker = LineageTracker("26-Q5", "M1", "起算日？")
    async_lineage = await async_tracker.record_retrieval_async(
        retrieved, gold_spans, latency_ms=120.5, judge_llm_provider=None,
    )
    assert async_lineage.recall_rate == sync_lineage.recall_rate
    assert async_lineage.missed_exact_spans == sync_lineage.missed_exact_spans


@pytest.mark.asyncio
async def test_record_retrieval_async_rescues_paraphrased_fact():
    """17-Q1 情境：Fact-RAG 檢索到的原文被自然語言化改寫，語意 fallback 應救回 Stage 1"""
    tracker = LineageTracker("17-Q1", "M4", "勞工結婚可以請幾天婚假？")
    gold_spans = ["勞工結婚者給予婚假八日，工資照給"]
    retrieved = ["勞工結婚時可以請八日的婚假，這段期間工資照常發給。"]

    judge = _FakeJudge(json.dumps({"results": [{"index": 1, "present": True}]}))
    lineage = await tracker.record_retrieval_async(
        retrieved, gold_spans, latency_ms=200.0, judge_llm_provider=judge,
    )
    assert lineage.recall_rate == 1.0
    assert lineage.missed_exact_spans == []

    diag = await tracker.diagnose_failure_async(gold_spans, judge_llm_provider=judge)
    assert "Success" in diag


@pytest.mark.asyncio
async def test_diagnose_failure_async_stage3_keeps_real_smoothing_error():
    """26-Q5 情境：Stage1/2都完整，Stage3的「當日」平滑化是真錯誤，語意fallback不該救回"""
    tracker = LineageTracker("26-Q5", "M4", "災區受災勞工保費補助期間與起算日？")
    gold_spans = ["自災害發生之當月一日起計算六個月", "由中央政府支應"]

    full_text = (
        "前條所定災後六個月期間之計算，自災害發生之當月一日起計算六個月。"
        "其災後六個月期間內被保險人應負擔之保險費，由中央政府支應。"
    )
    await tracker.record_retrieval_async(
        [full_text], gold_spans, latency_ms=90.0, judge_llm_provider=None,
    )
    await tracker.record_context_assembly_async(
        full_text, gold_spans, total_tokens=200, judge_llm_provider=None,
    )

    smoothed_answer = "災後六個月期間由中央政府支應，其期間自災害發生當日起計算六個月。"
    tracker.record_generation(
        raw_draft=smoothed_answer, final_output=smoothed_answer,
        grounding_passed=True, latency_ms=1500.0,
    )

    judge = _FakeJudge(json.dumps({"results": [{"index": 1, "present": False}]}))
    diag = await tracker.diagnose_failure_async(gold_spans, judge_llm_provider=judge)
    assert "Stage 3 Generation Failure" in diag
    assert "Intrinsic Hallucination / Smoothing" in diag


# ── 報告57 §2.2：SNR / Chain Completeness ──────────────────────────


def test_snr_computed_from_hit_spans_and_retrieved_length():
    tracker = LineageTracker(query_id="t-snr", arm="M1", question="q")
    lineage = tracker.record_retrieval(["ABCDEFGHIJ"], ["ABC"], latency_ms=1.0)
    assert lineage.retrieved_char_count == 10
    assert lineage.snr == 0.3


def test_snr_zero_when_no_retrieved_text():
    tracker = LineageTracker(query_id="t-snr-empty", arm="M1", question="q")
    lineage = tracker.record_retrieval([], ["ABC"], latency_ms=1.0)
    assert lineage.retrieved_char_count == 0
    assert lineage.snr == 0.0


def test_chain_completeness_none_without_atomic_gold_facts():
    """未傳入 atomic_gold_facts（既有呼叫端）＝零行為變化，不是0分。"""
    tracker = LineageTracker(query_id="t-cc-none", arm="M1", question="q")
    lineage = tracker.record_retrieval(["span1"], ["span1"], latency_ms=1.0)
    assert lineage.chain_completeness is None


def test_chain_completeness_none_when_single_source_law():
    """單一文件題目不適用此指標，回傳None而非懲罰性0分。"""
    tracker = LineageTracker(query_id="t-cc-single", arm="M1", question="q")
    facts = [
        AtomicGoldFact(exact_span="span1", source_law="N0030006", source_article="第2條"),
        AtomicGoldFact(exact_span="span2", source_law="N0030006", source_article="第7條"),
    ]
    lineage = tracker.record_retrieval(
        ["span1span2"], ["span1", "span2"], latency_ms=1.0, atomic_gold_facts=facts,
    )
    assert lineage.chain_completeness is None


def test_chain_completeness_partial_across_two_source_laws():
    """26-Q5類跨文件情境：只召回其中一份文件的事實，鏈完整度0.5。"""
    tracker = LineageTracker(query_id="26-Q5", arm="K", question="q")
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030", source_article="第3條",
        ),
        AtomicGoldFact(
            exact_span="其保費由中央政府補助", source_law="N0050011", source_article="第5條",
        ),
    ]
    gold_spans = [f.exact_span for f in facts]
    lineage = tracker.record_retrieval(
        ["自災害發生之當月一日起計算六個月"], gold_spans, latency_ms=1.0, atomic_gold_facts=facts,
    )
    assert lineage.chain_completeness == 0.5


def test_chain_completeness_full_when_all_source_laws_hit():
    tracker = LineageTracker(query_id="26-Q5", arm="K", question="q")
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030", source_article="第3條",
        ),
        AtomicGoldFact(
            exact_span="其保費由中央政府補助", source_law="N0050011", source_article="第5條",
        ),
    ]
    gold_spans = [f.exact_span for f in facts]
    lineage = tracker.record_retrieval(
        gold_spans, gold_spans, latency_ms=1.0, atomic_gold_facts=facts,
    )
    assert lineage.chain_completeness == 1.0


def test_chain_completeness_excludes_canary_synthetic_source_law():
    """Type-E拒答題的synthetic source_law='None'不計入分組（同evaluation_eligibility慣例）。"""
    tracker = LineageTracker(query_id="canary-P1", arm="M1", question="q")
    facts = [AtomicGoldFact(exact_span="未記載相關規定", source_law="None", source_article="None")]
    lineage = tracker.record_retrieval(
        [], ["未記載相關規定"], latency_ms=1.0, atomic_gold_facts=facts,
    )
    assert lineage.chain_completeness is None


@pytest.mark.asyncio
async def test_record_retrieval_async_chain_completeness_and_snr_match_sync():
    facts = [
        AtomicGoldFact(
            exact_span="自災害發生之當月一日起計算六個月",
            source_law="N0050030", source_article="第3條",
        ),
        AtomicGoldFact(
            exact_span="其保費由中央政府補助", source_law="N0050011", source_article="第5條",
        ),
    ]
    gold_spans = [f.exact_span for f in facts]
    retrieved = ["自災害發生之當月一日起計算六個月"]

    sync_tracker = LineageTracker("26-Q5", "K", "q")
    sync_lineage = sync_tracker.record_retrieval(
        retrieved, gold_spans, latency_ms=1.0, atomic_gold_facts=facts,
    )

    async_tracker = LineageTracker("26-Q5", "K", "q")
    async_lineage = await async_tracker.record_retrieval_async(
        retrieved, gold_spans, latency_ms=1.0, judge_llm_provider=None, atomic_gold_facts=facts,
    )

    assert async_lineage.chain_completeness == sync_lineage.chain_completeness == 0.5
    assert async_lineage.snr == sync_lineage.snr
    assert async_lineage.retrieved_char_count == sync_lineage.retrieved_char_count


# ── 報告62 T0：檢索 trace 欄位（只記錄、不參與判定、舊 records 相容）──────────

def test_record_retrieval_stores_trace_without_affecting_scores():
    gold = ["由中央政府支應"]
    evidence = [
        RetrievedEvidence(kind="fact", rank=0, text="由中央政府支應", score=0.9,
                          source_doc_id="d1", source_svo_chunk_index=2, in_prompt=True),
        RetrievedEvidence(kind="fact", rank=1, text="無關", score=0.5, in_prompt=False),
    ]
    plain = LineageTracker("q", "K", "問").record_retrieval(["由中央政府支應", "無關"], gold, 1.0)
    traced = LineageTracker("q", "K", "問").record_retrieval(
        ["由中央政府支應", "無關"], gold, 1.0, retrieval_trace=evidence,
    )

    assert traced.retrieval_trace == evidence
    assert plain.retrieval_trace == []
    assert (traced.recall_rate, traced.snr, traced.retrieved_char_count) == (
        plain.recall_rate, plain.snr, plain.retrieved_char_count)


def test_record_context_assembly_stores_prompt_lines_without_affecting_retention():
    gold = ["由中央政府支應"]
    tracker = LineageTracker("q", "K", "問")
    ctx = tracker.record_context_assembly(
        "- 由中央政府支應", gold, total_tokens=4,
        prompt_context_lines=[["- 無關"]],  # prompt 行不含 gold，但既有判定仍只看傳入的 context 字串
    )

    assert ctx.prompt_context_lines == [["- 無關"]]
    assert ctx.retained_exact_spans == gold  # 判定維持與凍結基準同定義


@pytest.mark.asyncio
async def test_async_variants_accept_trace_fields():
    tracker = LineageTracker("q", "K", "問")
    ev = [RetrievedEvidence(kind="triple", rank=0, text="A 導致 B")]

    r = await tracker.record_retrieval_async(["A 導致 B"], [], 1.0, retrieval_trace=ev)
    c = await tracker.record_context_assembly_async("A 導致 B", [], prompt_context_lines=[["- A 導致 B"]])

    assert r.retrieval_trace == ev
    assert c.prompt_context_lines == [["- A 導致 B"]]


def test_old_records_without_trace_fields_still_deserialize():
    """凍結基準的 records 沒有 retrieval_trace／prompt_context_lines，必須能反序列化。"""
    old = {
        "query_id": "q", "arm": "K", "question": "問",
        "stage1_retrieval": {"arm": "K", "retrieval_latency_ms": 1.0,
                             "retrieved_chunk_ids": [], "retrieved_fact_ids": ["", ""],
                             "hit_exact_spans": [], "missed_exact_spans": [], "recall_rate": 0.0,
                             "retrieved_char_count": 0, "snr": 0.0, "chain_completeness": None},
        "stage2_context": {"total_context_tokens": 0, "retained_exact_spans": [],
                           "dropped_exact_spans": [], "verbalization_omissions": []},
        "stage3_generation": {"llm_model": "m", "generation_latency_ms": 1.0, "raw_draft": "",
                              "grounding_passed": True, "final_output": ""},
        "failure_attribution": None,
    }

    lineage = FullQueryLineage(**old)

    assert lineage.stage1_retrieval.retrieval_trace == []
    assert lineage.stage2_context.prompt_context_lines == []
    assert isinstance(lineage.stage1_retrieval, RetrievalStageLineage)
