"""`core.kg_config.stages` —— 報告33 §4.4 stage-registry 骨架的一致性檢查。

登記表是宣告式資料;這些測試確保它跟 `KGConfig` 對得上、gate 引用合法、
不會靜默漏掉分區。
"""
from core.kg_config import KGConfig
from core.kg_config.stages import (
    STAGE_REGISTRY,
    Blocker,
    Harness,
    sections_covered,
    stages_for_section,
    stages_without_harness,
    unblocked_stages,
)


def test_every_kgconfig_section_has_at_least_one_stage():
    kg_sections = set(KGConfig().model_dump().keys())
    assert kg_sections <= sections_covered(), (
        f"未被任何 stage 涵蓋的 KGConfig 分區: {kg_sections - sections_covered()}"
    )


def test_every_stage_config_section_is_a_real_kgconfig_section():
    kg = KGConfig()
    for s in STAGE_REGISTRY.values():
        assert hasattr(kg, s.config_section), f"{s.id} 的 config_section '{s.config_section}' 不存在於 KGConfig"


def test_every_stage_param_is_a_real_field_of_its_section():
    kg = KGConfig()
    for s in STAGE_REGISTRY.values():
        section = getattr(kg, s.config_section)
        fields = set(section.model_dump().keys())
        for p in s.params:
            assert p in fields, f"{s.id} 的 param '{p}' 不在 {s.config_section} 分區"


def test_every_gate_metric_is_declared_in_its_stage():
    for s in STAGE_REGISTRY.values():
        metric_names = {m.name for m in s.metrics}
        for g in s.gates:
            assert g.metric in metric_names, f"{s.id} 的 gate 指向未宣告的 metric '{g.metric}'"


def test_gate_comparators_are_valid():
    for s in STAGE_REGISTRY.values():
        for g in s.gates:
            assert g.comparator in ("<=", ">=", "==")
            if isinstance(g.threshold, (int, float)):
                assert g.threshold >= 0


def test_registry_key_matches_stage_id():
    for key, s in STAGE_REGISTRY.items():
        assert key == s.id


def test_helpers_partition_the_registry():
    # unblocked = blocked_by NONE
    assert all(s.blocked_by is Blocker.NONE for s in unblocked_stages())
    # 目前所有 stage 都有 blocker（drain / extraction / l2）——列出來供人核對
    blocked = [s.id for s in STAGE_REGISTRY.values() if s.blocked_by is not Blocker.NONE]
    assert len(blocked) == len(STAGE_REGISTRY) - len(unblocked_stages())


def test_manual_harness_stages_are_the_consolidation_backlog():
    """`harness == MANUAL` 的階段 = 「把報告手動診斷收斂成自動 eval suite」的待辦。
    目前應是 dedup / reltype / routing / decompose 這幾個（報告19/20/25/27 已有 harness
    的不算）。"""
    manual_ids = {s.id for s in stages_without_harness()}
    assert manual_ids == {
        "routing.kg_select", "dedup.entity", "reltype.reconcile", "generation.decompose",
    }


def test_theta_sweep_stages_expose_their_params():
    """`run_theta_sweep.py` 可直接引用這些階段的 params，不必硬編碼常數名。"""
    bfs = stages_for_section("bfs")
    all_params = {p for s in bfs for p in s.params}
    assert {"seed_max_degree", "per_seed_limit", "expand_when_below"} <= all_params
