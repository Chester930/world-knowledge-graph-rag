# 本機生成模型初篩（2026-09-21）

## 決定

**是否採用候選生成模型：否，暫不替換。** 目前維持 `qwen2.5:7b` 作為生成模型，並維持 `bge-m3` 作為 embedding；這是暫時保留現況，不代表認定現行生成模型表現理想。

在本次受控 baseline 中，M2 的原子事實正確率與召回率都只有 70%，且「特休天數列舉」題三次都逾時。候選模型尚未有完整 RQ1 結果，且多款模型連第一題都無法穩定完成，因此目前沒有足夠證據支持替換。

本輪是初篩，不是完整排名。若要決定換模，應先讓 Ollama provider 可控制 thinking，再重跑同一套全題評測。

## 評測條件

- 專案目前設定：生成模型 `qwen2.5:7b`，embedding `bge-m3`；本輪全程固定 embedding。
- RTX 4070 Laptop，8 GB VRAM；Ollama 的 RQ1 provider 固定 `num_ctx=8192`、`num_predict=4096`、temperature 0。
- RQ1 資料集載入 32 題，其中 10 題通過正式 gold 資格；每題三次重跑。
- 固定 M2（Hybrid Text）檢索路徑，使用相同的 `qwen3:4b` 獨立 judge；單題 timeout 為 180 秒。
- 這輪只比較 M2 的生成結果，不代表目前預設 `both/K` 路徑的完整表現。

## 結果

| 模型 | 有效評測範圍 | 觀察 | 判斷 |
|---|---:|---|---|
| `qwen2.5:7b`（現行） | 完整 10 題 × 3 跑 | 原子事實正確率 70%、召回率 70%、p50 133.79 秒；18-Q5 三跑 timeout；兩題 Type-E canary 全數通過 | 暫留作 baseline，仍有明顯品質與延遲問題 |
| `qwen3.5:9b` | 1 題 × 3 跑 | 17-Q1 三跑都在 180 秒 timeout；載入時約 12% CPU／88% GPU | 不適合直接替換 |
| `granite4.2:8b` | 1 題 × 3 跑 | 17-Q1 三跑都在 180 秒 timeout；載入時約 8% CPU／92% GPU | 不適合直接替換 |
| `qwen3.5:4b` | 1 題 × 3 跑，另加 1 筆 think-off pilot | GPU 100%；標準呼叫三跑 timeout。RQ1 的 17-Q1 加 `think:false` 後仍 timeout | 目前專案流程下不適合直接替換 |
| `granite4.2:3b` | 2 題共 6 跑，另加 1 筆 think-off pilot | 標準呼叫的 17-Q1 暖載入兩跑成功（122.63、53.53 秒），17-Q2 三跑 timeout。Think-off 的 17-Q2 pilot 在 146.46 秒答對必要事實，但答案帶有長篇推理文字及不相關假別資訊 | 有短答能力，但不穩定且輸出品質未達替換門檻 |
| `qwen3.8:27b` | 未執行 | Ollama 權重約 18 GB，而本機 VRAM 為 8 GB；專案目前也只配置 8K context | 先不列入此機器候選 |

短 prompt 的獨立 smoke call 在 `think:false` 下，Qwen3.5:4B 用 18.44 秒、Granite 4.2:3B 用 7.47 秒答對婚假事實。這不能取代完整 RQ1：Qwen3.5:4B 的實際 M2 專案題仍 timeout；Granite 3B 雖通過一題 pilot，卻花 146 秒且輸出冗長、混入無關規定。

## 重要限制與下一步

專案的 [`Ollama provider`](../core/providers/llm/ollama.py) 對 `/api/generate` 沒有傳 `think` 參數。Ollama API 支援為 thinking 模型明確設定 `think:false`，但短 prompt 成功不足以證明 RAG 長上下文也會改善。本輪 `think:false` 只用於單題 pilot，並非可與完整 baseline 比較的全題結果。

建議下一輪先加入可設定的 thinking 控制，讓 baseline 和候選使用完全相同設定，再重跑 10 題 × 3 跑；通過後再以預設 `both/K` 路徑驗證。判斷門檻應同時看法規數字／條件完整性、Type-E 拒答、可見推理／離題內容、timeout 比率及 p50 延遲，不能只看 atomic score。

## 原始結果

- [Qwen2.5:7B baseline 摘要](model_cmp_20260921_qwen25_m2/summary.md)
- [Qwen2.5:7B baseline manifest](model_cmp_20260921_qwen25_m2/manifest.json)
- [Qwen3.5:9B 初篩 records](model_cmp_20260921_qwen35_9b_m2/records.json)
- [Granite 4.2:8B 初篩 records](model_cmp_20260921_granite42_8b_m2/records.json)
- [Qwen3.5:4B 初篩 records](model_cmp_20260921_qwen35_4b_m2/records.json)
- [Granite 4.2:3B 初篩 records](model_cmp_20260921_granite42_3b_m2/records.json)
- [Qwen3.5:4B think-off RQ1 pilot](model_cmp_20260921_qwen35_4b_thinkoff_pilot/summary.md)
- [Granite 4.2:3B think-off RQ1 pilot](model_cmp_20260921_granite42_3b_thinkoff_pilot/summary.md)
