"""`core.kg_config` —— 報告33 §3.9 / 論文 04 §4.10、05 §5.3.6 落地第 1 步的驗收測試。

涵蓋 §4.10「驗收標準」四項中的兩項（第 1 步交付）：
  - golden test：`KGConfig()` 逐欄位 == 重構前的模組常數值
  - deep-immutability test：任一層（含巢狀）寫入拋錯
另加合併語意 test 與來源層疊測試（第 2 步接線前先固定行為）。
"""
from __future__ import annotations

import json

import pytest

from core import constants as C
from core.kg_config import (
    CONFIG_SCHEMA_VERSION,
    ConfigLoader,
    ConfigSchemaVersionError,
    DictConfigSource,
    FileConfigSource,
    KGConfig,
    deep_merge,
)


# ── golden test：shipped defaults == 重構前常數 ─────────────────────────────
def test_kgconfig_defaults_match_live_module_constants():
    """`KGConfig()`（無任何設定來源）逐欄位等於 `core/constants.py`、
    `routers/agent.py`、`services/svo_service.py` 目前的模組常數值。遷移每一環都
    不得讓這條 fail —— 這是「行為零變化」不變式的機械化把關（論文 04 §4.10）。"""
    import routers.agent as agent
    import services.svo_service as svo

    cfg = KGConfig()

    # core/constants.py
    assert cfg.routing.kg_route_threshold == C.KG_ROUTE_THRESHOLD
    assert cfg.routing.classify_auto_threshold == C.CLASSIFY_AUTO_THRESHOLD
    assert cfg.routing.classify_min_threshold == C.CLASSIFY_MIN_THRESHOLD
    assert cfg.dedup.edit_ratio_threshold == C.ENTITY_DEDUP_EDIT_RATIO_THRESHOLD
    assert cfg.dedup.cosine_threshold == C.ENTITY_DEDUP_COSINE_THRESHOLD
    assert cfg.dedup.escalate_low_threshold == C.ENTITY_DEDUP_ESCALATE_LOW_THRESHOLD
    assert cfg.reltype.compare_cosine_threshold == C.COMPARE_COSINE_THRESHOLD
    assert cfg.reltype.qsim_assign_threshold == C.QSIM_ASSIGN_THRESHOLD
    assert cfg.reltype.qsim_escalate_low_threshold == C.QSIM_ESCALATE_LOW_THRESHOLD
    assert cfg.extraction.uncovered_sentence_threshold == svo.UNCOVERED_SENTENCE_THRESHOLD

    # routers/agent.py
    assert cfg.bfs.seed_entity_limit == agent._SEED_ENTITY_LIMIT
    assert cfg.bfs.seed_max_degree == agent._SEED_MAX_DEGREE
    assert cfg.bfs.per_seed_limit == agent._BFS_PER_SEED_LIMIT
    assert cfg.bfs.doc_scope_top_n_facts == agent._DOC_SCOPE_TOP_N_FACTS
    assert cfg.factlist.truncate_k == agent._FACT_LINE_TRUNCATE_K
    assert cfg.factlist.reorder_threshold_k == agent._FACT_LINE_REORDER_THRESHOLD_K
    assert cfg.factlist.bfs_keep_max == agent._BFS_KEEP_MAX
    assert cfg.factlist.min_bfs_slots == agent._MIN_BFS_SLOTS
    assert cfg.factlist.rrf_k == agent._RRF_K
    assert cfg.decompose.max_subquestions == agent._MAX_SUBQUESTIONS
    assert cfg.decompose.tier_min_members == agent._TIER_MIN_MEMBERS

    # services/svo_service.py
    assert cfg.bfs.expand_when_below == svo._BFS_EXPAND_WHEN_BELOW
    assert cfg.bfs.prize_top_k == svo._BFS_PRIZE_TOP_K

    # domain（第 3a 步）—— generation prompt 前綴逐字等於 _TAIWAN_CONTEXT_INSTRUCTION
    assert cfg.domain.system_context == agent._TAIWAN_CONTEXT_INSTRUCTION
    assert cfg.domain.target_language == "zh-Hant"
    assert cfg.domain.name == "taiwan-labor-law"


def test_loader_with_no_sources_equals_shipped_defaults():
    assert ConfigLoader().load().model_dump() == KGConfig().model_dump()


# ── deep-immutability test ────────────────────────────────────────────────
def test_kgconfig_is_deeply_frozen():
    from core.kg_config import BfsConfig

    cfg = KGConfig()
    with pytest.raises(Exception):
        cfg.bfs = BfsConfig()          # 頂層 frozen
    with pytest.raises(Exception):
        cfg.bfs.seed_max_degree = 999  # 巢狀子模型也 frozen
    with pytest.raises(Exception):
        cfg.dedup.cosine_threshold = 0.5


def test_kgconfig_rejects_unknown_field():
    with pytest.raises(Exception):
        KGConfig.model_validate({"bfs": {"seed_max_degree": 100, "nope": 1}})


