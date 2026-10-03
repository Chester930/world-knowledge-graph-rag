"""離線查證凍結題庫與「尚未施行」條文的涉及度。

只讀取題庫、報告267的既有分析 JSON 與兩個凍結清單候選，不連線、不讀取
``.env``，也不修改任何輸入檔。判定只使用 gold fact 的法規識別與條號。
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

ARTICLE_RE = re.compile(r"^第\s*(\d+(?:-\d+)?)\s*條")


def normalize_article(article: str | None) -> str | None:
    """將 ``第2條``、``第 21-3 條`` 等條號轉成基礎條號。"""
    if article is None:
        return None
    text = re.sub(r"\s+", "", str(article))
    match = ARTICLE_RE.match(text)
    if match:
        return match.group(1)
    match = re.match(r"^(\d+(?:-\d+)?)", text)
    return match.group(1) if match else text.replace("第", "").replace("條", "")


def source_law_to_document(source_law: str | None, documents: Iterable[Mapping[str, Any]]) -> str | None:
    """以 ``<pcode>_<名稱>`` 完整名稱對應分析 JSON 的 ``source``。"""
    if not isinstance(source_law, str):
        return None
    return next((str(document["source"]) for document in documents if document.get("source") == source_law), None)


def build_pending_index(analysis: Mapping[str, Any]) -> tuple[dict[str, dict[str, dict[str, Any]]], set[str], set[str]]:
    """建立五份待施行文件索引，並回傳待施行／未定日期的文件名稱集合。"""
    pending_docs: dict[str, dict[str, dict[str, Any]]] = {}
    pending_sources: set[str] = set()
    undetermined_sources: set[str] = set()
    for document in analysis.get("documents", []):
        source = str(document["source"])
        if document.get("kind") == "undetermined":
            undetermined_sources.add(source)
        articles = document.get("pending_articles", [])
        if not articles:
            continue
        pending_sources.add(source)
        by_article: dict[str, dict[str, Any]] = {}
        for article in articles:
            article_no = normalize_article(article.get("article_no"))
            if article_no is None:
                continue
            entry = by_article.setdefault(article_no, {"article_no": article_no, "scope": [], "effective_date": []})
            for scope in article.get("scopes", []):
                if scope not in entry["scope"]:
                    entry["scope"].append(scope)
            for effective_date in article.get("dates", []):
                if effective_date not in entry["effective_date"]:
                    entry["effective_date"].append(effective_date)
        pending_docs[source] = by_article
    return pending_docs, pending_sources, undetermined_sources


def load_frozen_question_ids(manifest: Mapping[str, Any], alternate: Mapping[str, Any]) -> list[str]:
    """比較兩個 42 題候選清單；不一致時明確失敗，不猜測權威來源。"""
    manifest_ids = list(manifest.get("eligible_ids", []))
    alternate_ids = [question["id"] for question in alternate.get("questions", [])]
    if manifest_ids != alternate_ids:
        only_manifest = sorted(set(manifest_ids) - set(alternate_ids))
        only_alternate = sorted(set(alternate_ids) - set(manifest_ids))
        raise ValueError(f"凍結42題候選清單不一致：manifest-only={only_manifest}; alternate-only={only_alternate}")
    if len(manifest_ids) != 42:
        raise ValueError(f"凍結題目數不是42：{len(manifest_ids)}")
    return manifest_ids


def _fact_record(fact: Mapping[str, Any], article_no: str | None = None) -> dict[str, Any]:
    record = {
        "exact_span": fact.get("exact_span"),
        "source_law": fact.get("source_law"),
        "source_article": fact.get("source_article"),
    }
    if article_no is not None:
        record["article_no"] = article_no
    return record


def classify_question(
    question: Mapping[str, Any],
    pending_index: Mapping[str, Mapping[str, Mapping[str, Any]]],
    pending_sources: set[str],
    undetermined_sources: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """分類單題的 gold facts，保留每個命中的原文與來源欄位。"""
    pending_hits: list[dict[str, Any]] = []
    undetermined_hits: list[dict[str, Any]] = []
    five_doc_non_pending: list[dict[str, Any]] = []
    for fact in question.get("atomic_gold_facts", []) or []:
        source_law = fact.get("source_law")
        article_no = normalize_article(fact.get("source_article"))
        if source_law in undetermined_sources:
            undetermined_hits.append(_fact_record(fact, article_no))
        if source_law in pending_sources:
            article = pending_index[source_law].get(article_no or "")
            if article:
                hit = _fact_record(fact, article_no)
                hit.update({"scope": list(article["scope"]), "effective_date": list(article["effective_date"])})
                pending_hits.append(hit)
            else:
                five_doc_non_pending.append(_fact_record(fact, article_no))
    return {"pending": pending_hits, "undetermined": undetermined_hits, "five_doc_non_pending": five_doc_non_pending}


def _question_summary(question: Mapping[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    return {"question_id": question.get("id"), "facts": facts}


def analyze_questions(
    questions: Iterable[Mapping[str, Any]],
    selected_ids: set[str],
    pending_index: Mapping[str, Mapping[str, Mapping[str, Any]]],
    pending_sources: set[str],
    undetermined_sources: set[str],
) -> dict[str, Any]:
    """對指定題目集合產生三類涉及度摘要。"""
    summaries = {"pending": [], "undetermined": [], "five_doc_non_pending": []}
    selected_questions = [question for question in questions if question.get("id") in selected_ids]
    for question in selected_questions:
        classified = classify_question(question, pending_index, pending_sources, undetermined_sources)
        for category, facts in classified.items():
            if facts:
                summaries[category].append(_question_summary(question, facts))
    return {
        "total_questions": len(selected_questions),
        "pending": {"question_count": len(summaries["pending"]), "question_ids": [x["question_id"] for x in summaries["pending"]], "questions": summaries["pending"]},
        "undetermined": {"question_count": len(summaries["undetermined"]), "question_ids": [x["question_id"] for x in summaries["undetermined"]], "questions": summaries["undetermined"]},
        "five_doc_non_pending": {"question_count": len(summaries["five_doc_non_pending"]), "question_ids": [x["question_id"] for x in summaries["five_doc_non_pending"]], "questions": summaries["five_doc_non_pending"]},
    }


def build_report(
    questions: list[Mapping[str, Any]],
    frozen_ids: list[str],
    analysis: Mapping[str, Any],
    *,
    frozen_manifest_path: str,
    frozen_alternate_path: str,
) -> dict[str, Any]:
    pending_index, pending_sources, undetermined_sources = build_pending_index(analysis)
    return {
        "as_of": analysis.get("as_of"),
        "frozen_42": analyze_questions(questions, set(frozen_ids), pending_index, pending_sources, undetermined_sources),
        "all_65": analyze_questions(questions, {str(question["id"]) for question in questions}, pending_index, pending_sources, undetermined_sources),
        "method": {
            "article_normalization": "先取第／條包住的第一個數字條號；否則保留數字前綴，去除空白；只比對 atomic_gold_facts。",
            "source_law_mapping": "source_law 必須與 <pcode>_<名稱> 形式的 documents[].source 完整相等。",
            "pending_sources": sorted(pending_sources),
            "undetermined_sources": sorted(undetermined_sources),
            "frozen_42_authority": frozen_manifest_path,
            "frozen_42_alternate_compared": frozen_alternate_path,
            "frozen_42_candidates_equal": True,
            "gold_fact_only": True,
            "note": "涉及度不代表檢索結果實際取到該條文。",
        },
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    question_path = root / "data/eval/test_cases.json"
    pending_path = root / "data/analysis/kg4_pending_effect_20261003.json"
    manifest_path = root / "data/eval/baseline_runs/20260920_frozen/frozen_manifest.json"
    alternate_path = root / "data/analysis/source_ambiguity/questions_frozen42.json"
    analysis = _read_json(pending_path)
    as_of = args.as_of or analysis.get("as_of")
    if not isinstance(as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise ValueError("as_of 必須是 YYYY-MM-DD 字串")
    date.fromisoformat(as_of)
    if analysis.get("as_of") != as_of:
        raise ValueError(f"as_of 與既有分析不一致：{as_of!r} != {analysis.get('as_of')!r}")
    questions_payload = _read_json(question_path)
    manifest = _read_json(manifest_path)
    alternate = _read_json(alternate_path)
    frozen_ids = load_frozen_question_ids(manifest, alternate)
    report = build_report(
        list(questions_payload["questions"]),
        frozen_ids,
        analysis,
        frozen_manifest_path=str(manifest_path.relative_to(root)),
        frozen_alternate_path=str(alternate_path.relative_to(root)),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frozen_42": report["frozen_42"], "all_65": report["all_65"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
