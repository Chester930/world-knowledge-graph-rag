export const narrations: string[] = [
  "除了真實 Demo，我還會保留一個可重複評估的 micro-benchmark，避免整個證明只靠現場展示。",
  "設計很簡單：五到八句可控文本、研究者制定示範用 gold triples，然後比較三種輸出。",
  "三種版本是純 RAG、未驗證 SVO、驗證後 SVO。純 RAG 沒有三元組，未驗證 SVO 可能部分正確，驗證後 SVO 才應該通過。",
  "指標先用 Precision、Recall、F1 和 Traceability，重點是把關係正確性與來源追溯都量化。",
  "但這裡要誠實說：目前證明的是可驗證，不是宣稱大規模穩定。正式實驗還要擴大資料、人工標註、錯誤類型，並接上主系統真實 SVO 輸出。",
];
