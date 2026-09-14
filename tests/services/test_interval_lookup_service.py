# -*- coding: utf-8 -*-
"""報告32 §9 G2 方案E（2026-09-13）測試：確定性「數值區間 → 對應值」查表
覆核。真實案例取自 `run_refusal_canary.py`（報告32 §9 C）的 P2/P3/P5/P6
探針，見報告42 §7。"""
from services.interval_lookup_service import (
    evaluate_lookup_override,
    extract_question_value,
    is_refusal_text,
    parse_interval_facts,
)

# --- fixture：真實金絲雀探針對應的事實清單 -----------------------------------
_VARIANCE_FACTS = [
    "1 以上，未滿 10 的容許濃度 變量係數為 2",
    "10 以上，未滿 100 的容許濃度 變量係數為 1.5",
]
_LEAD_FACTS = ["血中鉛濃度在十 μg/dl 以上者 屬於 第三級管理"]


class TestParseIntervalFacts:
    def test_parses_bounded_interval(self):
        result = parse_interval_facts(_VARIANCE_FACTS)
        assert len(result) == 2
        assert result[0].lower == 1.0 and result[0].upper == 10.0 and result[0].value == "2"
        assert result[1].lower == 10.0 and result[1].upper == 100.0 and result[1].value == "1.5"

    def test_parses_open_ended_interval_with_chinese_numeral(self):
        """「十」須先經 cn2an 正規化成 10 才抓得到——這是方案E存在的主因之一：
        中文數字混在句子裡讓舊有正則抓不到。"""
        result = parse_interval_facts(_LEAD_FACTS)
        assert len(result) == 1
        assert result[0].lower == 10.0
        assert result[0].upper is None
        assert "第3級" in result[0].value or "第三級" in result[0].value

    def test_no_interval_facts_returns_empty(self):
        assert parse_interval_facts(["普通傷病假一年內未超過三十日部分 工資折半發給"]) == []

    def test_malformed_interval_where_upper_not_greater_than_lower_is_skipped(self):
        # 防呆：抓錯數字對（上界 <= 下界）時跳過，不硬湊出一則錯誤的區間。
        assert parse_interval_facts(["10 以上，未滿 5 的容許濃度 變量係數為 2"]) == []


class TestExtractQuestionValue:
    def test_prefers_value_with_measurement_unit_over_time_unit(self):
        """P2 真實案例：「8 小時...為 0.5 ppm」須抓 0.5（有 ppm 單位），
        不能誤抓 8（後面接「小時」是時間單位，非待查值）。"""
        q = "8 小時日時量平均容許濃度為 0.5 ppm 時，變量係數是多少？"
        assert extract_question_value(q) == 0.5

    def test_p5_extracts_five(self):
        q = "8 小時日時量平均容許濃度為 5 ppm 時，變量係數是多少？"
        assert extract_question_value(q) == 5.0

    def test_p3_extracts_value_with_chinese_domain_unit(self):
        q = "血中鉛濃度為 12 μg/dl 的勞工，屬於第幾級健康管理？"
        assert extract_question_value(q) == 12.0

    def test_no_number_returns_none(self):
        assert extract_question_value("特別休假是否與服務年資有關？") is None


