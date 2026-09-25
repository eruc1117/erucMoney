# Iteration 40 — 新聞 + 股價 → 走勢：論文模型多模型比較

**日期：** 2026-09-24 深夜啟動，結果隔天早上看（本文件的「結果」段由 `NewsModels/run_all.py` 產出的 `AI/Doc/NewsModels.md` 為準）

## 起點

使用者：「上網找論文模型，依照新聞及股價變化訓練新模型，預測股價走勢，明天早上看結果，越多種越好」。

Iteration 38～39 已經有：三年新聞（117,891 則）、181 檔價格（追蹤 23 + 研究 159）、事件研究（媒體情緒有小訊號、
月營收公布日反應預測漂移、MOPS 為波動訊號）、M2 走查（字典特徵 + XGBoost，F1 +0.014）。這一輪換成問：
**用論文裡的文字模型，新聞能不能預測隔日方向、能贏純價格多少**。

## 文獻與對應實作（`NewsModels/nm_models.py` REGISTRY）

| 模型 | 出處 | 這裡的實作 |
|------|------|-----------|
| AZFinText | Schumaker & Chen 2009 | TF-IDF（jieba 1~2 gram）+ Logistic / Naive Bayes / LinearSVC |
| 字典情緒 | Tetlock 2007；現有 M2 | 字典分數統計 + 注意力 + 價格 → XGBoost |
| 事件驅動 CNN | Ding, Zhang, Liu, Duan 2015 IJCAI | 日事件向量（MiniLM 均值）短期／7 日／30 日三路，中長期 conv + max-pool |
| HAN | Hu, Liu, Bian, Liu, Liu 2018 WSDM「Listening to Chaotic Whispers」 | 新聞層注意力（每日 ≤ 12 則）→ bi-GRU → 日層注意力 |
| StockNet | Xu & Cohen 2018 ACL | 文字 + 價格 每日融合 → bi-GRU → 時間注意力（去掉 VAE 與 tweet 層） |
| FinBERT-LSTM | Araci 2019；Gu et al. 2024 | 中文財經情緒模型（bardsai/finance-sentiment-zh-base）日分數 + 價格 → XGBoost |
| BERT 向量 | Reimers & Gurevych 2019；arXiv 2107.08721 | paraphrase-multilingual-MiniLM-L12-v2 日向量 mean/max → Logistic / XGBoost / MLP |
| 時序 Transformer | Sawhney et al. 2020；TFT 精神 | 10 日 [向量 + 價格] Transformer encoder |
| 特徵融合 | — | 向量 PCA32 + 情緒 + 注意力 + 價格 → LightGBM |
| 基準 | — | 多數類、昨日延續、純價格 Logistic、純價格 GRU |
| 集成 | — | AUC 前三名機率平均（事後） |