def test_kgconfig_validates_ranges():
    with pytest.raises(Exception):
        KGConfig.model_validate({"dedup": {"cosine_threshold": 1.5}})
    with pytest.raises(Exception):
        KGConfig.model_validate({"bfs": {"seed_max_degree": 0}})


# ── 合併語意 test（報告33 §3.9.3 / 論文 05 §5.3.6）────────────────────────
def test_deep_merge_recurses_dicts_and_replaces_scalars():
    base = {"bfs": {"seed_max_degree": 100, "per_seed_limit": 30}, "x": 1}
    deep_merge(base, {"bfs": {"per_seed_limit": 60}, "x": 2})
    assert base == {"bfs": {"seed_max_degree": 100, "per_seed_limit": 60}, "x": 2}


def test_deep_merge_replaces_lists_wholesale():
    base = {"g": {"units": ["a", "b", "c"]}}
    deep_merge(base, {"g": {"units": ["x"]}})
    assert base == {"g": {"units": ["x"]}}


def test_deep_merge_none_is_explicit_override():
    base = {"k": "v"}
    deep_merge(base, {"k": None})
    assert base == {"k": None}


def test_deep_merge_absent_key_keeps_base():
    base = {"a": 1, "b": 2}
    deep_merge(base, {"a": 9})
    assert base == {"a": 9, "b": 2}


def test_deep_merge_skips_underscore_comment_keys():
    base = {"bfs": {"seed_max_degree": 100}}
    deep_merge(base, {"_note": "說明", "bfs": {"_c": "x", "seed_max_degree": 200}})
    assert base == {"bfs": {"seed_max_degree": 200}}


# ── 來源層疊 ──────────────────────────────────────────────────────────────
def test_layering_pack_then_kg_then_request():
    src = DictConfigSource(
        packs={"generic": {"bfs": {"seed_max_degree": 200, "expand_when_below": 12}}},
        kg_overrides={"kg-A": {"bfs": {"seed_max_degree": 300, "per_seed_limit": 45}}},
    )
    cfg = ConfigLoader([src]).load(
        "kg-A", domain_pack="generic", request_overrides={"bfs": {"per_seed_limit": 50}}
    )
    assert cfg.bfs.expand_when_below == 12         # pack 覆蓋 default
    assert cfg.bfs.seed_max_degree == 300          # kg 覆蓋 pack
    assert cfg.bfs.per_seed_limit == 50            # request 覆蓋 kg
    assert cfg.bfs.doc_scope_top_n_facts == KGConfig().bfs.doc_scope_top_n_facts  # 未覆蓋 = default


def test_load_without_domain_pack_ignores_packs():
    """`domain_pack=None`（預設）→ 不載入任何 pack，行為零變化。"""
    src = DictConfigSource(packs={"generic": {"bfs": {"seed_max_degree": 200}}})
    assert ConfigLoader([src]).load("kg-A").model_dump() == KGConfig().model_dump()


@pytest.mark.asyncio
async def test_two_kgconfigs_concurrent_no_cross_contamination():
    """報告33 §5.4 驗收標準之一：單一行程、兩個 KG、兩個 domain pack，並行載入
    → 兩邊的領域指示與門檻值互不污染（frozen KGConfig 無共享可變狀態）。"""
    import asyncio

    src = DictConfigSource(
        packs={
            "generic": {"domain": {"name": "generic", "system_context": "中性。"}},
        },
        kg_overrides={
            "kg-A": {"bfs": {"seed_max_degree": 111}},
            "kg-B": {"bfs": {"seed_max_degree": 222}},
        },
    )
    loader = ConfigLoader([src])

    async def load_a():
        return loader.load("kg-A", domain_pack="generic")

    async def load_b():
        return loader.load("kg-B")  # 台灣預設，不套包

    # 交錯並行載入多次，任一次的結果都不該受另一邊影響
    results = await asyncio.gather(*([load_a(), load_b()] * 15))
    a_results = results[0::2]
    b_results = results[1::2]
    assert all(r.domain.system_context == "中性。" for r in a_results)
    assert all(r.domain.system_context == KGConfig().domain.system_context for r in b_results)
    assert all(r.bfs.seed_max_degree == 111 for r in a_results)
    assert all(r.bfs.seed_max_degree == 222 for r in b_results)
    a, b = a_results[0], b_results[0]
    # frozen：任一邊都不能就地改
    with pytest.raises(Exception):
        a.bfs.seed_max_degree = 999
    with pytest.raises(Exception):
        b.domain.system_context = "x"


def test_multiple_sources_later_wins_in_same_layer():
    s1 = DictConfigSource(kg_overrides={"k": {"bfs": {"seed_max_degree": 111}}})
    s2 = DictConfigSource(kg_overrides={"k": {"bfs": {"seed_max_degree": 222}}})
    assert ConfigLoader([s1, s2]).load("k").bfs.seed_max_degree == 222


