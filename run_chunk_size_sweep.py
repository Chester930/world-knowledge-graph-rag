"""§5.3 前置參數校準：chunk-size 敏感度掃描 harness（P1a）。

對應 `docs/論文/05_實驗設計與評估.md` §5.3.1–§5.3.4。§5.3 明訂 chunk-size 校準
**必須先於 5.2 節一切消融**——B0/B1/B2/Full System 的切塊都吃它鎖定的值。

## 本 harness 做什麼

1. **字元 ↔ token 校準（§5.3.1 的誠實要求，可離線跑）**：對每個候選 `chunk_size`
   （字元數），實際跑 `sentence_aware_chunking()` 切一次語料，回報 chunk 數與
   **實測** token 數（用 `LocalEmbeddingProvider` 底層 `sentence-transformers`
   分詞器，`settings.local_embedding_model`）——讓「N 個中文字元 ≈ M 個子詞
   token」是量出來的，寫論文時才能誠實地與 Chen et al. 2024／Bhat et al. 2025
   的英文 token 區間對照，而非含糊帶過單位落差。

2. **三個下游消費端的評估（§5.3.3）——尚未接線**：CMP 分類準確率、HDBSCAN
   輪廓係數、下游 RAG 問答 P@K/R@K/F1。這三項需要：帶標籤驗證集（分類/分群）、
   §5.4 題組的**事實級標註**（P0a-2，`docs/論文/05_附錄A_測試題庫.md` §A.5）、
   以及對 KG#4 建各 chunk_size 的索引（`build_baseline_chunk_index.py`）。
   **卡 DRAIN-DONE ＋ P0a-2**，本 harness 先留 `--eval` 旗標與 stub。

## 用法

    # 只做字元/token 校準（離線，需 sentence-transformers 模型可載入）
    python run_chunk_size_sweep.py <kg_id> [--sizes 150,300,500,800,1200] [--overlap 50]

    # 之後每個勝出候選再各自建 B0/B1 索引
    python build_baseline_chunk_index.py <kg_id> --chunk-size <勝出值>

需要 `workspace/<kg_id>/<doc>/original.md`（KG#4 的 workspace 在
`D:/Users/666/Desktop/kg-runtime/workspace/...`，跑前把 `WORKSPACE_DIR` 指過去）。
不碰 Neo4j、不碰抽取 drain、不呼叫 LLM。
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path
from uuid import UUID

from core.config import settings
from parser.core import sentence_aware_chunking

try:
    from build_baseline_chunk_index import _read_original  # 共用原文讀取（去 frontmatter）
except ImportError:  # pragma: no cover
    _read_original = None  # type: ignore[assignment]

_DEFAULT_SIZES = [150, 300, 500, 800, 1200]
_DEFAULT_OVERLAP = 50


def _load_tokenizer(name: str):
    """回傳 sentence-transformers 模型的底層 HF tokenizer；載入失敗（無網路／
    模型未下載）時回傳 None，harness 只回報字元統計、跳過 token 統計。"""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(name).tokenizer
    except Exception as exc:  # noqa: BLE001 - 離線環境常見，非致命
        print(f"⚠️  無法載入分詞器 {name}（{type(exc).__name__}）→ 只回報字元統計")
        return None


def _gather_chunks(kg_id: UUID, chunk_size: int, overlap: int) -> list[str]:
    kg_folder = Path(settings.workspace_dir) / str(kg_id)
    if not kg_folder.is_dir():
        raise SystemExit(f"找不到 {kg_folder}（KG#4 的 workspace 在 kg-runtime，設 WORKSPACE_DIR）")
    if _read_original is None:
        raise SystemExit("build_baseline_chunk_index._read_original 匯入失敗")

    chunks: list[str] = []
    for doc_folder in sorted(p for p in kg_folder.iterdir() if p.is_dir()):
        pair = _read_original(doc_folder)
        if pair is None:
            continue
        _source, text = pair
        chunks.extend(sentence_aware_chunking(text, chunk_size, overlap))
    return chunks


def _summarise(chunks: list[str], tokenizer) -> dict:
    char_lens = [len(c) for c in chunks]
    row = {
        "n_chunks": len(chunks),
        "mean_chars": round(statistics.mean(char_lens), 1) if char_lens else 0.0,
        "median_chars": statistics.median(char_lens) if char_lens else 0,
        "max_chars": max(char_lens) if char_lens else 0,
        "mean_tokens": None,
        "median_tokens": None,
        "tokens_per_char": None,
    }
    if tokenizer is not None and chunks:
        tok_lens = [len(tokenizer.encode(c, add_special_tokens=False)) for c in chunks]
        row["mean_tokens"] = round(statistics.mean(tok_lens), 1)
        row["median_tokens"] = statistics.median(tok_lens)
        row["tokens_per_char"] = round(statistics.mean(tok_lens) / statistics.mean(char_lens), 3)
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="§5.3 chunk-size 敏感度掃描（字元/token 校準）")
    ap.add_argument("kg_id", type=UUID)
    ap.add_argument("--sizes", default=",".join(map(str, _DEFAULT_SIZES)),
                    help="逗號分隔的 chunk_size 候選（字元），預設 150,300,500,800,1200")
    ap.add_argument("--overlap", type=int, default=_DEFAULT_OVERLAP)
    ap.add_argument("--tokenizer", default=settings.local_embedding_model,
                    help=f"分詞器模型名，預設 {settings.local_embedding_model}")
    ap.add_argument("--eval", action="store_true",
                    help="（尚未接線）跑 §5.3.3 三個下游評估——卡 DRAIN-DONE + P0a-2")
    args = ap.parse_args()

    if args.eval:
        raise SystemExit(
            "§5.3.3 下游評估（CMP 分類準確率／HDBSCAN 輪廓係數／RAG P@K·R@K·F1）尚未接線。\n"
            "前置：① 帶標籤分類/分群驗證集 ② P0a-2 事實級標註（附錄 A §A.5）\n"
            "③ 對 KG#4 各 chunk_size 建索引（build_baseline_chunk_index.py）。全部卡 DRAIN-DONE。"
        )

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    tokenizer = _load_tokenizer(args.tokenizer)

    print(f"KG {args.kg_id}｜overlap={args.overlap}｜分詞器={args.tokenizer if tokenizer else '（未載入）'}")
    print(f"{'chunk_size':>10} | {'#chunks':>8} | {'mean_chars':>10} | {'median_chars':>12} | "
          f"{'max_chars':>9} | {'mean_tokens':>11} | {'median_tokens':>13} | {'tok/char':>8}")
    print("-" * 100)
    for size in sizes:
        row = _summarise(_gather_chunks(args.kg_id, size, args.overlap), tokenizer)
        mt = row["mean_tokens"] if row["mean_tokens"] is not None else "—"
        md = row["median_tokens"] if row["median_tokens"] is not None else "—"
        tpc = row["tokens_per_char"] if row["tokens_per_char"] is not None else "—"
        print(f"{size:>10} | {row['n_chunks']:>8} | {row['mean_chars']:>10} | {row['median_chars']:>12} | "
              f"{row['max_chars']:>9} | {str(mt):>11} | {str(md):>13} | {str(tpc):>8}")

    print("\n對照文獻 token 區間（英文子詞）：Bhat 2025 事實型 64–128 tok／脈絡型 512–1024 tok；"
          "Chen 2024 proposition ≈ 句內短片段。用上表 mean_tokens 欄與這些區間對照，"
          "在 §5.3.4 誠實標註「N 字元 ≈ M token」的實測換算，不要直接把字元數當 token 數。")


if __name__ == "__main__":
    main()
