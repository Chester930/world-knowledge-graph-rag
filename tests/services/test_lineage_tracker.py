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
from services.lineage_tracker import LineageTracker


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
