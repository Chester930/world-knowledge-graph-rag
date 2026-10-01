"""報告231 S1：`services/relation_lifecycle.py` 完整單元測試（全為虛構資料，不連任何資料庫或真實資料）。"""

import ast
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

from services import relation_lifecycle as rl
from services.relation_lifecycle import (
    CANDIDATE, CONTRADICTION, DISPUTED, EXTRACTED, REACTIVATE, REJECTED, REPLACED, RULED_KEEP, RULED_OTHER,
    SUPERSEDED, TERMINATE, TERMINATED, VALID, VERIFIED, VERIFY_FAILED,
    LifecycleEvent as Ev, LifecycleSpec, RelationInstance, apply_event, check_exclusivity, explain, replay,
)

_SRC = Path(__file__).resolve().parents[2] / "services" / "relation_lifecycle.py"

ALLOWED = [
    (None, EXTRACTED, CANDIDATE),
    (CANDIDATE, VERIFIED, VALID),
    (CANDIDATE, VERIFY_FAILED, REJECTED),
    (VALID, CONTRADICTION, DISPUTED),
    (VALID, REPLACED, SUPERSEDED),
    (VALID, TERMINATE, TERMINATED),
    (DISPUTED, RULED_KEEP, VALID),
    (DISPUTED, RULED_OTHER, SUPERSEDED),
    (TERMINATED, REACTIVATE, VALID),
]
ALL_STATES = [None, *sorted(rl.CORE_STATES)]
ILLEGAL = [(s, e) for s in ALL_STATES for e in sorted(rl.CORE_EVENTS) if (s, e) not in {(a, b) for a, b, _ in ALLOWED}]


# ── 基本結構 ─────────────────────────────────────────────────────────────────
def test_states_events_and_provisional_flag():
    assert rl.PROVISIONAL is True
    assert rl.CORE_STATES == {"候選", "有效", "已被取代", "已終止", "爭議", "已駁回"}
    assert rl.CORE_TERMINAL_STATES == {"已被取代", "已駁回"}
    assert len(rl.CORE_EVENTS) == 9 and len(rl.CORE_TRANSITIONS) == 9
    assert len(ALL_STATES) * len(rl.CORE_EVENTS) == len(ALLOWED) + len(ILLEGAL)


@pytest.mark.parametrize("src,event,dst", ALLOWED)
def test_every_allowed_transition(src, event, dst):
    r = apply_event(src, Ev(event))
    assert r.ok and r.from_state == src and r.to_state == dst and event in r.reason


@pytest.mark.parametrize("src,event", ILLEGAL)
def test_every_other_pair_is_illegal_with_reason_and_state_unchanged(src, event):
    r = apply_event(src, Ev(event))
    assert not r.ok and r.to_state == src and r.from_state == src
    assert r.reason and (src is None or src in r.reason) and event in r.reason


@pytest.mark.parametrize("terminal", sorted(rl.CORE_TERMINAL_STATES))
def test_terminal_states_have_no_exit_for_any_event(terminal):
    for event in sorted(rl.CORE_EVENTS):
        r = apply_event(terminal, Ev(event))
        assert not r.ok and "終點狀態" in r.reason
    assert rl.allowed_events(terminal) == ()


def test_superseded_and_rejected_cannot_return_to_valid():
    assert not apply_event(SUPERSEDED, Ev(REACTIVATE)).ok
    assert not apply_event(REJECTED, Ev(VERIFIED)).ok


def test_terminated_can_reactivate_but_nothing_else():
    assert rl.allowed_events(TERMINATED) == (REACTIVATE,)
    assert apply_event(TERMINATED, Ev(REACTIVATE)).to_state == VALID


def test_unknown_state_and_unknown_event_are_rejected_not_raised():
    r1 = apply_event("不存在的狀態", Ev(VERIFIED))
    assert not r1.ok and "未知狀態" in r1.reason
    r2 = apply_event(VALID, Ev("不存在的事件"))
    assert not r2.ok and "未知事件" in r2.reason


def test_first_event_must_be_extracted():
    r = apply_event(None, Ev(VERIFIED))
    assert not r.ok and "尚未建立" in r.reason and EXTRACTED in r.reason


def test_apply_event_does_not_mutate_inputs():
    ev = Ev(VERIFIED, effective_date="2020-01-01", reason="r")
    before = dataclasses.asdict(ev)
    r = apply_event(CANDIDATE, ev)
    assert dataclasses.asdict(ev) == before and r.event is ev


