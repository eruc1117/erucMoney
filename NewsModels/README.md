# NewsModels — 新聞 + 股價 → 走勢的多模型實驗（Iteration 40）

論文模型（AZFinText、Tetlock 字典、Ding 2015 事件 CNN、HAN 2018、StockNet 2018、FinBERT 路線、BERT 向量、時序 Transformer）
在同一份資料、同一套季度 walk-forward 上比較。結果 `AI/Doc/NewsModels.md`（y1）、`NewsModels_y3.md`、`NewsModels_y5.md`。

```
NewsModels/
├── nm_config.py        路徑、日期、超參數（不能叫 config.py：Crawler/config.py 會被蓋掉）
├── build_dataset.py    user_news + stock_daily_prices + research_daily_prices → data/{news,panel,samples,open_days}.pkl
├── embed.py            MiniLM 384 維新聞向量 + 中文財經情緒分數 → data/emb_minilm.npy, sent_zh.npy
├── nm_models.py        Data 容器、特徵、17 個模型（REGISTRY）
├── run_all.py          季度 walk-forward、指標、排行榜、報告；每完成一個模型就重寫報告
├── run_overnight.bat   等 venv → embed → y1 全部 → y3 / y5 主要模型（Start-Process 獨立跑）
├── results/            <model>_<label>.json（各折 + 合併指標）、_prob.npy（機率）、leaderboard_<label>.csv
├── logs/               run_all.log、embed.log、overnight.log
└── venv/               torch 2.5.1+cu121、sentence-transformers、transformers、jieba、xgboost、lightgbm
```

用法：
```
venv\Scripts\python build_dataset.py
venv\Scripts\python embed.py
venv\Scripts\python run_all.py [--models han,ding_cnn] [--label y1|y3|y5] [--skip-done]
```

設計重點
- 樣本 = 股票 × 有新聞的交易日（181 檔、31,584 個）；研究股的新聞用公司名補標，只在這裡、不寫回 user_news。
- 標籤 = 隔日（或 3／5 日）相對股票池等權均值的超額報酬 > 0；新聞歸屬日用 13:30 規則。
- 9 個季度擴張視窗；TF-IDF／PCA／標準化在 fold 內擬合；深度模型用訓練集最後 10% 早停。
- 交易指標：每日做多 P 前 20%／做空後 20% 的隔日超額報酬價差（未扣成本）。
- 純價格 Logistic 與 GRU 是門檻；新聞模型要贏它才算有增量。
