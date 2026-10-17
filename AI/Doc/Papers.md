# 論文紀錄（打敗大盤計畫的文獻基礎）

**建立：** 2026-10-14（Iteration 66）
**用途：** 每一篇都寫「它說什麼」「對這個專案的意思」「狀態」。新實驗必須能指回這裡的一條；狀態只有
`已測 #n`（指 `portfolio_runs.experiment_n`；預測模型那一側寫 `已測（Iteration NN）`）、`已採用`（已在引擎裡）、`待測`（有設計、還沒跑）、`待資料`（資料不在庫裡）、`不測`（寫理由）。
搜尋方式：WebSearch（第一批 2026-10-14：P1～P24；第二批 2026-10-15：P25～P46，第八節），只讀到摘要與二手整理的，在「來源」欄標「摘要」；全文沒讀過的數字不引進迭代紀錄。

對手與門檻（`.claude/rules/portfolio.md`）：0050 含息；年化主動 ≥ +3%、IR ≥ 0.5、DSR ≥ 0.95。目前正式策略 `win3+mom-t3-tsmcest`（#44），保留期 #69 年化主動 −6.1%。

## 一、台股月營收與營收動能

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P1 | （**所有用營收表的訊號共用的 caveat，Iteration 68 量到**：`signal_sue` 不檢查公告日 ≤ 訊號日，2024-04 起有精確公告日的月份有 10.4% 股票月反應日晚於訊號日）Hung, W., Lu, C.-C., & Yang, J. J. (2025). Market reaction to monthly revenue momentum. *Review of Quantitative Finance and Accounting*, DOI 10.1007/s11156-025-01434-0（線上 2025-06-21；RePEc 列 66(4), 1411–1433）。[Springer](https://link.springer.com/article/10.1007/s11156-025-01434-0)（摘要） | 用台股強制月營收，**營收年增率（YoY）本身**有動能，且與季報獨立；年增率「持續」的股票獲利更高，套利成本高的股票更明顯 | 我們測過的是驚喜（`sue`，#1）、加速（`rev_accel`，#45/#54）、連續（`rev_streak`，#46/#55），**沒測過 YoY 水準**。新訊號 `rev_yoy3`（最近三期 YoY 平均） | 已測 #73（dev −2.77%）：單獨不行；見 P2 的組合 |
| P2 | Chen, H.-Y., Chen, S.-S., Hsin, C.-W., & Lee, C.-F. (2014). Does revenue momentum drive or ride earnings or price momentum? *Journal of Banking & Finance*, 38, 166–185. [IDEAS](https://ideas.repec.org/a/eee/jbfina/v38y2014icp166-185.html)（摘要）；前身工作論文 Chen, Chen & Hsin (2009) *Price, Earnings, and Revenue Momentum Strategies* [PDF](http://pbfea2005.rutgers.edu/TaipeiPBFR&D/990515Papers/6-3.pdf) | 營收驚喜與盈餘驚喜合起來約解釋價格動能的 19%；三種動能**合併**的策略月報酬最高（工作論文摘要寫到 1.57%/月） | 支持「營收類＋價格動能」的組合方向——這正是 Iteration 53 唯一跨段一致的家族（`rev_accel+mom`、`win3+mom+rev_streak`）。本輪再加一個 `win3+mom+rev_yoy3` | 已測 #74（dev +8.58%，候選 +8.64%）、#77（valid +13.80%，候選 +15.71%）：沒有增量 |
| P3 | Lai, C.-C., Tsai, W.-H., Lin, Y.-N., & Lin, A. Y. (2026). Trading on record-breaking monthly revenue announcements. *Journal of Behavioral and Experimental Finance*（[ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S154461232600440X)、[SSRN 5345252](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5345252)）（摘要） | 創新高營收公告：公告前漲多的次日開盤**放空**有異常報酬（過度反應）；公告後買進持有 20 日有漂移（PEAD） | 我們的 `win`／`win3` 就是公告窗口反應；「公告前漲多→反轉」是 `rev1m` 的方向（#49/#58 不行）。可考慮「營收創新高」布林訊號，但沒有新資料欄位，先不測 | 不測（單一事件型訊號、月調倉抓不到 20 日持有） |
| P4 | Wang, C.-M., & Lien, M.-Y. (2022). 修正版 MAX 效果：漲停頻率（limit-hitting rate）高的股票之後報酬低，與月營收正向驚喜同時出現時散戶更不愛。*Journal of Risk and Financial Management*（摘要，見 [NCCU 論文庫](https://thesis.lib.nccu.edu.tw/thesis/detail/42280e83f7550215ef6c86d581dedb4b)） | 台股的 MAX／漲停效應（樂透型股票之後表現差），小型股最明顯 | 引擎已經排除「過去 20 日漲停次數前 10%」（`excl_limit_pct`） | 已採用（Iteration 49 起） |
| P5 | Fu, H., & Wood, A. (2010). Momentum in Taiwan: seasonality matters! *Applied Economics Letters*, 17(13), 1247–1253. [Taylor & Francis](https://www.tandfonline.com/doi/full/10.1080/00036840902917589)（摘要） | 台股動能只在年報截止後幾個月出現；其他月份反而是反向策略有效，農曆年與中秋前後最明顯 | 動能有季節性 → 可做「月份閘門」。但摘要沒寫清楚是哪幾個月，依摘要猜月份等於挑參數 | 待測（要先讀全文確定月份定義） |

## 二、動能的狀態依賴與殘差動能

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P6 | Cooper, M. J., Gutierrez, R. C., & Hameed, A. (2004). Market States and Momentum. *Journal of Finance*, 59(3), 1345–1365.（摘要） | 1929–1995 美股：市場過去三年報酬為正（UP）後動能月均 +0.93%，為負（DOWN）後 −0.37% | 動能只該在 UP 市場用 | 已測 #75（一年期：dev +5.17%／IR 0.413，反效果）、#81（三年期：2018–2024 一次都沒觸發，與 #30 相同）；家族關閉（Iteration 67）。驗證期的 0050 一年／三年狀態已看過（結果檔第二節），之後任何閘門變體的 valid 都不算乾淨 |
| P7 | Du, D., Huang, Z., & Liao, B.-S. (2009). Why is there no momentum in the Taiwan stock market? *Journal of Economics and Business*, 61(2), 140–152. [IDEAS](https://ideas.repec.org/a/eee/jebusi/v61y2009i2p140-152.html)（摘要） | 台股沒有動能，不是文化（Chui–Titman–Wei）而是**DOWN 市場更常出現、DOWN 之後動能更負**（Cooper 等人的狀態依賴） | 直接支持 P6 的閘門用在台股；也解釋為什麼單獨 `mom` 在開發期只有 +0.33%（#21）。閘門定義：0050 過去 252 日報酬 ≥ 0 為 UP（文獻三年；事前決定先用一年，為了和候選同一載入範圍、不暖機；三年期是同一假設家族的第二次抽樣） | 已測 #75（同 P6）：閘門關掉的 8 個月（2018-10～2019-03、2019-08～09），候選 #30 在 2018-10～2019-03 六個月的主動報酬全為正、合計比 #75 多 4.3 pp（結果檔第三節）；三年期版本 #81 用 0050 長歷史算，開發期與驗證期三年報酬最低 +22.6%，沒有 DOWN；家族關閉（Iteration 67） |
| P8 | Chui, A. C. W., Titman, S., & Wei, K. C. J. (2010). Individualism and Momentum around the World. *Journal of Finance*, 65(1), 361–392. [IDEAS](https://ideas.repec.org/a/bla/jfinan/v65y2010i1p361-392.html)（摘要） | 個人主義指數低的市場（台灣 17 對美國 91）動能利潤不顯著 | 台股的價格動能不能照搬；要靠基本面／公告反應來補（P1、P2） | 不測（背景） |
| P9 | Blitz, D., Huij, J., & Martens, M. (2011). Residual momentum. *Journal of Empirical Finance*, 18(3), 506–521. [EUR](https://repub.eur.nl/pub/22252)（摘要＋二手整理） | 用因子迴歸殘差算動能（過去 36 個月三因子迴歸，殘差 12-1 累積除以標準差）：因子暴露降一半、風險調整後報酬約兩倍；Huij & Lansdorp (2017) 全球樣本外成立 | 我們的 `mom` 用「減 0050」等於硬設 β = 1，高 β 股票在多頭會被當成強勢。新訊號 `resmom`：對 0050 做 252 日 OLS，殘差 12-1 累積 ÷ 殘差標準差。預期：追蹤誤差下降、IR 上升 | 已測 #78（單獨 dev +4.08%／TE 11.9%，`mom` #70 +5.96%／13.6%：TE 降、報酬更低）、#79／#80（`win3+resmom` dev +7.49%／valid +16.30%：跨段過門檻，開發期低於候選）；#71／#72／#76 是帶截距的錯版（一個月殘差反轉，tag=void）。**注意：這個家族的驗證期看了兩次**（#76 錯版、#80 修正版），#80 不算乾淨的一次性確認 |
| P10 | Daniel, K., & Moskowitz, T. J. (2016). Momentum crashes. *Journal of Financial Economics*, 122(2), 221–247. [Columbia PDF](https://business.columbia.edu/sites/default/files-efs/pubfiles/4607/mom11.pdf)（摘要） | 動能崩盤發生在大跌後、高波動、市場反彈時；用預測的動能均值／變異動態調整，Sharpe 約翻倍 | 和 P6 同一方向；波動管理版本要挑一個尺度常數，在開發期挑一次 | 待測（要先設計「現金腿」，引擎目前永遠滿倉） |
| P11 | Novy-Marx, R. (2015). Fundamentally, Momentum is Fundamental Momentum. NBER WP 20984. [NBER](https://www.nber.org/papers/w20984)（摘要） | （美股，季報盈餘驚喜）盈餘驚喜在橫斷面迴歸吸收掉過去報酬的解釋力；控制盈餘驚喜後價格動能報酬大減；盈餘動能用過去報酬當條件可去掉崩盤 | 台股月營收就是最高頻的「基本面驚喜」。支持把營收訊號和價格動能**互為條件**，不只是排名平均。目前 `sue` 單獨在全市場不行（#1），但 `rev_accel+mom` 行（#53/#62） | 已測 #82（`win3+momrev`：當月 SUE > 0 才算動能，dev +4.69%／IR 0.38，候選 +8.64%／0.67；候選池中位數 266 → 116 檔）：當條件沒有增量，家族關閉（Iteration 68）；`sue` 單獨已測 #1 |
| P12 | Moreira, A., & Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance*, 72(4), 1611–1644.（二手；注意 Liu et al. 2019 指出常數用全樣本選有前視） | 用上月已實現變異的倒數縮放部位，Sharpe 提高 | 同 P10；常數只能在開發期定 | 待測（同 P10） |

## 三、交易成本、組合建構、資料探勘風險

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P13 | Novy-Marx, R., & Velikov, M. (2016). A Taxonomy of Anomalies and Their Trading Costs. *Review of Financial Studies*, 29(1), 104–147. [NBER w20721](https://www.nber.org/papers/w20721.pdf) | 23 個異象分低／中／高換手；**buy/hold spread**（進場門檻比續抱門檻嚴）是最有效的降成本法；月單邊換手 < 50% 的大多淨報酬仍顯著 | 引擎的「緩衝區」（前 20 持有、前 40 續抱）與「分批輪動」就是這個；Iteration 50 量過換手 13–20 倍 → 3–4 倍 | 已採用（#5–#13 測換手） |
| P14 | Frazzini, A., Israel, R., & Moskowitz, T. J. (2018). Trading Costs. SSRN 3229719；前身 (2015) Trading Costs of Asset Pricing Anomalies.（二手） | 實盤成交資料估的成本比學術假設低很多；規模、價值、動能都能撐過成本 | 我們的成本假設（手續費 0.0855%、稅 0.3%、滑價 0.15%／0.3%）偏保守，是對的方向 | 不測（背景） |
| P15 | Bailey, D. H., & López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality. *Journal of Portfolio Management*, 40(5), 94–107. | 依試驗次數 N、報酬偏態峰態把 Sharpe 打折；N 要**誠實累計** | `dsr.py` 已照做；候選 DSR 0.13 的意思是「69 次試驗下這個 Sharpe 不稀奇」。本輪每一條假設都是 N+1，所以要少而有理由 | 已採用 |
| P16 | López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley, ch. 7（purged／embargoed CV、CPCV）、ch. 11（PBO） | 時間序列交叉驗證要清除重疊與加禁運期；CPCV 多條路徑估「回測過擬合機率」 | 我們用固定三段（開發／驗證／保留）。未來若做 ML 選股（P17），要用 CPCV 不是 K-fold | 待測（P17 時才用） |
| P17 | Gu, S., Kelly, B., & Xiu, D. (2020). Empirical Asset Pricing via Machine Learning. *Review of Financial Studies*, 33(5), 2223–2273. DOI 10.1093/rfs/hhaa009 | 樹模型與神經網路最好，優勢來自非線性交互；所有方法都同意主要訊號是動能、流動性、波動的變體 | 開發期只有 48 個月橫斷面，ML 會過擬合；先把線性排名平均做好。可借的是「動能 × 流動性 × 波動」的交互 | 不測（樣本太短） |

## 四、籌碼（法人）資料

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P18 | 台股外資買賣超與報酬：Springer 章節 *Dynamic Interactions Between Institutional Investors and the Taiwan Stock Returns*（VAR／門檻 VAR）；*Volatility of order imbalance of institutional traders and expected asset returns: Evidence from Taiwan*（ScienceDirect）；*Do informed option investors predict stock returns? Evidence from the Taiwan stock exchange*（ScienceDirect）（皆摘要） | 外資淨買超領先本土法人、在某些狀態領先報酬；外資委託不平衡對指數報酬有預測力；結論隨市場狀態與期間變 | 全市場三大法人買賣超原本**不在庫裡**（`stock_foreign_holding` 只有 26 檔）。Iteration 71 改走交易所官方檔（證交所 T86＋櫃買 insti/dailyTrade，不吃 FinMind 額度）建 `market_institutional_daily` | 已測 #93（`fflow` 單獨 dev −0.03%，追蹤誤差 7.3%；持股流動性名次中位數 153、不是權值股，原因沒量到）、#94（`win3+mom+fflow` dev **+10.33%／0.875** 超過候選）、#96（valid +14.34%／1.054 低於候選 #38 1.4 pp、IR 亦低；追蹤誤差與落後較小但差距不足以當理由）；`fflow` 與 `mom` ρ 0.06、持股交集 11／20；投信 `tflow` #95 沒過門檻（Iteration 73） |

## 五、這一輪從文獻推出的假設（事前登記，Iteration 66）

每條一跑、不調參，結構固定為候選的結構（分三批、持台積電估計權重、流動性前 300、前 20 等權）：

| 假設 | 來源 | 設定 | 對照 | 預期變好的指標 |
|---|---|---|---|---|
| H1 殘差動能比「減 0050」的動能好 | P9 | `resmom-t3-tsmcest` 對 `mom-t3-tsmcest`（後者之前沒跑過，補一次當對照） | 同結構的 `mom` | 追蹤誤差↓、IR↑ |
| H1b 候選裡的 `mom` 換成 `resmom` | P9 | `win3+resmom-t3-tsmcest` | #30／#38 | IR↑ |
| H2 營收 YoY 水準有動能 | P1、P2 | `rev_yoy3-t3-tsmcest`；`win3+mom+rev_yoy3-t3-tsmcest` | #46／#55（rev_streak）、#30／#38 | 年化主動↑ |
| H3 動能只在 UP 市場用 | P6、P7 | `win3+mom~up-t3-tsmcest`（DOWN 時只剩 `win3`） | #30／#38 | 相對最大落後↓、IR↑ |

跑法：`cd Crawler && python portfolio_search.py --grid ../AI/experiments/iter66_grid.json --segment dev`；開發期過門檻（年化主動 ≥ 3%、IR ≥ 0.5）的才跑一次 valid。

**結果（2026-10-14，N 70～80）：** 三條都沒超過候選。H1 追蹤誤差降但報酬更低；H1b 修正版兩段都過門檻但開發期低於候選，且驗證期已被錯版 #76 消耗一次；H2 單獨負、組合無增量；H3 反效果。
結果檔 `UnifiedModel/results/portfolio_iter66_papers.md`，讀法見 `AI/Doc/Iterations/Iteration-66.md`。

**不登記的觀察：** #72／#76（錯版）事實上就是「一個月殘差反轉」在 dev／valid 的結果（dev +10.30%／0.849、valid +8.54%／0.665，valid 低於候選）。兩段都已被看過，視同已測、**不登記、不重跑**。

### 第二代（Iteration 67，2026-10-15）

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H4 三年期市場狀態閘門（P6 第二次抽樣） | P6、P7；事前登記 `AI/experiments/iter67_hypothesis.md` | `win3+mom~up3-t3-tsmcest`，0050 長歷史另載 | #30、#75 | #81 與 #30 完全相同：三年期在 2018–2024 零次 DOWN（最低 +22.6%）；valid 不跑；家族關閉 |

### 第三代（Iteration 68，2026-10-15）

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H5 以營收驚喜為條件的動能 | P11；事前登記 `AI/experiments/iter68_hypothesis.md` | `win3+momrev-t3-tsmcest`（`momrev`＝`mom` 只給當月 SUE > 0 的股票） | #30、#53、#70 | #82 dev +4.69%／IR 0.38，低於候選、沒過 IR 門檻；valid 不跑；候選池中位數 266 → 116；家族關閉 |

### 第四代（Iteration 69，2026-10-15；文獻第二批）

valid 的規則從本代起收緊：只給「開發期過門檻**且年化主動或 IR 超過 #30**、tests 已過」的設定（過門檻但不會成為候選的，跑 valid 只耗 N）。

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H6 資訊連續性（相加） | P25、P33；事前登記 `AI/experiments/iter69_hypothesis.md` | `win3+mom+cont-t3-tsmcest`（`cont`＝12-1 窗口內異常報酬為正的天數比例減為負的） | #30 | #83 dev +6.49%／IR 0.515：過門檻、低於候選；valid 不跑 |
| H7 日內動能 | P29（台灣）、P26 | `win3+imom-t3-tsmcest`（`imom`＝12-1 窗口內日內異常報酬累積） | #30、#70 | #84 dev +7.00%／0.628、追蹤誤差 11.2%、相對最大落後 −11.5%（都比候選好），但年化主動與 IR 低於候選；valid 不跑。拿掉隔夜那一半報酬略降（單次相減，`omom` 未跑） |
| H8 中期動能 12-7 | P30 | `win3+mom127-t3-tsmcest` | #30 | #85 dev +3.07%／0.253：沒過 IR 門檻 |

### 第五代（Iteration 70，2026-10-15）

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H9 隔夜報酬的一個月短期持續 | P28（台灣）、P27；事前登記 `AI/experiments/iter70_hypothesis.md` | `win3+mom+ovn1m-t3-tsmcest`（`ovn1m`＝最近 21 日隔夜異常報酬累積） | #30 | #86 dev +6.31%／0.493：沒過 IR 門檻；加上 H7，隔夜／日內拆解家族關閉 |
| H10 Amihud 非流動性 | P35 | `win3+mom+illiq-t3-tsmcest`（`illiq`＝252 日 \|日報酬\| ÷ 成交金額 平均取 log） | #30、#38、#53、#62 | #87 dev **+11.09%／0.847**（19 次文獻試驗裡第一條有效實作在開發期超過候選；錯版 #72 不計）；#88 valid +14.14%／0.98 過年化主動與 IR 門檻（DSR 0.488 未達 0.95）但低於候選 #38（+15.71%／1.085）；前 20 持股流動性名次中位數 80 → 152；開發期優勢集中在 2021（+9.2% 對 +1.6%）；候選不換（使用者決定） |

### 第六代（Iteration 72，2026-10-15）

valid 規則統一為「過門檻且年化主動與 IR **兩項都**超過 #30」。

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H11 產業動能相加 | P47；事前登記 `AI/experiments/iter72_hypothesis.md` | `win3+mom+indmom-t3-tsmcest`（`indmom`＝同產業 `mom` 等權平均，≥ 5 檔） | #30 | #89 dev +7.89%／0.624：過門檻、低於候選；valid 不跑 |
| H12 扣掉產業的個股動能 | P48 | `win3+relmom-t3-tsmcest`（`relmom`＝`mom` − `indmom`） | #30、#38 | #90 dev **+10.12%／0.785**（兩項超過候選）；#92 valid +15.19%／1.07 對候選 +15.71%／1.085 持平、相對最大落後較小；與 `mom` ρ 0.95、前 20 重疊 18；最大產業占比最大值 60% → 45%；候選不換（使用者決定） |
| H13 同月季節性（1～3 個 lag） | P31、P49 | `win3+mom+seas-t3-tsmcest` | #30 | #91 dev +0.37%／0.03：沒過門檻；在 1～3 年歷史下沒有增量，等資料累積 |

### 第七代（Iteration 73，2026-10-16；法人買賣超，Iteration 71 的表）

事前登記 `AI/experiments/iter73_hypothesis.md` 寫於 2026-10-15 23:20（回補到 2021-01 時）、看任何法人數字之前。

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H14 外資淨買超（單獨） | P18、P44 | `fflow-t3-tsmcest`（`fflow`＝21 日外資淨買超金額占成交金額比例） | #30、#70 | #93 dev −0.03%／−0.004、追蹤誤差 7.3%：無訊息（持股流動性名次中位數 153、前 50 名 12%，不是權值股；追蹤誤差低的原因沒量到） |
| H14 外資淨買超（相加） | P18、P44 | `win3+mom+fflow-t3-tsmcest` | #30、#38 | #94 dev **+10.33%／0.875**（兩項超過候選）；#96 valid +14.34%／1.054（低於候選 1.4 pp、IR 低 0.03；追蹤誤差與落後兩段都較小）；ρ(mom, fflow) 0.06、持股交集 11／20——獨立訊號；候選不換（使用者決定） |
| H15 投信淨買超（相加） | P18 | `win3+mom+tflow-t3-tsmcest` | #30 | #95 dev +4.23%／0.346：沒過門檻，家族關閉 |

### 第八代（Iteration 78，2026-10-17；文獻第三批，第九節）

事前登記 `AI/experiments/iter78_hypothesis.md` 寫於 2026-10-17 20:20（mtime，`checks.json` `iter78-prereg-mtime`）、跑網格之前。

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H16 波動率調整動能 | P51、P52、P57 | `win3+vmom-t3-tsmcest`（`vmom`＝`mom` ÷ 同 12-1 窗口日異常報酬標準差，取代 `mom`） | #30 | #97 dev +7.92%／0.627：過門檻但兩項都低於候選（+8.64%／0.67）；追蹤誤差 12.6% 對 12.9%、相對最大落後 −15.7% 對 −14.7%——風險調整後沒有改善；valid 不跑 |
| H17 去極端波動的動能 | P52、P53、P56 | `win3+momx-t3-tsmcest`（`momx`＝`mom`，同窗口波動全市場最高十分位不給值） | #30 | #98 dev +6.94%／0.578：過門檻但低於候選；相對最大落後 −12.8%（候選 −14.7%）、追蹤誤差 12.0% 是唯一改善的地方，報酬少 1.7 pp；valid 不跑 |
| H18 價值（殖利率、益本比） | P58、P59、P60 | 資料前置：`market_valuation_daily`（交易所 BWIBBU_d＋櫃買 peQryDate，Iteration 78 建表回補） | — | 不算 N；訊號 `dy`、`ep` 等回補完、覆蓋率看過後下一代登記 |

### 第九代（Iteration 80，2026-10-17；價值，Iteration 78 的估值表）

事前登記 `AI/experiments/iter80_hypothesis.md` 存檔於 2026-10-17 22:55（`checks.json` `iter80-prereg-mtime`、`iter80-prereg-sha256`），跑網格（22:55:57）之前、只看過估值表的列數與分佈。

| 假設 | 來源 | 設定 | 對照 | 結果 |
|---|---|---|---|---|
| H19 殖利率（單獨） | P59、P60 | `dy-t3-tsmcest`（交易所殖利率，> 30% 不給值） | #30、#70 | #99 dev +4.12%／0.542（含候選未進場的 2018-03～10 與櫃買殖利率前視；共同窗口 2018-11-12 起 +3.63%／0.622、2019 起 +2.34%／0.392 未過門檻），相對最大落後 −7.2% 是開發期 run 裡最小、追蹤誤差 7.6%，年化主動低於候選；valid 不跑 |
| H19 殖利率（相加） | P58 | `win3+mom+dy-t3-tsmcest` | #30 | #101 dev +4.86%／0.431：沒過 IR 門檻、低於候選；加進去反而拉低動能 |
| H20 益本比（單獨） | P59 | `ep-t3-tsmcest`（1 ÷ 本益比，虧損股沒有值） | #30、#70 | #100 dev −3.33%／−0.401：反向，相對最大落後 −21.8% |
| H20 益本比（相加） | P58 | `win3+mom+ep-t3-tsmcest` | #30 | #102 dev +0.29%／0.027：沒過門檻 |

## 六、下一輪可登記的假設（還沒跑，不算 N）

| 候選假設 | 來源 | 要先做的事 |
|---|---|---|
| 動能 × 週轉率（低週轉率的贏家） | P32 | 要流通股數（FinMind `TaiwanStockShareholding` 或月報）才算得出週轉率 |
| 動能 × 流動性 × 波動的交互（非線性） | P17 | 先做簡單的二維分組，不做 ML；`illiq`（#87）已經是一維的流動性傾斜 |
| 動能季節性（年報截止後的月份） | P5 | 先讀全文確定月份定義 |
| 波動管理／時間序列動能的現金腿 | P10、P12、P42、P43 | 引擎要先能持現金；尺度常數只在開發期定一次 |
| 散戶融資餘額變動（反向） | P62 | 要先補全市場融資融券餘額表（證交所 MI_MARGN、櫃買融資融券餘額），同交易所檔路線 |

已關閉的家族（不再登記）：價值（交易所估值：殖利率 `dy` #99／#101、益本比 `ep` #100／#102；B/M 依 P59／P64 不試）、波動處理的動能（P51～P53、P56、P57：`vmom` #97、`momx` #98 都低於候選；`lowvol` 相加 #51／#60 亦然）、動能缺口閘門（P54；台灣證據為負 P55）、投信淨買超（P18，#95）、外資淨買超單獨（#93）、產業動能相加（P47，#89）、同月季節性（P31／P49，#91；1～3 個 lag 下沒有增量，等資料累積到 ≥ 5 年再看）、市場狀態閘門（P6／P7／P33）、以營收為條件的動能（P11）、隔夜／日內拆解（P26～P29；`imom` #84 與 `ovn1m` #86 都低於 `mom`，`omom` 反向訊號**未測、依判斷關閉**）、中期動能 12-7（P30；6-2 未跑）、資訊連續性相加（P25）。

## 七、預測模型（LSTM、跳空、波動率、新聞）的文獻

這些模型不是正式策略，但儀表板還在用；每篇對照專案自己的結論（Iteration 13／16／28／30／32／40／47）。

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P19 | Fischer, T., & Krauss, C. (2018). Deep learning with long short-term memory networks for financial market predictions. *European Journal of Operational Research*, 270(2), 654–669. DOI 10.1016/j.ejor.2017.11.054（摘要） | LSTM 用 S&P 500 成分股的落後報酬做隔日方向，2010 年以後優勢大幅衰退 | 和 Iteration 11（10 個 LSTM 等同天真基準）、Iteration 12（最佳 59.89%、出手率 5%）一致：單靠價格序列的 LSTM 沒有可持續的 edge。不再投入 LSTM 架構調整 | 已測（Iteration 11／12／28，否決） |
| P20 | Krauss, C., Do, X. A., & Huck, N. (2017). Deep neural networks, gradient-boosted trees, random forests: Statistical arbitrage on the S&P 500. *EJOR*, 259(2), 689–702. DOI 10.1016/j.ejor.2016.10.031（摘要） | 樹模型與集成在橫斷面統計套利上不輸深度網路，且較穩 | 專案的 M3 籌碼模型（Random Forest）、M2 新聞（XGBoost）走的是這條；Iteration 40 的 28 個新聞模型裡樹融合也沒輸給深度模型 | 不測（背景） |
| P21 | Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*, 7(2), 174–196.（二手） | HAR-RV：日／週／月（1、5、22 日）三個尺度的已實現波動線性組合，OLS 就能估，常贏 GARCH | 波動率模組（Iteration 13）用相關 0.606 贏 EWMA；美股版（Iteration 32）QLIKE 輸 EWMA 被否決。HAR-RV 是下一個該比的基準：三個尺度、無調參 | 待測（波動率模組對 HAR-RV，QLIKE 為準） |
| P22 | Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246–256.（二手） | 波動率預測只能用 MSE 與 QLIKE 這類「代理穩健」的損失比；QLIKE 不對稱，偏好高估 | Iteration 13／32 立的門檻「QLIKE 須先優於 EWMA」有文獻根據 | 已採用 |
| P23 | De Gooijer, J. G., Diks, C., & Gatarek, Ł. T. (2012). Information flows around the globe: predicting opening gaps from overnight foreign stock price patterns. *Central European Journal of Economic Modelling and Econometrics*（[UvA](https://dare.uva.nl/id/04d37c34-b9af-4a1a-8a51-8014a632f819)，摘要） | 用海外市場隔夜價格型態預測開盤跳空，非參數模型最好；效果主要來自歐亞市場 | 專案的跳空模型（Iteration 16：方向 67.3%；Iteration 28 加台指期夜盤 72.24%）同一機制；文獻說非線性有增量，但 Iteration 30 的巢狀走查否決了 v2 之後的升級（自身＋全部，外樣本 −0.0013），v2 維持不動 | 已測（Iteration 16／28／30） |
| P24 | Tetlock, P. C. (2007). Giving Content to Investor Sentiment: The Role of Media in the Stock Market. *Journal of Finance*, 62(3), 1139–1168. [SSRN](https://papers.ssrn.com/abstract=685145) | 媒體悲觀度預測短期下壓再回復；主要是市場層級、小幅 | Iteration 40：28 個新聞模型隔日方向 AUC 0.50～0.53，新聞增量 +0.004～0.007；Iteration 47 只有事件波動模型過關。和文獻一致：新聞對方向的訊息很小、對波動有 | 已測（Iteration 39／40／47） |

## 八、文獻第二批（Iteration 69，2026-10-15 WebSearch；全部只讀到摘要與二手整理）

挑選原則：能用現有 `market_daily_prices`（開盤、收盤、還原收盤、成交金額）直接做訊號的優先；台灣樣本的優先；已採用或已測過變體的也記，免得之後重做。

### 八之一、動能的結構：資訊連續性、日內／隔夜、形成期

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P25 | Da, Z., Gurun, U. G., & Warachka, M. (2014). Frog in the Pan: Continuous Information and Momentum. *Review of Financial Studies*, 27(7), 2171–2218. DOI 10.1093/rfs/hhu003。[作者 PDF](https://www3.nd.edu/~zda/Frog.pdf)、[SMU](https://ink.library.smu.edu.sg/lkcsb_research/1792)（摘要） | 投資人對連續到來的小資訊反應不足：以 ID ＝ sign(PRET) × (%neg − %pos) 分組，連續資訊的動能 5.94%、離散的 −2.07%（二手整理的數字），且連續的不反轉 | 新成分 `cont`（12-1 窗口內正天數比例減負天數比例），和 `mom` 相加 | 已測 #83（dev +6.49%／0.515，低於候選；`cont` 與 `mom` ρ 0.61）；家族關閉 |
| P26 | Lou, D., Polk, C., & Skouras, S. (2019). A tug of war: Overnight versus intraday expected returns. *Journal of Financial Economics*, 134(1), 192–213. DOI 10.1016/j.jfineco.2019.03.011。[LSE](https://eprints.lse.ac.uk/87481/)、[PDF](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)（摘要） | 美股：隔夜與日內報酬各自有持續、彼此反向；動能策略的利潤幾乎全在隔夜，其他策略在日內 | 動能可以拆成隔夜與日內兩半；哪一半有用要看市場 | 已測 #84（日內那一半，見 P29）：拿掉隔夜那一半報酬略降（單次相減、`omom` 未跑），這一跑沒有裁決本文與 P29 哪個在台股成立 |
| P27 | Aboody, D., Even-Tov, O., Lehavy, R., & Trueman, B. (2018). Overnight Returns and Firm-Specific Investor Sentiment. *Journal of Financial and Quantitative Analysis*, 53(2), 485–505. [IDEAS](https://ideas.repec.org/a/cup/jfinqa/v53y2018i02p485-505_00.html)、[PDF](https://anderson-review.ucla.edu/wp-content/uploads/2021/03/Aboody-et-al_overnight_returns_and_firmspecific_investor_sentiment_JFQA2018.pdf)（摘要） | 隔夜報酬是個股層級的情緒代理：短期持續（難估值的公司更強）、長期反轉 | 新成分 `ovn1m`（最近 21 日隔夜異常報酬累積） | 已測 #86（dev +6.31%／0.493，沒過 IR 門檻）；家族關閉 |
| P28 | Zhang, H., Tsai, W.-C., Weng, P.-S., & Tsai, P.-C. (2023). Overnight returns and investor sentiment: Further evidence from the Taiwan stock market. *Pacific-Basin Finance Journal*, 80, 102093. DOI 10.1016/j.pacfin.2023.102093。[IDEAS](https://ideas.repec.org/a/eee/pacfin/v80y2023ics0927538x23001646.html)（摘要） | **台股**：隔夜報酬短期持續、長期反轉，都來自情緒；散戶比重高的更強；隔夜報酬在很多非美市場不是好的情緒代理、在台股是 | 直接支持 P27 的訊號用在台股 | 已測 #86（同 P27）：月調倉下沒有增量 |
| P29 | Ho, H.-W., Hsiao, Y.-J., Lo, W.-C., & Yang, N.-T. (2023). Momentum investing and a tale of intraday and overnight returns: Evidence from Taiwan. *Pacific-Basin Finance Journal*, 82, 102151. DOI 10.1016/j.pacfin.2023.102151。[IDEAS](https://ideas.repec.org/a/eee/pacfin/v82y2023ics0927538x23002226.html)、[NTOU](https://scholars.ntou.edu.tw/handle/123456789/24532)（摘要） | **台股**：過去報酬拆成日內與隔夜，日內動能（IMOM）顯著為正且穩定、隔夜動能（OMOM）顯著為負，各持續約一年；IMOM 較少動能崩盤 | 候選的 `mom` 把兩半加在一起；新成分 `imom`（12-1 窗口內日內異常報酬累積） | 已測 #84（`win3+imom` dev +7.00%／0.628，追蹤誤差與落後較小但報酬與 IR 低於候選）：日內動能單獨為正且較穩，和本文對 IMOM 的描述一致；拿掉隔夜那一半報酬略降，沒重現「OMOM 為負」——但 `omom` 本身未跑，是單次相減。`omom` 反向訊號未測，依判斷關閉（見第六節） |
| P30 | Novy-Marx, R. (2012). Is momentum really momentum? *Journal of Financial Economics*, 103(3), 429–453. DOI 10.1016/j.jfineco.2011.05.003。[摘要](https://academicnewsletter.sufe.edu.cn/info/356869) | 動能主要來自形成期前 12 到 7 個月，不是最近 6 個月；大型流動股差距最大；國際指數、商品、匯率也一樣 | 新成分 `mom127`（跳過最近六個月） | 已測 #85（dev +3.07%／0.253，沒過門檻）：台股前 300 的最近六個月有訊息；家族關閉 |
| P31 | Heston, S. L., & Sadka, R. (2008). Seasonality in the cross-section of stock returns. *Journal of Financial Economics*, 87(2), 418–445. DOI 10.1016/j.jfineco.2007.02.003；國際版 Heston & Sadka (2010) *JFQA* 45(5), 1133–1160。[摘要](https://academicnewsletter.sufe.edu.cn/info/357254)、[IDEAS](https://ideas.repec.org/a/cup/jfinqa/v45y2010i05p1133-1160_00.html) | 同一支股票在同一個月份的報酬每年重複（lag 12、24、36 ……到 20 年），與規模、產業、盈餘公告無關；國際樣本成立 | 訊號 ＝ 過去幾年同月報酬的平均。全市場日線從 2018-01 起，開發期只有 1～3 年可回看 | 已測 #91（見 P49）：1～3 個 lag 下沒有增量 |
| P32 | Lee, C. M. C., & Swaminathan, B. (2000). Price Momentum and Trading Volume. *Journal of Finance*, 55(5), 2017–2069. DOI 10.1111/0022-1082.00280。[IDEAS](https://ideas.repec.org/a/bla/jfinan/v55y2000i5p2017-2069.html)、[PDF](https://www.johnhcochrane.com/s/lee_swaminathan_returns_volume_JF.pdf)（摘要） | 過去週轉率低的股票未來報酬高、高的低；週轉率預測動能的強度與持續（高量贏家反轉快）。台灣的二手證據方向不一（NCCU 2022 碩論：低週轉率報酬高；大葉大學工作論文 1993–2002：高週轉率動能更強） | 週轉率 ＝ 成交股數 ÷ 流通股數，流通股數不在庫裡（`stock_foreign_holding.shares_issued` 只有 26 檔） | 待資料 |
| P33 | Galvani, V. (2024). Frog in the Pan and the market-state effect on momentum. *Finance Research Letters*, 63, 105374. DOI 10.1016/j.frl.2024.105374。[IDEAS](https://ideas.repec.org/a/eee/finlet/v63y2024ics1544612324004045.html)（摘要） | 資訊連續性與動能的負向關係只在 UP 市場；DOWN 市場資訊更離散 | 等於 P25 × P6；市場狀態閘門家族已關（Iteration 67） | 不測（閘門家族已關；`cont` 單獨相加 #83 也沒增量） |

### 八之二、流動性、波動、樂透型股票

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P34 | Frazzini, A., & Pedersen, L. H. (2014). Betting against beta. *Journal of Financial Economics*, 111(1), 1–25. DOI 10.1016/j.jfineco.2013.10.005。[NBER w16601](https://nber.org/papers/w16601)、[CBS PDF](https://research-api.cbs.dk/ws/portalfiles/portal/60082899/lasse_heje_pedersen_et_al_betting_against_beta_publishersversion.pdf)（摘要）；反方 Novy-Marx & Velikov (2022) *JFE* | 槓桿受限的投資人抬高高 β 資產的價格；做多槓桿化的低 β、放空高 β 在各資產類別都有 α | 我們是 long-only、對 0050、不能槓桿：低 β 股票在多頭會落後指數。`lowvol` #47（−0.67%）、`win3+mom+lowvol` #51（+2.47%）已經是這個方向 | 不測（無槓桿；低波動變體已負） |
| P35 | Amihud, Y. (2002). Illiquidity and stock returns: cross-section and time-series effects. *Journal of Financial Markets*, 5(1), 31–56. DOI 10.1016/S1386-4181(01)00024-6。[PDF](https://www.cis.upenn.edu/~mkearns/finread/amihud.pdf)、[NYU](https://archive.nyu.edu/handle/2451/27420)（摘要）；Amihud (2019) *Critical Finance Review* 回顧仍顯著（二手） | ILLIQ ＝ \|日報酬\| ÷ 成交金額 的年平均；橫斷面上不流動的股票預期報酬高（小型股最強），時間序列上預期非流動性上升時溢酬上升 | 新成分 `illiq`（252 日 ILLIQ 取 log）；在「流動性前 300」的池子裡是往後半段偏 | 已測 #87（dev +11.09%／0.847，**超過候選**）、#88（valid +14.14%／0.98，過門檻、低於候選 #38）；持股流動性名次中位數 80 → 152；候選不換（使用者決定） |
| P36 | Gervais, S., Kaniel, R., & Mingelgrin, D. H. (2001). The High-Volume Return Premium. *Journal of Finance*, 56(3), 877–919. DOI 10.1111/0022-1082.00349。[IDEAS](https://ideas.repec.org/a/bla/jfinan/v56y2001i3p877-919.html)、[Wharton PDF](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/9901.pdf)（摘要） | 一天或一週的異常高量之後，接下來一個月報酬偏高（能見度假說） | `volchg`（20 日 ÷ 120 日成交金額）#50 是月頻率的變體，dev +0.54% | 已測（變體 #50）；不另做日／週版（月調倉抓不到一個月內的效果） |
| P37 | Kaniel, R., Ozoguz, A., & Starks, L. (2012). The high volume return premium: Cross-country evidence. *Journal of Financial Economics*, 103(2), 255–279. DOI 10.1016/j.jfineco.2011.08.012。[摘要](https://academicnewsletter.sufe.edu.cn/info/356889) | 41 國：已開發市場普遍有，新興市場較弱（二手整理說新興市場不顯著） | 同 P36，不另測 | 不測（背景） |
| P38 | Bali, T. G., Cakici, N., & Whitelaw, R. F. (2011). Maxing out: Stocks as lotteries and the cross-section of expected returns. *Journal of Financial Economics*, 99(2), 427–446. [NYU](https://archivefda.dlib.nyu.edu/handle/2451/27871)、[摘要](https://academicnewsletter.sufe.edu.cn/info/356984)；反方 Gorman 等 (2022) *CFR* 說是過度反應不是樂透偏好 | 上月單日最大報酬（MAX）高的股票之後報酬低，最低與最高十分位差 > 1%／月；控制 MAX 後 IVOL 之謎反轉 | 引擎排除「過去 20 日漲停次數前 10%」就是台股版的 MAX（P4） | 已採用（Iteration 49 起） |
| P39 | Ang, A., Hodrick, R. J., Xing, Y., & Zhang, X. (2006). The Cross-Section of Volatility and Expected Returns. *Journal of Finance*, 61(1), 259–299. DOI 10.1111/j.1540-6261.2006.00836.x。[NBER w10852](https://www.nber.org/papers/w10852)；國際版 NBER w13739 (2008)（摘要） | 相對三因子的特異波動高的股票平均報酬極低；全球都看得到 | `lowvol` #47 是總波動版本（dev −0.67%）；特異波動版本在 long-only 對 0050 的框架下和 P34 同一個問題 | 已測（變體 #47／#51）；不另做 IVOL 版 |
| P40 | Jegadeesh, N., & Titman, S. (1993). Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency. *Journal of Finance*, 48(1), 65–91. DOI 10.1111/j.1540-6261.1993.tb04702.x。[IDEAS](https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html)（摘要） | 3～12 個月形成與持有期的動能顯著；第二、三年部分反轉 | `mom`（12-1）就是它；候選 `win3+mom` 的一半 | 已採用（#21、#70、#30） |
| P41 | Asness, C. S., Frazzini, A., Israel, R., & Moskowitz, T. J. (2014). Fact, Fiction, and Momentum Investing. *Journal of Portfolio Management*, 40(5), 75–92。[AQR PDF](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/JPM-Fact-Fiction-and-Momentum-Investing.pdf)（摘要與二手整理） | 反駁十個迷思：動能不只在小型股、撐得過成本、不只靠放空、long-only 也有 | 支持我們 long-only、前 300 流動股做動能的設定 | 不測（背景） |
| P42 | Barroso, P., & Santa-Clara, P. (2015). Momentum has its moments. *Journal of Financial Economics*, 116(1), 111–120. DOI 10.1016/j.jfineco.2014.11.010。[IDEAS](https://ideas.repec.org/a/eee/jfinec/v116y2015i1p111-120.html)（摘要） | 動能的風險可預測；用已實現波動縮放部位幾乎消掉崩盤、Sharpe 近乎翻倍 | 同 P10／P12：要現金腿 | 待測（同 P10） |
| P43 | Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). Time series momentum. *Journal of Financial Economics*, 104(2), 228–250. DOI 10.1016/j.jfineco.2011.11.003。[SSRN](https://papers.ssrn.com/abstract=2089463)、[Yale PDF](https://fairmodel.econ.yale.edu/ec439/jpde.pdf)（摘要）；反方 Kim, Tse & Wald 說效果主要來自波動縮放（二手） | 58 個期貨：資產自己過去 12 個月報酬為正就做多，1～12 個月持續後部分反轉 | 要能持現金或減碼；可當 P6 閘門的替代（看 0050 自己的 12 個月報酬決定曝險）——但閘門家族已關、引擎永遠滿倉 | 待測（要現金腿；不做閘門版） |

### 八之三、台灣市場結構與 52 週高

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P44 | Barber, B. M., Lee, Y.-T., Liu, Y.-J., & Odean, T. (2009). Just How Much Do Individual Investors Lose by Trading? *Review of Financial Studies*, 22(2), 609–632. DOI 10.1093/rfs/hhn046。[IDEAS](https://ideas.repec.org/a/oup/rfinst/v22y2009i2p609-632.html)、[作者 PDF](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/justhowmuchdoindividualinvestorslose_rfs_2009.pdf)（摘要） | 台股 1995–1999 全部交易紀錄：散戶每年輸 3.8 個百分點（約 GDP 的 2.2%），幾乎全來自積極單；法人賺 1.5 個百分點，外資拿走法人利潤近半 | 法人（尤其外資）的交易方向有資訊——支持 P18 先補三大法人買賣超 | 已測（見 P18：外資淨買超相加 #94／#96 有增量、單獨 #93 沒有） |
| P45 | George, T. J., & Hwang, C.-Y. (2004). The 52-Week High and Momentum Investing. *Journal of Finance*, 59(5), 2145–2176. DOI 10.1111/j.1540-6261.2004.00695.x。[摘要](https://academicnewsletter.sufe.edu.cn/info/361244) | 現價 ÷ 52 週高點解釋大部分動能利潤，且不長期反轉 | `hi52` #48（dev +2.47%）、`mom+hi52` #52（+3.03%）已測 | 已測（Iteration 53） |
| P47 | Moskowitz, T. J., & Grinblatt, M. (1999). Do Industries Explain Momentum? *Journal of Finance*, 54(4), 1249–1290. DOI 10.1111/0022-1082.00146。[IDEAS](https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html)（摘要）；台灣二手：淡江 2011 碩論（1997–2010，三種動能都有顯著產業效果）、中央 2008 碩論（1992–2007，產業動能短中長期都顯著）[NCU](https://ir.lib.ncu.edu.tw/handle/987654321/12029) | 動能有很大一部分是產業層級的；產業動能單獨可獲利，控制產業後個股動能弱很多；一個月期最強、可持續一年 | 新成分 `indmom`（同產業 `mom` 等權平均，≥ 5 檔），`win3+mom+indmom`；`market_universe.industry_type` 上市 39 類、上櫃 32 類（**2026 年快照、沒有歷史版本**，回推 2018 是分類上的前視） | 已測 #89（dev +7.89%／0.624，低於候選）：產業動能當加分項沒有增量；產業那一塊在這個框架下是該扣的（見 P48） |
| P48 | Grundy, B. D., & Martin, J. S. (2001). Understanding the Nature of the Risks and the Source of the Rewards to Momentum Investing. *Review of Financial Studies*, 14(1), 29–78. DOI 10.1093/rfs/14.1.29。[IDEAS](https://ideas.repec.org/a/oup/rfinst/v14y2001i1p29-78.html)（摘要） | 用「個股特有」報酬成分排名比用總報酬排名更賺；產業效果與橫斷面期望報酬差異不是動能的主因（與 P47 對立） | 新成分 `relmom` ＝ `mom` − `indmom`（用產業平均當個股特有成分的代理），`win3+relmom` | 已測 #90（dev +10.12%／0.785，兩項超過候選）、#92（valid +15.19%／1.07，與候選 #38 持平、落後較小）；與 `mom` ρ 0.95（構造使然）、持股交集 18／20，#92 是候選家族的第二次抽樣；產業分類是 2026 快照（見 P47）；目前最接近候選的一組，換不換由使用者決定 |
| P49 | Keloharju, M., Linnainmaa, J. T., & Nyberg, P. (2016). Return Seasonalities. *Journal of Finance*, 71(4), 1557–1590. DOI 10.1111/jofi.12398。[NBER w20815](https://www.nber.org/papers/w20815.pdf)（摘要）；後續 Keloharju 等 (2021) *JFE*：季節性來自錯價、有反向的「其他月份」效果 | 用歷史同月報酬選股年化約 13%；異象組合、商品、國際指數、日頻都有 | 與 P31 同一假設；新成分 `seas`（前 1～3 年同調倉月累積異常報酬平均），`win3+mom+seas`。2018 起的資料只有 1～3 個 lag | 已測 #91（dev +0.37%／0.03，沒過門檻）：1～3 個 lag 下沒有增量，`seas` 與 `mom` ρ 0.16；等資料累積再說 |
| P50 | Hou, K. (2007). Industry Information Diffusion and the Lead-Lag Effect in Stock Returns. *Review of Financial Studies*, 20(4), 1113–1138. DOI 10.1093/revfin/hhm003。[IDEAS](https://ideas.repec.org/a/oup/rfinst/v20y2007i4p1113-1138.html)（摘要） | 大公司領先小公司主要發生在同產業內；壞消息反應慢的那一邊更明顯；小、冷門產業更強 | 訊號 ＝ 同產業流動性最大幾檔上個月的報酬，給其他成員；要先定義「領先股」（前 3 檔？）才能登記，門檻是參數 | 待測（下一代；先把 P47／P48 跑完） |
| P46 | Chang, C.-Y. (2011). The relationship between the 52-week high of an individual stock and stock market index level: Evidence from Taiwan. *Journal of International Financial Markets, Institutions and Money*, 21(1), 14–27. [IDEAS](https://ideas.repec.org/a/eee/intfin/v21y2011i1p14-27.html)（只有書目，摘要沒讀到）；另有 *IJBESAR* 16(1) 2023「52 週高的移動對台股動能利潤的影響」[PDF](https://ijbesar.ihu.gr/docs/volume16_issue1/16_01_07.pdf) | 台股 52 週高效應與大盤水位有關（2023 那篇：調整 52 週高的更新方式可提高動能利潤，限於效率較低的市場） | P45 的台灣證據；`hi52` 已測且弱 | 不測（背景） |

## 九、文獻第三批（Iteration 78，2026-10-17 WebSearch；全部只讀到摘要與二手整理，標「摘要」）

使用者：「現在繼續找不同種月調倉（打敗大盤），多看論文或是網路文章整理資料」。找的是**和動能排名不同種**的訊號：波動處理的動能（台股文獻）、價值（殖利率、益本比）、散戶融資、樂透股。網路文章只收有方法描述的（TEJ 因子研究），純觀點文不收。

### 九之一、波動處理的動能（台股）

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P51 | Huang, H.-H., Pan, Y.-R., & Wang, C.-P. (2026). The Performance Comparison Between Time-Series and Cross-Sectional Momentum Strategies in Taiwan Stock Market. *Journal of Risk and Financial Management*, 19(7), 462. DOI 10.3390/jrfm19070462。[MDPI](https://www.mdpi.com/1911-8074/19/7/462)（摘要；全文 403 擋） | 台股 1993-01～2025-12、1,169 檔含下市：波動縮放（volatility-scaled）的動能顯著優於一般動能；時間序列動能的報酬與風險調整後績效都高於橫斷面動能 | 橫斷面那一半 → H16 `vmom`＝`mom` ÷ 同窗口波動；時間序列那一半要現金腿（引擎沒有），和 P43 一起等 | 已登記 H16（#97） |
| P52 | Lin, C., Xia, C., Yang, N.-T., & Yang, S.-Y. (2020). Enhancing momentum profits in the Taiwan Stock Market: The role of extreme absolute strength. *Pacific-Basin Finance Journal*, 59, 101258. DOI 10.1016/j.pacfin.2019.101258。[IDEAS](https://ideas.repec.org/a/eee/pacfin/v59y2020ics0927538x19303993.html)（摘要） | 台股「沒有動能」的例外來自極端強勢股：它們波動很大、拖累動能；把它們從贏家／輸家組合拿掉後中期動能顯著、沒有動能崩盤 | 極端股的定義（P53）讀不到全文；兩篇都指出機制是高波動，所以本輪用「同窗口波動最高十分位排除」→ H17 `momx` | 已登記 H17（#98） |
| P53 | Yang, X., & Zhang, H. (2019). Extreme absolute strength of stocks and performance of momentum strategies. *Journal of Financial Markets*, 44, 71–90. DOI 10.1016/j.finmar.2019.01.001。[IDEAS](https://ideas.repec.org/a/eee/finmar/v44y2019icp71-90.html)（摘要） | 美股 1926～2015：極端絕對強度（累積報酬分佈的極端尾；二手整理寫 0～3 百分位，單尾或雙尾不確定）的股票波動極高、容易失去動能；拿掉後組合波動顯著降、多數情況平均報酬升 | 和 P52 同一個機制；本輪不用報酬尾（門檻讀不到），用波動十分位 | 併入 H17 |
| P54 | Huang, S. (2022). The Momentum Gap and Return Predictability. *Review of Financial Studies*, 35(7), 3303–3336。[IDEAS](https://ideas.repec.org/a/oup/rfinst/v35y2022i7p3303-3336..html)（摘要） | 動能缺口＝形成期（t−12～t−2）累積報酬第 75 與第 25 百分位之差，負向預測動能報酬；美國與 21 國成立；只在缺口低於第 80 百分位時做動能，Sharpe 0.78 | 是「市場狀態閘門」的另一種（P6／P7 家族已關閉）；而且台灣證據為負（P55） | 不登記 |
| P55 | Lin, C., Ko, K.-C., & Yang, N.-T. (2022). Does the momentum gap explain momentum in Taiwan? *Pacific-Basin Finance Journal*（2022-02）。[ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X22000270)（403 擋）、[二手](https://cas.xmu.edu.cn/en/info/1022/3603.htm) | 答案是否：動能缺口在台股不預測動能報酬，作者歸因於漲跌幅限制與市場參與者組成 | 閘門家族不再開；漲跌幅限制也是 P4、P53 那種「極端報酬」在台股要用波動而不是報酬尾定義的理由 | 不登記（負面證據記下） |
| P56 | TEJ 因子研究：特質波動率（2025，網路文章）。[tejwin.com](https://www.tejwin.com/en/insight/factor-research-idiosyncratic-volatility/) | 台股上市櫃 2005-01～2025-03、21 日 FF3 殘差標準差：低 IVOL 勝高 IVOL，21 日持有價差每日 −2.0 bp、IC −0.087（21D）、IC < 0 的比例 77%；作者結論是「當篩選或風險過濾比當多頭 alpha 訊號好」 | 和 `lowvol` 相加（#51／#60 低於候選）的經驗一致：單獨或相加不行，**當過濾**可能行 → 支持 H17 的「排除」而不是「相加」 | 併入 H17 |
| P57 | TEJ 波動率調整動能（VAM）策略（網路文章，LINE Today 轉載；連結未逐篇對應，[搜尋結果](https://today.line.me/tw/v3/article/eL5pGnB)） | 近 21 日累積報酬 ÷ 日報酬標準差排名，母體台灣中型 100、成交金額篩選、取前 10 等權、每月再平衡；文中沒有可核對的回測數字 | 只取定義（報酬 ÷ 波動）；窗口本輪沿用 `mom` 的 12-1 不用 21 日（那是搜參數） | 併入 H16 |

### 九之二、價值（殖利率、益本比）——要先補資料

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P58 | Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). Value and Momentum Everywhere. *Journal of Finance*, 68(3), 929–985. DOI 10.1111/jofi.12021。[PDF](https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf)（摘要） | 八個市場與資產類別都有價值與動能溢酬、共同因子結構；價值與動能負相關，合併後比各自好 | 候選是動能家族；價值是和它負相關的另一種訊號，合併（排名平均）是文獻直接支持的組合 | 已測 #101（`win3+mom+dy` +4.86%／0.431）、#102（`win3+mom+ep` +0.29%／0.027）：相加都低於候選；在這個池裡合併沒有改善 |
| P59 | Hsu, C.-H., Lee, K.-C., Chang, Y.-P., & Fung, H.-G. (2015). Value versus growth: Taiwan evidence. *Managerial Finance*, 41(8), 845–856. DOI 10.1108/MF-07-2014-0202。[Emerald](https://www.emerald.com/mf/article/41/8/845/289830)（摘要） | 台股用隨機優勢檢定：益本比（E/P）或殖利率（D/P）比淨值市價比（B/M）更好的價值代理；子樣本、不同頻率、排除金融股都成立 | 訊號用 `dy`（殖利率）與 `ep`（1 ÷ 本益比），不用 B/M；交易所每天公布這三個值 | 已測 #99（`dy` 單獨 +4.12%／0.542 過門檻、低於候選）、#100（`ep` 單獨 −3.33%／−0.401 反向）：D/P 開發期數字偏高（含櫃買前視與候選未進場的 2018-03～10）、共同窗口 2018-11-12 起 +3.63%／0.622 仍過、2019 起 +2.34%／0.392 未過、未確認；E/P 為負 |
| P60 | Liang, W.-L.（2020）。The Predictability of Stock Returns in Taiwan. SSRN 工作論文。[SSRN 作者頁](https://papers.ssrn.com/author=3570979)（摘要；二手） | 控制市場、價值、規模後，價值與現金流收益率在 1% 水準橫斷面預測台股報酬；加入 B/M、殖利率後總體變數失去顯著 | 支持 P59 的方向；工作論文，份量低 | 已測（同 P59：#99／#100） |
| P61 | Novy-Marx, R. (2013). The other side of value: The gross profitability premium. *Journal of Financial Economics*, 108(1), 1–28. DOI 10.1016/j.jfineco.2013.01.003。[IDEAS](https://ideas.repec.org/a/eee/jfinec/v108y2013i1p1-28.html)（摘要） | 毛利／資產預測橫斷面報酬的能力和 B/M 一樣好；加進價值策略後大幅改善，尤其大型流動股 | 要財報（毛利、總資產），庫裡沒有、交易所檔也沒有；要走 MOPS 季報——比估值表重很多 | 要先補財報，未登記 |

### 九之三、散戶融資、樂透股

| # | 論文 | 說的事 | 對專案的意思 | 狀態 |
|---|---|---|---|---|
| P62 | Ting, P.-H., Lu, C.-Y., & Chou, P.-H. (2018). Margin trading, differences of opinion, and stock returns. *Academia Economic Papers*, 46(3), 323–366。[CGU](https://pure.lib.cgu.edu.tw/en/publications/margin-trading-differences-of-opinion-and-stock-returns/)（摘要） | 把 Miller (1977) 意見分歧擴到融資融券：散戶融資買進對應正的錯價、之後報酬低；融券賣出相反；台股全部上市股 2006～2015 月頻率，證據強 | 「融資餘額增加」是反向訊號——和外資流量（P18）不同種的籌碼面；資料在證交所 MI_MARGN、櫃買融資融券餘額表，每日全市場，同一條交易所檔路線 | 要先補融資表（下一個資料工作） |
| P63 | Gorman, L. R., Akhtar, F., Durand, R. B., & Gould, J. (2022). It could be overreaction, not lottery-seeking, that is behind Bali, Cakici and Whitelaw's MAX effect. *Critical Finance Review*。[PDF](https://cfr.ivo-welch.info/published/papers/gorman2021could.pdf)；台灣：政大碩士論文（2024，上市櫃 2007～2022）[NCCU](https://nccur.lib.nccu.edu.tw/handle/140.119/151541) | MAX 效應（P38）是事件後的過度反應、不限於事前像樂透的股票；台灣的碩士論文說 MAX 效應顯著但**主要在小型股** | 候選池是流動性前 300，不是小型股；且 P4 的台灣版（漲停頻率）已在第一批記過；高 MAX 股在 H17 的波動排除裡大多會被拿掉 | 不登記 |
| P64 | Chen, A.-S., & Tu, E. H.（2002）。The determinants for stock returns in emerging markets: the case of Taiwan. *Studies in Economics and Finance*。[Emerald](https://emerald.com/insight/content/doi/10.1108/eb028765/full/html)（摘要） | 台股規模或 B/M 單獨都不解釋報酬，兩者合併才顯著 | 再一個「B/M 在台灣不是好代理」的證據，和 P59 一起決定不用 B/M | 不登記 |

本批 14 篇（P51～P64）。已登記假設兩條（H16、H17）、資料前置一項（H18 估值表）、下一個資料工作一項（P62 融資表）、不登記五篇（P54、P55、P61 待財報、P63、P64）。