# ── 事件與日期 ───────────────────────────────────────────────────────────────
def test_event_validation():
    with pytest.raises(ValueError):
        Ev("")
    with pytest.raises(ValueError):
        Ev("  ")
    with pytest.raises(ValueError):
        Ev(VERIFIED, effective_date="2020/01/01")
    with pytest.raises(ValueError):
        Ev(VERIFIED, trigger_kind="隨便")
    ev = Ev(VERIFIED, effective_date="2020-01-01", reason="r", evidence_ref="e", trigger_kind="人工")
    assert ev.effective_date == "2020-01-01" and ev.trigger_kind == "人工"
    for k in rl.TRIGGER_KINDS:
        assert Ev(VERIFIED, trigger_kind=k).trigger_kind == k


def _chain(dated: bool):
    seq = [(EXTRACTED, "2019-01-01"), (VERIFIED, "2019-02-01"), (CONTRADICTION, "2020-03-01"), (RULED_KEEP, "2020-04-01"),
           (TERMINATE, "2021-05-01"), (REACTIVATE, "2022-06-01"), (REPLACED, "2023-07-01")]
    return [Ev(t, effective_date=d if dated else None) for t, d in seq]


def test_undated_events_transition_normally_and_dating_does_not_change_result():
    a, b = replay(_chain(True)), replay(_chain(False))
    assert a.final_state == b.final_state == SUPERSEDED and a.ok and b.ok
    assert [s.to_state for s in a.steps] == [s.to_state for s in b.steps]
    assert [s.ok for s in a.steps] == [s.ok for s in b.steps]


def test_date_order_is_not_interpreted_so_out_of_order_dates_do_not_change_legality():
    shuffled = [Ev(EXTRACTED, "2030-01-01"), Ev(VERIFIED, "1990-01-01")]
    assert replay(shuffled).final_state == VALID


# ── 重播 ─────────────────────────────────────────────────────────────────────
def test_replay_projection_steps_and_determinism():
    events = _chain(True)
    results = [replay(events) for _ in range(5)]
    assert all(r == results[0] for r in results)
    assert [s.to_state for s in results[0].steps] == [CANDIDATE, VALID, DISPUTED, VALID, TERMINATED, VALID, SUPERSEDED]
    assert results[0].first_illegal is None and results[0].ok


def test_replay_empty_and_initial_state():
    assert replay([]).final_state is None and replay([]).steps == () and replay([]).ok
    assert replay([], initial=VALID).final_state == VALID
    assert replay([Ev(TERMINATE)], initial=VALID).final_state == TERMINATED


def test_replay_records_first_illegal_keeps_state_and_continues():
    events = [Ev(EXTRACTED), Ev(VERIFIED), Ev(REACTIVATE), Ev(REPLACED), Ev(TERMINATE)]
    r = replay(events)
    assert r.final_state == SUPERSEDED  # 被拒事件不改變狀態，其後合法事件仍套用
    i, step = r.first_illegal
    assert i == 2 and step.event.event_type == REACTIVATE and not step.ok and not r.ok
    assert [s.ok for s in r.steps] == [True, True, False, True, False]  # 已被取代後 TERMINATE 也被拒


def test_replay_accepts_any_iterable_and_is_not_affected_by_later_mutation_of_source_list():
    events = [Ev(EXTRACTED), Ev(VERIFIED)]
    r = replay(iter(events))
    events.append(Ev(TERMINATE))
    assert r.final_state == VALID and len(r.steps) == 2


# ── 互斥 ─────────────────────────────────────────────────────────────────────
def _inst(i, key, state):
    return RelationInstance(i, key, state)


K1, K2 = ("甲", "給", "乙"), ("丙", "給", "丁")


def test_exclusivity_zero_one_and_many_violations():
    assert check_exclusivity([]) == ()
    assert check_exclusivity([_inst("a", K1, VALID), _inst("b", K2, VALID)]) == ()
    one = check_exclusivity([_inst("b", K1, VALID), _inst("a", K1, VALID), _inst("c", K1, SUPERSEDED)])
    assert len(one) == 1 and one[0].key == K1 and one[0].instance_ids == ("a", "b")
    many = check_exclusivity([_inst("1", K2, VALID), _inst("2", K2, VALID), _inst("3", K1, VALID), _inst("4", K1, VALID),
                              _inst("5", K1, VALID)])
    assert [v.key for v in many] == sorted([K1, K2]) == [K2, K1]  # 依鍵的字面順序（丙 < 甲），決定性
    assert many[1].instance_ids == ("3", "4", "5") and many[0].instance_ids == ("1", "2")


