"""N4 搬移差分測試（報告160 U1）：搬移後的程式對 golden（搬移前實作產生）逐案比對。

golden 由 ``python -m tests.services.n4_differential_harness --write-golden`` 在**搬移前**產生；
內容含輸出、例外型別與訊息、``add_candidate``／``log_escalation`` 呼叫序列與 logger 記錄。
"""

import json

import pytest

from tests.services.n4_differential_harness import GOLDEN, run_all


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual():
    from services import svo_service

    return run_all(svo_service)


def test_case_count_at_least_1000(golden):
    assert len(golden) >= 1000


def test_same_case_list_shape(golden, actual):
    assert [(g["kind"], g["args"]) for g in golden] == [(a["kind"], a["args"]) for a in actual]


def test_every_case_result_identical(golden, actual):
    diffs = [(i, g["kind"]) for i, (g, a) in enumerate(zip(golden, actual)) if g["res"] != a["res"]]
    assert not diffs, f"{len(diffs)} 案不一致，前幾筆：{diffs[:5]}"