def test_kg_id_none_yields_shipped_defaults():
    src = DictConfigSource(kg_overrides={"kg-A": {"bfs": {"seed_max_degree": 999}}})
    assert ConfigLoader([src]).load(None).model_dump() == KGConfig().model_dump()


def test_domain_pack_overrides_system_context():
    """第 3a 步：載入名為 generic 的 domain pack → `domain.system_context` 被覆蓋，
    其餘欄位（含 scalar 門檻）不動。"""
    src = DictConfigSource(
        packs={"generic": {"domain": {"name": "generic", "system_context": "中性前綴。"}}}
    )
    cfg = ConfigLoader([src]).load("kg-A", domain_pack="generic")
    assert cfg.domain.system_context == "中性前綴。"
    assert cfg.domain.name == "generic"
    assert cfg.domain.target_language == "zh-Hant"           # 未覆蓋 = 預設
    assert cfg.bfs.seed_max_degree == KGConfig().bfs.seed_max_degree

    # 不指定 domain_pack（或指定不存在的）→ 台灣預設不變
    assert ConfigLoader([src]).load("kg-A").domain.system_context == KGConfig().domain.system_context


def test_shipped_domain_pack_files_parse():
    """`config/domain_packs/*.json` 能被 FileConfigSource 讀進來且結構合法。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "config"
    src = FileConfigSource(root)
    generic = ConfigLoader([src]).load(None, domain_pack="generic")
    assert generic.domain.name == "generic"
    assert generic.domain.system_context != KGConfig().domain.system_context  # 已換中性版
    taiwan = ConfigLoader([src]).load(None, domain_pack="taiwan-labor-law")
    assert taiwan.model_dump() == KGConfig().model_dump()  # 等於不載入任何 pack


def test_file_config_source_reads_json(tmp_path):
    (tmp_path / "domain_packs").mkdir()
    (tmp_path / "kg").mkdir()
    (tmp_path / "domain_packs" / "acme.json").write_text(
        json.dumps({"bfs": {"seed_max_degree": 250}}), encoding="utf-8"
    )
    (tmp_path / "kg" / "kg-7.json").write_text(
        json.dumps({"bfs": {"per_seed_limit": 77}}), encoding="utf-8"
    )
    cfg = ConfigLoader([FileConfigSource(tmp_path)]).load("kg-7", domain_pack="acme")
    assert cfg.bfs.seed_max_degree == 250          # pack
    assert cfg.bfs.per_seed_limit == 77            # kg profile


def test_file_config_source_missing_files_are_empty(tmp_path):
    assert ConfigLoader([FileConfigSource(tmp_path)]).load("nope").model_dump() == KGConfig().model_dump()


# ── schema 版本把關（報告33 §5 R6 / §6 第 5b 步）─────────────────────────────

def test_schema_version_absent_is_compatible():
    """未宣告 schema_version 的設定檔照常載入（相容所有既有檔）。"""
    src = DictConfigSource(kg_overrides={"kg-A": {"bfs": {"seed_max_degree": 111}}})
    assert ConfigLoader([src]).load("kg-A").bfs.seed_max_degree == 111


def test_schema_version_current_is_accepted_and_not_merged():
    """宣告當前版本 → 正常；schema_version 本身不進 KGConfig（不觸發 extra=forbid）。"""
    src = DictConfigSource(
        kg_overrides={"kg-A": {"schema_version": CONFIG_SCHEMA_VERSION,
                               "bfs": {"seed_max_degree": 123}}}
    )
    cfg = ConfigLoader([src]).load("kg-A")
    assert cfg.bfs.seed_max_degree == 123
    assert not hasattr(cfg, "schema_version")


def test_schema_version_future_is_rejected():
    src = DictConfigSource(
        packs={"p": {"schema_version": CONFIG_SCHEMA_VERSION + 1, "domain": {"name": "p"}}}
    )
    with pytest.raises(ConfigSchemaVersionError, match=r"domain pack 'p'"):
        ConfigLoader([src]).load("kg-A", domain_pack="p")


def test_schema_version_non_int_is_rejected():
    src = DictConfigSource(kg_overrides={"kg-A": {"schema_version": "1"}})
    with pytest.raises(ConfigSchemaVersionError, match="必須是整數"):
        ConfigLoader([src]).load("kg-A")


def test_schema_version_bool_is_rejected():
    """bool 是 int 的子型別 —— 明確擋掉 True/False 被當成 1/0。"""
    src = DictConfigSource(kg_overrides={"kg-A": {"schema_version": True}})
    with pytest.raises(ConfigSchemaVersionError, match="必須是整數"):
        ConfigLoader([src]).load("kg-A")


def test_shipped_domain_packs_declare_current_schema_version():
    """內建兩個 domain pack 都帶 schema_version，且等於當前版本。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "config" / "domain_packs"
    for name in ("taiwan-labor-law", "generic"):
        data = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
        assert data["schema_version"] == CONFIG_SCHEMA_VERSION