文獻來源：[Stock Market Prediction via Deep Learning Techniques: A Survey](https://arxiv.org/pdf/2212.12717)、
[Stock Market Analysis with Text Data: A Review](https://arxiv.org/pdf/2106.12985)、
[Deep learning for event-driven stock prediction](https://www.semanticscholar.org/paper/44229bef9966e65e7b13c2c9fe867afd9dd8b450)、
[Listening to Chaotic Whispers (HAN)](https://www.researchgate.net/publication/321604413)、
[Predicting Stock Prices with FinBERT-LSTM](https://arxiv.org/abs/2407.16150)、
[Stock Movement Prediction with Financial News using Contextualized Embedding from BERT](https://arxiv.org/abs/2107.08721)、
[Chinese Financial News Analysis for Sentiment and Stock Prediction](https://doi.org/10.3390/bdcc9100263)、
[Integrating Taiwan financial BERT sentiment analysis with CNN-BiLSTM-SA](https://link.springer.com/article/10.1007/s10791-025-09515-3)。

## 資料與評估設計（`NewsModels/build_dataset.py`、`run_all.py`）

- 股票池 181 檔（追蹤 23 + 研究 159）。研究股的新聞在 `user_news.tickers` 裡沒有標（打標只比對 stock_info 的 26 檔），
  這裡用 FinMind 公司名 + 「（代號）」在標題與內文前 2,000 字補標，**只在研究資料集裡，不寫回 user_news**。
  標到超過 10 檔的（盤勢綜述）不算個股新聞。結果：46,408 則、31,584 個「股票 × 有新聞的交易日」樣本。
- 新聞歸屬日沿用 13:30 規則；標籤 y1 = D 收盤到 D+1 收盤的超額報酬（− 股票池等權均值）是否 > 0，正類 46.4%。
  另有 y3 / y5。
- 9 個季度 walk-forward（2024Q3 ~ 2026Q3），擴張訓練視窗，訓練與測試之間空 5 個交易日；TF-IDF、PCA、標準化都在 fold 內擬合；
  深度模型用訓練集最後 10%（時間序）早停。
- 指標：AUC、Acc、MCC、macro-F1、高信心子集準確率；交易面：每個測試日做多 P 前 20%／做空後 20% 的隔日超額報酬日均價差與 t 值。
- 前視偏誤：向量模型 MiniLM 是 2021 年的、中文財經情緒模型 2023 年前，權重不含測試期；沒有用 LLM 直接打分。

## 環境

`NewsModels/venv`：torch 2.5.1+cu121（RTX 4060）、sentence-transformers、transformers、jieba、xgboost、lightgbm。
LSTM/venv 的 TensorFlow 在 Windows 沒有 GPU，所以另建。

## 執行

```
cd NewsModels
venv/Scripts/python build_dataset.py     # 18 秒
venv/Scripts/python embed.py             # MiniLM 46k 則 + 中文財經情緒
venv/Scripts/python run_all.py           # 全部模型 → results/、AI/Doc/NewsModels.md（每完成一個模型就更新）
```

日誌 `NewsModels/logs/run_all.log`。

## 結果

完整排行榜見 `AI/Doc/NewsModels.md`（y1）、`NewsModels_y3.md`、`NewsModels_y5.md`、`NewsModels_v1.md`（程式產出，每完成一個模型就更新）。

### 第一批（17 個模型、標籤 y1，2026-09-25 00:06 跑完，全部 7 分鐘）

| 模型 | AUC | Acc | MCC | 多空日均 | t | AUC>0.5 折 |
|------|-----|-----|-----|---------|---|-----------|
| ensemble_top3（ding_cnn + fused_lgbm + transformer） | **0.531** | 0.541 | +0.049 | +0.48% | +5.9 | 9/9 |
| ding_cnn（Ding 2015 事件 CNN） | 0.528 | 0.537 | +0.037 | +0.41% | +4.8 | 9/9 |
| fused_lgbm（向量 PCA + 情緒 + 注意力 + 價格） | 0.527 | 0.537 | +0.047 | +0.44% | +5.9 | 9/9 |
| transformer（10 日時序融合） | 0.525 | 0.535 | +0.037 | +0.35% | +4.1 | 8/9 |
| stocknet_lite（Xu & Cohen 2018） | 0.524 | 0.536 | +0.036 | +0.28% | +3.3 | 8/9 |
| **gru_price（純價格）** | 0.524 | 0.538 | +0.038 | +0.29% | +3.3 | 9/9 |
| dict_xgb（字典情緒，現有 M2 做法） | 0.524 | 0.532 | +0.036 | +0.44% | +5.9 | 8/9 |
| sentzh_xgb（中文財經情緒模型） | 0.524 | 0.534 | +0.040 | +0.46% | +6.1 | 9/9 |
| **price_logreg（純價格）** | 0.524 | 0.536 | +0.032 | +0.42% | +4.7 | 8/9 |
| han（Hu 2018） | 0.521 | 0.536 | +0.032 | +0.14% | +1.6 | 8/9 |
| emb_xgb | 0.521 | 0.528 | +0.027 | +0.42% | +5.7 | 8/9 |
| emb_logreg | 0.512 | 0.519 | +0.019 | +0.21% | +3.2 | 7/9 |
| tfidf_logreg / svm / nb（AZFinText） | 0.509~0.511 | 0.52 | +0.015 | +0.15% | +2.3 | 6~7/9 |
| majority / persist / mlp_fused | 0.50 | | | | | |

### 第一批判讀

1. **全部擠在 AUC 0.50～0.53**。這是文獻在真實樣本外資料上的常態（StockNet 論文自己的 acc 0.58 是在他們的推特資料上）。
   隔日方向本來就接近不可預測。
2. **純價格就有 0.524**，新聞模型最好的 ding_cnn 0.528、集成 0.531——新聞的增量是 **+0.004～+0.007 AUC**，方向與
   Iteration 38 的 M2 走查（F1 +0.014）、Iteration 39 的事件研究（方向訊號小）一致。
3. **純文字模型（TF-IDF 三種、emb_logreg）最弱**（0.51），比純價格差；文字要跟價格特徵一起進樹模型或時序模型才有用。
   HAN 在這裡沒有優勢（0.521，且多空價差最低）——它的設計假設是「同一天很多則新聞要挑重點」，我們每檔每天中位數只有 1～2 則。
4. **多空價差是可交易的候選**：fused_lgbm / sentzh_xgb / dict_xgb 日均 +0.44～0.46%（t 5.9～6.1、勝率 59～61%），
   但純價格 Logistic 也有 +0.42%（t 4.7）——大部分來自短期反轉（ex1、ex2 特徵），不是新聞。
   扣掉台股當沖來回 0.3～0.5% 的成本後所剩無幾；要看 y3／y5 標籤的價差能不能拉開。
5. **高信心子集**：fused_lgbm 在 |P−0.5| > 0.1 的 19% 樣本上 acc 0.555，集成 7% 樣本 0.599——「只在有把握時出手」的 M2 策略在這裡也成立。

### 第二批（消融、變體、y3／y5、波動標籤；01:23 全部跑完，共 28 個模型 × 4 個標籤）

**消融（y1）**——把新聞單獨拿出來看：

| 模型 | AUC | 多空日均 | t |
|------|-----|---------|---|
| news_only_xgb（只有新聞統計：字典、則數、注意力、中文財經情緒） | **0.497** | −0.14% | −2.1 |
| emb_only_xgb（只有 MiniLM 向量） | **0.506** | +0.07% | +1.1 |
| attn_logreg（異常注意力 + 則數 + 價格） | 0.525 | +0.41% | +4.8 |
| price_logreg / gru_price / gru_price_L20（純價格） | 0.524～0.526 | +0.29～0.42% | 3.3～4.7 |

新聞內容單獨對隔日方向 **AUC 0.50**——沒有訊號。所有「新聞模型」的 0.52～0.53 幾乎全部來自它們也吃了價格特徵。
其他變體：han_L5 0.526（比 L10 的 0.521 好）、transformer_L20 0.526、et_fused 0.525、rf_fused 0.524、lr_fused 0.517。

**y3 / y5（3 日、5 日超額報酬方向）**

| 標籤 | 最佳單模型 | AUC | 集成 AUC | 集成多空（持有期）| t |
|------|-----------|-----|---------|-----------------|---|
| y1 | ding_cnn | 0.528 | 0.533 | +0.51%（1 日） | 6.2 |
| y3 | transformer | 0.528 | 0.535 | +1.05%（3 日） | 7.4 |
| y5 | sentzh_xgb | 0.527 | 0.531 | +1.08%（5 日） | 5.6 |

拉長持有期價差變大、t 值沒有變差（y3 集成勝率 64%），但 AUC 沒有提高；純價格在 y3 也是 0.525。純文字模型在 y3／y5 掉到 0.50～0.51。

**波動標籤 v1**（隔日 |超額報酬| > 近 20 日日波動 × 0.8；正類 34%）

| 模型 | AUC | 高信心 Acc（覆蓋） |
|------|-----|-----------------|
| ensemble_top3 | **0.651** | 0.715（73%） |
| gru_price（純價格） | **0.647** | 0.714（72%） |
| stocknet_lite / transformer / dict_xgb / sentzh_xgb / han | 0.638～0.643 | 0.71 |
| price_logreg | 0.628 | 0.704 |
| news_only_xgb | **0.514** | 0.661 |

波動可以預測（AUC 0.65），但**幾乎全部來自價格的波動叢聚**（GRU 純價格 0.647 是第二名），新聞內容單獨只有 0.514，
加進去也沒有超過純價格。這修正了 Iteration 39 事件研究「新聞預測波動」的讀法：事件研究比的是「有新聞的日子 vs 沒新聞的日子」，
那是**有沒有新聞**的效果；這裡每個樣本都有新聞，比的是**新聞內容**，內容對波動也沒有增量。

### 結論

1. 28 個模型 × 4 個標籤，論文架構（Ding CNN、HAN、StockNet、Transformer、FinBERT 路線、AZFinText）在這份資料上
   **隔日方向 AUC 全部 0.50～0.53，純價格 0.524**；新聞內容單獨 0.50，最好的融合模型只比純價格多 +0.004～+0.009。
   這與 Iteration 38（M2 走查 F1 +0.014）、39（事件研究方向訊號小）三次一致——**目前的新聞資料對台股隔日方向沒有可用的內容訊號**。
2. 有用的是**「有沒有新聞、多少新聞」**（異常注意力 attn_logreg 與純價格持平、事件研究的 |AR| 放大），不是新聞說了什麼。
   字典情緒、MiniLM 向量、中文財經情緒模型、TF-IDF 四種文字表示法結果一樣，問題不在表示法。
3. 可交易的部分是價格的短期反轉與波動叢聚：多空日均 +0.4～0.5%（1 日）、+1.0%（3 日）、波動 AUC 0.65，都由純價格模型提供，
   已經有的閘門模型（Iteration 13 波動率、19 振幅）就是在做這件事。
4. 跑得最快的是樹模型（幾秒），深度模型早停在 2～4 個 epoch，樣本 3 萬筆不夠深度模型發揮；HAN 論文的設定是每天幾十則新聞，這裡中位數 1～2 則。

### 下一步（使用者決定）

- **內容訊號的最後一個候選是 LLM 結構化抽取**（news_pilot：event_type / is_expected / magnitude）。四種傳統表示法都是 0.50，
  值不值得花情境 B 的 $30 跑 2～3 萬則，取決於接受「可能還是 0.50」的風險。
- **把「有沒有新聞」變成特徵**：樣本改成全部交易日（含無新聞日），用 has_news / attn 進閘門模型，這是事件研究已經證實有的訊號。
- 波動模型 v1 的 GRU（AUC 0.647）可以跟 Iteration 13 的波動率模組（相關 0.606）對比，若更好可換。
- 不建議再堆新的文字模型架構。

## 基準（框架煙霧測試，2026-09-24 23:49）

| 模型 | AUC | Acc | 多空日均 | t |
|------|-----|-----|---------|---|
| price_logreg | 0.524 | 0.536 | +0.42% | +4.7 |
| dict_xgb | 0.524 | 0.532 | +0.44% | +5.9 |

純價格已經有 0.52 的 AUC 與顯著的多空價差（短期反轉），新聞模型要贏的是這條線。
