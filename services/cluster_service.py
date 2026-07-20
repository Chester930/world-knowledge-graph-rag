"""暫存區未分配文件的 AI 自動分群（HDBSCAN + LLM 命名）。

對應 docs/論文/03_系統設計與方法論.md § 3.1.1 §a。

**分群演算法**：HDBSCAN（McInnes, Healy, Astels, 2017, *Journal of Open Source
Software*）取代 v1（智慧知識庫）`cluster_service.py` 的門檻式連通分量分群——
後者用單一固定相似度門檻判斷「同群」，已知有連鎖效應缺陷（A-B、B-C 相似度都恰好
卡在門檻邊緣時，即使 A 與 C 完全不相關仍會被遞移地分進同一群）。

`min_cluster_size=3`（`core/constants.py` `CLUSTER_MIN_SIZE`）依需求設定——一個
候選分群/新 KG 至少要有 3 份文件。**`min_samples` 特意設為 1，而非 HDBSCAN 預設
的等於 `min_cluster_size`**：實測發現，預設 `min_samples` 會要求群內每個成員點
自己都要有夠多近鄰才算核心點，這對剛好卡在 `min_cluster_size` 邊界的小群（例如
剛好 3 個成員）過於嚴格，在資料量不大時容易被誤判為雜訊（見
tests/services/test_cluster_service.py 的實測記錄）；`min_samples=1` 讓「3 個
緊密的點」更可靠地被辨識成一個群，仍然由 `min_cluster_size` 把關「群要多大才
算數」。

**命名輸入篩選**：採 Khandelwal (2025)《Using LLM-Based Approaches to Enhance
and Automate Topic Labeling》驗證表現最佳的 **Approach 3（主導子群法）**——
對候選分群內的文件再做一次同樣的 HDBSCAN 分群（巢狀），取文件數最多的子群，
其文件的高頻概念才是 LLM 生成建議名稱的依據，藉此過濾可能混入候選分群、但
主題略有偏移的邊緣文件，避免稀釋生成名稱的聚焦度。**重要**：主導子群篩選只
影響命名時餵給 LLM 的輸入，候選分群本身包含哪些檔案（`ClusterSuggestion.
candidate_folders`）不受影響，使用者審核檔案清單時看到的仍是整個候選分群。

**降維前處理的決策（2026-07-20）**：BERTopic（Grootendorst, 2022，見第二章 2.4.2
可信任專案背書）標準管線在 HDBSCAN 前固定接一段 UMAP 降維，原因是原始向量維度
`VECTOR_DIM=384`（`core/constants.py`）偏高，HDBSCAN 賴以判斷密度的 mutual
reachability distance 在高維空間容易受維度詛咒影響而失真。本模組**採條件式降維**
而非照抄「一律先 UMAP」：僅在未分配池規模達 `UMAP_MIN_POOL_SIZE`（見
`core/constants.py`，訂在略高於 UMAP 預設 `n_neighbors=15` 的規模）才套用，因為
UMAP 本身在點數過少時的流形估計並不穩定，盲目套用反而可能傷害本已針對小樣本
（`allow_single_cluster=True`）調校過的分群品質。`_reduce_dimensionality()` 固定
`random_state=42`，確保同一批輸入的降維結果可重現，呼應 `docs/ARCHITECTURE.md`
「實驗可追溯性規範」。

**擴展性上限的決策（2026-07-20）**：`mean_pairwise_cosine_similarity()` 與
HDBSCAN 的距離計算皆為 O(n²)，而未分配資料夾池會隨時間持續累積（見 §a 正文）。
本模組現階段**不引入近似最近鄰（如 FAISS）等額外基礎設施**——這會是比目前規模
更大的架構決策，需要獨立評估；改為在池規模達 `_UNASSIGNED_POOL_WARN_SIZE`
（500）時記錄警告，讓維運者/未來研究者有明確、可觀測的訊號知道何時需要重新
評估此設計，而非讓效能劣化悄悄發生。若第五章實驗語料規模觸及此門檻，需將
「導入 ANN」列為第七章未來工作，而非現階段的正式研究貢獻。
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

import hdbscan
import numpy as np
import umap

from core.constants import CLUSTER_MIN_SIZE, UMAP_MIN_POOL_SIZE, UMAP_N_COMPONENTS
from core.providers.factory import get_llm_provider
from models.knowledge_graph import ClusterAnalyzeResult, ClusterSuggestion
from services.classify_service import compute_document_vector, cosine_similarity, read_chunk_bodies

logger = logging.getLogger(__name__)

# 見模組 docstring：min_samples 刻意設低於 HDBSCAN 預設值，避免剛好達
# min_cluster_size 邊界的小群在資料量不大時被誤判為雜訊。
_HDBSCAN_MIN_SAMPLES = 1

# 未分配資料夾池達此規模才對 mean_pairwise_cosine_similarity／HDBSCAN 的 O(n^2)
# 計算量發出警告——見模組 docstring「擴展性上限的決策」，此為觀測性警告，
# 不是演算法複雜度本身的修正。
_UNASSIGNED_POOL_WARN_SIZE = 500


# ── 純分群邏輯（不涉及 I/O，方便以合成向量單元測試）───────────────────────────

def _reduce_dimensionality(vectors: list[list[float]]) -> list[list[float]]:
    """UMAP 降維前處理，僅在點數足以讓 UMAP 可靠學習流形結構時套用
    （`len(vectors) >= UMAP_MIN_POOL_SIZE`，見 `core/constants.py` 註解與模組
    docstring「降維前處理的決策」）；點數不足時原樣回傳，不降維，也不引入 UMAP
    在小樣本下的不穩定行為。`random_state` 固定，確保同一批輸入的降維結果可重現
    （呼應 `docs/ARCHITECTURE.md`「實驗可追溯性規範」）。
    """
    n_components = min(UMAP_N_COMPONENTS, len(vectors) - 2)
    reducer = umap.UMAP(n_components=n_components, random_state=42)
    return reducer.fit_transform(np.array(vectors)).tolist()


def cluster_vectors(
    vectors: list[list[float]],
    min_cluster_size: int = CLUSTER_MIN_SIZE,
) -> list[int]:
    """對一組向量做 HDBSCAN 分群，回傳每個點的群標籤（-1 代表雜訊）。

    點數少於 `min_cluster_size` 時，數學上不可能形成任何合格分群，直接全部
    標記為雜訊，不呼叫 HDBSCAN（避免對過小輸入的邊界行為做無意義的假設）。

    點數達 `UMAP_MIN_POOL_SIZE` 時，先做 UMAP 降維再交給 HDBSCAN——原始向量
    維度 `VECTOR_DIM=384`（見 `core/constants.py`），HDBSCAN 賴以判斷密度的
    mutual reachability distance 在高維空間容易受維度詛咒影響而失真，此處仿
    BERTopic（Grootendorst, 2022，見 §a 可信任專案背書段落）的標準管線做法；
    未達門檻時直接對原始向量分群，避免 UMAP 在小樣本下的不穩定估計反而傷害
    分群品質（見模組 docstring「降維前處理的決策」）。
    """
    if len(vectors) < min_cluster_size:
        return [-1] * len(vectors)

    cluster_input = _reduce_dimensionality(vectors) if len(vectors) >= UMAP_MIN_POOL_SIZE else vectors

    X = np.array(cluster_input)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=_HDBSCAN_MIN_SAMPLES,
        metric="euclidean",
        # 實測發現：若未分配池裡「唯一存在的真實結構」剛好只有一組達
        # min_cluster_size 的緊密群、其餘都是雜訊（沒有第二個對照群），HDBSCAN
        # 預設會因為缺乏可比較的群集結構而傾向整批判為雜訊，即使群內本身緊密；
        # allow_single_cluster=True 讓演算法願意把「資料集裡唯一的密集結構」
        # 視為一個合格分群，實測確認不影響多群情境下的正常區分能力。
        allow_single_cluster=True,
    )
    labels = clusterer.fit_predict(X)
    return labels.tolist()


def dominant_subcluster_indices(
    vectors: list[list[float]],
    min_cluster_size: int = CLUSTER_MIN_SIZE,
) -> list[int]:
    """對候選分群內的文件再做一次分群（巢狀），取文件數最多的子群的索引清單
    （Khandelwal 2025 Approach 3）。無法再細分出任何子群時（例如點數太少、
    或分群結果全是雜訊），退回使用全部索引，確保命名步驟一定有輸入可用。
    """
    if len(vectors) < min_cluster_size:
        return list(range(len(vectors)))

    labels = cluster_vectors(vectors, min_cluster_size=min_cluster_size)
    counts = Counter(l for l in labels if l != -1)
    if not counts:
        return list(range(len(vectors)))

    dominant_label = counts.most_common(1)[0][0]
    return [i for i, l in enumerate(labels) if l == dominant_label]


def extract_top_concepts(bodies: list[str], top_n: int = 15) -> list[str]:
    """簡易高頻詞統計，供命名 prompt 參考用的粗略關鍵詞。

    這**不是**正式的概念抽取（正式概念抽取屬 services/concept_engine.py，
    3.2 節 RQ2 路由層範圍，尚未實作）——此處只需要足夠代表性的關鍵詞餵給
    LLM 生成名稱，不需要完整的 LLM 概念抽取管線，避免命名這個工程借鏡型
    功能反過來依賴尚未完成的路由層研究問題。
    """
    counter: Counter[str] = Counter()
    for body in bodies:
        tokens = re.findall(r"[一-鿿A-Za-z]{2,}", body)
        counter.update(tokens)
    return [word for word, _ in counter.most_common(top_n)]


def mean_pairwise_cosine_similarity(vectors: list[list[float]]) -> float:
    """群內平均兩兩 cosine 相似度，用於 `ClusterSuggestion.intra_similarity`
    （呈現給使用者參考這個候選分群的內聚程度）。少於 2 個點時無意義，回傳 1.0。"""
    n = len(vectors)
    if n < 2:
        return 1.0
    total, count = 0.0, 0
    for i in range(n):
        for j in range(i + 1, n):
            total += cosine_similarity(vectors[i], vectors[j])
            count += 1
    return total / count if count else 0.0


def build_naming_prompt(folder_names: list[str], top_concepts: list[str]) -> str:
    files_str = "\n".join(f"- {f}" for f in folder_names[:10])
    concepts_str = "、".join(top_concepts[:20])
    return (
        "以下是一批主題相近的文件，請為它們建議一個知識圖譜（KG）的分類名稱和簡短描述。\n\n"
        f"文件列表：\n{files_str}\n\n"
        f"共同關鍵概念：{concepts_str}\n\n"
        "請用以下格式回答（只回這兩行，不加其他文字）：\n"
        "名稱：<2-8個字的中文名稱>\n"
        "描述：<一句話說明這個知識庫的主題範圍>"
    )


def parse_naming_response(raw: str) -> tuple[str, str]:
    """解析 LLM 回應的「名稱：.../描述：...」格式，解析失敗時給預設值而非拋例外
    （命名生成本身是輔助功能，失敗不應阻斷整個分群建議流程）。"""
    name, desc = "", ""
    for line in raw.strip().splitlines():
        line = line.strip()
        if line.startswith(("名稱：", "名称：")):
            name = line.split("：", 1)[-1].strip()
        elif line.startswith("描述："):
            desc = line.split("：", 1)[-1].strip()
    if not name:
        name = "新知識庫"
    return name, desc


# ── I/O 入口 ─────────────────────────────────────────────────────────────────

async def _suggest_name(folder_names: list[str], top_concepts: list[str]) -> tuple[str, str]:
    prompt = build_naming_prompt(folder_names, top_concepts)
    try:
        raw = await get_llm_provider().generate(prompt)
        return parse_naming_response(raw)
    except Exception as e:
        logger.warning(f"LLM 建議 KG 名稱失敗：{e}")
        return "新知識庫", ""


async def analyze_staging_pool(
    staging_folder: Path,
    min_cluster_size: int = CLUSTER_MIN_SIZE,
) -> ClusterAnalyzeResult:
    """分析暫存區未分配文件池，回傳候選分群建議清單（一次可能產生多個）。

    每個候選分群：完整檔案清單（candidate_folders）+ 依主導子群生成的建議
    名稱/描述（naming_basis_folders 記錄實際用於命名的檔案，供除錯/稽核）。

    池規模達 `_UNASSIGNED_POOL_WARN_SIZE` 時記錄警告——`mean_pairwise_cosine_
    similarity()` 與 HDBSCAN 距離計算皆為 O(n^2)，此為觀測性警告，不是演算法
    複雜度本身的修正；若第五章實驗語料規模達到此門檻，需評估導入近似最近鄰
    （如 FAISS）作為未來工作，見模組 docstring「擴展性上限的決策」。
    """
    if not staging_folder.exists():
        return ClusterAnalyzeResult()

    doc_folders = sorted(p for p in staging_folder.iterdir() if p.is_dir())
    if len(doc_folders) >= _UNASSIGNED_POOL_WARN_SIZE:
        logger.warning(
            f"未分配資料夾池規模達 {len(doc_folders)}（門檻 {_UNASSIGNED_POOL_WARN_SIZE}），"
            "分群的兩兩距離計算為 O(n^2)，執行時間可能明顯增加。"
        )
    if len(doc_folders) < min_cluster_size:
        return ClusterAnalyzeResult(unclustered_folders=[p.name for p in doc_folders])

    vectors: list[list[float] | None] = [compute_document_vector(p) for p in doc_folders]
    valid_idx = [i for i, v in enumerate(vectors) if v is not None]
    valid_vectors = [vectors[i] for i in valid_idx]
    valid_folders = [doc_folders[i] for i in valid_idx]

    labels = cluster_vectors(valid_vectors, min_cluster_size=min_cluster_size)

    clusters: dict[int, list[int]] = {}
    for pos, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append(pos)

    suggestions: list[ClusterSuggestion] = []
    clustered_positions: set[int] = set()

    for member_positions in clusters.values():
        clustered_positions.update(member_positions)
        member_folders = [valid_folders[p] for p in member_positions]
        member_vectors = [valid_vectors[p] for p in member_positions]

        dominant_local_idx = dominant_subcluster_indices(member_vectors, min_cluster_size=min_cluster_size)
        naming_folders = [member_folders[i] for i in dominant_local_idx]

        bodies = [body for f in naming_folders for body in read_chunk_bodies(f)]
        top_concepts = extract_top_concepts(bodies)
        name, desc = await _suggest_name([f.name for f in naming_folders], top_concepts)

        suggestions.append(ClusterSuggestion(
            suggested_name=name,
            suggested_description=desc,
            candidate_folders=[f.name for f in member_folders],
            naming_basis_folders=[f.name for f in naming_folders],
            intra_similarity=round(mean_pairwise_cosine_similarity(member_vectors), 4),
        ))

    unclustered = [
        valid_folders[pos].name for pos in range(len(valid_folders))
        if pos not in clustered_positions
    ] + [doc_folders[i].name for i in range(len(doc_folders)) if i not in valid_idx]

    return ClusterAnalyzeResult(suggestions=suggestions, unclustered_folders=sorted(unclustered))
