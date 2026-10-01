"""報告218 M2b：已保存檢索 trace ↔ KG#4 唯讀 join，補算 fields／relation_type／article_no／實體型別標示分布。

結構：**純運算**（索引建立、join、彙整；以假資料單元測試）與 **DB 存取**（`fetch_*`，只收 `ReadOnlyRunner`）分離。
不寫 KG、不呼叫 LLM／embedding、不改 production；標示名稱／值域為 PROVISIONAL（見 `services/semantic_marks.py`）。

對回規則（不猜測）：
- Fact：鍵 `(source_doc_id, source_svo_chunk_index, fact_text)`；實體型別以 Fact 的 subject／object 名稱對 `Entity.name`
  （KG#4 內 Entity 名稱唯一，查得 0 組重複）。名稱查無 Entity ＝「無法對回Entity」。
- triple：鍵與 `services/retrieval/bfs.py` 一致——文件取邊上 `citations_json` **最後一筆**，文字＝`natural_text`，
  無則 `f"{subject} {verb} {object}"`（verb 取最後一筆引用的 verb，缺則 rel_type）。條號取同一筆引用。
  已保存 trace 的 triple `source_svo_chunk_index` 全為 None（報告164 V3 前的快照），故以 `(doc, text)` 對回，
  trace 帶有 chunk 索引時才再以它縮小。
- 同鍵多筆：標示一致則採用；不一致列「歧義」不計入；查無列「無法對回」。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.semantic_marks_replay import EVAL_DIR, iter_trace_entries  # noqa: E402
from services import semantic_marks as sm  # noqa: E402

UNMATCHED_ENTITY = "無法對回Entity"
SCHEMES = ("A", "B", "strict")

_FACT_QUERY = (
    "MATCH (f:Fact {kg_id: $k}) "
    "OPTIONAL MATCH (f)-[:SUPPORTED_BY]->(a:LawArticle) "
    "OPTIONAL MATCH (se:Entity {kg_id: $k, name: f.subject}) "
    "OPTIONAL MATCH (oe:Entity {kg_id: $k, name: f.object}) "
    "RETURN f.source_doc_id AS doc, f.source_svo_chunk_index AS idx, f.fact_text AS text, "
    "f.subject AS subject, f.object AS object, f.verb AS verb, f.rel_type AS rel_type, "
    "a.article_no AS article_no, se.type AS subject_type, se.name AS subject_entity, "
    "oe.type AS object_type, oe.name AS object_entity"
)
_EDGE_QUERY = (
    "MATCH (s:Entity {kg_id: $k})-[x]->(o:Entity {kg_id: $k}) "
    "RETURN s.name AS subject, s.type AS subject_type, type(x) AS rel_type, "
    "x.natural_text AS natural_text, o.name AS object, o.type AS object_type, "
    "x.citations_json AS citations_json"
)


# ── DB 存取（只收 ReadOnlyRunner）─────────────────────────────────────────────
def fetch_facts(runner, kg_id: str) -> list[dict]:
    return runner.run("M2b：Fact 全表（含條號、主受詞 Entity 型別）", _FACT_QUERY, k=kg_id)


def fetch_edges(runner, kg_id: str) -> list[dict]:
    return runner.run("M2b：Entity 邊全表（含 citations_json）", _EDGE_QUERY, k=kg_id)


# ── 純運算 ────────────────────────────────────────────────────────────────────
def entity_type_marks(raw_type: str | None, found: bool, core: Mapping[str, str], ext: Mapping[str, str]) -> dict[str, str]:
    """A／B／strict 三種「概念」處理並列；查無 Entity 時三者皆為 `無法對回Entity`（不猜型別）。"""
    if not found:
        return {s: UNMATCHED_ENTITY for s in SCHEMES}
    return {s: sm.mark_entity_type(raw_type, core, ext, s) for s in SCHEMES}


def _flatten_types(role: str, per_scheme: Mapping[str, str]) -> dict[str, str]:
    return {f"{role}_type_{s}": m for s, m in per_scheme.items()}


def build_fact_index(
    rows: Iterable[dict], core: Mapping[str, str], ext: Mapping[str, str], extra_fields: tuple[str, ...] = ()
) -> dict[tuple, list[dict]]:
    rows = list(rows)
    docs_with_article = {str(r.get("doc")) for r in rows if sm.has_article_no(r.get("article_no"))}
    index: dict[tuple, list[dict]] = {}
    for r in rows:
        marks = {
            "fields": sm.mark_fact_fields(r.get("subject"), r.get("object"), r.get("verb")),
            "relation_type": sm.mark_relation_type(r.get("rel_type")),
            "article_no": sm.mark_article_no(r.get("article_no"), str(r.get("doc")) in docs_with_article),
        }
        marks.update(_flatten_types("subject", entity_type_marks(
            r.get("subject_type"), r.get("subject_entity") is not None, core, ext)))
        marks.update(_flatten_types("object", entity_type_marks(
            r.get("object_type"), r.get("object_entity") is not None, core, ext)))
        marks.update({f: r.get(f) for f in extra_fields})  # 報告223：呼叫端可附帶原列欄位（如端點名稱）；預設無
        index.setdefault((str(r.get("doc")), r.get("idx"), r.get("text")), []).append(marks)
    return index


def _parse(raw: Any) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def build_edge_index(
    rows: Iterable[dict], core: Mapping[str, str], ext: Mapping[str, str], extra_fields: tuple[str, ...] = ()
) -> dict[tuple, list[dict]]:
    """以邊最後一筆引用建鍵（同 `bfs._bfs_records_to_triples`）。無引用的邊無法產生與 trace 一致的鍵，略過。"""
    rows = list(rows)
    docs_with_article: set[str] = set()
    parsed: list[tuple[dict, dict]] = []
    for r in rows:
        cites = _parse(r.get("citations_json"))
        for c in cites:
            if sm.has_article_no(c.get("article_no")):
                docs_with_article.add(str(c.get("source_doc_id") or "None"))
        if cites:
            parsed.append((r, cites[-1]))
    index: dict[tuple, list[dict]] = {}
    for r, latest in parsed:
        verb = latest.get("verb", r.get("rel_type"))
        text = r.get("natural_text") or f"{r.get('subject')} {verb} {r.get('object')}".rstrip()
        doc = str(latest.get("source_doc_id")) if latest.get("source_doc_id") else "None"
        marks = {
            "fields": sm.mark_fact_fields(r.get("subject"), r.get("object"), verb),
            "relation_type": sm.mark_relation_type(r.get("rel_type")),
            "article_no": sm.mark_article_no(latest.get("article_no"), doc in docs_with_article),
        }
        marks.update(_flatten_types("subject", entity_type_marks(r.get("subject_type"), True, core, ext)))
        marks.update(_flatten_types("object", entity_type_marks(r.get("object_type"), True, core, ext)))
        marks.update({f: r.get(f) for f in extra_fields})
        index.setdefault((doc, text), []).append({"idx": latest.get("source_svo_chunk_index"), "marks": marks})
    return index


def _edge_candidates(edge_index: dict, e: dict) -> list[dict]:
    """triple 鍵為 `(doc, text)`；trace 帶 chunk 索引時再以它縮小（舊快照恆為 None，不縮小）。"""
    items = edge_index.get((str(e.get("source_doc_id")), e.get("text"))) or []
    idx = e.get("source_svo_chunk_index")
    if idx is not None:
        items = [i for i in items if i["idx"] == idx]
    return [i["marks"] for i in items]


def join_summarize(entries: Iterable[tuple[str, dict]], fact_index: dict, edge_index: dict) -> dict:
    """依 kind 分別 join；回傳各 kind 的 對回統計＋被檢索／進 prompt（in_prompt is True）各維度標示計數。"""
    out: dict[str, dict] = {}
    for _qid, e in entries:
        kind = e.get("kind")
        if kind not in ("fact", "triple"):
            continue
        s = out.setdefault(kind, {"entries": 0, "matched": 0, "unmatched": 0, "ambiguous": 0,
                                  "in_prompt_matched": 0, "retrieved": {}, "in_prompt": {}})
        s["entries"] += 1
        if kind == "fact":
            cands = fact_index.get((str(e.get("source_doc_id")), e.get("source_svo_chunk_index"), e.get("text")))
        else:
            cands = _edge_candidates(edge_index, e)
        if not cands:
            s["unmatched"] += 1
            continue
        if any(c != cands[0] for c in cands[1:]):
            s["ambiguous"] += 1
            continue
        s["matched"] += 1
        ip = e.get("in_prompt") is True
        if ip:
            s["in_prompt_matched"] += 1
        for dim, mark in cands[0].items():
            s["retrieved"].setdefault(dim, Counter())[mark] += 1
            if ip:
                s["in_prompt"].setdefault(dim, Counter())[mark] += 1
    for s in out.values():
        for grp in ("retrieved", "in_prompt"):
            s[grp] = {d: dict(c) for d, c in s[grp].items()}
    return out


def run_join(runner, kg_id: str, core: Mapping[str, str], ext: Mapping[str, str], eval_dir: Path = EVAL_DIR) -> dict:
    fact_index = build_fact_index(fetch_facts(runner, kg_id), core, ext)
    edge_index = build_edge_index(fetch_edges(runner, kg_id), core, ext)
    per_file: dict[str, dict] = {}
    for path in sorted(eval_dir.rglob("records*.json")):
        if "backup" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = list(iter_trace_entries(data))
        if entries:
            per_file[path.relative_to(eval_dir).as_posix()] = join_summarize(entries, fact_index, edge_index)
    return {"per_file": per_file, "fact_index_keys": len(fact_index), "edge_index_keys": len(edge_index)}


def _env_value(env_file: Path, key: str) -> str | None:
    """讀單一 .env 值；不改 os.environ、不輸出。"""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        m = re.match(rf"\s*{re.escape(key)}\s*=\s*(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return None


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    from core.constants import ENTITY_TYPES  # noqa: PLC0415
    from neo4j import GraphDatabase  # noqa: PLC0415
    from scripts.analysis.semantic_layer_invariants import (  # noqa: PLC0415
        BOLT_URI_DEFAULT, EXPECTED_TOTALS, KG_ID_DEFAULT, ReadOnlyRunner, totals,
    )

    password = _env_value(args.env_file, "NEO4J_PASSWORD")
    if not password:
        raise SystemExit("需要 .env 的 NEO4J_PASSWORD")
    core = {sm.normalize_type_key(k): k for k in ENTITY_TYPES}
    ext_payload = json.loads((_REPO / "data" / "schema_org_entity_types.json").read_text(encoding="utf-8"))
    ext = {sm.normalize_type_key(t["label"]): t["id"] for t in ext_payload.get("types", [])}
    driver = GraphDatabase.driver(BOLT_URI_DEFAULT, auth=(_env_value(args.env_file, "NEO4J_USER") or "neo4j", password))
    try:
        runner = ReadOnlyRunner(driver)
        before = totals(runner, KG_ID_DEFAULT, "before")
        if before != EXPECTED_TOTALS:
            raise SystemExit(f"資料量與預期不符，停止：{before}")
        result = run_join(runner, KG_ID_DEFAULT, core, ext)
        after = totals(runner, KG_ID_DEFAULT, "after")
        if after != before:
            raise SystemExit(f"唯讀前後總數不一致：{before} -> {after}")
    finally:
        driver.close()
    result.update({"before": before, "after": after, "totals_identical": before == after, "cypher_log": runner.log})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"totals_identical": result["totals_identical"], "before": before,
                      "files": len(result["per_file"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