def test_exclusivity_counts_only_valid_state():
    states = [CANDIDATE, DISPUTED, TERMINATED, SUPERSEDED, REJECTED, None]
    assert check_exclusivity([_inst(str(i), K1, s) for i, s in enumerate(states)]) == ()
    assert check_exclusivity([_inst("x", K1, VALID), _inst("y", K1, DISPUTED)]) == ()


# ── 擴充（Q1）────────────────────────────────────────────────────────────────
def _pause_spec(**kw):
    base = dict(
        relation_type="虛構-暫停適用",
        extra_states=frozenset({"暫停"}),
        extra_events=frozenset({"暫停適用", "恢復適用"}),
        extra_transitions={(VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID, ("暫停", TERMINATE): TERMINATED},
    )
    base.update(kw)
    return LifecycleSpec(**base)


def test_valid_extension_works_and_core_is_unchanged():
    spec = _pause_spec()
    assert rl.validate_spec(spec).ok
    lc = rl.resolve_spec(spec)
    assert all(lc.transitions[k] == v for k, v in rl.CORE_TRANSITIONS.items())  # 核心轉換全在
    r = replay([Ev(EXTRACTED), Ev(VERIFIED), Ev("暫停適用"), Ev("恢復適用"), Ev("暫停適用"), Ev(TERMINATE), Ev(REACTIVATE)], lifecycle=lc)
    assert [s.to_state for s in r.steps] == [CANDIDATE, VALID, "暫停", VALID, "暫停", TERMINATED, VALID] and r.ok
    # 同一事件序列在核心下，擴充事件被視為未知事件
    core = replay([Ev(EXTRACTED), Ev(VERIFIED), Ev("暫停適用")])
    assert core.final_state == VALID and not core.ok and "未知事件" in core.first_illegal[1].reason
    assert rl.CORE_STATES == {"候選", "有效", "已被取代", "已終止", "爭議", "已駁回"}  # 核心常數未被污染


def test_extension_does_not_change_core_lifecycle_object():
    before = dict(rl.CORE_LIFECYCLE.transitions)
    rl.resolve_spec(_pause_spec())
    assert dict(rl.CORE_LIFECYCLE.transitions) == before and rl.CORE_LIFECYCLE.states == rl.CORE_STATES


def test_lifecycle_for_falls_back_to_core():
    lc = rl.resolve_spec(_pause_spec())
    assert rl.lifecycle_for("虛構-暫停適用", {"虛構-暫停適用": lc}) is lc
    assert rl.lifecycle_for("別的關係", {"虛構-暫停適用": lc}) is rl.CORE_LIFECYCLE
    assert rl.lifecycle_for("x") is rl.CORE_LIFECYCLE


@pytest.mark.parametrize("spec,needle", [
    (_pause_spec(extra_transitions={(VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID, (SUPERSEDED, "暫停適用"): "暫停"}),
     "終點狀態「已被取代」不得有任何轉出"),
    (_pause_spec(extra_transitions={(VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID, (REJECTED, "恢復適用"): VALID}),
     "終點狀態「已駁回」不得有任何轉出"),
    (_pause_spec(extra_transitions={(VALID, TERMINATE): VALID, (VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID}),
     "不得改寫或重述核心轉換"),
    (_pause_spec(extra_transitions={(VALID, REPLACED): TERMINATED, (VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID}),
     "不得改寫或重述核心轉換"),
    (_pause_spec(removed_core_transitions=frozenset({(VALID, TERMINATE)})), "不得刪除核心轉換"),
    (_pause_spec(extra_states=frozenset({"暫停", VALID})), "不得重新宣告核心狀態「有效」"),
    (_pause_spec(extra_events=frozenset({"暫停適用", "恢復適用", TERMINATE})), "不得重新宣告核心事件「終止」"),
    (_pause_spec(extra_transitions={(None, "暫停適用"): "暫停", (VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID}),
     "建立轉換只能進入「候選」"),
    (_pause_spec(extra_transitions={(VALID, "暫停適用"): "不存在", ("暫停", "恢復適用"): VALID}), "轉換終點狀態未知"),
    (_pause_spec(extra_transitions={(VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID, ("幽靈", "恢復適用"): VALID}),
     "轉換來源狀態未知"),
    (_pause_spec(extra_transitions={(VALID, "未宣告事件"): "暫停", ("暫停", "恢復適用"): VALID}), "轉換事件未知"),
    (_pause_spec(extra_transitions={(VALID, "暫停適用"): "暫停"}), "沒有任何轉出，必須宣告為終點狀態"),
    (_pause_spec(extra_terminal_states=frozenset({"幽靈"})), "不是已知狀態"),
])
def test_extensions_that_break_core_invariants_are_rejected_with_reason(spec, needle):
    v = rl.validate_spec(spec)
    assert not v.ok and any(needle in e for e in v.errors), v.errors
    with pytest.raises(ValueError):
        rl.resolve_spec(spec)


def test_extra_terminal_state_may_not_have_exit_and_may_exist_without_one():
    ok = _pause_spec(extra_states=frozenset({"暫停", "作廢"}), extra_events=frozenset({"暫停適用", "恢復適用", "作廢"}),
                     extra_transitions={(VALID, "作廢"): "作廢", (VALID, "暫停適用"): "暫停", ("暫停", "恢復適用"): VALID},
                     extra_terminal_states=frozenset({"作廢"}))
    lc = rl.resolve_spec(ok)
    assert "作廢" in lc.terminal_states and not apply_event("作廢", Ev(REACTIVATE), lc).ok
    bad = _pause_spec(extra_states=frozenset({"暫停", "作廢"}), extra_events=frozenset({"暫停適用", "恢復適用", "作廢", "復活"}),
                      extra_transitions={(VALID, "作廢"): "作廢", ("作廢", "復活"): VALID, (VALID, "暫停適用"): "暫停",
                                         ("暫停", "恢復適用"): VALID},
                      extra_terminal_states=frozenset({"作廢"}))
    assert any("終點狀態「作廢」不得有任何轉出" in e for e in rl.validate_spec(bad).errors)


# ── explain ──────────────────────────────────────────────────────────────────
def test_explain_lists_steps_reasons_dates_and_final_state():
    events = [Ev(EXTRACTED, "2019-01-01", trigger_kind="事件", evidence_ref="虛構文件#1"), Ev(VERIFIED, reason="人工確認"),
              Ev(REACTIVATE)]
    text = explain(replay(events))
    lines = text.split("\n")
    assert len(lines) == 4
    assert "第1步 ✓ （無） —[抽取完成]→ 候選" in lines[0] and "日期：2019-01-01" in lines[0] and "依據：虛構文件#1" in lines[0]
    assert "日期：未提供" in lines[1] and "原因：人工確認" in lines[1]
    assert lines[2].startswith("第3步 ✗") and "被拒" in lines[2] and "不允許事件「重新生效」" in lines[2]
    assert lines[3] == "最終狀態：有效"
    assert explain(()) == "最終狀態：（尚未建立）"
    assert explain(replay([], initial=VALID)).endswith("最終狀態：有效")
    assert explain(replay(events).steps) == text  # 也接受步驟序列


# ── 不可變性／純運算 ────────────────────────────────────────────────────────
def test_events_and_results_are_immutable():
    ev = Ev(VERIFIED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.event_type = "x"
    r = apply_event(CANDIDATE, ev)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ok = False
    rr = replay([Ev(EXTRACTED)])
    with pytest.raises(dataclasses.FrozenInstanceError):
        rr.final_state = "x"
    assert isinstance(rr.steps, tuple)
    with pytest.raises(AttributeError):
        rr.steps.append(r)


def test_core_tables_are_read_only():
    with pytest.raises(TypeError):
        rl.CORE_TRANSITIONS[(VALID, TERMINATE)] = VALID
    with pytest.raises(TypeError):
        rl.CORE_LIFECYCLE.transitions[("x", "y")] = "z"
    with pytest.raises(AttributeError):
        rl.CORE_STATES.add("x")


def test_module_has_no_mutating_or_storage_api():
    public = {n for n in dir(rl) if not n.startswith("_")}
    banned = ("update", "delete", "remove_event", "set_state", "save", "load", "write", "persist", "serialize")
    assert not [n for n in public if any(b in n.lower() for b in banned) and n != "validate_spec"]


def test_module_imports_only_stdlib_and_uses_no_clock_or_io():
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add((node.module or "").split(".")[0])
    assert mods <= {"__future__", "re", "collections", "dataclasses", "types"}, mods
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"open", "now", "today", "utcnow", "time", "environ", "write_text", "read_text", "getenv"}


def test_import_does_not_touch_os_environ():
    # 以全新子程序驗證（同程序內其他測試可能已改動 os.environ，會讓快照比較不可靠）
    code = ("import os; b = dict(os.environ); import services.relation_lifecycle; "
            "assert dict(os.environ) == b, 'os.environ 被改動'")
    r = subprocess.run([sys.executable, "-c", code], cwd=_SRC.parents[1], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
