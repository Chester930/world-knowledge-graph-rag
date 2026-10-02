"""報告262 Q2：`scripts/kg/pilot_import.py` 的離線測試（`--plan`、閘門、密碼不外洩、對 core/config 零修改、執行流程的結構守衛）。"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.analysis import pilot_version_corpus_builder as builder
from scripts.kg import pilot_import as pi

REPO = Path(pi._REPO)
SRC = Path(pi.__file__).read_text(encoding="utf-8")
FAKE_REPO = [Path("/nonexistent-repo-root")]


def _row(article, content, valid_from, **kw):
    return {
        "pcode": "N0030006", "law_name": "勞工請假規則", "article_no": article, "content": content,
        "version_date": valid_from, "valid_from": valid_from, "valid_to": None, "is_current": True,
        "valid_from_basis": "official_revision_or_current_date", "version_id": f"v-{article}-{valid_from}",
        "content_hash": hashlib.sha1(content.encode("utf-8")).hexdigest(), "retrieved_at": "2026-08-19T17:00:00+08:00",
        "source_url": "https://example.test", **kw,
    }


@pytest.fixture()
def corpus(tmp_path):
    files = {"moj_history_20260819T000000Z-history.json": [
        _row("1", "甲版本第一條內容", "2020-01-01"), _row("1", "乙版本第一條完全不同", "2024-01-01"),
        _row("10-1", "甲版本第十之一內容", "2020-01-01"), _row("10-1", "乙版本第十之一完全不同", "2024-01-01"),
    ]}
    built = builder.build_corpus(files)
    out = tmp_path / "kg-runtime-pilot" / str(builder.PILOT_KG_ID_DEFAULT)
    builder.write_corpus(built, out, FAKE_REPO)
    return out, built


# ---- 解析與離線讀取 ------------------------------------------------------------

def test_parse_articles_round_trips_builder_output_and_uses_heading_format():
    rendered = builder.render_original_md("N_x@2020-01-01", [("1", "甲內容"), ("10-1", "乙內容"), ("20", "丙內容")])
    body = pi.split_original_md(rendered, "N_x@2020-01-01")
    assert body == "第 1 條\n\n甲內容\n\n第 10-1 條\n\n乙內容\n\n第 20 條\n\n丙內容"
    assert pi.parse_articles(body) == [
        {"ArticleNo": "第 1 條", "ArticleContent": "甲內容"}, {"ArticleNo": "第 10-1 條", "ArticleContent": "乙內容"},
        {"ArticleNo": "第 20 條", "ArticleContent": "丙內容"}]


def test_split_and_parse_reject_malformed_files():
    good = builder.render_original_md("s", [("1", "甲")])
    with pytest.raises(ValueError):
        pi.split_original_md(good, "other-source")
    with pytest.raises(ValueError):
        pi.split_original_md(good.rstrip("\r\n"), "s")  # 結尾缺換行
    with pytest.raises(ValueError):
        pi.parse_articles("沒有條號的內容")


def test_chunk_eligibility_matches_article_aware_rules():
    assert pi.chunk_eligible({"ArticleNo": "第 1 條", "ArticleContent": "內容"})
    for bad in ({"ArticleNo": "", "ArticleContent": "x"}, {"ArticleNo": "第 1 條", "ArticleContent": " "},
                {"ArticleNo": "第 1 條", "ArticleContent": "（刪除）"}, {"ArticleNo": "第 1 條", "ArticleContent": "(刪除)"},
                {"ArticleNo": "第 1 條", "ArticleContent": "刪除"}):
        assert not pi.chunk_eligible(bad)


def test_deleted_markers_do_not_drift_from_production_chunker():
    from services import svo_chunking  # 僅測試匯入（會載入設定，不連線）

    assert pi.DELETED_ARTICLE_MARKERS == svo_chunking._DELETED_ARTICLE_MARKERS


def test_chunk_and_stage_would_reproduce_q1_original_md_bytes(tmp_path, corpus):
    """鎖定偵察結論：`write_original_text(body, source, dir)` 寫出的 original.md 與 Q1 輸出逐位元組相同（Windows 文字模式換行）。"""
    from parser.chunk_writer import write_original_text  # 僅測試匯入（會載入設定，不連線）

    out, built = corpus
    manifest = pi.load_manifest(out)
    for folder in pi.load_corpus(out, manifest):
        written = write_original_text(folder["body"], folder["source"], tmp_path / "stage")
        q1 = (out / folder["source"] / "original.md").read_bytes()
        got = written.read_bytes()
        if os.linesep == "\r\n":
            assert got == q1
        else:  # 非 Windows：只比較換行正規化後的內容
            assert got.replace(b"\r\n", b"\n") == q1.replace(b"\r\n", b"\n")


# ---- --plan -----------------------------------------------------------------------

def test_plan_counts_and_steps(corpus):
    out, built = corpus
    plan = pi.build_plan(out)
    assert plan["mode"] == "plan" and plan["connects"] is False and plan["pilot_kg_id"] == str(builder.PILOT_KG_ID_DEFAULT)
    assert plan["totals"] == {"documents": 2, "law_article_nodes": 4, "expected_svo_chunks": 4}
    assert [p["articles"] for p in plan["per_folder"]] == [2, 2]
    assert plan["kg_folder"] == str(out.resolve()) and plan["required_env"] == list(pi.REQUIRED_ENV)
    assert [s["n"] for s in plan["steps"]] == [1, 2, 3, 4, 5] and plan["steps"][3]["count"] == 2 and plan["steps"][4]["count"] == 4
    assert "--worker" in plan["worker_command"] and plan["target_port_default"] == 28687
    json.dumps(plan, ensure_ascii=False)
    assert pi.build_plan(out) == plan  # 決定性


def test_plan_detects_tampering_and_manifest_mismatch(corpus):
    out, built = corpus
    first = next(p for p in out.iterdir() if p.is_dir())
    original = first / "original.md"
    data = original.read_bytes()
    original.write_bytes(data + b"x")
    with pytest.raises(ValueError, match="雜湊"):
        pi.build_plan(out)
    original.write_bytes(data)
    pi.build_plan(out)
    manifest_path = out / "pilot_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["pilot_kg_id"] = str(uuid4())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="pilot_kg_id"):
        pi.build_plan(out)


def test_plan_main_prints_json_and_does_not_load_core_config(corpus):
    out, _ = corpus
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "from scripts.kg import pilot_import as pi\n"
        f"rc = pi.main(['--plan', '--corpus-dir', {str(out)!r}])\n"
        "print('RC', rc, 'core.config' in sys.modules, 'neo4j' in sys.modules, 'services.svo_service' in sys.modules)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", cwd=str(out.parent))
    assert result.returncode == 0, result.stderr[-500:]
    assert result.stdout.strip().splitlines()[-1] == "RC 0 False False False"
    assert json.loads(result.stdout[: result.stdout.rindex("RC 0")])["connects"] is False


# ---- 閘門 ------------------------------------------------------------------------

@pytest.mark.parametrize("uri", ["bolt://localhost:28687", "bolt://127.0.0.1:28687"])
def test_gate_accepts_pilot_endpoint(uri):
    assert pi.validate_target_uri(uri) == f"{uri.split('//')[1]}"


@pytest.mark.parametrize("uri", [
    "bolt://localhost:17990", "bolt://localhost:27687", "bolt://localhost:7687", "bolt://localhost:28000",
    "bolt://kg2-neo4j:28687", "http://localhost:28687", "bolt://example.com:28687", "bolt://localhost:notaport",
    "bolt://localhost", "neo4j://localhost:28687",
])
def test_gate_rejects_wrong_or_protected_targets(uri):
    with pytest.raises(pi.GateViolation):
        pi.validate_target_uri(uri)


def test_allow_port_must_not_be_a_protected_port_and_must_match():
    assert pi.validate_target_uri("bolt://localhost:28999", allow_port=28999) == "localhost:28999"
    for port in pi.FORBIDDEN_PORTS:
        with pytest.raises(pi.GateViolation):
            pi.validate_target_uri(f"bolt://localhost:{port}", allow_port=port)
    with pytest.raises(pi.GateViolation):
        pi.validate_target_uri("bolt://localhost:28687", allow_port=28999)  # 指定了別的埠就不再接受預設埠


def test_credentials_in_uri_are_masked():
    assert pi.validate_target_uri("bolt://user:SECRETPW@localhost:28687") == "localhost:28687"
    with pytest.raises(pi.GateViolation) as exc:
        pi.validate_target_uri("bolt://user:SECRETPW@localhost:17990")
    assert "SECRETPW" not in str(exc.value)


def test_kg_id_gate():
    manifest_id = str(builder.PILOT_KG_ID_DEFAULT)
    assert str(pi.validate_kg_id(manifest_id, manifest_id)) == manifest_id
    with pytest.raises(pi.GateViolation):
        pi.validate_kg_id(uuid4(), manifest_id)
    with pytest.raises(pi.GateViolation):
        pi.validate_kg_id(pi.KG4_ID, str(pi.KG4_ID))  # 即使 manifest 被改成 KG#4 也拒絕


def _env(corpus_dir, **override):
    env = {"NEO4J_URI": "bolt://localhost:28687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "S3cr3t-PW-xyz",
           "WORKSPACE_DIR": str(corpus_dir.parent), "EMBEDDING_PROVIDER": "ollama"}
    env.update(override)
    return {k: v for k, v in env.items() if v is not None}


def test_environment_gate(corpus):
    out, _ = corpus
    manifest = pi.load_manifest(out)
    facts = pi.validate_environment(_env(out), out, manifest)
    assert facts == {"target": "localhost:28687", "kg_id": str(builder.PILOT_KG_ID_DEFAULT), "kg_folder": str(out.resolve()),
                     "workspace_dir": str(out.parent)}
    assert "S3cr3t" not in json.dumps(facts)
    for name in pi.REQUIRED_ENV:
        with pytest.raises(pi.GateViolation, match="缺少"):
            pi.validate_environment(_env(out, **{name: None}), out, manifest)
    for bad in ({"NEO4J_URI": "bolt://localhost:17990"}, {"EMBEDDING_PROVIDER": "local"},
                {"WORKSPACE_DIR": str(out.parent.parent)}, {"WORKSPACE_DIR": str(out)}):
        with pytest.raises(pi.GateViolation):
            pi.validate_environment(_env(out, **bad), out, manifest)
    with pytest.raises(pi.GateViolation):
        pi.validate_environment(_env(out), out, manifest, kg_id=uuid4())


def test_environment_gate_rejects_corpus_outside_pilot_root(tmp_path, corpus):
    out, _ = corpus
    moved = tmp_path / "elsewhere" / out.name
    moved.parent.mkdir()
    out.rename(moved)
    with pytest.raises(pi.GateViolation):
        pi.validate_environment(_env(moved), moved, pi.load_manifest(moved))


def test_failed_gate_messages_and_main_never_echo_password(corpus, monkeypatch, capsys):
    out, _ = corpus
    for key, value in _env(out, NEO4J_URI="bolt://localhost:17990").items():
        monkeypatch.setenv(key, value)
    rc = pi.main(["--execute", "--corpus-dir", str(out)])
    captured = capsys.readouterr()
    assert rc == 2 and "S3cr3t-PW-xyz" not in captured.out + captured.err and "停止（閘門）" in captured.err


# ---- 結構守衛 ---------------------------------------------------------------------

def _function(name):
    return next(n for n in ast.walk(ast.parse(SRC)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_top_level_imports_are_light_and_core_is_imported_lazily_after_the_gate():
    top = [n for n in ast.parse(SRC).body if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = [a.name for n in top if isinstance(n, ast.Import) for a in n.names] + [n.module or "" for n in top if isinstance(n, ast.ImportFrom)]
    assert not [m for m in modules if m.split(".")[0] in {"core", "neo4j", "httpx", "models", "repositories", "parser"} or m.startswith("services")]
    execute = ast.get_source_segment(SRC, _function("execute"))
    assert execute.index("_validated_env(") < execute.index("from core.config import")
    worker = ast.get_source_segment(SRC, _function("run_worker"))
    assert worker.index("_validated_env(") < worker.index("from core.config import")


def test_execute_pipeline_order_and_keyword_arguments_match_recon():
    calls = []
    for node in ast.walk(_function("execute")):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            calls.append((node.lineno, name, {k.arg for k in node.keywords}))
    order = [name for _, name, _ in sorted(calls)]
    expected = ["merge_document", "merge_law_articles", "chunk_and_stage", "assign_document_to_kg", "trigger_extraction"]
    positions = [order.index(name) for name in expected]
    assert positions == sorted(positions)
    trigger = next(kw for _, name, kw in calls if name == "trigger_extraction")
    assert {"articles", "kg_folder"} <= trigger  # 虛擬歸屬下必須指定 kg_folder，SVO 輸出才會落在 worker 讀取的 KG 資料夾
    index_names = ["create_entity_index", "create_chunk_vector_index", "create_related_to_vector_index",
                   "create_entity_name_vector_index", "create_entity_name_fulltext_index"]
    assert [order.index(n) for n in index_names] == sorted(order.index(n) for n in index_names)
    assert order.index("create_entity_index") < order.index("ensure_pilot_kg") < order.index("merge_document")


def _code_strings():
    """程式碼中的字串常數（排除模組／函式 docstring）。"""
    tree = ast.parse(SRC)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docstrings.add(id(body[0].value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def test_no_core_config_modification_env_mutation_or_secret_printing():
    tree = ast.parse(SRC)
    # 17990 只作為保護埠整數常數出現在 FORBIDDEN_PORTS，不在任何字串（連線字串）裡
    ints = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == 17990]
    assert len(ints) == 1
    assert all(not ("17990" in text and "://" in text) for text in _code_strings())  # 說明文字可提到埠號，但不得有含 17990 的連線字串
    assert ".env" not in _code_strings() and "env_file" not in SRC  # 訊息文字可提到 .env，但不得把它當檔名使用
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assert not (isinstance(target, ast.Subscript) and ast.get_source_segment(SRC, target).startswith("os.environ"))
                assert not (isinstance(target, ast.Attribute) and ast.get_source_segment(SRC, target).startswith("settings."))
    assert "putenv" not in SRC and "environ.setdefault" not in SRC and "load_dotenv" not in SRC
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            segment = ast.get_source_segment(SRC, node)
            assert "PASSWORD" not in segment and "environ" not in segment


def test_pilot_import_never_touches_protected_resources_or_config_files():
    strings = " ".join(_code_strings())
    for needle in ("docker", "kg2_neo4j_data", "core/config.py"):
        assert needle not in strings, needle
    assert ".env" not in _code_strings() and not any(text.endswith(".env") for text in _code_strings())
    imported = [n.module or "" for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.ImportFrom)]
    imported += [a.name for n in ast.walk(ast.parse(SRC)) if isinstance(n, ast.Import) for a in n.names]
    assert "subprocess" not in imported and "dotenv" not in imported
    assert ".write_text(" not in SRC and ".write_bytes(" not in SRC  # 本腳本自己不寫任何檔（寫檔都在既有 production 函式內）
    config = (REPO / "core" / "config.py").read_text(encoding="utf-8")
    assert "pilot" not in config.lower()  # 沒有為試點改動 core/config.py


def test_ensure_pilot_kg_creates_with_given_id_and_verifies_folder(tmp_path):
    class Driver:
        def __init__(self, folder):
            self.folder, self.calls = folder, []

        async def execute_query(self, statement, **params):
            self.calls.append((statement, params))
            return SimpleNamespace(records=[{"folder_path": self.folder}])

    kg_id, folder = builder.PILOT_KG_ID_DEFAULT, tmp_path / "kg-runtime-pilot" / "kg"
    driver = Driver(str(folder))
    asyncio.run(pi.ensure_pilot_kg(driver, kg_id, folder))
    statement, params = driver.calls[0]
    assert "MERGE (k:KnowledgeGraph {id: $id})" in statement and params["id"] == str(kg_id) and params["folder_path"] == str(folder)
    assert "DELETE" not in statement and params["pronoun_exclude"] == ["其", "該"] and folder.is_dir()
    with pytest.raises(RuntimeError):
        asyncio.run(pi.ensure_pilot_kg(Driver("D:/somewhere/else"), kg_id, folder))
