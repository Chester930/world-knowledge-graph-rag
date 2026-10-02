"""關係生命週期狀態機——純運算原型（報告230 S1；設計依據報告229 §3）。**PROVISIONAL，未接線。**

純運算、無 I/O：匯入只有標準庫；不連 DB、不讀寫檔、不使用時間函式（日期只是事件上選用的字串屬性，不解析；唯一的日期比較是檔尾 `state_as_of` 以 ISO 字串字典序判定事件是否已生效）、
不改 `os.environ`。**所有狀態、事件、轉換都是提案（使用者尚未決定 schema），不是已定案的資料模型**，也不得寫回任何儲存資料。

⚠️ **零行為變更**：除測試與 `scripts/analysis/relation_lifecycle_demo.py` 外，沒有任何程式匯入本模組；
不得接進 `svo_service`／`merge_*`／`extract_*`／檢索／prompt／`routers`（接線需「關係實例」結構與儲存變更，屬使用者尚未決定的後續階段）。

核心觀念（借自使用者 Round 3，只借觀念）：**事件是已發生且不可改的事實；狀態是事件重播的投影**。
更正以「追加事件」表達，本模組**不提供**任何就地修改或刪除事件的 API（事件為 frozen dataclass、序列為 tuple）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

PROVISIONAL = True

# ── 狀態（暫定）──────────────────────────────────────────────────────────────
CANDIDATE = "候選"      # 第一個狀態：剛被抽取，尚未驗證（報告229 Q2：候選併入狀態機）
VALID = "有效"
SUPERSEDED = "已被取代"  # 終點狀態
TERMINATED = "已終止"    # 可「重新生效」
DISPUTED = "爭議"
REJECTED = "已駁回"      # 終點狀態
CORE_STATES = frozenset({CANDIDATE, VALID, SUPERSEDED, TERMINATED, DISPUTED, REJECTED})
CORE_TERMINAL_STATES = frozenset({SUPERSEDED, REJECTED})

# ── 事件（暫定；時間只是事件的選用屬性）──────────────────────────────────────────
EXTRACTED = "抽取完成"        # 建立：無 → 候選
VERIFIED = "驗證通過"
VERIFY_FAILED = "驗證不通過"
CONTRADICTION = "偵測到矛盾"
RULED_KEEP = "裁決保留"
RULED_OTHER = "裁決以他條為準"
REPLACED = "新版取代"          # 修法生效／新版出現
TERMINATE = "終止"            # 廢止／關係結束
REACTIVATE = "重新生效"        # 結束後重新開始
REVOKED = "撤銷"               # 已採信關係被撤銷 → 已駁回
CORE_EVENTS = frozenset({EXTRACTED, VERIFIED, VERIFY_FAILED, CONTRADICTION, RULED_KEEP, RULED_OTHER, REPLACED,
                         TERMINATE, REACTIVATE, REVOKED})

# D3：參數化的預設可檢索狀態集合；None 代表欄位缺席／尚未處理。
DEFAULT_RETRIEVABLE_STATES = frozenset({None, CANDIDATE, VALID, DISPUTED})

TRIGGER_KINDS = ("時間", "事件", "偵測", "人工")  # 僅記錄用，不影響轉換合法性

# 允許轉換（報告229 §3）：鍵＝(前狀態或 None〔尚未建立〕, 事件)；其餘一律非法
CORE_TRANSITIONS: Mapping[tuple[str | None, str], str] = MappingProxyType({
    (None, EXTRACTED): CANDIDATE,
    (CANDIDATE, VERIFIED): VALID,
    (CANDIDATE, VERIFY_FAILED): REJECTED,
    (VALID, CONTRADICTION): DISPUTED,
    (VALID, REPLACED): SUPERSEDED,
    (VALID, TERMINATE): TERMINATED,
    (DISPUTED, RULED_KEEP): VALID,
    (DISPUTED, RULED_OTHER): SUPERSEDED,
    (TERMINATED, REACTIVATE): VALID,
    (VALID, REVOKED): REJECTED,
    (DISPUTED, REVOKED): REJECTED,
    (TERMINATED, REVOKED): REJECTED,
})

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── 事件（不可變）────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LifecycleEvent:
    """不可變事件。`effective_date`（選用）只做字串形狀檢查（YYYY-MM-DD），不解析、不比較、不影響轉換。"""

    event_type: str
    effective_date: str | None = None
    reason: str | None = None
    evidence_ref: str | None = None
    trigger_kind: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type 必須是非空字串")
        if self.effective_date is not None and not (
            isinstance(self.effective_date, str) and _ISO_DATE_RE.match(self.effective_date)
        ):
            raise ValueError(f"effective_date 必須是 YYYY-MM-DD 字串或 None，收到 {self.effective_date!r}")
        if self.trigger_kind is not None and self.trigger_kind not in TRIGGER_KINDS:
            raise ValueError(f"trigger_kind 必須是 {TRIGGER_KINDS} 之一或 None，收到 {self.trigger_kind!r}")


# ── 生命週期定義與擴充（Q1：通用核心＋可個別擴充）───────────────────────────────────
@dataclass(frozen=True)
class LifecycleSpec:
    """個別關係型別的**擴充**請求（只能追加；核心不變量不可被破壞，由 `validate_spec` 檢查）。

    `removed_core_transitions` 用來表達「想刪除核心轉換」的請求——這種請求一律不被允許，保留此欄位是為了讓違規可被明確偵測與報錯。
    """

    relation_type: str
    extra_states: frozenset[str] = frozenset()
    extra_events: frozenset[str] = frozenset()
    extra_transitions: Mapping[tuple[str | None, str], str] = field(default_factory=dict)
    extra_terminal_states: frozenset[str] = frozenset()
    removed_core_transitions: frozenset[tuple[str | None, str]] = frozenset()


@dataclass(frozen=True)
class SpecValidation:
    ok: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class Lifecycle:
    """已解析（核心＋擴充）的生命週期定義；不可變。"""

    name: str
    states: frozenset[str]
    events: frozenset[str]
    transitions: Mapping[tuple[str | None, str], str]
    terminal_states: frozenset[str]


CORE_LIFECYCLE = Lifecycle("核心", CORE_STATES, CORE_EVENTS, CORE_TRANSITIONS, CORE_TERMINAL_STATES)


def validate_spec(spec: LifecycleSpec) -> SpecValidation:
    """檢查擴充是否破壞核心不變量；回傳驗證結果（不丟例外）。

    規則：①不得重新宣告核心狀態／事件；②不得刪除、改寫或重述核心轉換；③終點狀態（核心與擴充）不得有任何轉出；
    ④建立轉換（前狀態為 None）只能進入「候選」；⑤擴充轉換的來源／終點必須是已知狀態、事件必須已知；
    ⑥擴充狀態若沒有任何轉出，必須宣告為終點狀態（避免無出口的陷阱狀態）。
    """
    errors: list[str] = []
    new_states, new_events = set(spec.extra_states), set(spec.extra_events)
    for s in sorted(new_states & CORE_STATES):
        errors.append(f"不得重新宣告核心狀態「{s}」")
    for e in sorted(new_events & CORE_EVENTS):
        errors.append(f"不得重新宣告核心事件「{e}」")
    for key in sorted(spec.removed_core_transitions, key=str):
        errors.append(f"不得刪除核心轉換 {key[0]}—[{key[1]}]→{CORE_TRANSITIONS.get(key, '?')}")
    states = CORE_STATES | new_states
    events = CORE_EVENTS | new_events
    terminal = CORE_TERMINAL_STATES | set(spec.extra_terminal_states)
    for s in sorted(set(spec.extra_terminal_states) - states):
        errors.append(f"終點狀態「{s}」不是已知狀態")
    for (src, ev), dst in sorted(spec.extra_transitions.items(), key=lambda kv: str(kv[0])):
        label = f"{src}—[{ev}]→{dst}"
        if (src, ev) in CORE_TRANSITIONS:
            errors.append(f"不得改寫或重述核心轉換：{label}")
            continue
        if src in terminal:
            errors.append(f"終點狀態「{src}」不得有任何轉出：{label}")
        if src is not None and src not in states:
            errors.append(f"轉換來源狀態未知：{label}")
        if dst not in states:
            errors.append(f"轉換終點狀態未知：{label}")
        if ev not in events:
            errors.append(f"轉換事件未知：{label}")
        if src is None and dst != CANDIDATE:
            errors.append(f"建立轉換只能進入「{CANDIDATE}」：{label}")
    with_exit = {src for (src, _ev) in spec.extra_transitions}
    for s in sorted(new_states - with_exit - set(spec.extra_terminal_states)):
        errors.append(f"擴充狀態「{s}」沒有任何轉出，必須宣告為終點狀態")
    return SpecValidation(not errors, tuple(errors))


def resolve_spec(spec: LifecycleSpec) -> Lifecycle:
    """核心＋擴充 → `Lifecycle`。擴充違規時丟 `ValueError`（這是定義階段的錯誤，不是轉換）。"""
    v = validate_spec(spec)
    if not v.ok:
        raise ValueError("擴充違反核心不變量：" + "；".join(v.errors))
    transitions = dict(CORE_TRANSITIONS)
    transitions.update(spec.extra_transitions)
    return Lifecycle(
        name=spec.relation_type,
        states=frozenset(CORE_STATES | spec.extra_states),
        events=frozenset(CORE_EVENTS | spec.extra_events),
        transitions=MappingProxyType(transitions),
        terminal_states=frozenset(CORE_TERMINAL_STATES | spec.extra_terminal_states),
    )


def lifecycle_for(relation_type: str, extensions: Mapping[str, Lifecycle] | None = None) -> Lifecycle:
    """依關係型別取生命週期；沒有擴充＝核心。（呼叫端自備 `relation_type → 已解析擴充` 的對照表。）"""
    return (extensions or {}).get(relation_type, CORE_LIFECYCLE)


def is_retrievable(
    state: str | None, retrievable: frozenset[str | None] = DEFAULT_RETRIEVABLE_STATES
) -> bool:
    """回報狀態是否屬於可檢索集合。

    集合是參數、不是定案 schema；預設集合也不是把檢索行為接入本模組。
    在還沒有自動「驗證通過」流程前，不可把「候選」排除，否則新抽取的
    Fact 會全部停在候選而讓檢索消失。``None`` 代表舊 Fact 缺席狀態，
    即「尚未處理」。
    """
    return state in retrievable


# ── 轉換與重播 ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TransitionResult:
    """單次轉換結果。非法轉換時 `ok=False`、`to_state == from_state`、`reason` 說明原因；不丟例外。"""

    ok: bool
    from_state: str | None
    event: LifecycleEvent
    to_state: str | None
    reason: str


def allowed_events(state: str | None, lifecycle: Lifecycle = CORE_LIFECYCLE) -> tuple[str, ...]:
    if state in lifecycle.terminal_states:
        return ()
    return tuple(sorted(ev for (src, ev) in lifecycle.transitions if src == state))


def apply_event(state: str | None, event: LifecycleEvent, lifecycle: Lifecycle = CORE_LIFECYCLE) -> TransitionResult:
    """純函式：`state`（`None`＝尚未建立）＋事件 → 結果。非法轉換回傳含原因的結果，不修改輸入、不丟例外。"""
    def deny(reason: str) -> TransitionResult:
        return TransitionResult(False, state, event, state, reason)

    if state is not None and state not in lifecycle.states:
        return deny(f"未知狀態「{state}」")
    if event.event_type not in lifecycle.events:
        return deny(f"未知事件「{event.event_type}」")
    if state in lifecycle.terminal_states:
        return deny(f"「{state}」是終點狀態，不得有任何轉出（收到事件「{event.event_type}」；需要新的關係實例重新走候選→有效）")
    dest = lifecycle.transitions.get((state, event.event_type))
    if dest is None:
        if state is None:
            return deny(f"尚未建立：第一個事件必須是「{EXTRACTED}」，收到「{event.event_type}」")
        allowed = "、".join(allowed_events(state, lifecycle)) or "（無）"
        return deny(f"狀態「{state}」不允許事件「{event.event_type}」（允許：{allowed}）")
    return TransitionResult(True, state, event, dest, f"{state or '（無）'} —[{event.event_type}]→ {dest}")


@dataclass(frozen=True)
class ReplayResult:
    """重播結果：狀態是事件序列的投影。`steps` 含每個事件（合法或被拒）；被拒事件不改變狀態、重播繼續。"""

    final_state: str | None
    steps: tuple[TransitionResult, ...]
    first_illegal: tuple[int, TransitionResult] | None  # (0 起算的索引, 該步結果)

    @property
    def ok(self) -> bool:
        return self.first_illegal is None


def replay(
    events: Iterable[LifecycleEvent], initial: str | None = None, lifecycle: Lifecycle = CORE_LIFECYCLE
) -> ReplayResult:
    """依序套用事件（決定性：同序列必得同結果）。被拒事件記錄但不改變狀態；`first_illegal` 為第一個被拒事件。"""
    state = initial
    steps: list[TransitionResult] = []
    first_illegal: tuple[int, TransitionResult] | None = None
    for i, ev in enumerate(tuple(events)):
        r = apply_event(state, ev, lifecycle)
        steps.append(r)
        if r.ok:
            state = r.to_state
        elif first_illegal is None:
            first_illegal = (i, r)
    return ReplayResult(state, tuple(steps), first_illegal)


# ── 互斥檢查 ─────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RelationInstance:
    """關係實例（僅供互斥檢查的輸入）：識別字、鍵〔主詞, 關係型別, 受詞〕、當前狀態。**不是儲存結構。**"""

    instance_id: str
    key: tuple[str, str, str]
    state: str | None


@dataclass(frozen=True)
class ExclusivityViolation:
    key: tuple[str, str, str]
    instance_ids: tuple[str, ...]


def check_exclusivity(instances: Iterable[RelationInstance]) -> tuple[ExclusivityViolation, ...]:
    """同一鍵在同一時刻最多一個「有效」。回傳違規（依鍵排序、實例識別字排序，決定性）。"""
    by_key: dict[tuple[str, str, str], list[str]] = {}
    for inst in instances:
        if inst.state == VALID:
            by_key.setdefault(inst.key, []).append(inst.instance_id)
    return tuple(
        ExclusivityViolation(k, tuple(sorted(ids))) for k, ids in sorted(by_key.items()) if len(ids) > 1
    )


# ── 可讀說明 ─────────────────────────────────────────────────────────────────
def explain(history: ReplayResult | Sequence[TransitionResult]) -> str:
    """中文轉換日誌（每步一行；被拒事件標「✗」並寫原因）。"""
    steps = history.steps if isinstance(history, ReplayResult) else tuple(history)
    lines: list[str] = []
    for i, r in enumerate(steps, start=1):
        ev = r.event
        date = ev.effective_date or "未提供"
        extras = [f"日期：{date}"]
        if ev.trigger_kind:
            extras.append(f"觸發：{ev.trigger_kind}")
        if ev.reason:
            extras.append(f"原因：{ev.reason}")
        if ev.evidence_ref:
            extras.append(f"依據：{ev.evidence_ref}")
        meta = "（" + "；".join(extras) + "）"
        if r.ok:
            lines.append(f"第{i}步 ✓ {r.from_state or '（無）'} —[{ev.event_type}]→ {r.to_state}　{meta}")
        else:
            lines.append(f"第{i}步 ✗ 事件「{ev.event_type}」被拒，狀態維持「{r.from_state or '（無）'}」：{r.reason}　{meta}")
    final = history.final_state if isinstance(history, ReplayResult) else (steps[-1].to_state if steps else None)
    lines.append(f"最終狀態：{final or '（尚未建立）'}")
    return "\n".join(lines)


# ── 時間維度：as_of 重播（報告260 N1；新增，零接線）─────────────────────────────────
# 註：以下以 ISO 字串（YYYY-MM-DD，與 `LifecycleEvent.effective_date` 同形狀）做字典序比較來判定事件是否已生效；
# 這是本模組唯一比較日期之處（模組開頭 docstring 已同步說明；上方既有函式皆不比較日期）。仍不解析日期、不使用時間函式。
AS_OF_STATUSES = ("no_events", "not_yet_effective", "replayed", "illegal")


@dataclass(frozen=True)
class AsOfResult:
    """`state_as_of` 結果。`status`：`no_events`（Fact 沒有任何事件＝尚未處理）、`not_yet_effective`（有事件但全部晚於
    `as_of`＝尚未生效）、`replayed`（以生效事件重播且全部合法）、`illegal`（重播時有被拒事件；`state` 仍取
    `final_state`＝已忽略被拒事件的投影，只是標示事件紀錄有異常供稽核）。`included`／`excluded`＝納入／排除的事件數。"""

    state: str | None
    status: str
    included: int
    excluded: int
    replay: ReplayResult | None


def state_as_of(
    events: Sequence[LifecycleEvent], as_of: str, lifecycle: Lifecycle = CORE_LIFECYCLE
) -> AsOfResult:
    """只重播 `effective_date` 為 `None` 或 `<= as_of` 的事件（**保持原順序**，不依日期重排），回傳狀態與判定類別。

    `as_of` 必須是 `YYYY-MM-DD`，否則 `ValueError`。不修改 `replay`；被拒事件的語意以 `replay` 為準。
    """
    if not isinstance(as_of, str) or not _ISO_DATE_RE.match(as_of):
        raise ValueError(f"as_of 必須是 YYYY-MM-DD 字串，收到 {as_of!r}")
    events = tuple(events)
    if not events:
        return AsOfResult(None, "no_events", 0, 0, None)
    included = tuple(e for e in events if e.effective_date is None or e.effective_date <= as_of)
    excluded = len(events) - len(included)
    if not included:
        return AsOfResult(None, "not_yet_effective", 0, excluded, None)
    result = replay(included, lifecycle=lifecycle)
    return AsOfResult(result.final_state, "replayed" if result.ok else "illegal", len(included), excluded, result)


def is_retrievable_as_of(
    result: AsOfResult, retrievable: frozenset[str | None] = DEFAULT_RETRIEVABLE_STATES
) -> bool:
    """`no_events`→`None in retrievable`；`not_yet_effective`→`False`；`replayed`／`illegal`→狀態是否在可檢索集合。

    `illegal` 採不隱藏（fail-open，與現有 zero-out 行為一致）；呼叫端應依 `result.status` 另行報告異常。
    """
    if result.status == "not_yet_effective":
        return False
    if result.status == "no_events":
        return None in retrievable
    return is_retrievable(result.state, retrievable)
