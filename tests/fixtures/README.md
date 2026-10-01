# 測試 fixture 來源

`law_version_real_sample.json` 是報告235 P2 使用的小型真實材料，來源為姊妹專案允許讀取的：

`D:\Users\666\Desktop\labor-compliance-collector\data\processed\moj_laws\moj_history_20260819T093233Z-history.json`

- 來源檔筆數：209
- 來源檔 SHA-256：`3a8aceb9c176fb98ea6cc5cacbba0843daa46385ce08d30b538de62448129d40`
- fixture 筆數：12（N0030001 第 2、3、8 條；N0030006 第 7、9、12 條，各含 2023／1984 舊版與 2024／2025 現行版）
- `version_id`、`content_hash`、日期與狀態欄位依來源列抄錄。
- 為保持 fixture 小型，N0030006 第 12 條只保留必要法規正文與導覽標記片段；不代表完整網頁尾巴。P1 全量盤點仍直接讀來源檔，不使用 fixture 代替。

fixture 僅存放本專案內；未讀取姊妹專案的 `.env`、`.claude`、`.git`，未執行其程式，未在該專案寫入任何檔案。
