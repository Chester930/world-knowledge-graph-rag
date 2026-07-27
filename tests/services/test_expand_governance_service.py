import pytest

from services import expand_governance_service as svc


def _db_path(tmp_path):
    return tmp_path / "task_queue.db"


class TestAddCandidateAndPoolSize:
    def test_add_candidate_registers_pending_row(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])

        assert svc.pool_size(db_path, "kg-1") == 1
        candidates = svc.pending_candidates(db_path, "kg-1")
        assert candidates == [
            {"verb": "導致惡化", "verb_embedding": [0.1, 0.2, 0.3], "occurrence_count": 1}
        ]

    def test_repeated_verb_increments_occurrence_count_not_new_row(self, tmp_path):
        """主鍵 (kg_id, verb) 去重——同一動詞重複觸發不應新增列，只遞增計數。"""
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])

        assert svc.pool_size(db_path, "kg-1") == 1
        assert svc.pending_candidates(db_path, "kg-1")[0]["occurrence_count"] == 3

    def test_pool_size_scoped_per_kg(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])
        svc.add_candidate(db_path, "kg-2", "加劇因果", [0.4, 0.5, 0.6])

        assert svc.pool_size(db_path, "kg-1") == 1
        assert svc.pool_size(db_path, "kg-2") == 1

    def test_distinct_verbs_each_count_separately(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])
        svc.add_candidate(db_path, "kg-1", "加劇因果", [0.4, 0.5, 0.6])

        assert svc.pool_size(db_path, "kg-1") == 2


class TestDiscardAndRevival:
    def test_mark_discarded_excludes_from_pool_size(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])

        svc.mark_discarded(db_path, "kg-1", ["導致惡化"])

        assert svc.pool_size(db_path, "kg-1") == 0
        assert svc.pending_candidates(db_path, "kg-1") == []

    def test_discarded_verb_revives_to_pending_on_reappearance(self, tmp_path):
        """DISCARD 後不是永久拉黑——同一動詞未來若再被觸發，應自動復活回
        pending 並延續累加 occurrence_count（見設計文件誠實聲明）。"""
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])
        svc.mark_discarded(db_path, "kg-1", ["導致惡化"])
        assert svc.pool_size(db_path, "kg-1") == 0

        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])

        assert svc.pool_size(db_path, "kg-1") == 1
        assert svc.pending_candidates(db_path, "kg-1")[0]["occurrence_count"] == 2

    def test_mark_discarded_on_empty_list_is_noop(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])

        svc.mark_discarded(db_path, "kg-1", [])

        assert svc.pool_size(db_path, "kg-1") == 1


class TestMarkCommitted:
    def test_mark_committed_excludes_from_pool_size(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.add_candidate(db_path, "kg-1", "導致惡化", [0.1, 0.2, 0.3])

        svc.mark_committed(db_path, "kg-1", ["導致惡化"])

        assert svc.pool_size(db_path, "kg-1") == 0


class TestRegistry:
    def test_register_type_then_find_similar_returns_match_above_threshold(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.register_type(
            db_path, "AGGRAVATES", "A 使 B 的情況惡化", [1.0, 0.0, 0.0], "kg-1"
        )

        result = svc.find_similar_registered_type(db_path, [1.0, 0.0, 0.0], threshold=0.75)

        assert result == ("AGGRAVATES", pytest.approx(1.0))

    def test_find_similar_returns_none_when_below_threshold(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.register_type(
            db_path, "AGGRAVATES", "A 使 B 的情況惡化", [1.0, 0.0, 0.0], "kg-1"
        )

        result = svc.find_similar_registered_type(db_path, [0.0, 1.0, 0.0], threshold=0.75)

        assert result is None

    def test_find_similar_returns_none_when_registry_empty(self, tmp_path):
        db_path = _db_path(tmp_path)
        assert svc.find_similar_registered_type(db_path, [1.0, 0.0, 0.0], threshold=0.75) is None

    def test_register_type_does_not_overwrite_existing_entry(self, tmp_path):
        """type_name 已存在時不覆寫——REUSE 分支不應改動原始核准來源。"""
        db_path = _db_path(tmp_path)
        svc.register_type(
            db_path, "AGGRAVATES", "A 使 B 的情況惡化", [1.0, 0.0, 0.0], "kg-1"
        )

        svc.register_type(
            db_path, "AGGRAVATES", "不同的描述句", [0.0, 1.0, 0.0], "kg-2"
        )

        result = svc.find_similar_registered_type(db_path, [1.0, 0.0, 0.0], threshold=0.75)
        assert result == ("AGGRAVATES", pytest.approx(1.0))

    def test_find_similar_picks_highest_scoring_type_among_multiple(self, tmp_path):
        db_path = _db_path(tmp_path)
        svc.register_type(db_path, "AGGRAVATES", "描述 A", [1.0, 0.0, 0.0], "kg-1")
        svc.register_type(db_path, "MITIGATES", "描述 B", [0.0, 0.0, 1.0], "kg-1")

        result = svc.find_similar_registered_type(db_path, [0.9, 0.1, 0.0], threshold=0.5)

        assert result[0] == "AGGRAVATES"
