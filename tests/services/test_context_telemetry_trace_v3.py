"""V3（報告164）：`build_retrieval_trace` 三元組欄位修補的差分測試。

`old_build_retrieval_trace` 是修補前（`0be8e09`）函式的逐字副本。唯一預期差異：三元組有
`source_svo_chunk_index`／`source_article_no` 值時，兩欄由 `None` 變為該值；其餘（含 `json.dumps` 字串與鍵順序）
必須相同。
"""

import json
import random
from uuid import uuid4

from models.knowledge_graph import SVOTriple
from services.context.fact_lines import strip_type_markers
from services.context import telemetry


def old_build_retrieval_trace(
    triples: list[SVOTriple],
    fact_results: list[dict],
    prompt_lines: list[list[str]] | None,
) -> dict:
    """報告62 T0：把「檢索到什麼、排第幾、有沒有進 prompt」整理成可序列化的 trace。

    **純記錄，不改動任何檢索／排序／截斷結果。** `fact_results`／`triples` 傳入的是
    `chat()` 範圍過濾後、`_arrange_fact_lines()` 截斷**之前**的完整清單，所以
    `rank` 是檢索順位（Fact＝`vector_search_facts()` 順序、triple＝`bfs_query()`
    走訪順序，兩者不共用名次）；`in_prompt` 才反映截斷結果。

    `prompt_lines`：`_build_prompt(trace_sink=)` 收集的實際 prompt 事實行（每次
    prompt 組裝一份）。`None`（呼叫端沒有收集）時 `in_prompt` 一律為 None，
    表示「未量測」而不是「沒進 prompt」。判斷方式是比對渲染後的行文字
    （`- ` + 去型別標記後的文字，與 `_split_fact_lines()` 一致）；被
    `_split_fact_lines()` 去重／過濾掉的證據本來就不會出現在任何 prompt 行，
    因此 `in_prompt=False`，不等於「被截斷」——兩種情況要看 `prompt_lines`
    與 rank 一起判讀。
    """
    prompt_set = (
        {ln for lines in prompt_lines for ln in lines} if prompt_lines is not None else None
    )

    def _in_prompt(rendered: str) -> bool | None:
        return None if prompt_set is None else rendered in prompt_set

    fact_entries = []
    for rank, f in enumerate(fact_results):
        text = f.get("fact_text") or ""
        idx = f.get("source_svo_chunk_index")
        fact_entries.append({
            "kind": "fact",
            "rank": rank,
            "text": text,
            "score": f.get("score"),
            "source_doc_id": str(f["source_doc_id"]) if f.get("source_doc_id") is not None else None,
            "source_svo_chunk_index": int(idx) if idx is not None else None,
            "article_no": f.get("article_no"),
            "in_prompt": _in_prompt(f"- {strip_type_markers(text)}"),
        })

    triple_entries = []
    for rank, t in enumerate(triples):
        raw = t.natural_text if t.natural_text else f"{t.subject} {t.verb} {t.object}".rstrip()
        triple_entries.append({
            "kind": "triple",
            "rank": rank,
            "text": raw or "",
            "score": None,
            "source_doc_id": str(t.source_doc_id) if t.source_doc_id is not None else None,
            "source_svo_chunk_index": None,
            "article_no": None,
            "in_prompt": _in_prompt(f"- {strip_type_markers(raw or '')}"),
        })

    return {"facts": fact_entries, "triples": triple_entries, "prompt_lines": prompt_lines}


def _rand_triple(rng, with_source):
    kw = {}
    if rng.random() < 0.7:
        kw["source_doc_id"] = uuid4()
    if with_source and rng.random() < 0.8:
        kw["source_svo_chunk_index"] = rng.randint(1, 40)
    if with_source and rng.random() < 0.4:
        kw["source_article_no"] = rng.choice(["第 1 條", "第 2 條", "", "第 10 條"])
    if rng.random() < 0.5:
        kw["natural_text"] = rng.choice(["自然句。", "", None, "含 PERSON 的句子"])
    return SVOTriple(subject=rng.choice(["甲", "乙", ""]), verb=rng.choice(["導致", "給予"]), object=rng.choice(["丙", "丁"]), **kw)


def _rand_fact(rng):
    f = {"fact_text": rng.choice(["甲 規定 乙", "", None, "丙"]), "score": rng.choice([None, 0.5, 0.91])}
    if rng.random() < 0.7:
        f["source_doc_id"] = rng.choice([None, str(uuid4())])
    if rng.random() < 0.7:
        f["source_svo_chunk_index"] = rng.choice([None, 3, "4"])
    if rng.random() < 0.5:
        f["article_no"] = rng.choice([None, "第1條"])
    return f


def _expected_from_old(old, triples):
    """把舊輸出的三元組兩欄換成三元組實際值（唯一預期差異）。"""
    exp = json.loads(json.dumps(old))
    for entry, t in zip(exp["triples"], triples):
        entry["source_svo_chunk_index"] = t.source_svo_chunk_index
        entry["article_no"] = t.source_article_no
    return exp


def test_differential_1200_random_inputs_only_expected_fields_change():
    rng = random.Random(20260930)
    changed = 0
    for i in range(1200):
        with_source = i % 3 != 0
        triples = [_rand_triple(rng, with_source) for _ in range(rng.randint(0, 5))]
        facts = [_rand_fact(rng) for _ in range(rng.randint(0, 5))]
        prompt_lines = rng.choice([None, [], [["- 自然句。", "- 丙"]], [["- x"], ["- 甲 導致 丙"]]])
        old = old_build_retrieval_trace(triples, facts, prompt_lines)
        new = telemetry.build_retrieval_trace(triples, facts, prompt_lines)
        assert list(new) == list(old)
        assert new["facts"] == old["facts"] and new["prompt_lines"] == old["prompt_lines"]
        expected = _expected_from_old(old, triples)
        assert new == expected
        # 鍵名與順序不變
        for a, b in zip(new["triples"], old["triples"]):
            assert list(a) == list(b)
        # json.dumps 字串：無來源值的三元組輸出與舊版逐字相同
        if all(t.source_svo_chunk_index is None and t.source_article_no is None for t in triples):
            assert json.dumps(new, ensure_ascii=False) == json.dumps(old, ensure_ascii=False)
        else:
            changed += 1
            assert json.dumps(new, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)
    assert changed > 300


def test_triple_chunk_index_and_article_no_are_filled():
    t = SVOTriple(subject="甲", verb="導致", object="乙", source_svo_chunk_index=7, source_article_no="第 3 條")
    trace = telemetry.build_retrieval_trace([t], [], None)
    assert trace["triples"][0]["source_svo_chunk_index"] == 7
    assert trace["triples"][0]["article_no"] == "第 3 條"
