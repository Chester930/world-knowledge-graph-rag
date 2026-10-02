"""Q2：L3′ 試點語料匯入（報告262 §5）——把 Q1 的試點語料資料夾匯入**指定的拋棄式／試點 Neo4j** 並入抽取佇列。

三種模式（皆由規劃對話執行；實作者只寫、不執行 `--execute`／`--worker`）：

- ``--plan``：**完全離線**。只讀 Q1 輸出、驗證雜湊、列出將執行的步驟與數量；不連線、不匯入 `core`／`services`（故不讀 `.env`）。
- ``--execute``：連線匯入。目標由**行程環境變數**指定（`NEO4J_URI`／`NEO4J_USER`／`NEO4J_PASSWORD`／`WORKSPACE_DIR`／
  `EMBEDDING_PROVIDER`；`core/config.py` 的 pydantic-settings 環境變數優先於 `.env`，本腳本**不改** `core/config.py`）。連線前先過閘門：
  埠必須是 28687（或 `--allow-port` 明確指定且不是 17990／27687／7687）、拒絕任何含 `kg2-neo4j` 的名稱、`--kg-id` 必須等於
  manifest 的 `pilot_kg_id`、`WORKSPACE_DIR` 必須就是語料根目錄（使 KG 資料夾＝Q1 輸出資料夾）。密碼只從環境變數讀入，絕不印出。
- ``--worker``：同樣的閘門後啟動既有 `run_extraction_worker`（消費試點工作區的 `task_queue.db`）。

步驟與重用的既有程式見報告263 §偵察。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import UUID

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.analysis.pilot_version_corpus_builder import (  # noqa: E402  (只含常數／純函式；不匯入 core／services.svo_*)
    DEFAULT_OUT_ROOT,
    OUT_ROOT_DIRNAME,
    PILOT_KG_ID_DEFAULT,
)

MANIFEST_SCHEMA = "pilot_manifest/v1"
DEFAULT_PILOT_PORT = 28687
FORBIDDEN_PORTS = (17990, 27687, 7687)  # KG#4、P3 拋棄式驗證容器、Neo4j 預設埠
KG4_ID = UUID("236903cf-055a-40a8-8923-b9d06601f3b7")
ALLOWED_HOSTS = ("localhost", "127.0.0.1")
REQUIRED_ENV = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "WORKSPACE_DIR", "EMBEDDING_PROVIDER")
PILOT_KG_NAME = "L3′ 條文版本試點 KG（勞基法／請假規則歷史版本）"
PILOT_KG_DESCRIPTION = "報告262 L3′ 試點：collector 歷史檔的條文版本（實質修改對與對照），合成試點，不是正式資料。"
PILOT_PRONOUN_EXCLUDE = ["其", "該"]  # 與既有匯入腳本意圖一致（ArticleAware 路徑本身不做代名詞消解）
# 與 `services.svo_chunking._DELETED_ARTICLE_MARKERS` 相同（本腳本離線 `--plan` 不能匯入該模組：它會連帶載入 core.config／.env；
# 兩者一致由 tests 的漂移測試守住）。
DELETED_ARTICLE_MARKERS = frozenset({"（刪除）", "(刪除)", "刪除"})
_HEADING_SPLIT_RE = re.compile(r"(?:^|\n\n)第 ([0-9]+(?:-[0-9]+)?) 條\n\n")


class GateViolation(RuntimeError):
    """目標 URI／kg_id／環境不符合試點閘門。"""


# ── 讀取 Q1 輸出（離線）──────────────────────────────────────────────────────
def default_corpus_dir() -> Path:
    return DEFAULT_OUT_ROOT / str(PILOT_KG_ID_DEFAULT)


def load_manifest(corpus_dir: Path) -> dict[str, Any]:
    path = corpus_dir / "pilot_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"找不到 pilot_manifest.json：{path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"manifest schema 不符：{manifest.get('schema')!r}（預期 {MANIFEST_SCHEMA}）")
    if manifest.get("pilot_kg_id") != corpus_dir.name:
        raise ValueError(f"語料資料夾名稱 {corpus_dir.name!r} 必須等於 manifest 的 pilot_kg_id {manifest.get('pilot_kg_id')!r}")
    return manifest


def split_original_md(text: str, source: str) -> str:
    """去掉前置 frontmatter，回傳條文主體（換行正規化為 LF，已去掉結尾單一換行）。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    header = f'---\nsource: "{source}"\n---\n\n'
    if not normalized.startswith(header):
        raise ValueError(f"original.md 的 frontmatter 與預期 source 不符：{source}")
    body = normalized[len(header):]
    if not body.endswith("\n"):
        raise ValueError(f"original.md 結尾必須是單一換行：{source}")
    return body[:-1]


