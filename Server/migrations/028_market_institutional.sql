-- Iteration 71：全市場三大法人買賣超（Papers.md P18／P44 的資料前提；資料工作，不算 N）
--
-- 為什麼要新表：既有 stock_chip_analysis 只有 26 檔追蹤股（FinMind 逐檔），且 stock_id 混入非股票代號；
-- 「打敗大盤」的法人籌碼訊號需要 2018 起全市場、每日、上市＋上櫃，來源用交易所官方檔（證交所 T86、櫃買 insti/dailyTrade），
-- 一天兩次呼叫拿全市場，不吃 FinMind 額度——和 market_daily_prices 同一條路線。
-- 單位：股。外資 = 外資及陸資（含外資自營商）；自營商 = 自行買賣 + 避險；total_net 是交易所原表的「三大法人買賣超」欄，
-- 寫入前逐列驗證 total_net = foreign_net + trust_net + dealer_net（格式變了會在解析時擋下）。
-- 誰寫：Crawler/institutional_data.py（回補與每日 18:35 排程 job_institutional_daily）。誰讀：之後的 portfolio_signal 法人訊號。

CREATE TABLE IF NOT EXISTS market_institutional_daily (
    stock_id      VARCHAR(10) NOT NULL,
    trade_date    DATE        NOT NULL,
    foreign_buy   BIGINT,
    foreign_sell  BIGINT,
    foreign_net   BIGINT      NOT NULL,
    trust_buy     BIGINT,
    trust_sell    BIGINT,
    trust_net     BIGINT      NOT NULL,
    dealer_buy    BIGINT,
    dealer_sell   BIGINT,
    dealer_net    BIGINT      NOT NULL,
    total_net     BIGINT      NOT NULL,
    source        VARCHAR(10) NOT NULL,          -- twse / tpex
    fetched_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_id, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_market_institutional_date ON market_institutional_daily (trade_date);