class TestEvaluateLookupOverride:
    def test_gap_case_draft_refuses_is_force_supported(self):
        """P2 baseline：0.5 落在缺口（< 最小下界 1），草稿誠實拒答——判斷正確，
        不該被 judge 誤判成未接地觸發不必要的重生成。"""
        q = "8 小時日時量平均容許濃度為 0.5 ppm 時，變量係數是多少？"
        result = evaluate_lookup_override(
            q, _VARIANCE_FACTS, "資料未明確記載，無法確認。", is_refusal_text
        )
        assert result.decision == "force_supported"
        assert result.extra_prompt_note is None

    def test_gap_case_draft_picks_nearest_value_is_force_unsupported_with_note(self):
        """P2 型失效模式：0.5 落在缺口，但草稿挑了最近一列（1.5）硬套——
        必須強制觸發重生成去修正，且須帶上 `GAP_REFUSAL_NOTE`（2026-09-13
        真實測試發現：沒有這段提示，重生成會在壓力下編造新區間去湊答案，
        比原本的失效更嚴重，見報告42 §7）。"""
        q = "8 小時日時量平均容許濃度為 0.5 ppm 時，變量係數是多少？"
        result = evaluate_lookup_override(
            q, _VARIANCE_FACTS, "變量係數為 1.5。", is_refusal_text
        )
        assert result.decision == "force_unsupported"
        assert result.extra_prompt_note is not None
        assert "編造" in result.extra_prompt_note

    def test_in_range_case_correct_answer_is_force_supported(self):
        """P5：5 落在 [1,10)，正解 2。草稿答對且未拒答——確定性判斷已足夠
        確認正確，不該再讓 judge 的誤判觸發重生成。"""
        q = "8 小時日時量平均容許濃度為 5 ppm 時，變量係數是多少？"
        result = evaluate_lookup_override(
            q, _VARIANCE_FACTS, "根據事實清單，變量係數為 2。", is_refusal_text
        )
        assert result.decision == "force_supported"

    def test_in_range_case_wrong_value_is_force_unsupported_without_gap_note(self):
        """P5 baseline 真實失效：5 落在 [1,10) 正解應為 2，草稿卻套用了鄰近
        區間 [10,100) 的 1.5——必須強制觸發重生成修正。這是「命中區間但挑
        錯值」，不是缺口案例，不該帶 `GAP_REFUSAL_NOTE`（既有查表指令已足夠，
        2026-09-13 第一輪測試已驗證這種案例修好：0/3→3/3）。"""
        q = "8 小時日時量平均容許濃度為 5 ppm 時，變量係數是多少？"
        result = evaluate_lookup_override(
            q, _VARIANCE_FACTS, "變量係數為 1.5。", is_refusal_text
        )
        assert result.decision == "force_unsupported"
        assert result.extra_prompt_note is None

    def test_in_range_case_refusal_is_force_unsupported(self):
        """數值明明落在某一列區間內，草稿卻拒答——這也是錯誤（該答卻沒答），
        須強制觸發重生成讓它試著查表。"""
        q = "8 小時日時量平均容許濃度為 5 ppm 時，變量係數是多少？"
        result = evaluate_lookup_override(
            q, _VARIANCE_FACTS, "資料未明確記載，無法確認。", is_refusal_text
        )
        assert result.decision == "force_unsupported"

    def test_no_interval_facts_returns_no_override(self):
        result = evaluate_lookup_override(
            "特別休假是否與服務年資有關？",
            ["特別休假 依表現或獎勵事由核發"],
            "與服務年資無關。",
            is_refusal_text,
        )
        assert result.decision == "no_override"

    def test_no_question_value_returns_no_override(self):
        result = evaluate_lookup_override(
            "特別休假是否與服務年資有關？", _VARIANCE_FACTS, "與服務年資無關。", is_refusal_text
        )
        assert result.decision == "no_override"

    def test_p3_lead_level_open_ended_match(self):
        """P3：12 落在開放句式「十以上」的範圍內，正解「第三級」。這個案例
        在真實金絲雀組裡即使套用方案E仍會判為 force_supported——因為第三級
        事實實際上有被檢索到（經由 Fact-RAG 管道，繞過了 P3 monkeypatch 只
        擋 BFS 的漏洞，見報告42 §7／`docs/參考文獻/22` README）。方案E本身
        的判斷邏輯在此案例上是正確的：只要事實清單裡真的有這條查表資訊，
        確定性覆核就該支持它——這不是方案E的瑕疵，是另一個獨立的檢索端
        測試設計缺口。"""
        q = "血中鉛濃度為 12 μg/dl 的勞工，屬於第幾級健康管理？"
        result = evaluate_lookup_override(
            q, _LEAD_FACTS, "血中鉛濃度為 12 μg/dl 的勞工，屬於第三級管理。", is_refusal_text
        )
        assert result.decision == "force_supported"


class TestIsRefusalText:
    def test_detects_known_refusal_markers(self):
        assert is_refusal_text("資料未明確記載，無法確認。")
        assert is_refusal_text("事實清單中沒有提到相關規定。")

    def test_does_not_flag_normal_answer(self):
        assert not is_refusal_text("依規定，變量係數為 2。")
