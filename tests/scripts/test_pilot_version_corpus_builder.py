"""報告262 Q1：試點語料建構器的離線測試（小型假歷史檔；不依賴 collector／kg-runtime 實體路徑）。"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import pytest

from scripts.analysis import pilot_version_corpus_builder as b

SRC = Path(b.__file__).read_text(encoding="utf-8")
REAL_KG4_FILE = Path(r"D:\Users\666\Desktop\kg-runtime\236903cf-055a-40a8-8923-b9d06601f3b7\N0030006_勞工請假規則\original.md")
FAKE_REPO = [Path("/nonexistent-repo-root")]  # 測試以固定的「假 repo 根」避免 pytest basetemp 落在 repo 內時守衛誤擋


def row(article, content, valid_from, version_id=None, *, pcode="N0030006", law_name="勞工請假規則", content_hash=None,
        valid_to=None, version_date=None):
    return {
        "pcode": pcode, "law_name": law_name, "article_no": article, "content": content,
        "version_date": version_date or valid_from, "valid_from": valid_from, "valid_to": valid_to,
        "is_current": valid_to is None, "valid_from_basis": "official_revision_or_current_date",
        "version_id": version_id or f"v-{pcode}-{article}-{valid_from}",
        "content_hash": content_hash or hashlib.sha1(content.encode("utf-8")).hexdigest(),
        "retrieved_at": "2026-08-19T17:00:00+08:00", "source_url": "https://example.test",
    }


def one_file(*rows):
    return {"moj_history_20260819T000000Z-history.json": list(rows)}


# ---- 正規化、雜訊、渲染 -------------------------------------------------------

def test_article_normalization_and_sorting_and_law_name():
    assert b.normalize_article_no(" 10 - 1 ") == "10-1"
    assert b.normalize_article_no("１０－１") == "10-1"
    assert sorted(["10", "2", "10-1", "1"], key=b.article_sort_key) == ["1", "2", "10", "10-1"]
    assert b.clean_law_name("勞動基準法 EN") == "勞動基準法" and b.clean_law_name("勞工請假規則") == "勞工請假規則"


def test_truncate_navigation_noise_keeps_text_unconverted():
    text, cut = b.truncate_navigation_noise("條文內容，保持全形：正文。 ::: 最新訊息 導覽雜訊")
    assert cut and text == "條文內容，保持全形：正文。 "
    full, cut_full = b.truncate_navigation_noise("正文。：：： 最新訊息 雜訊")  # 全形冒號也以 NFKC 判為標記
    assert cut_full and full == "正文。"
    assert b.truncate_navigation_noise("沒有雜訊的條文，；：") == ("沒有雜訊的條文，；：", False)


KG4_HEAD = (
    '---\r\nsource: "N0030006_勞工請假規則"\r\n---\r\n\r\n第 1 條\r\n\r\n本規則依勞動基準法（以下簡稱本法）第四十三條規定訂定之。'
    '\r\n\r\n第 2 條\r\n\r\n勞工結婚者給予婚假八日，工資照給。\r\n'
)


def test_render_original_md_matches_kg4_structure_byte_for_byte():
    rendered = b.render_original_md("N0030006_勞工請假規則", [
        ("1", "本規則依勞動基準法（以下簡稱本法）第四十三條規定訂定之。"), ("2", "勞工結婚者給予婚假八日，工資照給。")])
    assert rendered == KG4_HEAD
    data = rendered.encode("utf-8")
    assert data.startswith(b"---\r\n") and b"\r\r\n" not in data and data.endswith("。\r\n".encode("utf-8"))
    assert not data.endswith(b"\r\n\r\n")


@pytest.mark.skipif(not REAL_KG4_FILE.is_file(), reason="KG#4 kg-runtime 不在此機器")
def test_render_matches_real_kg4_file_prefix():
    real = REAL_KG4_FILE.read_bytes().decode("utf-8")
    assert real.startswith(KG4_HEAD.rsplit("第 2 條", 1)[0])  # 標頭＋第 1 條逐位元組相同
    assert real.startswith(KG4_HEAD[:-2])  # 到第 2 條條文結尾為止逐位元組相同


def test_render_normalizes_embedded_newlines_to_crlf_only():
    assert b.render_original_md("s", [("1", "甲\n乙\r\n丙")]) == '---\r\nsource: "s"\r\n---\r\n\r\n第 1 條\r\n\r\n甲\r\n乙\r\n丙\r\n'


# ---- 身分、去重、衝突 -----------------------------------------------------------

def test_identity_dedup_latest_snapshot_authoritative_and_conflicts():
    files = {
        "moj_history_a.json": [row("1", "舊", "2020-01-01", "v-old", content_hash="h1"), row("2", "二", "2020-01-01", "v2")],
        "moj_history_b.json": [row("1", "新", "2020-01-01", "v-new", content_hash="h2"), row("2", "二", "2020-01-01", "v2")],
    }
    records, conflicts = b.authoritative_records(files)
    assert [(r["article_no_normalized"], r["_snapshot_file"], r["content"]) for r in records] == [
        ("1", "moj_history_b.json", "新"), ("2", "moj_history_b.json", "二")]
    assert len(conflicts) == 1 and conflicts[0]["article_no"] == "1" and conflicts[0]["authority_version_id"] == "v-new"
    assert [o["file"] for o in conflicts[0]["occurrences"]] == ["moj_history_a.json", "moj_history_b.json"]


def test_article_no_normalized_in_identity():
    files = {"a.json": [row(" 10-1 ", "甲", "2020-01-01")], "b.json": [row("１０－１", "甲", "2020-01-01")]}
    records, conflicts = b.authoritative_records(files)
    assert len(records) == 1 and records[0]["article_no_normalized"] == "10-1" and records[0]["_snapshot_file"] == "b.json"
    assert len(conflicts) == 1  # version_id 不同（fixture 以條號字串組 id）→ 衝突


def test_known_inconsistent_articles_are_conflicts_excluded_from_controls_but_kept_in_substantive():
    files = one_file(
        row("86", "舊文", "2020-01-01", pcode="N0030001", law_name="勞動基準法"),
        row("86", "全新的實質不同文字", "2024-01-01", pcode="N0030001", law_name="勞動基準法"),
        row("87", "相同", "2020-01-01", pcode="N0030001", law_name="勞動基準法", content_hash="same"),
        row("87", "相同", "2024-01-01", pcode="N0030001", law_name="勞動基準法", content_hash="same"),
        row("12", "排版 一", "2020-01-01"), row("12", "排版一", "2024-01-01"),
        row("13", "排版 一", "2020-01-01"), row("13", "排版一", "2024-01-01"))
    manifest = b.build_corpus(files)["manifest"]
    assert [list(x) for x in b.KNOWN_SNAPSHOT_INCONSISTENT] == manifest["known_snapshot_inconsistent_articles"]
    by_key = {(v["pcode"], v["article_no"], v["valid_from"]): v for v in manifest["versions"]}
    # 勞基法第 86 條：實質修改→仍入選（是衝突版本）；請假規則第 12 條：僅排版→衝突條文不入對照
    assert by_key[("N0030001", "86", "2020-01-01")]["is_conflict"] and by_key[("N0030001", "86", "2020-01-01")]["roles"] == ["substantive_old"]
    assert ("N0030006", "12", "2020-01-01") not in by_key
    assert ("N0030006", "13", "2020-01-01") in by_key and not by_key[("N0030006", "13", "2020-01-01")]["is_conflict"]
    assert by_key[("N0030001", "87", "2020-01-01")]["roles"] == ["control_same_hash"]


# ---- 選材、角色、時間欄位 ---------------------------------------------------------

def _chain_files():
    return one_file(
        row("1", "第一版內容", "2020-01-01"), row("1", "第二版完全不同的內容", "2022-02-02"), row("1", "第三版又不同的內容", "2024-03-03"),
        row("2", "不變條文", "2020-01-01", content_hash="x"), row("2", "不變條文", "2024-03-03", content_hash="x"))


def test_roles_middle_version_has_both_and_valid_to_is_derived():
    manifest = b.build_corpus(_chain_files())["manifest"]
    by_vf = {(v["article_no"], v["valid_from"]): v for v in manifest["versions"]}
    middle = by_vf[("1", "2022-02-02")]
    assert middle["roles"] == ["substantive_old", "substantive_new"]
    assert len(middle["pair_ids"]) == 2 and middle["diff_from_previous"] == "substantive" and middle["diff_to_next"] == "substantive"
    assert by_vf[("1", "2020-01-01")]["valid_to_derived"] == "2022-02-02" and by_vf[("1", "2020-01-01")]["valid_to_original"] is None
    assert by_vf[("1", "2024-03-03")]["valid_to_derived"] is None
    assert by_vf[("2", "2020-01-01")]["roles"] == ["control_same_hash"] and by_vf[("2", "2020-01-01")]["diff_to_next"] == "same_hash"
    assert manifest["summary"]["valid_to_contiguous_pairs"] == 0


def test_original_valid_to_is_preserved_and_contiguity_counted():
    files = one_file(row("1", "甲版本內容", "2020-01-01", valid_to="2022-02-02"), row("1", "乙版本不同內容", "2022-02-02"))
    manifest = b.build_corpus(files)["manifest"]
    first = manifest["versions"][0]
    assert first["valid_to_original"] == "2022-02-02" and first["valid_to_derived"] == "2022-02-02"
    assert manifest["summary"]["valid_to_contiguous_pairs"] == 1


def test_control_selection_is_deterministic_limited_and_order_independent():
    rows = []
    for n in range(1, 26):  # 25 條 format_only
        rows += [row(str(n), f"條文 {n} 甲", "2020-01-01"), row(str(n), f"條文{n}甲", "2024-01-01")]
    forward = b.build_corpus(one_file(*rows))
    backward = b.build_corpus(one_file(*reversed(rows)))
    assert forward["manifest"]["summary"]["selected_pairs"] == {"substantive": 0, "control_format_only": 10, "control_same_hash": 0}
    picked = [v["article_no"] for v in forward["manifest"]["versions"] if v["valid_from"] == "2020-01-01"]
    assert picked == [str(n) for n in range(1, 11)]  # 依條號（自然排序）取前 10，非隨機
    assert json.dumps(forward["manifest"], ensure_ascii=False) == json.dumps(backward["manifest"], ensure_ascii=False)
    assert {s: f["original_md"] for s, f in forward["folders"].items()} == {s: f["original_md"] for s, f in backward["folders"].items()}
    assert b.build_corpus(one_file(*rows), control_limit=3)["manifest"]["summary"]["selected_pairs"]["control_format_only"] == 3


def test_noise_truncation_recorded_and_removed_from_original():
    files = one_file(row("1", "正文甲乙丙。 ::: 最新訊息 這是導覽" + "雜訊" * 5, "2020-01-01"), row("1", "正文完全不同。", "2024-01-01"))
    corpus = b.build_corpus(files)
    v = next(x for x in corpus["manifest"]["versions"] if x["valid_from"] == "2020-01-01")
    assert v["noise_truncated"] and v["original_length"] > v["truncated_length"] == len("正文甲乙丙。")
    text = next(f["original_md"] for s, f in corpus["folders"].items() if s.endswith("@2020-01-01"))
    assert "最新訊息" not in text and "正文甲乙丙。" in text
    summary = corpus["manifest"]["summary"]
    assert summary["noise_truncated_versions"] == 1 and summary["noise_truncated_total_chars_removed"] == v["original_length"] - v["truncated_length"]
    assert "不宣稱" in corpus["manifest"]["noise_rule"]


def test_folder_grouping_naming_and_source_doc_id():
    from core.constants import DOCUMENT_ID_NAMESPACE

    files = one_file(row("1", "甲內容", "2020-01-01", law_name="勞工請假規則 EN"), row("1", "乙內容不同", "2024-01-01", law_name="勞工請假規則"),
                     row("2", "丙內容", "2020-01-01"), row("2", "丁內容不同", "2024-01-01"))
    corpus = b.build_corpus(files)
    assert sorted(corpus["folders"]) == ["N0030006_勞工請假規則@2020-01-01", "N0030006_勞工請假規則@2024-01-01"]
    folder = corpus["folders"]["N0030006_勞工請假規則@2020-01-01"]
    assert [a for a, _ in folder["articles"]] == ["1", "2"]
    assert folder["original_md"].startswith('---\r\nsource: "N0030006_勞工請假規則@2020-01-01"\r\n---\r\n\r\n第 1 條\r\n\r\n甲內容\r\n\r\n第 2 條\r\n\r\n丙內容\r\n')
    for v in corpus["manifest"]["versions"]:
        assert v["source_doc_id"] == str(uuid5(DOCUMENT_ID_NAMESPACE, v["folder"]))
    entry = corpus["manifest"]["folders"][0]
    assert entry["original_md_sha256"] == hashlib.sha256(corpus["folders"][entry["source"]]["original_md"].encode("utf-8")).hexdigest()


def test_manifest_fields_complete():
    files = one_file(row("1", "甲內容", "2020-01-01"), row("1", "乙內容不同", "2024-01-01"))
    manifest = b.build_corpus(files, source_manifest=[{"file": "f.json", "sha256": "0" * 64, "rows": 2}])["manifest"]
    assert set(manifest) >= {"schema", "pilot_kg_id", "source_files", "identity_rule", "selection_rule", "noise_rule", "summary", "conflicts",
                             "known_snapshot_inconsistent_articles", "folders", "versions"}
    assert manifest["source_files"][0]["file"] == "f.json"
    required = {"pcode", "law_name", "article_no", "law_article_no", "valid_from", "valid_to_original", "valid_to_derived", "version_id", "content_hash",
                "snapshot_file", "roles", "pair_ids", "diff_from_previous", "diff_to_next", "folder", "source_doc_id", "is_conflict",
                "noise_truncated", "original_length", "truncated_length"}
    assert all(set(v) == required for v in manifest["versions"])
    assert {role for v in manifest["versions"] for role in v["roles"]} <= set(b.ROLES)
    # Q4 對照：LawArticle 識別＝source_doc_id＋law_article_no（`第 N 條`，與既有 LawArticle.article_no 同格式）
    assert all(v["law_article_no"] == f"第 {v['article_no']} 條" for v in manifest["versions"])
    assert set(manifest["summary"]["role_counts"]) == set(b.ROLES)


def test_pilot_kg_id_is_deterministic_and_overridable():
    assert b.PILOT_KG_ID_DEFAULT == uuid5(NAMESPACE_URL, "world-knowledge-graph-rag/pilot/law-version/v1")
    files = one_file(row("1", "甲內容", "2020-01-01"), row("1", "乙內容不同", "2024-01-01"))
    assert b.build_corpus(files)["manifest"]["pilot_kg_id"] == str(b.PILOT_KG_ID_DEFAULT)
    other = uuid4()
    assert b.build_corpus(files, other)["manifest"]["pilot_kg_id"] == str(other)


# ---- 輸出路徑守衛與寫檔 ------------------------------------------------------------

def test_output_dir_guard(tmp_path):
    ok = tmp_path / "kg-runtime-pilot" / str(b.PILOT_KG_ID_DEFAULT)
    assert b.validate_output_dir(ok, FAKE_REPO) == ok.resolve()
    with pytest.raises(b.OutputPathError):
        b.validate_output_dir(tmp_path / "somewhere" / "x", FAKE_REPO)
    with pytest.raises(b.OutputPathError):
        b.validate_output_dir(tmp_path / "kg-runtime-pilot", FAKE_REPO)  # kg-runtime-pilot 必須是「上層」目錄，不能是輸出目錄本身
    inside = tmp_path / "repo" / "kg-runtime-pilot" / "k"
    with pytest.raises(b.OutputPathError):
        b.validate_output_dir(inside, [tmp_path / "repo"])  # 即使名稱符合，在 repo 內仍拒絕
    repo_inside = Path(b._REPO) / "kg-runtime-pilot" / "k"
    with pytest.raises(b.OutputPathError):
        b.validate_output_dir(repo_inside)  # 預設守衛：本 repo 內拒絕
    for root in b.repo_roots():
        assert root.is_absolute()


def test_write_corpus_writes_bytes_idempotently_and_refuses_stale(tmp_path):
    corpus = b.build_corpus(one_file(row("1", "甲內容", "2020-01-01"), row("1", "乙內容不同", "2024-01-01")))
    out = tmp_path / "kg-runtime-pilot" / "kg"
    target = b.write_corpus(corpus, out, FAKE_REPO)
    md = target / "N0030006_勞工請假規則@2020-01-01" / "original.md"
    assert md.read_bytes() == corpus["folders"]["N0030006_勞工請假規則@2020-01-01"]["original_md"].encode("utf-8")
    assert b"\r\r\n" not in md.read_bytes() and md.read_bytes().startswith(b"---\r\n")
    manifest_bytes = (target / "pilot_manifest.json").read_bytes()
    assert json.loads(manifest_bytes.decode("utf-8")) == corpus["manifest"] and b"\r\n" not in manifest_bytes
    b.write_corpus(corpus, out, FAKE_REPO)  # 冪等
    assert (target / "pilot_manifest.json").read_bytes() == manifest_bytes
    (target / "stale-folder").mkdir()
    with pytest.raises(b.OutputPathError):
        b.write_corpus(corpus, out, FAKE_REPO)


def test_main_dry_run_writes_nothing_and_full_run_never_modifies_source(tmp_path, monkeypatch, capsys):
    src = tmp_path / "collector"
    src.mkdir()
    payload = [row("1", "甲內容", "2020-01-01"), row("1", "乙內容不同", "2024-01-01")]
    history = src / "moj_history_20260819T000000Z-history.json"
    history.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    before = history.read_bytes()
    monkeypatch.setattr(b, "repo_roots", lambda: FAKE_REPO)
    out_root = tmp_path / "kg-runtime-pilot"
    assert b.main(["--source-dir", str(src), "--out-root", str(out_root), "--dry-run"]) == 0
    assert not out_root.exists() and json.loads(capsys.readouterr().out)["written"] is False
    assert b.main(["--source-dir", str(src), "--out-root", str(out_root)]) == 0
    assert (out_root / str(b.PILOT_KG_ID_DEFAULT) / "pilot_manifest.json").is_file()
    assert history.read_bytes() == before and sorted(p.name for p in src.iterdir()) == [history.name]
    manifest = json.loads((out_root / str(b.PILOT_KG_ID_DEFAULT) / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_files"][0]["sha256"] == hashlib.sha256(before).hexdigest()


# ---- 腳本文字守衛 -----------------------------------------------------------------

def test_script_is_offline_and_never_writes_to_collector():
    imported = []
    for node in ast.walk(ast.parse(SRC)):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    banned = ("neo4j", "subprocess", "socket", "requests", "httpx", "urllib", "ollama", "dotenv", "core.config", "services.svo_service")
    assert not [m for m in imported if any(m == x or m.startswith(x + ".") for x in banned)], imported
    for needle in ("17990", "bolt://", ".env", "docker", "os.environ"):
        assert needle not in SRC, needle
    # 唯一寫檔點在 write_corpus 內，且目標一律經 validate_output_dir
    tree = ast.parse(SRC)
    writers = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and ("write_bytes" in ast.get_source_segment(SRC, n) or "write_text" in ast.get_source_segment(SRC, n) or ".mkdir(" in ast.get_source_segment(SRC, n))]
    assert writers == ["write_corpus"]
    assert "validate_output_dir(out_dir, forbidden_roots)" in SRC
