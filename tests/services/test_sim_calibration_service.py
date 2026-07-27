import pytest

from services import sim_calibration_service as svc


def _db_path(tmp_path):
    return tmp_path / "task_queue.db"


class TestLogEscalation:
    def test_log_escalation_persists_event(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.81, "CAUSES")

        assert svc.sim_agreement_rate(db_path, "CAUSES", window=1) == pytest.approx(1.0)

    def test_multiple_events_for_different_types_are_independent(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.81, "CAUSES")
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "MANNER_OF", 0.76, "RELATED_TO")

        assert svc.sim_agreement_rate(db_path, "CAUSES", window=1) == pytest.approx(1.0)
        assert svc.sim_agreement_rate(db_path, "MANNER_OF", window=1) == pytest.approx(0.0)


class TestSimAgreementRate:
    def test_returns_none_when_fewer_than_window_events(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.81, "CAUSES")

        assert svc.sim_agreement_rate(db_path, "CAUSES", window=3) is None

    def test_computes_fraction_where_final_matches_sim_suggestion(self, tmp_path):
        db_path = _db_path(tmp_path)
        # SIM 建議 CAUSES：3 次最終判定真的是 CAUSES（SIM 對），1 次最終判定是 IS_A（SIM 錯，LLM 對）
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.81, "CAUSES")
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.79, "CAUSES")
        svc.log_escalation(db_path, "kg-1", "IS_A", "CAUSES", 0.77, "CAUSES")
        svc.log_escalation(db_path, "kg-1", "IS_A", "CAUSES", 0.76, "IS_A")

        assert svc.sim_agreement_rate(db_path, "CAUSES", window=4) == pytest.approx(0.75)

    def test_uses_most_recent_window_events_only(self, tmp_path):
        db_path = _db_path(tmp_path)
        # 最舊 2 筆 SIM 對，最新 2 筆 SIM 錯——window=2 只看最新 2 筆
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.81, "CAUSES")
        svc.log_escalation(db_path, "kg-1", "RELATED_TO", "CAUSES", 0.81, "CAUSES")
        svc.log_escalation(db_path, "kg-1", "IS_A", "CAUSES", 0.76, "IS_A")
        svc.log_escalation(db_path, "kg-1", "IS_A", "CAUSES", 0.76, "IS_A")

        assert svc.sim_agreement_rate(db_path, "CAUSES", window=2) == pytest.approx(0.0)

    def test_returns_none_when_no_events_for_type(self, tmp_path):
        db_path = _db_path(tmp_path)
        assert svc.sim_agreement_rate(db_path, "CAUSES", window=1) is None
