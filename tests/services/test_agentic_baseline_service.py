"""services/agentic_baseline_service.py（B2 證據蒐集側）單元測試。

用假的 retrieve／reflect 注入函式，不碰 LLM／索引。
"""
from services import agentic_baseline_service as svc
from services.agentic_baseline_service import ReflectVerdict


# ── route_complexity ──────────────────────────────────────────────

def test_route_complexity_two_question_marks_is_complex():
    assert svc.route_complexity("要滿幾個月？獎勵金發幾個月？") == "complex"


def test_route_complexity_conjunction_is_complex():
    # 報告 36 §7 的連接詞判準（且/或/以及/並/分別）
    assert svc.route_complexity("應於開始僱用之日起三十日內，並於連續滿三個月之日起申請。") == "complex"
    assert svc.route_complexity("分別完成報備及申請。") == "complex"


def test_route_complexity_entity_count_threshold():
    assert svc.route_complexity("關於甲乙丙的規定。", entity_count=3) == "complex"
    assert svc.route_complexity("關於甲的規定。", entity_count=1) == "simple"


def test_route_complexity_plain_question_is_simple():
    assert svc.route_complexity("婚假可以請幾天？") == "simple"


# ── split_into_subquestions ──────────────────────────────────────

def test_split_two_questions():
    assert svc.split_into_subquestions("要滿幾個月？獎勵金發幾個月？") == [
        "要滿幾個月？", "獎勵金發幾個月？"
    ]


def test_split_single_question_unchanged():
    assert svc.split_into_subquestions("婚假幾天？") == ["婚假幾天？"]


def test_split_caps_at_max():
    q = "？".join(f"問{i}" for i in range(10)) + "？"
    assert len(svc.split_into_subquestions(q)) == svc._MAX_SUBQUESTIONS


# ── gather_evidence_agentic：simple 路徑 ─────────────────────────

def _hit(source, idx, text="內容"):
    return {"source": source, "chunk_index": idx, "chunk_text": text}


def test_simple_path_single_retrieval_no_reflect():
    calls = []

    def retrieve(q, *, top_k):
        calls.append((q, top_k))
        return [_hit("N01", 0)]

    def reflect(sq, ev):  # 不該被呼叫
        raise AssertionError("simple 路徑不應反思")

    result = svc.gather_evidence_agentic("婚假幾天？", retrieve, reflect)
    assert result.complexity == "simple"
    assert result.retrieval_calls == 1
    assert result.reflect_calls == 0
    assert result.context_lines == ["【來源：N01，第0段】\n內容"]


# ── gather_evidence_agentic：complex 路徑 ───────────────────────

def test_complex_sufficient_first_round_one_retrieve_per_subq():
    def retrieve(q, *, top_k):
        return [_hit("N01", 0)]

    def reflect(sq, ev):
        return ReflectVerdict(sufficient=True)

    result = svc.gather_evidence_agentic("要滿幾個月？發幾個月？", retrieve, reflect)
    assert result.complexity == "complex"
    assert result.sub_questions == ["要滿幾個月？", "發幾個月？"]
    assert result.retrieval_calls == 2   # 每子問題一次、都足夠
    assert result.reflect_calls == 2
    assert result.rounds_per_subquestion == [1, 1]


def test_complex_insufficient_refines_query_with_missing_then_retries():
    seen_queries = []

    def retrieve(q, *, top_k):
        seen_queries.append(q)
        return [_hit("N01", len(seen_queries))]

    n = {"calls": 0}

    def reflect(sq, ev):
        n["calls"] += 1
        # 每個子問題：第一輪不足（給缺口），第二輪足夠
        return ReflectVerdict(sufficient=n["calls"] % 2 == 0, missing="核銷期限")

    result = svc.gather_evidence_agentic("補助多少？期限多久？", retrieve, reflect)
    assert result.complexity == "complex"
    # 不足時第二輪查詢應帶上 missing
    assert any("核銷期限" in q for q in seen_queries)
    assert result.rounds_per_subquestion == [2, 2]


def test_complex_respects_max_rounds():
    def retrieve(q, *, top_k):
        return [_hit("N01", 0)]

    def reflect(sq, ev):
        return ReflectVerdict(sufficient=False, missing="更多")  # 永遠不足

    result = svc.gather_evidence_agentic(
        "問一？問二？", retrieve, reflect, max_rounds=3, retrieval_budget=99
    )
    assert result.rounds_per_subquestion == [3, 3]
    assert result.retrieval_calls == 6


def test_complex_respects_retrieval_budget():
    def retrieve(q, *, top_k):
        return [_hit("N01", 0)]

    def reflect(sq, ev):
        return ReflectVerdict(sufficient=False, missing="更多")

    result = svc.gather_evidence_agentic(
        "問一？問二？問三？", retrieve, reflect, max_rounds=5, retrieval_budget=4
    )
    assert result.retrieval_calls == 4  # 總預算封頂，不到 3×5


def test_evidence_deduped_by_source_and_chunk_index():
    def retrieve(q, *, top_k):
        return [_hit("N01", 0, "同一塊"), _hit("N02", 1, "另一塊")]

    def reflect(sq, ev):
        return ReflectVerdict(sufficient=True)

    result = svc.gather_evidence_agentic("問一？問二？", retrieve, reflect)
    assert len(result.evidence) == 2  # 兩子問題各回傳相同兩塊 → 去重成 2
    assert result.context_char_len == sum(len(l) for l in result.context_lines)
