# Iteration 62 — 條件可以 AND／OR 組合：一條規則多個條件用「且」「或」連起來，日期條件也能和指標條件搭

**日期：** 2026-10-09
**依據：** 使用者：「設定條件可以 AND／OR 組合」。接在 Iteration 61 的條件規則之後。
**規則：** 規則格式往回相容——`when` 仍可是單一條件；群組是 `{"op": "and"|"or", "conds": [條件…]}`，可巢狀兩層、每層 1～8 個。公開、只讀，走同一個 `POST /sim/rules`。

## 一、做了什麼

### 後端：`Crawler/trading_strategy.py`

- `is_group`／`leaves`／`has_date_leaf`／`cond_text`：群組攤平成葉節點；規則文字用「（A 且 B）」「（A 或 B）」。
- `_validate_when` 遞迴：op 只能 and／or、conds 1～8 個、最多巢狀兩層、葉節點照原本的參數檢查。條件壞掉的那條不再往下驗動作。
- `_eval(when, ctx)` 遞迴求值：and 要全部成立（值是各葉的值）、or 任一成立；日期類葉用 `_date_hit`，指標類葉用 `_check_leaf`（原 `_check`）。`_indicators` 走葉節點，只算用得到的。
- **判斷時點**：含日期類葉的規則在**當天開盤**判斷，群組裡的指標葉此時看**前一個交易日的收盤**（例：「每月 5 日 且 在 60 日均線之下」= 5 日那天開盤，看前一日收盤是否在均線下）；不含日期類的規則照舊收盤判斷、隔天開盤成交。
- 預設值跟著葉節點：含每月固定日 → `max_times` 不限；含日期類 → 買單不擋「沒持股才買」。

### 頁面：`Screen/src/components/RuleBuilder.jsx`（meeting_front_end 同一份）

每條規則可「＋ 加條件」（最多 8 個），第二個條件起前面是「且／或」按鈕，點了整條規則切換；每個條件可刪（剩一個時不能）。規則文字自動顯示括號與連接詞，含日期條件時提示「當天開盤判斷，指標看前一日收盤」。
模板加兩個：**定投在均線下**（每月 5 日 且 前一日收盤在 60 日均線之下 才買 2 萬）、**雙重確認**（穿過 20 日均線 且 RSI(14) > 50 才買 10 萬；跌破 20 日均線 或 比成本低 10% 就賣光）。

## 二、結果

| 檢查 | 結果 | 來源 |
|---|---|---|
| `test_trading_strategy.py` 加 2 項（共 5） | 群組驗證與文字（含巢狀、三種壞法）；AND 兩葉都成立才在隔天開盤買、AND 一葉不成立不買、OR 任一成立就買且只買一次、「每月 13 日 且 前一日收盤 < 150」當天開盤買、「且 < 50」不買；觸發紀錄的條件值 | `checks.json` name=pytest |
| Crawler pytest 全套 | 220 項通過 | 同上 |
| Screen vite build、meeting_front_end build | 通過 | `checks.json` name=vite-build、mfe-build |
| 正式 API 匿名呼叫 | 雙重確認（2330）＋ 定投在均線下（0050），2024-01-02～09-30、30 萬：見 `rules-anon-combo` 的數字 | `checks.json` name=rules-anon-combo |
| Node | 路由不變（`/sim/rules` 原樣轉），jest 未重跑 | — |

## 三、讀法

1. 群組讓規則表達「進場要兩個訊號都到」「出場任一條件就走」，這是大多數人說的「策略」的最小單位；之前單條件只能各自獨立觸發。
2. 日期條件搭指標的「前一日收盤」設計是為了不偷看：5 日當天開盤時還沒有當天收盤，只能用昨天的；同樣的規則拿去引擎實際跑也只能這樣做。
3. 沒做的：NOT、跨股票條件（A 的條件觸發 B 的動作）、相對 0050 的條件、成交量。

## 變更檔案

修改：`Crawler/trading_strategy.py`、`Crawler/tests/test_trading_strategy.py`、`Crawler/rules_anon_evidence.py`（--template combo）、`Screen/src/components/RuleBuilder.jsx`、`meeting_front_end/src/stock/components/RuleBuilder.jsx`、`AI/Doc/README.md`、`progress.md`。
