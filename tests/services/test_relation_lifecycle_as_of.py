"""報告260 N1／N2：`state_as_of`／`is_retrievable_as_of`（純函式，不連 Neo4j）。"""
import pytest

from services import relation_lifecycle as rl
from services.relation_lifecycle import (
    CANDIDATE, DEFAULT_RETRIEVABLE_STATES, EXTRACTED, REPLACED, SUPERSEDED, VALID, VERIFIED, LifecycleEvent,
    is_retrievable_as_of, state_as_of,
)


def ev(kind, date=None):
    return LifecycleEvent(kind, date)


NEW_VERSION = [ev(EXTRACTED, "2025-12-09"), ev(VERIFIED, "2025-12-09")]
OLD_VERSION = [ev(EXTRACTED, "2023-05-01"), ev(VERIFIED, "2023-05-01"), ev(REPLACED, "2025-12-09")]
NOT_IN_FORCE = [ev(EXTRACTED, "2027-01-01"), ev(VERIFIED, "2027-01-01")]


def test_no_events():
    r = state_as_of([], "2026-10-02")
    assert (r.state, r.status, r.included, r.excluded, r.replay) == (None, "no_events", 0, 0, None)


def test_all_events_without_date_are_included():
    r = state_as_of([ev(EXTRACTED), ev(VERIFIED)], "2000-01-01")
    assert (r.state, r.status, r.included, r.excluded) == (VALID, "replayed", 2, 0)


def test_all_events_later_than_as_of():
    r = state_as_of(NOT_IN_FORCE, "2026-10-02")
    assert (r.state, r.status, r.included, r.excluded, r.replay) == (None, "not_yet_effective", 0, 2, None)


def test_partial_effective_events():
    r = state_as_of(OLD_VERSION, "2024-01-01")
    assert (r.state, r.status, r.included, r.excluded) == (VALID, "replayed", 2, 1)


def test_boundary_date_equal_is_included():
    assert state_as_of(NEW_VERSION, "2025-12-09").state == VALID
    assert state_as_of(NEW_VERSION, "2025-12-08").status == "not_yet_effective"
    r = state_as_of(OLD_VERSION, "2025-12-09")
    assert (r.state, r.included, r.excluded) == (SUPERSEDED, 3, 0)


def test_mixed_dated_and_undated_events():
    r = state_as_of([ev(EXTRACTED), ev(VERIFIED, "2030-01-01")], "2026-10-02")
    assert (r.state, r.status, r.included, r.excluded) == (CANDIDATE, "replayed", 1, 1)


def test_not_yet_in_force_article_before_and_after():  # 報告260 §2 更正：所有事件日期＝施行日
    before = state_as_of(NOT_IN_FORCE, "2026-12-31")
    on_day = state_as_of(NOT_IN_FORCE, "2027-01-01")
    after = state_as_of(NOT_IN_FORCE, "2027-06-01")
    assert before.status == "not_yet_effective" and not is_retrievable_as_of(before)
    assert on_day.state == VALID and is_retrievable_as_of(on_day)
    assert after.state == VALID and is_retrievable_as_of(after)


def test_time_travel_old_version():
    assert is_retrievable_as_of(state_as_of(OLD_VERSION, "2025-12-08"))
    superseded = state_as_of(OLD_VERSION, "2025-12-09")
    assert superseded.state == SUPERSEDED and not is_retrievable_as_of(superseded)
    assert not is_retrievable_as_of(state_as_of(OLD_VERSION, "2026-10-02"))
    assert not is_retrievable_as_of(state_as_of(OLD_VERSION, "2023-04-30"))  # 事件全未生效


def test_illegal_sequence_keeps_final_state_and_does_not_hide():
    events = [ev(EXTRACTED, "2024-01-01"), ev(REPLACED, "2024-02-01"), ev(VERIFIED, "2024-03-01")]
    r = state_as_of(events, "2026-10-02")
    assert r.status == "illegal"
    assert r.state == VALID  # 候選 +（被拒的新版取代）+ 驗證通過 → 有效
    assert r.replay is not None and not r.replay.ok and r.replay.first_illegal[0] == 1
    assert [s.ok for s in r.replay.steps] == [True, False, True]
    assert is_retrievable_as_of(r)  # fail-open
    # 被拒事件不改變狀態：只含被拒事件的前綴
    first_only = state_as_of(events[:2], "2026-10-02")
    assert first_only.status == "illegal" and first_only.state == CANDIDATE


