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
    ConfigLoader,
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
