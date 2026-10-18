-- Iteration 81：全市場外資持股與發行股數（Papers.md P70～P72 的資料前提；資料工作，不算 N）
--
-- 為什麼要新表：外資「持股水準」（Huang & Shiu 2009：高外資持股股票報酬高）和 market_institutional_daily 的「流量」不同；
-- 同一張交易所檔還給「發行股數」，讓週轉率（成交股數 ÷ 發行股數，Lee & Swaminathan 2000 的台灣版 P72）與市值（發行股數 × 收盤）算得出來——
-- 這是 Papers.md P32 擱置的原因（庫裡沒有流通股數）。既有 stock_foreign_holding 只有 26 檔追蹤股。
-- 來源：證交所 fund/MI_QFIIS（外資及陸資投資持股統計，selectType=ALLBUT0999）＋ 櫃買 insti/qfii（僑外資及陸資持股比例排行表），一天兩次呼叫。
-- 寫入前逐列檢查「持股比率 ≈ 持有股數 ÷ 發行股數」（差超過 0.5 個百分點就當欄位對錯擋下）；foreign_ratio 一律存自己算的值。
-- 誰寫：Crawler/holding_data.py（回補與每日 18:41 排程 job_holding_daily）。誰讀：之後的 portfolio_signal 持股水準／週轉率訊號。

CREATE TABLE IF NOT EXISTS market_foreign_holding_daily (
    stock_id        VARCHAR(10)  NOT NULL,
    trade_date      DATE         NOT NULL,
    shares_issued   BIGINT       NOT NULL,       -- 發行股數（股）
    foreign_shares  BIGINT       NOT NULL,       -- 全體外資及陸資持有股數（股）
    foreign_ratio   NUMERIC(6,2) NOT NULL,       -- 持股比率（%），自己算的 foreign_shares ÷ shares_issued × 100
    source          VARCHAR(10)  NOT NULL,       -- twse / tpex
    fetched_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_market_foreign_holding_date ON market_foreign_holding_daily (trade_date);
