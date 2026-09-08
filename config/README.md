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

哪個 domain pack 生效，取決於該知識圖譜 Neo4j 節點的 `domain_pack` 屬性（預設
`taiwan-labor-law`，其 pack 檔不覆蓋任何 shipped default，等於不套包 → 行為零變化）。
未指定 / KG 查無 → 不套任何 pack。

## 如何加你自己的 domain pack

1. 在 `domain_packs/` 放一個 `<name>.json`（或 `.toml` / `.yaml`），只寫要覆蓋的鍵：
   ```json
   {
     "domain": {
       "name": "my-corpus",
       "system_context": "你是<某領域>問答助理，只根據下方事實回答…",
       "target_language": "zh-Hant"
     }
   }
   ```
   目前 `domain.system_context` / `target_language` 已接線（生成 prompt 前綴、輸出語言）；
   `svo_fewshots`、`guard_profile`（抽取少樣本、CJK 守衛）為後續步驟。

2. 把某個知識圖譜指向這個 pack —— 用既有的 KG 更新端點（同 `pronoun_lexicon_exclude`）：
   ```
   PATCH /knowledge-graphs/<kg_id>   {"domain_pack": "my-corpus"}
   ```

3. （選配）該 KG 專屬的門檻覆蓋放 `kg/<kg_id>.json`，例如 `{"bfs": {"seed_max_degree": 200}}`。

`config/domain_packs/generic.json` 是內建的領域中性範例；把 KG 的 `domain_pack` 設成
`generic` 即可讓該 KG 的生成 prompt 不綁台灣勞動法規。