def parse_articles(body: str) -> list[dict[str, str]]:
    """條文主體 → `articles` payload（`ArticleNo`＝`第 N 條`、`ArticleContent`），與既有匯入腳本／`LawArticle.article_no` 同格式。"""
    parts = _HEADING_SPLIT_RE.split(body)
    if parts[0] != "" or len(parts) < 3 or len(parts) % 2 == 0:
        raise ValueError("original.md 條文格式不符（預期以 `第 N 條` 開頭）")
    return [{"ArticleNo": f"第 {parts[i]} 條", "ArticleContent": parts[i + 1]} for i in range(1, len(parts), 2)]


def chunk_eligible(article: Mapping[str, str]) -> bool:
    """與 `build_article_aware_chunks`／`_derive_law_articles` 相同的濾除規則：條號或內容為空、或內容為「（刪除）」佔位者不產生 chunk。"""
    content = (article.get("ArticleContent") or "").strip()
    return bool((article.get("ArticleNo") or "").strip()) and bool(content) and content not in DELETED_ARTICLE_MARKERS


def load_corpus(corpus_dir: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """逐資料夾讀 `original.md`、驗證與 manifest 的雜湊／條文一致，回傳 `[{source, body, articles, entry, ...}]`（依 source 排序）。"""
    versions_by_folder: dict[str, list[Mapping[str, Any]]] = {}
    for version in manifest["versions"]:
        versions_by_folder.setdefault(version["folder"], []).append(version)
    result = []
    for entry in sorted(manifest["folders"], key=lambda e: e["source"]):
        source = entry["source"]
        path = corpus_dir / source / "original.md"
        if not path.is_file():
            raise FileNotFoundError(f"缺少 original.md：{path}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["original_md_sha256"]:
            raise ValueError(f"original.md 雜湊與 manifest 不符（檔案被改動？）：{source}")
        body = split_original_md(raw.decode("utf-8"), source)
        articles = parse_articles(body)
        expected = sorted(f"第 {v['article_no']} 條" for v in versions_by_folder.get(source, []))
        if sorted(a["ArticleNo"] for a in articles) != expected:
            raise ValueError(f"original.md 的條文與 manifest 不一致：{source}")
        result.append({"source": source, "source_doc_id": entry["source_doc_id"], "law_name": entry["law_name"],
                       "valid_from": entry["valid_from"], "original_md_sha256": entry["original_md_sha256"],
                       "body": body, "articles": articles})
    return result


# ── 閘門（離線）─────────────────────────────────────────────────────────────
def validate_target_uri(uri: str, *, allow_port: int | None = None) -> str:
    """回傳遮蔽憑證後的 `host:port`；不合格一律 `GateViolation`。"""
    if "kg2-neo4j" in uri.lower():
        raise GateViolation("拒絕與 kg2-neo4j 相關的 URI")
    parsed = urlsplit(uri)
    try:
        port = parsed.port
    except ValueError as exc:
        raise GateViolation("URI 埠號格式無效") from exc
    if parsed.scheme != "bolt" or parsed.hostname not in ALLOWED_HOSTS:
        raise GateViolation("只允許 localhost／127.0.0.1 的 bolt URI")
    if port in FORBIDDEN_PORTS:
        raise GateViolation(f"拒絕保護埠 {port}")
    if allow_port is not None and allow_port in FORBIDDEN_PORTS:
        raise GateViolation(f"--allow-port 不得是保護埠 {allow_port}")
    if port != (allow_port if allow_port is not None else DEFAULT_PILOT_PORT):
        raise GateViolation(f"只允許試點埠 {allow_port if allow_port is not None else DEFAULT_PILOT_PORT}，收到 {port}")
    return f"{parsed.hostname}:{port}"


def validate_kg_id(kg_id: UUID | str, manifest_kg_id: str) -> UUID:
    value = UUID(str(kg_id))
    if value == KG4_ID:
        raise GateViolation("拒絕 KG#4 的 kg_id")
    if str(value) != str(UUID(manifest_kg_id)):
        raise GateViolation("kg_id 必須等於 manifest 的 pilot_kg_id")
    return value


def validate_environment(env: Mapping[str, str], corpus_dir: Path, manifest: Mapping[str, Any],
                         *, kg_id: UUID | str | None = None, allow_port: int | None = None) -> dict[str, Any]:
    """連線前的全部閘門。只回傳**不含秘密**的事實（遮蔽後的 host:port、KG 資料夾）。"""
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        raise GateViolation(f"缺少必要環境變數（須在行程環境明確設定，不依賴 .env）：{missing}")
    target = validate_target_uri(env["NEO4J_URI"], allow_port=allow_port)
    validated_kg = validate_kg_id(kg_id if kg_id is not None else manifest["pilot_kg_id"], manifest["pilot_kg_id"])
    if corpus_dir.resolve().parent.name != OUT_ROOT_DIRNAME:
        raise GateViolation(f"語料資料夾必須在 {OUT_ROOT_DIRNAME} 之下：{corpus_dir}")
    if Path(env["WORKSPACE_DIR"]).resolve() != corpus_dir.resolve().parent:
        raise GateViolation("WORKSPACE_DIR 必須等於語料根目錄（使 KG 資料夾＝Q1 輸出資料夾，且佇列／暫存區與正式工作區隔離）")
    if env["EMBEDDING_PROVIDER"] != "ollama":
        raise GateViolation("EMBEDDING_PROVIDER 必須是 ollama（local 在本機已知不可用）")
    return {"target": target, "kg_id": str(validated_kg), "kg_folder": str(corpus_dir.resolve()), "workspace_dir": env["WORKSPACE_DIR"]}


# ── 計畫（離線）─────────────────────────────────────────────────────────────
def build_plan(corpus_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(corpus_dir)
    folders = load_corpus(corpus_dir, manifest)
    per_folder = [{
        "source": f["source"], "source_doc_id": f["source_doc_id"], "valid_from": f["valid_from"],
        "articles": len(f["articles"]), "law_article_nodes": sum(chunk_eligible(a) for a in f["articles"]),
        "expected_svo_chunks": sum(chunk_eligible(a) for a in f["articles"]),
    } for f in folders]
    totals = {
        "documents": len(per_folder), "law_article_nodes": sum(p["law_article_nodes"] for p in per_folder),
        "expected_svo_chunks": sum(p["expected_svo_chunks"] for p in per_folder),
    }
    kg_folder = str(corpus_dir.resolve())
    steps = [
        {"n": 1, "action": "驗證環境與目標：埠 28687（或 --allow-port；拒絕 17990／27687／7687）、拒絕 kg2-neo4j、kg_id＝pilot_kg_id、"
                           "WORKSPACE_DIR＝語料根目錄、EMBEDDING_PROVIDER＝ollama"},
        {"n": 2, "action": "連線；建立 schema／索引（Entity 唯一約束、chunk／related_to／entity_name 向量索引、entity_name 全文索引；維度取 embedding provider）"},
        {"n": 3, "action": f"MERGE KnowledgeGraph 節點 id={manifest['pilot_kg_id']}，folder_path={kg_folder}"},
        {"n": 4, "action": "逐份文件：merge_document → merge_law_articles → chunk_and_stage（暫存區）→ assign_document_to_kg（虛擬歸屬）"
                           " → trigger_extraction(articles=…, kg_folder=…)（CHUNKREADY→向量化→ENQUEUE）", "count": totals["documents"]},
        {"n": 5, "action": "抽取：另開 `--worker`（或 uvicorn main:app，使用相同環境變數）消費試點工作區的 task_queue.db", "count": totals["expected_svo_chunks"]},
    ]
    return {
        "mode": "plan", "connects": False, "pilot_kg_id": manifest["pilot_kg_id"], "corpus_dir": str(corpus_dir),
        "kg_folder": kg_folder, "required_env": list(REQUIRED_ENV), "target_port_default": DEFAULT_PILOT_PORT,
        "totals": totals, "per_folder": per_folder, "steps": steps,
        "worker_command": "python scripts/kg/pilot_import.py --worker  （環境變數同 --execute）",
        "notes": ["law_article_nodes＝expected_svo_chunks（ArticleAware 一條一塊；刪除佔位與空內容不產生）",
                  "本步驟不寫 LawArticle 版本屬性（Q4）；對照見 manifest.versions 的 source_doc_id＋law_article_no"],
    }


# ── 連線模式（實作者不得執行）─────────────────────────────────────────────────
def _validated_env(corpus_dir: Path, kg_id: str | None, allow_port: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = load_manifest(corpus_dir)
    facts = validate_environment(os.environ, corpus_dir, manifest, kg_id=kg_id, allow_port=allow_port)
    return manifest, facts


ENSURE_KG_CYPHER = """
MERGE (k:KnowledgeGraph {id: $id})
ON CREATE SET k.name = $name, k.description = $description, k.folder_path = $folder_path,
              k.is_public = false, k.db_name = '', k.doc_count = 0, k.entity_count = 0, k.relation_count = 0,
              k.pronoun_lexicon_exclude = $pronoun_exclude, k.domain_pack = 'taiwan-labor-law',
              k.created_at = $now, k.updated_at = $now
RETURN k.folder_path AS folder_path
"""


async def ensure_pilot_kg(driver: Any, kg_id: UUID, kg_folder: Path) -> None:
    """以**指定 id** 建立 KG 節點（`KGRepository.create` 固定用 uuid4，無法指定）；已存在則驗證 folder_path 相同。"""
    from datetime import datetime, timezone

    result = await driver.execute_query(
        ENSURE_KG_CYPHER, id=str(kg_id), name=PILOT_KG_NAME, description=PILOT_KG_DESCRIPTION, folder_path=str(kg_folder),
        pronoun_exclude=PILOT_PRONOUN_EXCLUDE, now=datetime.now(timezone.utc).isoformat(),
    )
    if result.records[0]["folder_path"] != str(kg_folder):
        raise RuntimeError(f"既有 KG 節點的 folder_path 與預期不同：{result.records[0]['folder_path']!r}")
    kg_folder.mkdir(parents=True, exist_ok=True)


async def execute(corpus_dir: Path, kg_id: str | None, allow_port: int | None) -> int:
    manifest, facts = _validated_env(corpus_dir, kg_id, allow_port)
    folders = load_corpus(corpus_dir, manifest)
    # 閘門通過後才匯入 core：`core.config.settings` 在匯入時建立，此時行程環境變數已確認（環境變數優先於 .env）。
    from core.config import settings, staging_folder
    from core.database import connect, disconnect, get_driver
    from core.providers.factory import init_providers
    from models.law_document import LawArticleCreate, LawDocumentCreate
    from parser.chunk_writer import read_sentences_index
    from repositories.law_document_repo import LawDocumentRepository
    from services import svo_service
    from services.classify_service import KGInfo, assign_document_to_kg
    from services.document_record_service import document_uuid
    from services.ingestion_service import chunk_and_stage
    from services.svo_chunking import read_svo_index

    if settings.neo4j_uri != os.environ["NEO4J_URI"] or Path(settings.workspace_dir).resolve() != Path(os.environ["WORKSPACE_DIR"]).resolve():
        raise GateViolation("有效設定與行程環境變數不一致（.env 覆蓋？），停止")
    validate_target_uri(settings.neo4j_uri, allow_port=allow_port)

    import httpx

    kg_uuid = UUID(facts["kg_id"])
    kg_folder = Path(facts["kg_folder"])
    await connect()
    embedding = init_providers()
    driver = get_driver()
    try:
        await svo_service.create_entity_index(driver)
        await svo_service.create_chunk_vector_index(driver, embedding.dim)
        await svo_service.create_related_to_vector_index(driver, embedding.dim)
        await svo_service.create_entity_name_vector_index(driver, embedding.dim)
        await svo_service.create_entity_name_fulltext_index(driver)
        await ensure_pilot_kg(driver, kg_uuid, kg_folder)
        kg_info = KGInfo(kg_id=kg_uuid, kg_name=PILOT_KG_NAME, folder_path=kg_folder)
        law_doc_repo = LawDocumentRepository(driver)
        imported = skipped = failed = 0
        for index, folder in enumerate(folders, start=1):
            source = folder["source"]
            source_doc_id = document_uuid(source)
            if str(source_doc_id) != folder["source_doc_id"]:
                raise RuntimeError(f"source_doc_id 與 manifest 不一致：{source}")
            if read_svo_index(kg_folder / source) is not None:  # Q1 已預先建立資料夾，不能用「資料夾是否存在」判斷已匯入
                skipped += 1
                continue
            articles = folder["articles"]
            await law_doc_repo.merge_document(LawDocumentCreate(
                kg_id=kg_uuid, source_doc_id=source_doc_id, source=source, title=folder["law_name"], record_type="law",
                content_hash=folder["original_md_sha256"],
            ))
            await law_doc_repo.merge_law_articles([
                LawArticleCreate(kg_id=kg_uuid, source_doc_id=source_doc_id, article_no=a["ArticleNo"], article_content=a["ArticleContent"])
                for a in articles if chunk_eligible(a)
            ])
            staging_doc_folder, _record = chunk_and_stage(folder["body"], source, staging_folder())
            staged = (staging_doc_folder / "original.md").read_bytes()
            if hashlib.sha256(staged).hexdigest() != folder["original_md_sha256"]:
                raise RuntimeError(f"暫存區 original.md 與 Q1 輸出不一致（格式漂移）：{source}")
            dest = assign_document_to_kg(staging_doc_folder, kg_info, method="manual")
            sentences = read_sentences_index(source, staging_folder()) or []
            timeout_seconds = max(600, len(sentences) * 5)
            try:
                await asyncio.wait_for(
                    svo_service.trigger_extraction(driver, dest, kg_uuid, articles=articles, kg_folder=kg_folder),
                    timeout=timeout_seconds,
                )
            except (asyncio.TimeoutError, httpx.HTTPError) as exc:
                failed += 1
                print(f"⚠️ 觸發抽取失敗（{type(exc).__name__}），之後可重跑補上：{source}", flush=True)
                continue
            imported += 1
            print(f"[{index}/{len(folders)}] 已匯入並入佇列：{source}（{len(articles)} 條）", flush=True)
        print(json.dumps({"mode": "execute", "target": facts["target"], "kg_id": facts["kg_id"], "imported": imported,
                          "skipped": skipped, "failed": failed, "next": "啟動抽取：python scripts/kg/pilot_import.py --worker"},
                         ensure_ascii=False))
        return 0 if failed == 0 else 1
    finally:
        await disconnect()


async def run_worker(corpus_dir: Path, kg_id: str | None, allow_port: int | None) -> int:
    _validated_env(corpus_dir, kg_id, allow_port)
    from core.config import settings
    from core.database import connect, disconnect, get_driver
    from core.providers.factory import init_providers
    from services.extraction_worker import run_extraction_worker

    if settings.neo4j_uri != os.environ["NEO4J_URI"]:
        raise GateViolation("有效設定與行程環境變數不一致，停止")
    validate_target_uri(settings.neo4j_uri, allow_port=allow_port)
    await connect()
    init_providers()
    try:
        await run_extraction_worker(get_driver())
    finally:
        await disconnect()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true", help="離線：只列步驟與數量，不連線")
    mode.add_argument("--execute", action="store_true", help="連線匯入（由規劃對話執行）")
    mode.add_argument("--worker", action="store_true", help="啟動既有抽取 worker（由規劃對話執行）")
    parser.add_argument("--corpus-dir", type=Path, default=None, help="Q1 輸出資料夾（預設為固定 pilot_kg_id 的資料夾）")
    parser.add_argument("--kg-id", default=None, help="必須等於 manifest 的 pilot_kg_id")
    parser.add_argument("--allow-port", type=int, default=None, help="明確允許的非預設試點埠（不得是 17990／27687／7687）")
    args = parser.parse_args(argv)
    corpus_dir = args.corpus_dir or default_corpus_dir()
    if args.plan:
        print(json.dumps(build_plan(corpus_dir), ensure_ascii=False, indent=2))
        return 0
    try:
        if args.execute:
            return asyncio.run(execute(corpus_dir, args.kg_id, args.allow_port))
        return asyncio.run(run_worker(corpus_dir, args.kg_id, args.allow_port))
    except GateViolation as exc:
        print(f"停止（閘門）：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
