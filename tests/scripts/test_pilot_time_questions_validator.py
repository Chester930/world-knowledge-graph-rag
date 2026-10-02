"""報告264 Q5：時間感知問題集驗證器與題庫（`data/eval/pilot_time_questions.json`）的離線測試。"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.analysis import pilot_time_questions_validator as v
from scripts.analysis import pilot_version_corpus_builder as builder

REPO = Path(v._REPO)
QUESTIONS = REPO / "data" / "eval" / "pilot_time_questions.json"
SRC = Path(v.__file__).read_text(encoding="utf-8")
CRITERIA_SHA256 = "07648c6a7fe70024c3b767d1e772fe6960c873acd3134ee2a6306d864c08a1de"  # 判準在看到任何檢索結果前定稿；改動即失敗
REAL_CORPUS = Path(r"D:\Users\666\Desktop\kg-runtime-pilot") / str(builder.PILOT_KG_ID_DEFAULT)


def row(pcode, article, content, valid_from, content_hash=None, law_name="某法"):
    return {"pcode": pcode, "law_name": law_name, "article_no": article, "content": content, "version_date": valid_from, "valid_from": valid_from,
            "valid_to": None, "is_current": True, "valid_from_basis": "x", "version_id": f"v-{pcode}-{article}-{valid_from}",
            "content_hash": content_hash or hashlib.sha1(content.encode()).hexdigest(), "retrieved_at": "2026-08-19T17:00:00+08:00", "source_url": "u"}


def fake_files():
    rows = []
    for n in range(1, 10):  # N0030001 第 1～9 條：實質修改
        rows += [row("N0030001", str(n), f"條文{n}的內容甲乙丙", "2000-01-01"), row("N0030001", str(n), f"條文{n}的完全不同內容丁戊己", "2020-01-01")]
    for n in range(10, 20):  # 10～19：僅排版
        rows += [row("N0030001", str(n), f"條文 {n} 排版 內容", "2000-01-01"), row("N0030001", str(n), f"條文{n}排版內容", "2020-01-01")]
    for n in range(20, 30):  # 20～29：雜湊相同
        rows += [row("N0030001", str(n), f"條文{n}相同內容", "2000-01-01", "h"), row("N0030001", str(n), f"條文{n}相同內容", "2020-01-01", "h")]
    for n in range(1, 4):  # 請假規則第 1～3 條：實質修改
        rows += [row("N0030006", str(n), f"規則{n}內容甲乙", "2001-02-03"), row("N0030006", str(n), f"規則{n}完全不同內容丙丁", "2021-04-05")]
    return {"moj_history_20260819T000000Z-history.json": rows}


@pytest.fixture(scope="module")
def data():
    files = fake_files()
    manifest = builder.build_corpus(files, control_limit=10)["manifest"]
    return files, manifest


# ---- 選題規則 ------------------------------------------------------------------

def test_selection_stride_full_coverage_and_controls(data):
    _, manifest = data
    selected = v.select_question_pairs(manifest)
    assert [i for i, _ in selected["substantive"]] == [0, 4, 8, 9, 10, 11]  # 勞基法 9 對每隔 4 取 → 0,4,8；請假規則全部 3 對 → 9,10,11
    assert [(p["old"]["pcode"], p["old"]["article_no"]) for _, p in selected["substantive"]] == [
        ("N0030001", "1"), ("N0030001", "5"), ("N0030001", "9"), ("N0030006", "1"), ("N0030006", "2"), ("N0030006", "3")]
    assert [i for i, _ in selected["format_only"]] == [0, 3, 6] and [i for i, _ in selected["same_hash"]] == [0, 3, 6]
    assert [p["old"]["article_no"] for _, p in selected["format_only"]] == ["10", "13", "16"]
    assert v.select_question_pairs(manifest) == selected  # 決定性


def test_selection_uses_numeric_article_order_not_string_order():
    rows = []
    for n in (2, 10, 1, 11, 3):
        rows += [row("N0030001", str(n), f"條文{n}內容甲乙丙", "2000-01-01"), row("N0030001", str(n), f"條文{n}完全不同內容丁戊", "2020-01-01")]
    manifest = builder.build_corpus({"moj_history_20260819T000000Z-history.json": rows})["manifest"]
    picked = [p["old"]["article_no"] for _, p in v.select_question_pairs(manifest)["substantive"]]
    assert picked == ["1", "11"]  # 數值排序 1,2,3,10,11 → 序號 0、4 → 第 1、11 條（字串排序 1,10,11,2,3 會得到第 1、3 條）


def test_skeleton_ids_as_of_and_expected_versions(data):
    _, manifest = data
    skeleton = v.skeleton_questions(manifest)
    assert len(skeleton) == 6 * 2 + 3 + 3
    by_id = {s["id"]: s for s in skeleton}
    old, new = by_id["PTQ-N0030001-1-old"], by_id["PTQ-N0030001-1-new"]
    assert (old["as_of"], old["expected_valid_from"], old["other_valid_from"], old["expected_role"]) == ("2000-01-31", "2000-01-01", "2020-01-01", "old")
    assert (new["as_of"], new["expected_valid_from"], new["other_valid_from"], new["expected_role"]) == ("2020-01-31", "2020-01-01", "2000-01-01", "new")
    ctl = by_id["PTQ-N0030001-10-ctl-format_only"]
    assert ctl["as_of"] == "2020-01-31" and ctl["acceptable_valid_froms"] == ["2000-01-01", "2020-01-01"] and ctl["expected_role"] == "either"
    assert v.as_of_for("2024-07-31") == "2024-08-30" and v.as_of_for("1984-07-30") == "1984-08-29"
    assert all(s["is_conflict"] is False for s in skeleton)


# ---- 單題核對 -------------------------------------------------------------------

def _question(manifest, qid="PTQ-N0030001-1-old", **override):
    skeleton = {s["id"]: s for s in v.skeleton_questions(manifest)}[qid]
    base = {k: skeleton[k] for k in ("id", "as_of", "law_id", "article_no", "expected_valid_from", "other_valid_from", "pair_kind", "is_conflict", "selection_index")}
    base.update(question="勞工每週正常工作時間不得超過多少小時？", gold_exact_span="條文1的內容甲乙丙", contrast_exact_span="條文1的完全不同內容丁戊己")
    base.update(override)
    return base


def _check(data, question):
    files, manifest = data
    versions = {(x["pcode"], x["article_no"], x["valid_from"]): x for x in manifest["versions"]}
    return v.validate_question(question, v.load_texts(files), versions)


def test_valid_question_passes_and_whitespace_is_ignored(data):
    _, manifest = data
    assert _check(data, _question(manifest))["issues"] == []
    spaced = _check(data, _question(manifest, gold_exact_span="條文1 的內容 甲乙丙", contrast_exact_span="條文 1的完全不同 內容丁戊己"))
    assert spaced["issues"] == []


@pytest.mark.parametrize("override,check", [
    ({"gold_exact_span": "並不存在的文字"}, "gold_in_expected_version"),
    ({"gold_exact_span": "條文1的完全不同內容丁戊己"}, "gold_in_expected_version"),  # 取自另一版而非期望版本
    ({"contrast_exact_span": "並不存在的文字"}, "contrast_in_other_version"),
    ({"contrast_exact_span": "條文1的內容甲乙丙"}, "contrast_in_other_version"),  # 取自期望版本而非另一版
    ({"contrast_exact_span": None}, "contrast_in_other_version"),
    ({"as_of": "2020-01-31"}, "as_of_within_expected_validity"),  # 落在另一版有效期間
    ({"as_of": "1999-12-31"}, "as_of_within_expected_validity"),  # 早於期望版本 valid_from
    ({"as_of": "2000/01/31"}, "as_of_format"),
    ({"question": "民國八十年的規定是什麼？"}, "question_has_no_time_terms"),
    ({"question": "修正前的規定是什麼？"}, "question_has_no_time_terms"),
    ({"question": "最新規定是什麼？"}, "question_has_no_time_terms"),
])
def test_invalid_questions_are_flagged(data, override, check):
    _, manifest = data
    assert check in {i["check"] for i in _check(data, _question(manifest, **override))["issues"]}


def test_contrast_equal_to_gold_and_missing_fields_and_unknown_version(data):
    _, manifest = data
    same = _check(data, _question(manifest, gold_exact_span="條文1的內容甲乙丙", contrast_exact_span="條文1的內容甲乙丙"))
    assert "contrast_in_other_version" in {i["check"] for i in same["issues"]}
    broken = _question(manifest)
    del broken["gold_exact_span"]
    assert [i["check"] for i in _check(data, broken)["issues"]] == ["required_fields"]
    assert "versions_exist" in {i["check"] for i in _check(data, _question(manifest, article_no="第 99 條"))["issues"]}


def test_control_question_must_have_null_contrast_and_info_flags(data):
    _, manifest = data
    qid = "PTQ-N0030001-10-ctl-format_only"
    ok = _question(manifest, qid, gold_exact_span="條文10排版內容", contrast_exact_span=None)
    assert _check(data, ok)["issues"] == []
    bad = _question(manifest, qid, gold_exact_span="條文10排版內容", contrast_exact_span="條文10排版內容")
    assert "control_has_no_contrast" in {i["check"] for i in _check(data, bad)["issues"]}
    assert _check(data, ok)["info"]["gold_also_in_other_version"] is True  # 僅排版：兩版去空白後相同


def test_addition_style_question_is_disclosed_not_failed(data):
    files, manifest = data
    # 「共同句」當對照：contrast 也出現在期望版本 → 只揭露（info），不是硬性失敗
    shared = row("N0030001", "1", "共同句。新增條款內容", "2020-01-01")
    base = row("N0030001", "1", "共同句。", "2000-01-01")
    local = builder.build_corpus({"moj_history_20260819T000000Z-history.json": [base, shared]})["manifest"]
    texts = v.load_texts({"moj_history_20260819T000000Z-history.json": [base, shared]})
    versions = {(x["pcode"], x["article_no"], x["valid_from"]): x for x in local["versions"]}
    question = {"id": "PTQ-N0030001-1-new", "question": "新增了什麼條款？".replace("新", "增"), "as_of": "2020-01-31", "law_id": "N0030001", "article_no": "第 1 條",
                "expected_valid_from": "2020-01-01", "other_valid_from": "2000-01-01", "gold_exact_span": "新增條款內容", "contrast_exact_span": "共同句。",
                "pair_kind": "substantive", "is_conflict": False, "selection_index": 0}
    result = v.validate_question(question, texts, versions)
    assert result["issues"] == [] and result["info"]["contrast_also_in_expected_version"] is True


# ---- 整份題庫（選題可重現）------------------------------------------------------------

def _doc(manifest, files):
    texts = v.load_texts(files)
    questions = []
    for s in v.skeleton_questions(manifest):
        key = (s["law_id"], s["article_no"].replace("第 ", "").replace(" 條", ""))
        gold = texts[(*key, s["expected_valid_from"])]
        other = texts[(*key, s["other_valid_from"])]
        questions.append({**{k: s[k] for k in v.REQUIRED_FIELDS if k not in ("question", "gold_exact_span", "contrast_exact_span")},
                          "question": "請問這一條規定了什麼內容？", "gold_exact_span": gold,
                          "contrast_exact_span": other if s["pair_kind"] == "substantive" else None})
    return {"meta": {"criteria": v.EVALUATION_CRITERIA}, "questions": questions}


def test_validate_questions_ok_and_reproducibility_failures(data):
    files, manifest = data
    doc = _doc(manifest, files)
    report = v.validate_questions(doc, manifest, files)
    assert report["ok"], report["issues"][:3]
    assert report["questions"] == 18 and report["by_pair_kind"] == {"substantive": 12, "format_only": 3, "same_hash": 3}
    assert report["selection_indices"]["substantive"] == [0, 4, 8, 9, 10, 11] and report["criteria_sha256"] == CRITERIA_SHA256
    missing = copy.deepcopy(doc)
    missing["questions"].pop()
    assert "selection_reproducible" in {i["check"] for i in v.validate_questions(missing, manifest, files)["issues"]}
    extra = copy.deepcopy(doc)
    extra["questions"].append({**extra["questions"][0], "id": "PTQ-EXTRA"})
    assert "selection_reproducible" in {i["check"] for i in v.validate_questions(extra, manifest, files)["issues"]}
    duplicated = copy.deepcopy(doc)
    duplicated["questions"].append(dict(duplicated["questions"][0]))
    assert "ids_unique" in {i["check"] for i in v.validate_questions(duplicated, manifest, files)["issues"]}
    shifted = copy.deepcopy(doc)
    shifted["questions"][0]["as_of"] = "2001-01-01"
    assert "selection_reproducible" in {i["check"] for i in v.validate_questions(shifted, manifest, files)["issues"]}
    tampered = copy.deepcopy(doc)
    tampered["meta"]["criteria"] = {**v.EVALUATION_CRITERIA, "primary_metrics": {"asof_leak_rate_max": 0.5}}
    assert "criteria_frozen" in {i["check"] for i in v.validate_questions(tampered, manifest, files)["issues"]}


def test_criteria_are_frozen():
    assert v.criteria_sha256() == CRITERIA_SHA256
    c = v.EVALUATION_CRITERIA
    assert c["retrieval"]["top_k"] == 20 and c["retrieval"]["modes"] == ["asof", "naive"] and c["primary_metrics"]["asof_leak_rate_max"] == 0.05
    assert "naive 的 hit 率" in c["primary_metrics"]["asof_hit_rate_min"] and "is_conflict" in c["conflict"]


# ---- 實際題庫檔（repo 內）-------------------------------------------------------------

@pytest.fixture(scope="module")
def doc():
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))


def test_real_question_file_structure(doc):
    questions = doc["questions"]
    assert len(questions) == doc["meta"]["question_count"] == 34
    assert [q["pair_kind"] for q in questions].count("substantive") == 28
    assert [q["pair_kind"] for q in questions].count("format_only") == 3 and [q["pair_kind"] for q in questions].count("same_hash") == 3
    assert sum(q["is_conflict"] for q in questions) == 4 and {q["article_no"] for q in questions if q["is_conflict"]} == {"第 86 條", "第 12 條"}
    assert len({q["id"] for q in questions}) == 34 and all(set(v.REQUIRED_FIELDS) <= set(q) for q in questions)
    assert doc["meta"]["criteria"] == v.EVALUATION_CRITERIA and doc["meta"]["criteria_sha256"] == CRITERIA_SHA256
    for q in questions:
        assert not [t for t in v.FORBIDDEN_TERMS if t in q["question"]], q["id"]
        assert q["gold_exact_span"].strip() and (q["contrast_exact_span"] is None) == (q["pair_kind"] != "substantive")
        assert q["as_of"] == v.as_of_for(q["expected_valid_from"]) and q["law_id"] in {"N0030001", "N0030006"}
        assert q["expected_valid_from"] in q["acceptable_valid_froms"]
    substantive = [q for q in questions if q["pair_kind"] == "substantive"]
    assert sorted({q["selection_index"] for q in substantive}) == [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 41, 42, 43]
    assert all(sum(1 for x in substantive if x["article_no"] == q["article_no"] and x["law_id"] == q["law_id"]) == 2 for q in substantive)
    for article in {(q["law_id"], q["article_no"]) for q in substantive}:
        pair = [q for q in substantive if (q["law_id"], q["article_no"]) == article]
        assert pair[0]["question"] == pair[1]["question"] and {p["expected_role"] for p in pair} == {"old", "new"}
        assert pair[0]["expected_valid_from"] == pair[1]["other_valid_from"] and pair[0]["other_valid_from"] == pair[1]["expected_valid_from"]
        assert pair[0]["gold_exact_span"] == pair[1]["contrast_exact_span"] and pair[0]["contrast_exact_span"] == pair[1]["gold_exact_span"]


@pytest.mark.skipif(not (REAL_CORPUS / "pilot_manifest.json").is_file() or not builder.DEFAULT_SOURCE_DIR.is_dir(), reason="試點語料或 collector 不在此機器")
def test_real_question_file_passes_validator_against_real_data(doc):
    from scripts.analysis.law_version_inventory import load_history_files
    from scripts.kg import pilot_import as pi

    manifest = pi.load_manifest(REAL_CORPUS)
    report = v.validate_questions(doc, manifest, load_history_files(builder.DEFAULT_SOURCE_DIR))
    assert report["ok"], report["issues"][:3]
    assert report["checks_passed"] == {"gold_in_expected_version": 34, "contrast_in_other_version": 34, "as_of_within_expected_validity": 34, "question_has_no_time_terms": 34}
    assert report["time_term_hits"] == [] and report["selection_indices"]["format_only"] == [0, 3, 6]


def test_cli_exit_codes(tmp_path, data, monkeypatch, capsys):
    files, manifest = data
    out = tmp_path / "kg-runtime-pilot" / manifest["pilot_kg_id"]
    builder.write_corpus(builder.build_corpus(files, control_limit=10), out, [Path("/nonexistent-repo-root")])
    source = tmp_path / "collector"
    source.mkdir()
    (source / "moj_history_20260819T000000Z-history.json").write_text(json.dumps(files["moj_history_20260819T000000Z-history.json"], ensure_ascii=False), encoding="utf-8")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_doc(manifest, files), ensure_ascii=False), encoding="utf-8")
    assert v.main(["--questions", str(good), "--corpus-dir", str(out), "--source-dir", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    bad_doc = _doc(manifest, files)
    bad_doc["questions"][0]["gold_exact_span"] = "不存在"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(bad_doc, ensure_ascii=False), encoding="utf-8")
    assert v.main(["--questions", str(bad), "--corpus-dir", str(out), "--source-dir", str(source)]) == 1


def test_validator_is_offline_and_read_only():
    tree = ast.parse(SRC)
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in imported if m.split(".")[0] in {"neo4j", "httpx", "requests", "subprocess", "socket"} or m.startswith(("core", "services.svo"))]
    for needle in ("17990", "bolt://", ".env", "docker", ".write_text(", ".write_bytes(", "open("):
        assert needle not in SRC, needle
    assert date.fromisoformat("2026-01-01") - timedelta(days=1) == date(2025, 12, 31)
