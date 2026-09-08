# `config/` —— per-KG 設定與 domain pack（報告33 §3.9 / 論文 03 §3.9、04 §4.10）

`routers/agent.py::chat()` 用 `FileConfigSource(settings.kg_config_dir)`（預設就是這個
目錄）疊在 `KGConfig` 的 shipped defaults 之上。**目錄或檔案缺 → 該層貢獻 `{}` → 退回
預設值（＝重構前的模組常數）**，行為零變化。

## 佈局

```
config/
  domain_packs/<name>.{json,toml,yaml}   # 領域包（第 3 步才會有內容）
  kg/<kg_id>.{json,toml,yaml}            # 某個知識圖譜的 per-KG 覆蓋值
```

- 副檔名分派：`.json`（一定支援）、`.toml`（Python 3.11+ 內建）、`.yaml`（需另裝 PyYAML）。
- 檔案頂層必須是 mapping，**只寫要覆蓋的鍵**（比照 Kustomize overlay）。

## 範例：`config/kg/236903cf-055a-40a8-8923-b9d06601f3b7.json`

```json
{
  "bfs": { "seed_max_degree": 200, "per_seed_limit": 60 }
}
```

未列出的鍵沿用 `KGConfig` 預設。可覆蓋的完整鍵見 `core/kg_config/model.py`。

## 疊合順序（低→高）

shipped defaults → `domain_packs/<domain_pack>` → `kg/<kg_id>` → per-request（`ChatRequest`
的 `svo_hops` / `top_k`）。
