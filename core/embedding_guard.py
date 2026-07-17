from __future__ import annotations
import logging

from neo4j import AsyncDriver

logger = logging.getLogger(__name__)


class EmbeddingProviderMismatchError(RuntimeError):
    """啟動時偵測到目前設定的 embedding provider/model 與既有向量索引的記錄不一致。

    不同 provider 或 model 的向量空間互不相容（見 core/providers/embedding/README.md
    「模型一致性」文獻依據，Muennighoff et al., 2023）；靜默沿用舊索引會讓 cosine
    相似度計算失去意義，卻不會有任何錯誤訊息——本例外的存在就是為了讓這種情況
    無法被忽略，直接擋下啟動。
    """


async def check_and_register(driver: AsyncDriver, provider: str, model_name: str, dim: int) -> None:
    """啟動時呼叫一次：比對這次啟動使用的 embedding provider/model/dim，
    與資料庫中既有記錄是否一致。

    - 資料庫尚無記錄（首次啟動）：視為合法初始化，直接寫入記錄。
    - 記錄存在且一致：放行，不做任何變更。
    - 記錄存在但不一致：拋出 EmbeddingProviderMismatchError，擋下啟動。
    """
    result = await driver.execute_query(
        "MATCH (m:_EmbeddingMeta) RETURN m.provider AS provider, m.model AS model, m.dim AS dim LIMIT 1"
    )

    if not result.records:
        await driver.execute_query(
            "CREATE (m:_EmbeddingMeta {provider: $provider, model: $model, dim: $dim})",
            provider=provider, model=model_name, dim=dim,
        )
        logger.info(f"Embedding provider 記錄已建立：{provider}/{model_name}（dim={dim}）")
        return

    record = result.records[0]
    existing = (record["provider"], record["model"], record["dim"])
    current = (provider, model_name, dim)
    if existing != current:
        raise EmbeddingProviderMismatchError(
            "偵測到 embedding provider 設定與既有向量索引不一致，已擋下啟動：\n"
            f"  資料庫既有記錄：provider={existing[0]!r}, model={existing[1]!r}, dim={existing[2]}\n"
            f"  目前 .env 設定：provider={current[0]!r}, model={current[1]!r}, dim={current[2]}\n"
            "不同 provider/model 的向量空間互不相容，繼續啟動會讓所有既有向量的 cosine 相似度"
            "計算失去意義（分類分數、AI 分群、路由層粗篩皆會受影響），且不會有任何執行期錯誤"
            "提示這件事已經發生。請選擇以下其中一種方式處理：\n"
            "  1. 將 .env 的 embedding_provider／對應 model 設定改回與資料庫記錄一致的值；\n"
            "  2. 若確定要切換 provider/model，需先對所有既有文件與 ConceptNode 重新執行向量化，"
            "再手動更新（或刪除）資料庫中的 `_EmbeddingMeta` 節點，讓系統以新設定重新初始化記錄。"
        )