def test_illegal_first_event_leaves_state_none_and_retrievable_by_none_in_set():
    r = state_as_of([ev(VERIFIED, "2024-01-01")], "2026-10-02")
    assert (r.status, r.state) == ("illegal", None)
    assert is_retrievable_as_of(r)  # None 在預設可檢索集合


@pytest.mark.parametrize("bad", ["2026/10/02", "2026-1-2", "", "today", "2026-10-02T00:00", None, 20261002])
def test_as_of_format_error(bad):
    with pytest.raises(ValueError):
        state_as_of(NEW_VERSION, bad)


def test_event_order_is_preserved_not_resorted_by_date():
    # 記錄順序：驗證通過 的日期早於 抽取完成；若被日期重排會變成合法，但函式只依原順序重播
    events = [ev(EXTRACTED, "2025-06-01"), ev(VERIFIED, "2024-01-01"), ev(REPLACED, "2026-01-01")]
    r = state_as_of(events, "2026-10-02")
    assert r.status == "replayed" and r.state == SUPERSEDED  # 原順序：抽取→驗證→取代
    # 日期亂序且全納入：結果只取決於「納入集合＋原順序」
    shuffled = [ev(VERIFIED, "2024-01-01"), ev(EXTRACTED, "2025-06-01")]
    s = state_as_of(shuffled, "2026-10-02")
    assert s.status == "illegal" and s.state == CANDIDATE
    # as_of 排除中間事件：被排除者不參與、其餘保持原順序
    partial = state_as_of(events, "2025-12-31")
    assert (partial.included, partial.excluded, partial.state) == (2, 1, VALID)


def test_is_retrievable_as_of_four_statuses():
    none_ = state_as_of([], "2026-10-02")
    nye = state_as_of(NOT_IN_FORCE, "2026-10-02")
    rep_ok = state_as_of(NEW_VERSION, "2026-10-02")
    rep_bad = state_as_of(OLD_VERSION, "2026-10-02")
    ill = state_as_of([ev(EXTRACTED), ev(REPLACED)], "2026-10-02")
    assert is_retrievable_as_of(none_) is True
    assert is_retrievable_as_of(nye) is False
    assert is_retrievable_as_of(rep_ok) is True and is_retrievable_as_of(rep_bad) is False
    assert ill.status == "illegal" and is_retrievable_as_of(ill) is True


def test_custom_retrievable_set():
    only_valid = frozenset({VALID})
    assert is_retrievable_as_of(state_as_of([], "2026-10-02"), only_valid) is False  # None 不在集合
    assert is_retrievable_as_of(state_as_of(NEW_VERSION, "2026-10-02"), only_valid) is True
    assert is_retrievable_as_of(state_as_of([ev(EXTRACTED)], "2026-10-02"), only_valid) is False  # 候選
    assert is_retrievable_as_of(state_as_of([], "2026-10-02"), frozenset({None})) is True
    assert is_retrievable_as_of(state_as_of(NOT_IN_FORCE, "2026-10-02"), frozenset({None, VALID})) is False


def test_does_not_mutate_inputs_or_existing_api():
    events = list(OLD_VERSION)
    state_as_of(events, "2024-01-01")
    assert events == OLD_VERSION
    assert rl.AS_OF_STATUSES == ("no_events", "not_yet_effective", "replayed", "illegal")
    assert DEFAULT_RETRIEVABLE_STATES == frozenset({None, "候選", "有效", "爭議"})


def test_result_is_frozen():
    r = state_as_of(NEW_VERSION, "2026-10-02")
    with pytest.raises(Exception):
        r.state = "x"  # type: ignore[misc]
