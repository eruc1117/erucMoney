# Iteration 86 — 正式策略頁把實單列（#68）用 API 的段別名顯示：段別與標記的中文統一由 `portfolio_api` 給，兩頁不再各自寫死

**日期：** 2026-10-18
**依據：** 使用者：「實單加到正式策略中」→ 第一版把名字寫在頁面裡 → 使用者：「不要寫死的方式，用 API 動態顯示」
**規則：** 純顯示與 API 欄位，不碰回測、不寫 `portfolio_runs`（N 114 不動）、保留期未開

## 一、做了什麼

1. **問題**：月調倉頁「贏過大盤的回測」的段別篩選把 live 列（#68，正式策略每日重算）叫「實單」（`portfolio_api.SEGMENT_LABEL`），正式策略頁同一列卻叫「全期間至今（每日更新）」（頁面自己的 `SEG_LABEL`），標記 `official-live` 在清單裡又叫「正式 live」——三個地方三個名字。
2. **改法（API 動態）**：
   - `Crawler/portfolio_api.py`：段別中文 `SEGMENT_LABEL` 原本就在這裡；新增 `SEGMENT_LABEL_FULL`（候選全期間列「開發＋驗證（全期間）」——資料表裡段別是 dev，不是一個段）、`TAG_LABEL`（candidate／official／official-live／void 的中文）與 `tag_label()`；`_run_row` 每列多 `tag_label`，所以 `/portfolio/runs`、`/portfolio/candidates` 都帶。
   - `Crawler/portfolio_official.py` `status()`：`segments` 每段多 `segment`、`segment_label`、`tag`、`tag_label`（live → 實單、holdout → 保留期、full → 開發＋驗證（全期間））。
   - `Screen/src/pages/OfficialStrategy.jsx`：刪掉頁面自己的 `SEG_LABEL`，改讀 `segments[k].segment_label`（沒有才退回鍵名），只留順序 `SEG_ORDER` 與補充說明（保留期「只開一次」、實單「全期間至今，每日更新」）；各段列多印 `#experiment_n` 與 `tag_label`；標題與說明文字用 API 給的名字。
   - `Screen/src/components/BeatMarketList.jsx`：刪掉 `TAG_LABEL`，改讀 `r.tag_label`。
   - `Server/tests/helpers/fastapi-mock.js`：`/portfolio/official` 假資料的 `segments` 補上四個欄位（Node 端沒改程式，代理原樣轉）。
   - 兩個頁面同步到 `meeting_front_end/src/stock/`（改前兩檔與 Screen 一字不差）。
3. **測試**：`tests/test_portfolio_official.py` 的 `test_promote_once_and_update_in_place` 多六條斷言（full 的段別是 dev、標籤是 `SEGMENT_LABEL_FULL`；live 叫「實單」、tag `official-live` 的中文；holdout 的 tag 中文；`tag_label(None)` 是 None）。

## 二、結果

直接呼叫 `portfolio_official.status()`（本機、改後；MoneyCrawlerApi 重啟前端點還是舊的）：

| 段鍵 | run | `segment` | `segment_label` | `tag` | `tag_label` |
|---|---|---|---|---|---|
| dev | #30 | dev | 開發期 | candidate | 候選 ★ |
| valid | #38 | valid | 驗證期 | candidate | 候選 ★ |
| full | #44 | dev | 開發＋驗證（全期間） | candidate | 候選 ★ |
| holdout | #69 | holdout | 保留期 | official | 正式策略・保留期 |
| live | #68 | live | **實單** | official-live | 正式策略・實單 |

`/portfolio/runs` 的列：#67 `void` → 作廢、#68 → 正式策略・實單、#69 → 正式策略・保留期、#30／#38／#44 → 候選 ★。

| 驗證 | 結果 |
|---|---|
| `pytest-86` | `test_portfolio_official` 3 passed（含新六條斷言） |
| `pytest-86-full`、`jest-unit-86` | 283 passed（全套，36.0 秒）；Node 單元 44 passed（3 suites） |
| `vite-build-86`、`mfe-build-86` | 都過（Screen 1.57 秒；meeting_front_end 12 秒） |
| 第一版（寫死在頁面）的 `vite-build-86`／`mfe-build-86` | 被同名第二次覆蓋；第一版的程式已被第二版取代、沒留下 |

## 三、讀法

- 名字的單一來源現在是 `Crawler/portfolio_api.py` 的兩張對照表；要改中文只改那裡，三個頁面（月調倉實驗日誌、贏過大盤清單、正式策略）一起變。
- 實單列本來就在正式策略頁（三段指標表、淨值曲線、逐年、本月清單都是它），這輪只是讓它用同一個名字、並印出 run 編號與標記，沒有新的資料或計算。
- 「實單」仍是**回測引擎每天重算到最新行情的那一列**，不是紙上帳戶的實際成交曲線（頁面的說明框照舊寫明）；凱基實單未接。
- **要重啟 `MoneyCrawlerApi`**（`portfolio_api.py`／`portfolio_official.py` 由 `api.py` 載入）；Node 沒改程式不用重啟；前端 push 後 GitHub Pages 約 3 分鐘。

## 變更檔案

修改：`Crawler/portfolio_api.py`、`Crawler/portfolio_official.py`、`Crawler/tests/test_portfolio_official.py`、`Screen/src/pages/OfficialStrategy.jsx`、`Screen/src/components/BeatMarketList.jsx`、`Server/tests/helpers/fastapi-mock.js`、`AI/Doc/README.md`、`progress.md`；
`meeting_front_end/src/stock/pages/OfficialStrategy.jsx`、`src/stock/components/BeatMarketList.jsx`（同步）。
新增：`AI/experiments/segment_counts.py`（回答「開發期 63／驗證期 24／實單 1」是什麼：各段列數與主動 > 0 的數，只讀；`universe_composition.py` 已隨 Iteration 85 提交 5f9f4ad）。
資料：沒有。
